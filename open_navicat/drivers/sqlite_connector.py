"""SQLite connector implementation using aiosqlite."""

from __future__ import annotations

import json
import time
from decimal import Decimal

import aiosqlite

#: Values of ``ConnectionInfo.host`` that mean "no file path given".
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", ""})

from open_navicat.drivers.base_connector import BaseConnector
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


def _adapt_params(params) -> tuple:
    """Adapt values to sqlite3's binding types.

    sqlite3 accepts only ``None``/int/float/str/bytes.  The migration layer
    deliberately produces driver-agnostic values (``Decimal`` for NUMERIC
    columns, native objects for JSON), so each connector must adapt them:
    without this, ``executemany`` raises ``type 'decimal.Decimal' is not
    supported`` and every numeric import batch fails.
    """
    if not params:
        return tuple(params or ())
    out = []
    for value in params:
        if isinstance(value, Decimal):
            out.append(float(value))
        elif isinstance(value, (dict, list)):
            out.append(json.dumps(value, ensure_ascii=False, default=str))
        else:
            out.append(value)
    return tuple(out)


class SQLiteConnector(BaseConnector):
    """Async SQLite connector backed by aiosqlite."""

    def __init__(self, info: ConnectionInfo) -> None:
        super().__init__()
        self._info = info
        self._db: aiosqlite.Connection | None = None
        # Historically the file path lived in `host`; `database` is the natural
        # field and is what the DSN parser fills in.  Accept both so old saved
        # connections keep working.
        # Which field holds the file path?
        #   * `database` is the documented home for it (and what the DSN parser
        #     fills in), so it wins whenever it is set.
        #   * older saved profiles kept it in `host`.  ConnectionInfo.host
        #     defaults to "127.0.0.1", so a real path is only recognisable by
        #     looking like one - otherwise every legacy profile would resolve to
        #     "127.0.0.1" and quietly open an in-memory database instead.
        if info.database:
            self._db_path = info.database
        elif info.host and info.host not in _LOOPBACK_HOSTS:
            self._db_path = info.host
        else:
            # No file given at all: an in-memory database, not a file literally
            # named after the loopback address.
            self._db_path = ":memory:"

    # ---- connection lifecycle ----

    async def connect(self) -> bool:
        try:
            self._db = await aiosqlite.connect(self._db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA foreign_keys=ON")
            return True
        except Exception as exc:
            self._last_error = exc
            return False

    async def disconnect(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def is_connected(self) -> bool:
        return self._db is not None

    async def ping(self) -> bool:
        if not self._db:
            return False
        try:
            await self._db.execute("SELECT 1")
            return True
        except Exception:
            return False

    # ---- metadata ----

    async def list_databases(self) -> list[DatabaseInfo]:
        # SQLite has no separate databases; the file IS the database
        name = self._db_path.split("/")[-1].split("\\")[-1]
        return [DatabaseInfo(name=name, charset="UTF-8", collation="BINARY")]

    async def list_tables(self, database: str) -> list[str]:
        rows = await self._fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [str(r[0]) for r in rows]

    async def list_views(self, database: str) -> list[str]:
        rows = await self._fetch_all(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
        )
        return [str(r[0]) for r in rows]

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        # SQLite has no stored procedures/functions
        return []

    async def list_triggers(self, database: str) -> list[tuple[str, str]]:
        """Triggers come from sqlite_master, the only catalog SQLite has."""
        _ = database
        rows = await self._fetch_all(
            "SELECT name, tbl_name FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
        )
        return [(str(r[0]), str(r[1])) for r in rows]

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        # Columns
        rows = await self._fetch_all(f"PRAGMA table_info(`{table}`)")
        columns = []
        for r in rows:
            columns.append(
                ColumnInfo(
                    name=str(r[1]),
                    data_type=str(r[2]),
                    nullable=not r[3],
                    default=str(r[4]) if r[4] is not None else None,
                    is_primary_key=bool(r[5]),
                    is_auto_increment=False,  # SQLite auto_increment is via INTEGER PRIMARY KEY
                    comment="",
                    ordinal_position=r[0] + 1,
                )
            )

        # Indexes
        idx_rows = await self._fetch_all(f"PRAGMA index_list(`{table}`)")
        indexes = []
        for idx_r in idx_rows:
            idx_name = str(idx_r[1])
            is_unique = bool(idx_r[2])
            idx_info_rows = await self._fetch_all(f"PRAGMA index_info(`{idx_name}`)")
            cols = [str(i[2]) for i in idx_info_rows]
            indexes.append(
                IndexInfo(
                    name=idx_name,
                    columns=cols,
                    is_unique=is_unique,
                    index_type="BTREE",
                )
            )

        # Foreign keys
        fk_rows = await self._fetch_all(f"PRAGMA foreign_key_list(`{table}`)")
        foreign_keys = []
        for fk_r in fk_rows:
            foreign_keys.append(
                ForeignKeyInfo(
                    name=f"fk_{table}_{fk_r[3]}",
                    column=str(fk_r[3]),
                    ref_table=str(fk_r[2]),
                    ref_column=str(fk_r[4]),
                    on_update=str(fk_r[5]) if fk_r[5] else "NO ACTION",
                    on_delete=str(fk_r[6]) if fk_r[6] else "NO ACTION",
                )
            )

        # Row count
        try:
            result = await self._fetch_one(f"SELECT COUNT(*) FROM `{table}`")
            row_count = result[0] if result else 0
        except Exception:
            row_count = 0

        return TableInfo(
            name=table,
            database=database,
            columns=columns,
            indexes=indexes,
            foreign_keys=foreign_keys,
            engine="SQLite",
            charset="UTF-8",
            row_count=row_count,
            data_length=0,
            auto_increment=False,
            comment="",
        )

    # ---- query ----

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        if not self._db:
            return QueryResult(success=False, error_message="Not connected")
        start = time.monotonic()
        try:
            # Determine if SELECT
            stripped = sql.strip().upper()
            is_select = (
                stripped.startswith("SELECT")
                or stripped.startswith("PRAGMA")
                or stripped.startswith("EXPLAIN")
            )

            if is_select:
                cursor = await self._db.execute(sql, _adapt_params(params))
                rows = await cursor.fetchall()
                columns = []
                if cursor.description:
                    for i, desc in enumerate(cursor.description):
                        columns.append(
                            ColumnMeta(
                                name=desc[0],
                                table_name="",
                                data_type="TEXT",
                                ordinal_position=i + 1,
                            )
                        )
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(
                    success=True,
                    columns=columns,
                    rows=[tuple(r) for r in rows],
                    row_count=len(rows),
                    execution_time_ms=elapsed,
                )
            else:
                cursor = await self._db.execute(sql, _adapt_params(params))
                await self._db.commit()
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(
                    success=True,
                    affected_rows=cursor.rowcount,
                    insert_id=cursor.lastrowid,
                    execution_time_ms=elapsed,
                )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(
                success=False,
                error_message=str(e),
                execution_time_ms=elapsed,
            )

    async def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        if not self._db:
            return 0
        cursor = await self._db.executemany(sql, [_adapt_params(p) for p in params_list])
        await self._db.commit()
        return cursor.rowcount

    async def fetch_page(
        self,
        database: str,
        table: str,
        offset: int,
        limit: int,
        order_by: str | None = None,
        order_dir: str = "ASC",
    ) -> QueryResult:
        sql = f"SELECT * FROM `{table}`"
        if order_by:
            sql += f" ORDER BY `{order_by}` {order_dir}"
        sql += f" LIMIT {limit} OFFSET {offset}"
        return await self.execute(sql)

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        cols = list(rows[0].keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(f"`{c}`" for c in cols)
        sql = f"INSERT INTO `{table}` ({col_names}) VALUES ({placeholders})"
        params_list = [tuple(r.get(c) for c in cols) for r in rows]
        return await self.execute_many(sql, params_list)

    async def update_row(
        self,
        database: str,
        table: str,
        values: dict,
        where: dict,
    ) -> int:
        set_parts = ", ".join(f"`{k}` = ?" for k in values)
        where_parts = " AND ".join(f"`{k}` = ?" for k in where)
        sql = f"UPDATE `{table}` SET {set_parts} WHERE {where_parts}"
        params = tuple(values.values()) + tuple(where.values())
        result = await self.execute(sql, params)
        return result.affected_rows if result.success else 0

    async def delete_row(self, database: str, table: str, where: dict) -> int:
        where_parts = " AND ".join(f"`{k}` = ?" for k in where)
        sql = f"DELETE FROM `{table}` WHERE {where_parts}"
        result = await self.execute(sql, tuple(where.values()))
        return result.affected_rows if result.success else 0

    # ---- internal helpers ----

    async def _fetch_all(self, sql: str, params: tuple | None = None) -> list[tuple]:
        if not self._db:
            return []
        cursor = await self._db.execute(sql, params or ())
        return await cursor.fetchall()

    async def _fetch_one(self, sql: str, params: tuple | None = None) -> tuple | None:
        if not self._db:
            return None
        cursor = await self._db.execute(sql, params or ())
        return await cursor.fetchone()
