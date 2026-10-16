"""ClickHouse connector, backed by ``clickhouse-connect``.

``clickhouse-connect`` speaks the HTTP(S) interface synchronously, so every
blocking call is bridged onto a dedicated single-thread executor — the same
pattern as :mod:`open_navicat.drivers.sqlserver_connector`, chosen because
client objects are not documented as thread-safe and one worker per connector
removes that question entirely.

Requires the ``clickhouse`` extra
(``pip install open-navicat[clickhouse]``).  Default port is the HTTP interface
(8123); ``?ssl=on`` uses HTTPS (8443 when no port is given).
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
    import clickhouse_connect
except ImportError:  # pragma: no cover - exercised by the registry
    clickhouse_connect = None  # type: ignore[assignment]

from open_navicat.drivers.base_connector import BaseConnector
from open_navicat.errors import DriverNotFoundError
from open_navicat.models import (
    ColumnInfo,
    ColumnMeta,
    ConnectionInfo,
    DatabaseInfo,
    IndexInfo,
    QueryResult,
    TableInfo,
)

T = TypeVar("T")

#: ClickHouse types that behave like a primary key for editing round-trips.
_KEY_TYPES = frozenset({"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"})


def _normalize_value(value: Any) -> Any:
    """Make a clickhouse-connect value JSON-serialisable."""
    if isinstance(value, decimal.Decimal):
        # Decimal128/256 columns; keep precision readable without losing it.
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list):
        return [_normalize_value(v) for v in value]
    return value


def _bare_type(data_type: str) -> str:
    """``Nullable(UInt64)`` / ``Array(String)`` -> the inner type name, lower-cased."""
    text = (data_type or "").strip()
    while text.startswith(("Nullable(", "LowCardinality(")):
        inner = text.partition("(")[2]
        text = inner.rpartition(")")[0].strip()
    return text.lower()


class ClickHouseConnector(BaseConnector):
    """Async ClickHouse connector over the synchronous clickhouse-connect driver."""

    engine = "clickhouse"

    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__()
        self._info = info
        self._client: Any = None
        self._executor: ThreadPoolExecutor | None = None
        self._lock = asyncio.Lock()

    # ---- async/sync bridge ----

    async def _run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a blocking clickhouse-connect call on this connector's worker thread."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"clickhouse-{self._info.id}"
            )
        loop = asyncio.get_running_loop()
        call = functools.partial(fn, *args, **kwargs)
        return await loop.run_in_executor(self._executor, call)

    def _client_kwargs(self) -> dict[str, Any]:
        use_https = bool(self._info.use_ssl)
        port = self._info.port or (8443 if use_https else 8123)
        kwargs: dict[str, Any] = {
            "host": self._info.host or "127.0.0.1",
            "port": port,
            "username": self._info.user or "default",
            "password": self._info.password,
            "database": self._info.database or "default",
            "query_limit": 0,
        }
        timeout = self._info.connect_timeout or 10
        kwargs["connect_timeout"] = timeout
        kwargs["send_receive_timeout"] = timeout * 10
        if use_https:
            kwargs["secure"] = True
            if self._info.ssl_ca:
                kwargs["ca_cert"] = self._info.ssl_ca
                kwargs["verify"] = True
            else:
                # Self-signed dev servers are common; only downgrade verification
                # when no CA was supplied.
                kwargs["verify"] = False
        return kwargs

    # ---- connection lifecycle ----

    async def connect(self) -> bool:
        if clickhouse_connect is None:
            raise DriverNotFoundError(
                "ClickHouse driver (clickhouse-connect) is not installed; "
                "install with: pip install open-navicat[clickhouse]"
            )
        try:
            self._client = await self._run(clickhouse_connect.get_client, **self._client_kwargs())
            return True
        except Exception as exc:
            self._last_error = exc
            self._client = None
            return False

    async def disconnect(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await self._run(client.close)
            except Exception:  # noqa: BLE001 - teardown must not raise
                pass
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    async def is_connected(self) -> bool:
        return self._client is not None

    async def ping(self) -> bool:
        if self._client is None:
            return False
        try:
            await self._command("SELECT 1")
            return True
        except Exception:
            return False

    # ---- metadata ----

    async def list_databases(self) -> list[DatabaseInfo]:
        rows = await self._fetch_all(
            "SELECT name, engine FROM system.databases "
            "WHERE name NOT IN ('INFORMATION_SCHEMA', 'information_schema') "
            "ORDER BY name"
        )
        return [
            DatabaseInfo(name=str(r[0]), charset="UTF-8", collation=str(r[1] or "")) for r in rows
        ]

    async def list_tables(self, database: str) -> list[str]:
        return await self._list_objects(database, not_view=True, not_view_desc="!= 'View'")

    async def list_views(self, database: str) -> list[str]:
        return await self._list_objects(database, not_view=False, not_view_desc="= 'View'")

    async def _list_objects(self, database: str, not_view: bool, not_view_desc: str) -> list[str]:
        sql = (
            "SELECT name FROM system.tables "
            f"WHERE database = %(db)s AND engine {not_view_desc} ORDER BY name"
        )
        rows = await self._fetch_all(sql, {"db": database or "default"})
        return [str(r[0]) for r in rows]

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        # ClickHouse has no stored procedures/functions catalogue.
        return []

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        db, name = _split_qualified(table, database or "default")
        info = TableInfo(name=name, database=db)
        info.engine = "ClickHouse"
        info.charset = "UTF-8"

        engine_rows = await self._fetch_all(
            "SELECT engine FROM system.tables WHERE database = %(db)s AND name = %(t)s",
            {"db": db, "t": name},
        )
        if engine_rows:
            info.engine = str(engine_rows[0][0]) or "ClickHouse"

        count_rows = await self._fetch_all(
            "SELECT total_rows FROM system.tables WHERE database = %(db)s AND name = %(t)s",
            {"db": db, "t": name},
        )
        if count_rows and count_rows[0][0] is not None:
            info.row_count = int(count_rows[0][0])

        col_rows = await self._fetch_all(
            "SELECT name, type, default_kind, default_expression, comment "
            "FROM system.columns WHERE database = %(db)s AND table = %(t)s "
            "ORDER BY position",
            {"db": db, "t": name},
        )
        for r in col_rows:
            bare = _bare_type(str(r[1]))
            info.columns.append(
                ColumnInfo(
                    name=str(r[0]),
                    data_type=str(r[1]),
                    # ClickHouse encodes nullability in the type, not a flag column.
                    nullable="nullable" in str(r[1]).lower(),
                    default=f"{r[2]} {r[3]}".strip() if r[2] else (r[3] or ""),
                    comment=str(r[4] or ""),
                    is_primary_key=bare in _KEY_TYPES,
                )
            )

        idx_rows = await self._fetch_all(
            "SELECT name, type, expression FROM system.table_indexes "
            "WHERE database = %(db)s AND table = %(t)s ORDER BY name",
            {"db": db, "t": name},
        )
        for r in idx_rows:
            info.indexes.append(
                IndexInfo(
                    name=str(r[0]),
                    columns=[str(c) for c in (r[2] or "").split(",") if str(c).strip()],
                    is_unique=False,
                    is_primary=str(r[0]) == "primary",
                    index_type=str(r[1] or ""),
                )
            )

        # ClickHouse has no enforced foreign keys; ForeignKeyInfo stays empty.
        return info

    # ---- query execution ----

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        result = QueryResult()
        start = time.perf_counter()
        if self._client is None:
            result.success = False
            result.error_message = "ClickHouse connection is not open"
            return result

        # clickhouse-bindings only supports named %(name)s substitution.  A
        # positional tuple cannot be mapped, so it is rejected rather than
        # silently dropped (dropping it could change query semantics).
        if params is not None and not isinstance(params, dict):
            result.success = False
            result.error_message = (
                "ClickHouse binds named parameters only; pass a dict, e.g. {'db': 'x'}"
            )
            return result
        try:
            async with self._lock:
                rs = await self._run(self._client.query, sql, params)
            cols = [ColumnMeta(name=str(c), data_type="") for c in rs.column_names]
            rows = [[_normalize_value(v) for v in row] for row in rs.result_rows]
            result.columns = cols
            result.rows = rows
            result.row_count = len(rows)
            result.affected_rows = len(rows) if not cols else 0
            result.execution_time_ms = (time.perf_counter() - start) * 1000
        except Exception as exc:
            self._last_error = exc
            result.success = False
            result.error_message = str(exc)
        return result

    async def _command(self, sql: str) -> None:
        await self._run(self._client.command, sql)

    async def _fetch_all(self, sql: str, params: dict | None = None) -> list[tuple]:
        if self._client is None:
            return []
        async with self._lock:
            rs = await self._run(self._client.query, sql, params)
            return [tuple(row) for row in rs.result_rows]

    async def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        if self._client is None or not params_list:
            return 0
        try:
            async with self._lock:
                await self._run(self._client.insert, sql, [list(p) for p in params_list])
            return len(params_list)
        except Exception as exc:
            self._last_error = exc
            return 0

    async def fetch_page(
        self,
        database: str,
        table: str,
        offset: int,
        limit: int,
        order_by: str | None = None,
        order_dir: str = "ASC",
    ) -> QueryResult:
        db, name = _split_qualified(table, database or "default")
        direction = "DESC" if (order_dir or "ASC").upper() == "DESC" else "ASC"
        order = f" ORDER BY {_quote(order_by)} {direction}" if order_by else ""
        sql = (
            f"SELECT * FROM {_quote(db)}.{_quote(name)}{order} "
            f"LIMIT {int(limit)} OFFSET {int(offset)}"
        )
        return await self.execute(sql)

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if not rows or self._client is None:
            return 0
        db, name = _split_qualified(table, database or "default")
        columns = list(rows[0].keys())
        data = [[r.get(c) for c in columns] for r in rows]
        sql = f"INSERT INTO {_quote(db)}.{_quote(name)} ({', '.join(_quote(c) for c in columns)})"
        try:
            async with self._lock:
                await self._run(self._client.insert, sql, data)
            return len(rows)
        except Exception as exc:
            self._last_error = exc
            return 0

    async def update_row(self, database: str, table: str, values: dict, where: dict) -> int:
        db, name = _split_qualified(table, database or "default")
        sets = ", ".join(f"{_quote(k)} = {_literal(v)}" for k, v in values.items())
        where_clause = _where_sql(where)
        sql = f"ALTER TABLE {_quote(db)}.{_quote(name)} UPDATE {sets} WHERE {where_clause}"
        result = await self.execute(sql)
        return 1 if result.success else 0

    async def delete_row(self, database: str, table: str, where: dict) -> int:
        db, name = _split_qualified(table, database or "default")
        where_clause = _where_sql(where)
        sql = f"ALTER TABLE {_quote(db)}.{_quote(name)} DELETE WHERE {where_clause}"
        result = await self.execute(sql)
        return 1 if result.success else 0


def _split_qualified(table: str, database: str) -> tuple[str, str]:
    """``analytics.events`` -> ``("analytics", "events")``; bare name uses *database*."""
    if "." in table:
        schema, _, name = table.partition(".")
        return schema, name
    return database, table


def _quote(identifier: str | None) -> str:
    """Quote a ClickHouse identifier for backtick embedding."""
    return "`" + str(identifier or "").replace("`", "\\`") + "`"


def _where_sql(where: dict) -> str:
    if not where:
        return "1"
    return " AND ".join(f"{_quote(k)} = {_literal(v)}" for k, v in where.items())


def _literal(value: Any) -> str:
    """Render a Python value as a ClickHouse SQL literal.

    ClickHouse parameters cannot be bound inside ALTER ... UPDATE/DELETE
    mutations, so mutations inline safe literals instead.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, decimal.Decimal)):
        return str(value)
    if isinstance(value, _dt.datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(value, _dt.date):
        return f"'{value.isoformat()}'"
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


__all__ = ["ClickHouseConnector"]
