"""MySQL/MariaDB connector implementation using aiomysql."""

from __future__ import annotations

import time
from typing import Any

import aiomysql

from open_navicat.dal.base_connector import BaseConnector
from open_navicat.models import (
    ConnectionInfo,
    DatabaseInfo,
    TableInfo,
    ColumnInfo,
    IndexInfo,
    ForeignKeyInfo,
    QueryResult,
    ColumnMeta,
)


class MySQLConnector(BaseConnector):
    """Async MySQL connector backed by aiomysql."""

    def __init__(self, info: ConnectionInfo) -> None:
        self._info = info
        self._pool: aiomysql.Pool | None = None

    # ---- connection lifecycle ----

    async def connect(self) -> bool:
        try:
            self._pool = await aiomysql.create_pool(
                host=self._info.host,
                port=self._info.port,
                user=self._info.user,
                password=self._info.password,
                db=self._info.database if self._info.database else None,
                charset=self._info.charset,
                minsize=self._info.pool_min,
                maxsize=self._info.pool_max,
                connect_timeout=self._info.connect_timeout,
                autocommit=True,
            )
            return True
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None

    async def is_connected(self) -> bool:
        return self._pool is not None and not self._pool._closed

    async def ping(self) -> bool:
        if not self._pool:
            return False
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
                    return True
        except Exception:
            return False

    # ---- metadata ----

    async def list_databases(self) -> list[DatabaseInfo]:
        sql = "SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME"
        rows = await self._fetch_all(sql)
        return [
            DatabaseInfo(
                name=r[0],
                charset=r[1] or "utf8mb4",
                collation=r[2] or "utf8mb4_general_ci",
            )
            for r in rows
        ]

    async def list_tables(self, database: str) -> list[str]:
        sql = "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME"
        rows = await self._fetch_all(sql, (database,))
        return [str(r[0]) for r in rows]

    async def list_tables_with_info(self, database: str) -> list[dict]:
        """Return table list with metadata: name, auto_increment, update_time, data_length, engine."""
        sql = """
            SELECT TABLE_NAME, AUTO_INCREMENT, UPDATE_TIME,
                   DATA_LENGTH, ENGINE
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
        """
        rows = await self._fetch_all(sql, (database,))
        return [
            {
                "name": str(r[0]),
                "auto_increment": r[1],
                "update_time": str(r[2]) if r[2] else "",
                "data_length": r[3] or 0,
                "engine": str(r[4]) if r[4] else "",
            }
            for r in rows
        ]

    async def list_views(self, database: str) -> list[str]:
        sql = "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'VIEW' ORDER BY TABLE_NAME"
        rows = await self._fetch_all(sql, (database,))
        return [str(r[0]) for r in rows]

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        sql = "SELECT ROUTINE_NAME, ROUTINE_TYPE FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA = %s ORDER BY ROUTINE_NAME"
        try:
            rows = await self._fetch_all(sql, (database,))
            return [(str(r[0]), str(r[1]) if len(r) > 1 else "PROCEDURE") for r in rows]
        except Exception:
            return []

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        info = TableInfo(name=table, database=database)

        # Table-level info
        tbl_sql = """
            SELECT ENGINE, TABLE_COLLATION, TABLE_COMMENT, AUTO_INCREMENT,
                   TABLE_ROWS, CREATE_TIME, UPDATE_TIME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        """
        rows = await self._fetch_all(tbl_sql, (database, table))
        if rows:
            r = rows[0]
            info.engine = r[0] or "InnoDB"
            info.collation = r[1] or "utf8mb4_general_ci"
            info.comment = r[2] or ""
            info.auto_increment = r[3]
            info.row_count = r[4] or 0
            info.create_time = str(r[5] or "")
            info.update_time = str(r[6] or "")

        # Columns
        col_sql = """
            SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
                   EXTRA, COLUMN_COMMENT, CHARACTER_SET_NAME, COLLATION_NAME,
                   IF(COLUMN_KEY = 'PRI', TRUE, FALSE),
                   IF(COLUMN_KEY = 'UNI', TRUE, FALSE),
                   NUMERIC_PRECISION, NUMERIC_SCALE, CHARACTER_MAXIMUM_LENGTH
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """
        col_rows = await self._fetch_all(col_sql, (database, table))
        for r in col_rows:
            info.columns.append(ColumnInfo(
                name=r[0],
                data_type=r[1],
                nullable=(r[2] == "YES"),
                default=r[3],
                is_auto_increment="auto_increment" in (r[4] or ""),
                comment=r[5] or "",
                character_set=r[6] or "",
                collation=r[7] or "",
                is_primary_key=bool(r[8]),
                is_unique=bool(r[9]),
                numeric_precision=r[10],
                numeric_scale=r[11],
                char_max_length=r[12],
            ))

        # Indexes
        idx_sql = """
            SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE, INDEX_TYPE,
                   IF(INDEX_NAME = 'PRIMARY', TRUE, FALSE)
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY INDEX_NAME, SEQ_IN_INDEX
        """
        idx_rows = await self._fetch_all(idx_sql, (database, table))
        idx_map: dict[str, IndexInfo] = {}
        for r in idx_rows:
            name = r[0]
            if name not in idx_map:
                idx_map[name] = IndexInfo(
                    name=name,
                    is_unique=not bool(r[2]),
                    is_primary=bool(r[4]),
                    index_type=r[3] or "BTREE",
                )
            idx_map[name].columns.append(r[1])
        info.indexes = list(idx_map.values())

        # Foreign keys
        fk_sql = """
            SELECT k.CONSTRAINT_NAME, k.COLUMN_NAME,
                   k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME,
                   COALESCE(r.DELETE_RULE, 'RESTRICT'), COALESCE(r.UPDATE_RULE, 'RESTRICT')
            FROM information_schema.KEY_COLUMN_USAGE k
            LEFT JOIN information_schema.REFERENTIAL_CONSTRAINTS r
              ON k.CONSTRAINT_NAME = r.CONSTRAINT_NAME
              AND k.CONSTRAINT_SCHEMA = r.CONSTRAINT_SCHEMA
            WHERE k.TABLE_SCHEMA = %s AND k.TABLE_NAME = %s
              AND k.REFERENCED_TABLE_NAME IS NOT NULL
            ORDER BY k.CONSTRAINT_NAME, k.ORDINAL_POSITION
        """
        fk_rows = await self._fetch_all(fk_sql, (database, table))
        for r in fk_rows:
            info.foreign_keys.append(ForeignKeyInfo(
                name=r[0], column=r[1], ref_table=r[2],
                ref_column=r[3], on_delete=r[4], on_update=r[5],
            ))

        return info

    # ---- query execution ----

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        result = QueryResult()
        start = time.perf_counter()
        try:
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, params or ())

                    if cur.description:
                        # SELECT-like
                        result.columns = [
                            ColumnMeta(name=d[0], data_type=str(d[1]))
                            for d in cur.description
                        ]
                        result.rows = await cur.fetchall()
                        result.row_count = len(result.rows)
                        result.affected_rows = cur.rowcount
                    else:
                        # INSERT/UPDATE/DELETE/DDL
                        result.affected_rows = cur.rowcount
                        if cur.lastrowid:
                            result.insert_id = cur.lastrowid

            result.execution_time_ms = (time.perf_counter() - start) * 1000
        except Exception as e:
            result.success = False
            result.error_message = str(e)
        return result

    async def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(sql, params_list)
                return cur.rowcount

    async def fetch_page(
        self, database: str, table: str,
        offset: int, limit: int,
        order_by: str | None = None,
        order_dir: str = "ASC",
    ) -> QueryResult:
        quoted_table = f"`{database}`.`{table}`"
        order = f"ORDER BY `{order_by}` {order_dir}" if order_by else ""
        sql = f"SELECT * FROM {quoted_table} {order} LIMIT %s OFFSET %s"
        return await self.execute(sql, (limit, offset))

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        columns = list(rows[0].keys())
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(f"`{c}`" for c in columns)
        sql = f"INSERT INTO `{database}`.`{table}` ({col_names}) VALUES ({placeholders})"
        params = [[r[c] for c in columns] for r in rows]
        return await self.execute_many(sql, params)

    async def update_row(
        self, database: str, table: str,
        values: dict, where: dict,
    ) -> int:
        set_clause = ", ".join(f"`{k}` = %s" for k in values)
        where_clause = " AND ".join(f"`{k}` = %s" for k in where)
        sql = f"UPDATE `{database}`.`{table}` SET {set_clause} WHERE {where_clause}"
        params = tuple(list(values.values()) + list(where.values()))
        result = await self.execute(sql, params)
        return result.affected_rows

    async def delete_row(self, database: str, table: str, where: dict) -> int:
        where_clause = " AND ".join(f"`{k}` = %s" for k in where)
        sql = f"DELETE FROM `{database}`.`{table}` WHERE {where_clause}"
        result = await self.execute(sql, tuple(where.values()))
        return result.affected_rows

    # ---- private helpers ----

    async def _fetch_all(self, sql: str, params: tuple = ()) -> list[tuple]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                return await cur.fetchall()
