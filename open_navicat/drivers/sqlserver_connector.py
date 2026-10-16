"""Microsoft SQL Server connector, backed by pyodbc.

``pyodbc`` is synchronous, so every blocking call is handed to a dedicated
single-thread executor.  Using one worker thread (rather than the shared
default pool) matters for two reasons:

* ODBC connections are not safe to use from two threads at once, and
* a connection can be pinned to the thread that created it.

One thread per connector removes both hazards without serialising the whole
application.

Requires the ``sqlserver`` extra (``pip install open-navicat[sqlserver]``) plus
an ODBC driver for SQL Server installed on the machine.
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
    import pyodbc
except ImportError:  # pragma: no cover - exercised by the registry
    pyodbc = None  # type: ignore[assignment]

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

#: ODBC drivers we will accept, newest first.
PREFERRED_DRIVERS: tuple[str, ...] = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)


def pick_odbc_driver(available: list[str] | None = None) -> str | None:
    """Return the best installed ODBC driver, or ``None`` if there is none."""
    names = available if available is not None else (pyodbc.drivers() if pyodbc else [])
    for preferred in PREFERRED_DRIVERS:
        if preferred in names:
            return preferred
    return None


def _normalize_value(value: Any) -> Any:
    """Make a pyodbc value JSON-serialisable.

    SQL Server returns ``Decimal`` for numeric/decimal columns and ``bytes`` for
    binary ones; neither survives a JSON export, so they are converted here
    rather than blowing up later in the export or AI layers.
    """
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


class SQLServerConnector(BaseConnector):
    """Async SQL Server connector over a synchronous pyodbc driver."""

    engine = "sqlserver"

    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__()
        self._info = info
        self._conn: Any = None
        self._executor: ThreadPoolExecutor | None = None
        self._lock = asyncio.Lock()
        self._driver: str | None = None

    # ---- async/sync bridge ----

    async def _run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a blocking pyodbc call on this connector's worker thread."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"mssql-{self._info.id}"
            )
        loop = asyncio.get_running_loop()
        call = functools.partial(fn, *args, **kwargs)
        return await loop.run_in_executor(self._executor, call)

    def _connection_string(self, driver: str) -> str:
        server = self._info.host or "127.0.0.1"
        if self._info.port:
            server = f"{server},{self._info.port}"
        parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={server}",
            f"UID={self._info.user}",
            f"PWD={self._info.password}",
            f"Connection Timeout={self._info.connect_timeout or 15}",
            # Driver 18 encrypts by default; honour the profile's SSL choice
            # explicitly instead of relying on the driver default.
            f"Encrypt={'yes' if self._info.use_ssl else 'no'}",
            # TODO: allow pinning a CA.  pyodbc has no portable option for it,
            # so self-signed dev servers would otherwise be unusable.
            "TrustServerCertificate=yes",
        ]
        if self._info.database:
            parts.append(f"DATABASE={self._info.database}")
        if self._info.charset:
            parts.append("ClientCharset=UTF-8")
        return ";".join(parts) + ";"

    # ---- connection lifecycle ----

    async def connect(self) -> bool:
        if pyodbc is None:
            raise DriverNotFoundError(
                "SQL Server driver (pyodbc) is not installed; "
                "install with: pip install open-navicat[sqlserver]"
            )
        driver = pick_odbc_driver()
        if driver is None:
            raise DriverNotFoundError(
                "no ODBC driver for SQL Server is installed on this machine; "
                "install 'ODBC Driver 18 for SQL Server' from Microsoft"
            )
        self._driver = driver
        try:
            self._conn = await self._run(
                pyodbc.connect, self._connection_string(driver), autocommit=True
            )
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
            await self._fetch_all("SELECT 1")
            return True
        except Exception:
            return False

    # ---- metadata ----

    async def list_databases(self) -> list[DatabaseInfo]:
        sql = (
            "SELECT name, collation_name FROM sys.databases "
            "WHERE state = 0 AND name NOT IN ('tempdb') ORDER BY name"
        )
        rows = await self._fetch_all(sql)
        return [
            DatabaseInfo(name=str(r[0]), charset="UTF-8", collation=str(r[1] or "")) for r in rows
        ]

    async def list_tables(self, database: str) -> list[str]:
        return await self._list_objects("BASE TABLE", database)

    async def list_views(self, database: str) -> list[str]:
        return await self._list_objects("VIEW", database)

    async def _list_objects(self, table_type: str, database: str) -> list[str]:
        if database:
            await self._use_database(database)
        sql = (
            "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_TYPE = ? ORDER BY TABLE_SCHEMA, TABLE_NAME"
        )
        rows = await self._fetch_all(sql, (table_type,))
        return [f"{r[0]}.{r[1]}" if r[0] != "dbo" else str(r[1]) for r in rows]

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        if database:
            await self._use_database(database)
        sql = (
            "SELECT ROUTINE_NAME, ROUTINE_TYPE FROM INFORMATION_SCHEMA.ROUTINES "
            "ORDER BY ROUTINE_NAME"
        )
        try:
            rows = await self._fetch_all(sql)
            return [(str(r[0]), str(r[1])) for r in rows]
        except Exception:
            return []

    async def list_triggers(self, database: str) -> list[tuple[str, str]]:
        """DML triggers (parent_class = 1) with their parent table."""
        if database:
            await self._use_database(database)
        sql = (
            "SELECT tr.name, OBJECT_NAME(tr.parent_id) FROM sys.triggers tr "
            "WHERE tr.parent_class = 1 ORDER BY tr.name"
        )
        try:
            rows = await self._fetch_all(sql)
            return [(str(r[0]), str(r[1] or "")) for r in rows]
        except Exception:
            return []

    async def _use_database(self, database: str) -> None:
        """Switch the connection's database for schema-less introspection."""
        safe = database.replace("]", "]]")
        try:
            await self._run(self._execute_raw, f"USE [{safe}]")
        except Exception as exc:  # noqa: BLE001 - non-fatal, metadata only
            self._last_error = exc

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        schema, name = _split_qualified(table)
        if database:
            await self._use_database(database)

        info = TableInfo(name=name, database=database)
        info.engine = "SQL Server"
        info.charset = "UTF-8"
        if self._info.charset:
            info.collation = self._info.charset

        col_sql = """
            SELECT c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE, c.COLUMN_DEFAULT,
                   c.CHARACTER_MAXIMUM_LENGTH, c.NUMERIC_PRECISION, c.NUMERIC_SCALE,
                   c.CHARACTER_SET_NAME, c.COLLATION_NAME, c.COLUMNPROPERTY(
                       OBJECT_ID(c.TABLE_SCHEMA + '.' + c.TABLE_NAME), c.COLUMN_NAME, 'IsIdentity'),
                   COLUMNPROPERTY(OBJECT_ID(c.TABLE_SCHEMA + '.' + c.TABLE_NAME),
                                  c.COLUMN_NAME, 'IsComputed')
            FROM INFORMATION_SCHEMA.COLUMNS c
            WHERE c.TABLE_SCHEMA = ? AND c.TABLE_NAME = ?
            ORDER BY c.ORDINAL_POSITION
        """
        col_rows = await self._fetch_all(col_sql, (schema, name))
        if not col_rows:
            return info

        pk_sql = """
            SELECT kcu.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
              ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
             AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
              AND tc.TABLE_SCHEMA = ? AND tc.TABLE_NAME = ?
        """
        pk_rows = await self._fetch_all(pk_sql, (schema, name))
        pk_set = {str(r[0]) for r in pk_rows}

        for r in col_rows:
            info.columns.append(
                ColumnInfo(
                    name=r[0],
                    data_type=r[1],
                    nullable=(r[2] == "YES"),
                    default=r[3],
                    char_max_length=r[4],
                    numeric_precision=r[5],
                    numeric_scale=r[6],
                    character_set=r[7] or "",
                    collation=r[8] or "",
                    is_primary_key=r[0] in pk_set,
                    is_auto_increment=bool(r[9]),
                )
            )

        count_sql = f"SELECT COUNT_BIG(*) FROM [{schema}].[{name}]"
        try:
            count_rows = await self._fetch_all(count_sql)
            if count_rows:
                info.row_count = int(count_rows[0][0] or 0)
        except Exception:  # noqa: BLE001 - count is best effort
            pass

        idx_sql = """
            SELECT i.name, c.name, i.is_unique, i.is_primary_key, i.type_desc
            FROM sys.indexes i
            JOIN sys.index_columns ic ON i.object_id = ic.object_id
                                      AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id
                               AND ic.column_id = c.column_id
            WHERE i.object_id = OBJECT_ID(?)
              AND i.name IS NOT NULL AND ic.is_included_column = 0
            ORDER BY i.name, ic.key_ordinal
        """
        for r in await self._fetch_all(idx_sql, (f"{schema}.{name}",)):
            idx_name = str(r[0])
            existing = next((i for i in info.indexes if i.name == idx_name), None)
            if existing is None:
                existing = IndexInfo(
                    name=idx_name,
                    is_unique=bool(r[2]),
                    is_primary=bool(r[3]),
                    index_type=str(r[4] or "BTREE"),
                )
                info.indexes.append(existing)
            existing.columns.append(str(r[1]))

        fk_sql = """
            SELECT fk.name, pc.name, OBJECT_NAME(fk.referenced_object_id),
                   rc.name, fk.delete_referential_action_desc,
                   fk.update_referential_action_desc
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
            JOIN sys.columns pc ON fkc.parent_object_id = pc.object_id
                               AND fkc.parent_column_id = pc.column_id
            JOIN sys.columns rc ON fkc.referenced_object_id = rc.object_id
                               AND fkc.referenced_column_id = rc.column_id
            WHERE fk.parent_object_id = OBJECT_ID(?)
            ORDER BY fk.name
        """
        for r in await self._fetch_all(fk_sql, (f"{schema}.{name}",)):
            info.foreign_keys.append(
                ForeignKeyInfo(
                    name=str(r[0]),
                    column=str(r[1]),
                    ref_table=str(r[2]),
                    ref_column=str(r[3]),
                    on_delete=str(r[4] or "NO ACTION"),
                    on_update=str(r[5] or "NO ACTION"),
                )
            )

        return info

    # ---- query execution ----

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        result = QueryResult()
        start = time.perf_counter()
        if self._conn is None:
            result.success = False
            result.error_message = "SQL Server connection is not open"
            return result

        def _work() -> tuple[list[ColumnMeta], list[list[Any]], int, int]:
            cursor = self._conn.cursor()
            try:
                cursor.execute(sql, params) if params else cursor.execute(sql)
                if cursor.description:
                    cols = [
                        ColumnMeta(
                            name=d[0],
                            data_type=_type_name(d[1]),
                            nullable=bool(d[6]) if len(d) > 6 else True,
                        )
                        for d in cursor.description
                    ]
                    rows = [[_normalize_value(v) for v in row] for row in cursor.fetchall()]
                    return cols, rows, 0, 0
                affected = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
                return [], [], affected, 0
            finally:
                cursor.close()

        try:
            async with self._lock:
                cols, rows, affected, insert_id = await self._run(_work)
            result.columns = cols
            result.rows = rows
            result.row_count = len(rows)
            result.affected_rows = affected
            result.insert_id = insert_id or None
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
                cursor.fast_executemany = True
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
        schema, name = _split_qualified(table)
        if database:
            await self._use_database(database)
        direction = "DESC" if order_dir.upper() == "DESC" else "ASC"
        order = f"ORDER BY [{_escape(order_by)}] {direction} " if order_by else ""
        # SQL Server requires ORDER BY before OFFSET/FETCH.
        if not order_by:
            order = "ORDER BY (SELECT NULL) "
        sql = f"SELECT * FROM [{schema}].[{name}] {order}OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
        return await self.execute(sql, (int(offset), int(limit)))

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        schema, name = _split_qualified(table)
        if database:
            await self._use_database(database)
        columns = list(rows[0].keys())
        col_list = ", ".join(f"[{_escape(c)}]" for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        sql = f"INSERT INTO [{schema}].[{name}] ({col_list}) VALUES ({placeholders})"
        params = [tuple(r.get(c) for c in columns) for r in rows]
        return await self.execute_many(sql, params)

    async def update_row(self, database: str, table: str, values: dict, where: dict) -> int:
        schema, name = _split_qualified(table)
        if database:
            await self._use_database(database)
        set_clause = ", ".join(f"[{_escape(k)}] = ?" for k in values)
        where_clause = " AND ".join(f"[{_escape(k)}] = ?" for k in where)
        sql = f"UPDATE [{schema}].[{name}] SET {set_clause} WHERE {where_clause}"
        result = await self.execute(sql, tuple(values.values()) + tuple(where.values()))
        return result.affected_rows

    async def delete_row(self, database: str, table: str, where: dict) -> int:
        schema, name = _split_qualified(table)
        if database:
            await self._use_database(database)
        where_clause = " AND ".join(f"[{_escape(k)}] = ?" for k in where)
        sql = f"DELETE FROM [{schema}].[{name}] WHERE {where_clause}"
        result = await self.execute(sql, tuple(where.values()))
        return result.affected_rows

    # ---- private helpers ----

    async def _execute_raw(self, sql: str) -> None:
        """Run a statement with no parameters and discard any result."""
        if self._conn is None:
            return

        def _work() -> None:
            cursor = self._conn.cursor()
            try:
                cursor.execute(sql)
            finally:
                cursor.close()

        async with self._lock:
            await self._run(_work)

    async def _fetch_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        if self._conn is None:
            return []

        def _work() -> list[tuple]:
            cursor = self._conn.cursor()
            try:
                cursor.execute(sql, params) if params else cursor.execute(sql)
                return list(cursor.fetchall())
            finally:
                cursor.close()

        async with self._lock:
            return await self._run(_work)


def _split_qualified(table: str) -> tuple[str, str]:
    """``dbo.Users`` -> ``("dbo", "Users")``; a bare name defaults to ``dbo``."""
    if "." in table:
        schema, _, name = table.partition(".")
        return schema, name
    return "dbo", table


def _escape(identifier: str | None) -> str:
    """Escape a SQL Server identifier for use inside ``[...]``."""
    return str(identifier or "").replace("]", "]]")


def _type_name(sql_type: int) -> str:
    """Map an ODBC SQL type code to a readable name."""
    if pyodbc is None:  # pragma: no cover - defensive
        return str(sql_type)
    try:
        return pyodbc.SQL_TYPE_NAMES.get(sql_type, str(sql_type))  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover - older pyodbc
        return str(sql_type)
