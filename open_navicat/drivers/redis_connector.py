"""Redis connector — async driver backed by redis.asyncio."""

from __future__ import annotations

import time
from typing import Any

from open_navicat.drivers.base_connector import BaseConnector
from open_navicat.errors import DriverNotFoundError
from open_navicat.models import (
    ColumnInfo,
    ColumnMeta,
    ConnectionInfo,
    DatabaseInfo,
    QueryResult,
    TableInfo,
)

# ponytail: redis is optional — import guarded, fails at connect() if missing


def _split_command(sql: str) -> list[str]:
    """Split a Redis command line, honouring double-quoted arguments.

    ``SET note "see you friday"`` must reach the server as three arguments, with
    the last one intact - a plain ``str.split()`` would break it into four.
    """
    tokens: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in sql.strip():
        if char == '"':
            in_quotes = not in_quotes
            continue
        if char.isspace() and not in_quotes:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))
    return tokens


def _shape_reply(reply: Any) -> tuple[list[list[Any]], list[ColumnMeta]]:
    """Turn a raw Redis reply into ``(rows, columns)`` for the grid.

    Redis replies come in a handful of shapes and the driver should not care
    which: scalars, byte strings, lists (LRANGE, SMEMBERS, ...) and maps
    (HGETALL).  Bytes are decoded because a result grid showing ``b"alpha"`` is
    not what anyone wants.
    """
    if reply is None:
        return [], []

    def decode(value: Any) -> Any:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8", errors="replace")
        return value

    if isinstance(reply, dict):
        rows = [[decode(k), decode(v)] for k, v in reply.items()]
        return rows, [
            ColumnMeta(name="field", data_type="string"),
            ColumnMeta(name="value", data_type="string"),
        ]

    if isinstance(reply, (list, tuple, set)):
        items = list(reply)
        rows = [[decode(v)] for v in items]
        return rows, [ColumnMeta(name="value", data_type="string")]

    return [[decode(reply)]], [ColumnMeta(name="value", data_type="string")]


class RedisConnector(BaseConnector):
    """Async Redis connector using redis.asyncio."""

    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__()
        self._info = info
        self._redis: Any = None  # redis.asyncio.Redis
        self._db_index: int = 0

    async def connect(self) -> bool:
        try:
            import redis.asyncio as _aioredis  # noqa: F811
        except ImportError as exc:
            raise DriverNotFoundError(
                "Redis driver (redis) is not installed; "
                "install with: pip install open-navicat[redis]",
                from_exc=exc,
            ) from exc
        try:
            # Parse database index from info.database (default 0)
            try:
                self._db_index = int(self._info.database) if self._info.database else 0
            except (ValueError, TypeError):
                self._db_index = 0

            kwargs: dict[str, Any] = {
                "host": self._info.host,
                "port": self._info.port,
                "db": self._db_index,
                "socket_timeout": self._info.connect_timeout,
                "decode_responses": True,
            }
            if self._info.password:
                kwargs["password"] = self._info.password
            if self._info.user:
                kwargs["username"] = self._info.user
            client = _aioredis.Redis(**kwargs)
            await client.ping()
            # Only publish the client once it has answered: leaving a half-built
            # client on self makes is_connected() report True for a dead
            # connection and leaks the socket pool.
            self._redis = client
            return True
        except Exception as exc:
            self._last_error = exc
            self._redis = None
            return False

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    async def is_connected(self) -> bool:
        if not self._redis:
            return False
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False

    async def ping(self) -> bool:
        return await self.is_connected()

    # ---- metadata ----

    async def list_databases(self) -> list[DatabaseInfo]:
        # Always return all 16 Redis databases (0-15)
        result = []
        for i in range(16):
            result.append(DatabaseInfo(name=str(i)))
        return result

    async def list_tables(self, database: str) -> list[str]:
        # In Redis, "tables" are key namespaces (prefix before first ':')
        # Scan all keys and extract unique prefixes
        if not self._redis:
            return []
        namespaces: set[str] = set()
        cursor = 0
        count = 0
        while True:
            cursor, keys = await self._redis.scan(cursor=cursor, count=500)
            for key in keys:
                if ":" in key:
                    namespaces.add(key.split(":")[0])
                else:
                    namespaces.add("(root)")
            count += len(keys)
            if cursor == 0 or count > 10000:
                break
        return sorted(namespaces)

    async def list_views(self, database: str) -> list[str]:
        return []

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        return []

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        info = TableInfo(name=table, database=database, engine="Redis")
        info.columns = [
            ColumnInfo(name="key", data_type="string", is_primary_key=True),
            ColumnInfo(name="type", data_type="string", nullable=False),
            ColumnInfo(name="value", data_type="string"),
            ColumnInfo(name="ttl", data_type="int64"),
            ColumnInfo(name="size", data_type="int64"),
        ]
        if not self._redis:
            return info
        # Count matching keys
        pattern = f"{table}:*" if table != "(root)" else "*"
        count = 0
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=500)
            count += len(keys)
            if cursor == 0 or count > 100000:
                break
        info.row_count = count
        return info

    # ---- query ----

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        if not self._redis:
            return QueryResult(success=False, error_message="Not connected")
        start = time.monotonic()
        try:
            parts = _split_command(sql)
            if not parts:
                return QueryResult(success=False, error_message="Empty command")
            cmd = parts[0].upper()
            args = parts[1:]

            # Route common Redis commands
            if cmd == "PING":
                await self._redis.ping()
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(
                    success=True,
                    columns=[ColumnMeta(name="result", data_type="string")],
                    rows=[["PONG"]],
                    row_count=1,
                    execution_time_ms=elapsed,
                )
            elif cmd == "GET" and args:
                val = await self._redis.get(args[0])
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(
                    success=True,
                    columns=[ColumnMeta(name="value", data_type="string")],
                    rows=[[val]],
                    row_count=1 if val is not None else 0,
                    execution_time_ms=elapsed,
                )
            elif cmd == "SET" and len(args) >= 2:
                await self._redis.set(args[0], args[1])
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(success=True, row_count=1, execution_time_ms=elapsed)
            elif cmd == "DEL" and args:
                n = await self._redis.delete(*args)
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(success=True, row_count=n, execution_time_ms=elapsed)
            elif cmd == "KEYS":
                pattern = args[0] if args else "*"
                keys = await self._redis.keys(pattern)
                elapsed = (time.monotonic() - start) * 1000
                rows = [[k] for k in keys]
                return QueryResult(
                    success=True,
                    columns=[ColumnMeta(name="key", data_type="string")],
                    rows=rows,
                    row_count=len(rows),
                    execution_time_ms=elapsed,
                )
            elif cmd == "DBSIZE":
                n = await self._redis.dbsize()
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(
                    success=True,
                    columns=[ColumnMeta(name="dbsize", data_type="int64")],
                    rows=[[n]],
                    row_count=1,
                    execution_time_ms=elapsed,
                )
            elif cmd == "INFO" and args:
                info_str = await self._redis.info(args[0])
                elapsed = (time.monotonic() - start) * 1000
                rows = [[str(k), str(v)] for k, v in info_str.items()]
                return QueryResult(
                    success=True,
                    columns=[
                        ColumnMeta(name="key", data_type="string"),
                        ColumnMeta(name="value", data_type="string"),
                    ],
                    rows=rows,
                    row_count=len(rows),
                    execution_time_ms=elapsed,
                )
            elif cmd == "SELECT" and args:
                # Switch database
                try:
                    new_db = int(args[0])
                    await self._redis.select(new_db)
                    self._db_index = new_db
                    elapsed = (time.monotonic() - start) * 1000
                    return QueryResult(success=True, row_count=1, execution_time_ms=elapsed)
                except Exception as e:
                    return QueryResult(success=False, error_message=str(e))
            elif cmd == "FLUSHDB":
                await self._redis.flushdb()
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(success=True, row_count=1, execution_time_ms=elapsed)
            else:
                # Not one of the shaped commands above.  Forward it rather than
                # refusing: Redis has hundreds of commands and the client already
                # knows how to speak them, so the driver should not be the
                # thing that decides which ones are allowed.
                reply = await self._redis.execute_command(cmd, *args)
                elapsed = (time.monotonic() - start) * 1000
                rows, columns = _shape_reply(reply)
                return QueryResult(
                    success=True,
                    columns=columns,
                    rows=rows,
                    row_count=len(rows),
                    execution_time_ms=elapsed,
                )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(success=False, error_message=str(e), execution_time_ms=elapsed)

    async def execute_many(self, sql: str, params_list: list[tuple]) -> int:
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
        if not self._redis:
            return QueryResult(success=False, error_message="Not connected")
        start = time.monotonic()
        try:
            pattern = f"{table}:*" if table != "(root)" else "*"
            keys: list[str] = []
            cursor = 0
            scanned = 0
            while True:
                cursor, batch = await self._redis.scan(
                    cursor=cursor, match=pattern, count=offset + limit + 100
                )
                keys.extend(batch)
                scanned += len(batch)
                if cursor == 0 or scanned > offset + limit + 1000:
                    break
            # Sort
            if order_by == "key":
                keys.sort(reverse=(order_dir.upper() == "DESC"))
            elif not order_by:
                keys.sort()
            # Paginate
            page_keys = keys[offset : offset + limit]
            if not page_keys:
                return QueryResult(success=True, row_count=0)

            columns = [
                ColumnMeta(name="key", data_type="string"),
                ColumnMeta(name="type", data_type="string"),
                ColumnMeta(name="value", data_type="string"),
                ColumnMeta(name="ttl", data_type="int64"),
            ]
            rows = []
            pipe = self._redis.pipeline()
            for k in page_keys:
                pipe.type(k)
                pipe.get(k)
                pipe.ttl(k)
            results = await pipe.execute()
            for i, k in enumerate(page_keys):
                idx = i * 3
                ktype = results[idx]
                val = results[idx + 1]
                ttl = results[idx + 2]
                rows.append([k, ktype, val, ttl])

            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(
                success=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(success=False, error_message=str(e), execution_time_ms=elapsed)

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if not self._redis or not rows:
            return 0
        try:
            pipe = self._redis.pipeline()
            count = 0
            for row in rows:
                key = row.get("key", "")
                value = row.get("value", "")
                if key:
                    pipe.set(key, value)
                    count += 1
            await pipe.execute()
            return count
        except Exception:
            return 0

    async def update_row(
        self,
        database: str,
        table: str,
        values: dict,
        where: dict,
    ) -> int:
        if not self._redis:
            return 0
        try:
            key = where.get("key", "")
            if not key:
                return 0
            if "value" in values:
                await self._redis.set(key, values["value"])
                return 1
            return 0
        except Exception:
            return 0

    async def delete_row(self, database: str, table: str, where: dict) -> int:
        if not self._redis:
            return 0
        try:
            key = where.get("key", "")
            if not key:
                return 0
            return await self._redis.delete(key)
        except Exception:
            return 0
