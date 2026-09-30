"""Oracle connector, backed by ``python-oracledb``.

Uses the driver's **synchronous** API bridged onto a dedicated single-thread
executor — the same pattern as :mod:`open_navicat.drivers.sqlserver_connector`
and :mod:`open_navicat.drivers.clickhouse_connector`.  Reasons to prefer the
sync API here over ``oracledb.Async``:

* it works identically in Thin and Thick modes (Thick is the only option for
  old database versions), and
* mock-based unit tests stay uniform with the other bridged drivers.

Requires the ``oracle`` extra (``pip install open-navicat[oracle]``).
Thin mode needs no Oracle Client libraries.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import decimal
import functools
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

try:
    import oracledb
except ImportError:  # pragma: no cover - exercised by the registry
    oracledb = None  # type: ignore[assignment]

from open_navicat.drivers.base_connector import BaseConnector
from open_navicat.errors import DriverNotFoundError
from open_navicat.models import (
    ColumnInfo,
    ColumnMeta,
    ConnectionInfo,
    DatabaseInfo,
    ForeignKeyInfo,
    IndexInfo,
    QueryResult,
    TableInfo,
)

T = TypeVar("T")


def _normalize_value(value: Any) -> Any:
    """Make an oracledb value JSON-serialisable.

    ``DatabaseLOB`` must be read while the connection is still open, which is
    why conversion happens on the worker thread inside ``_work`` below.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if _is_lob(value):
        try:
            return value.read()
        except Exception:  # noqa: BLE001 - unreadable LOB becomes a placeholder
            return None
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (_dt.timedelta, uuid.UUID)):
        return str(value)
    return value


def _is_lob(value: Any) -> bool:
    if oracledb is None:  # pragma: no cover - defensive
        return False
    return isinstance(value, (oracledb.DbLob, oracledb.Blob, oracledb.Clob))


class OracleConnector(BaseConnector):
    """Async Oracle connector over the synchronous python-oracledb driver."""

    engine = "oracle"

    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__()
        self._info = info
        self._conn: Any = None
        self._executor: ThreadPoolExecutor | None = None
        self._lock = asyncio.Lock()

    # ---- async/sync bridge ----

    async def _run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a blocking oracledb call on this connector's worker thread."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"oracle-{self._info.id}"
            )
        loop = asyncio.get_running_loop()
        call = functools.partial(fn, *args, **kwargs)
        return await loop.run_in_executor(self._executor, call)

    def _connect_params(self) -> dict[str, Any]:
        host = self._info.host or "127.0.0.1"
        port = self._info.port or 1521
        service = self._info.database or ""
        kwargs: dict[str, Any] = {
            "user": self._info.user or "",
            "password": self._info.password,
        }
        timeout = self._info.connect_timeout or 10
        # oracledb takes network timeouts in milliseconds.
        kwargs["tcp_connect_timeout"] = timeout * 1000
        if service:
            kwargs["dsn"] = oracledb.makedsn(host, port, service_name=service)
        else:
            kwargs["dsn"] = f"{host}:{port}"
        return kwargs

    # ---- connection lifecycle ----

    async def connect(self) -> bool:
        if oracledb is None:
            raise DriverNotFoundError(
                "Oracle driver (python-oracledb) is not installed; "
                "install with: pip install open-navicat[oracle]"
            )
        try:
            self._conn = await self._run(oracledb.connect, **self._connect_params())
            return True
        except Exception as exc:
            self._last_error = exc
            self._conn = None
            return False

    async def disconnect(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await self._run(conn.close)
            except Exception:  # noqa: BLE001 - teardown must not raise
                pass
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    async def is_connected(self) -> bool:
        return self._conn is not None

    async def ping(self) -> bool:
        if self._conn is None:
            return False
        try:
            await self._fetch_all("SELECT 1 FROM DUAL")
            return True
        except Exception:
            return False

    # ---- metadata ----

    async def list_databases(self) -> list[DatabaseInfo]:
        # Oracle's unit comparable to a "database" in this UI is the schema/user.
        rows = await self._fetch_all(
            "SELECT username FROM all_users ORDER BY username"
        )
        return [DatabaseInfo(name=str(r[0]), charset="UTF-8", collation="") for r in rows]

    async def list_tables(self, database: str) -> list[str]:
        owner = database or self._default_owner()
        rows = await self._fetch_all(
            "SELECT table_name FROM all_tables WHERE owner = :1 ORDER BY table_name",
            (owner,),
        )
        return [str(r[0]) for r in rows]

    async def list_views(self, database: str) -> list[str]:
        owner = database or self._default_owner()
        rows = await self._fetch_all(
            "SELECT view_name FROM all_views WHERE owner = :1 ORDER BY view_name",
            (owner,),
        )
        return [str(r[0]) for r in rows]

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        owner = database or self._default_owner()
        rows = await self._fetch_all(
            "SELECT object_name, object_type FROM all_objects "
            "WHERE owner = :1 AND object_type IN ('PROCEDURE', 'FUNCTION', 'PACKAGE') "
            "ORDER BY object_name",
            (owner,),
        )
        return [(str(r[0]), str(r[1])) for r in rows]

    def _default_owner(self) -> str:
        """Schema the connection logs into — Oracle owns objects per user."""
        return (self._info.user or "").upper()

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        owner, name = _split_qualified(table, database or self._default_owner())
        info = TableInfo(name=name, database=owner)
        info.engine = "Oracle"
        info.charset = self._info.charset or "UTF-8"

        meta_rows = await self._fetch_all(
            "SELECT c.comments, t.last_analyzed FROM all_tab_comments c "
            "JOIN all_tables t ON t.owner = c.table_name_owner AND t.table_name = c.table_name "
            "WHERE c.table_name_owner = :1 AND c.table_name = :2",
            (owner, name),
        )
        if meta_rows:
            info.comment = str(meta_rows[0][0] or "")

        col_rows = await self._fetch_all(
            "SELECT column_id, data_type, data_length, data_precision, data_scale, "
            "nullable, data_default, char_used, column_name FROM all_tab_cols "
            "WHERE owner = :1 AND table_name = :2 ORDER BY column_id",
            (owner, name),
        )
        pk_rows = await self._fetch_all(
            "SELECT acc.column_name FROM all_constraints ac "
            "JOIN all_cons_columns acc ON acc.owner = ac.owner "
            "AND acc.constraint_name = ac.constraint_name "
            "WHERE ac.owner = :1 AND ac.table_name = :2 AND ac.constraint_type = 'P'",
            (owner, name),
        )
        pk_set = {str(r[0]) for r in pk_rows}

        for r in col_rows:
            if r[0] is None:
                continue  # hidden collection/table-of-object column
            info.columns.append(
                ColumnInfo(
                    name=str(r[8]),
                    data_type=str(r[1]),
                    char_max_length=int(r[2]) if r[2] is not None else None,
                    numeric_precision=int(r[3]) if r[3] is not None else None,
                    numeric_scale=int(r[4]) if r[4] is not None else None,
                    nullable=(str(r[5]) == "Y"),
                    default=str(r[6]).strip() if r[6] is not None else None,
                    is_primary_key=str(r[8]) in pk_set,
                )
            )

        idx_rows = await self._fetch_all(
            "SELECT i.index_name, i.uniqueness, i.index_type, c.column_name "
            "FROM all_indexes i JOIN all_ind_columns c ON c.index_owner = i.owner "
            "AND c.index_name = i.index_name "
            "WHERE i.table_owner = :1 AND i.table_name = :2 "
            "ORDER BY i.index_name, c.column_position",
            (owner, name),
        )
        for r in idx_rows:
            idx_name = str(r[0])
            existing = next((i for i in info.indexes if i.name == idx_name), None)
            if existing is None:
                existing = IndexInfo(
                    name=idx_name,
                    is_unique=(str(r[1]) == "UNIQUE"),
                    is_primary=_is_pk_index(idx_name),
                    index_type=str(r[2] or "NORMAL"),
                )
                info.indexes.append(existing)
            existing.columns.append(str(r[3]))

        fk_rows = await self._fetch_all(
            "SELECT ac.constraint_name, acc.column_name, "
            "r_ac.owner || '.' || r_ac.table_name, r_acc.column_name, "
            "ac.delete_rule FROM all_constraints ac "
            "JOIN all_cons_columns acc ON acc.owner = ac.owner "
            "AND acc.constraint_name = ac.constraint_name "
            "JOIN all_constraints r_ac ON r_ac.owner = ac.r_owner "
            "AND r_ac.constraint_name = ac.r_constraint_name "
            "JOIN all_cons_columns r_acc ON r_acc.owner = r_ac.owner "
            "AND r_acc.constraint_name = r_ac.constraint_name "
            "AND r_acc.position = acc.position "
            "WHERE ac.owner = :1 AND ac.table_name = :2 AND ac.constraint_type = 'R' "
            "ORDER BY ac.constraint_name, acc.position",
            (owner, name),
        )
        for r in fk_rows:
            info.foreign_keys.append(
                ForeignKeyInfo(
                    name=str(r[0]),
                    column=str(r[1]),
                    ref_table=str(r[2]),
                    ref_column=str(r[3]),
                    on_delete=str(r[4] or "NO ACTION"),
                    on_update="NO ACTION",  # Oracle has no ON UPDATE clause
                )
            )

        count_rows = await self._fetch_all(
            f"SELECT COUNT(*) FROM {_quote(owner)}.{_quote(name)}"
        )
        if count_rows:
            info.row_count = int(count_rows[0][0] or 0)
        return info

    # ---- query execution ----

    async def execute(self, sql: str, params: tuple | dict | None = None) -> QueryResult:
        result = QueryResult()
        start = time.perf_counter()
        if self._conn is None:
            result.success = False
            result.error_message = "Oracle connection is not open"
            return result

        def _work() -> tuple[list[ColumnMeta], list[list[Any]], int]:
            cursor = self._conn.cursor()
            try:
                cursor.execute(sql, params) if params else cursor.execute(sql)
                if cursor.description:
                    cols = [
                        ColumnMeta(
                            name=str(d[0]),
                            data_type=str(d[1]) if d[1] is not None else "",
                        )
                        for d in cursor.description
                    ]
                    # LOBs are read while the connection is open, on this thread.
                    rows = [[_normalize_value(v) for v in row] for row in cursor.fetchall()]
                    return cols, rows, 0
                affected = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
                return [], [], affected
            finally:
                cursor.close()

        try:
            async with self._lock:
                cols, rows, affected = await self._run(_work)
            result.columns = cols
            result.rows = rows
            result.row_count = len(rows)
            result.affected_rows = affected
            result.execution_time_ms = (time.perf_counter() - start) * 1000
        except Exception as exc:
            self._last_error = exc
            result.success = False
            result.error_message = str(exc)
        return result

    async def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        if self._conn is None or not params_list:
            return 0

        def _work() -> int:
            cursor = self._conn.cursor()
            try:
                cursor.executemany(sql, params_list)
                return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            finally:
                cursor.close()

        async with self._lock:
            return await self._run(_work)

    async def fetch_page(
        self,
        database: str,
        table: str,
        offset: int,
        limit: int,
        order_by: str | None = None,
        order_dir: str = "ASC",
    ) -> QueryResult:
        owner, name = _split_qualified(table, database or self._default_owner())
        direction = "DESC" if (order_dir or "ASC").upper() == "DESC" else "ASC"
        order = f" ORDER BY {_quote(order_by)} {direction}" if order_by else ""
        # Oracle 12c+ row-paging syntax; bind names avoid literal injection.
        sql = (
            f"SELECT * FROM {_quote(owner)}.{_quote(name)}{order} "
            "OFFSET :offset_rows ROWS FETCH NEXT :fetch_rows ROWS ONLY"
        )
        return await self.execute(sql, {"offset_rows": int(offset), "fetch_rows": int(limit)})

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        owner, name = _split_qualified(table, database or self._default_owner())
        columns = list(rows[0].keys())
        col_list = ", ".join(_quote(c) for c in columns)
        placeholders = ", ".join(f":{i + 1}" for i in range(len(columns)))
        sql = f"INSERT INTO {_quote(owner)}.{_quote(name)} ({col_list}) VALUES ({placeholders})"
        params = [tuple(r.get(c) for c in columns) for r in rows]
        return await self.execute_many(sql, params)

    async def update_row(self, database: str, table: str, values: dict, where: dict) -> int:
        owner, name = _split_qualified(table, database or self._default_owner())
        set_clause = ", ".join(f"{_quote(k)} = :{i + 1}" for i, k in enumerate(values))
        where_clause = " AND ".join(
            f"{_quote(k)} = :{len(values) + i + 1}" for i, k in enumerate(where)
        )
        sql = f"UPDATE {_quote(owner)}.{_quote(name)} SET {set_clause} WHERE {where_clause}"
        result = await self.execute(sql, tuple(values.values()) + tuple(where.values()))
        return result.affected_rows

    async def delete_row(self, database: str, table: str, where: dict) -> int:
        owner, name = _split_qualified(table, database or self._default_owner())
        where_clause = " AND ".join(f"{_quote(k)} = :{i + 1}" for i, k in enumerate(where))
        sql = f"DELETE FROM {_quote(owner)}.{_quote(name)} WHERE {where_clause}"
        result = await self.execute(sql, tuple(where.values()))
        return result.affected_rows

    # ---- private helpers ----

    async def _fetch_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        if self._conn is None:
            return []

        def _work() -> list[tuple]:
            cursor = self._conn.cursor()
            try:
                cursor.execute(sql, params) if params else cursor.execute(sql)
                return [tuple(_normalize_value(v) for v in row) for row in cursor.fetchall()]
            finally:
                cursor.close()

        async with self._lock:
            return await self._run(_work)


def _split_qualified(table: str, owner: str) -> tuple[str, str]:
    """``HR.EMPLOYEES`` -> ``("HR", "EMPLOYEES")``; bare name uses *owner*."""
    if "." in table:
        schema, _, name = table.partition(".")
        return schema.upper(), name.upper()
    return owner, table.upper()


def _quote(identifier: str | None) -> str:
    """Quote an Oracle identifier for use inside double quotes."""
    return '"' + str(identifier or "").replace('"', '""') + '"'


def _is_pk_index(index_name: str) -> bool:
    """Oracle names the PK index after the PK constraint (``SYS_C00n`` / user name)."""
    upper = str(index_name).upper()
    return upper.startswith("SYS_C") or upper.endswith("_PK")


__all__ = ["OracleConnector"]
