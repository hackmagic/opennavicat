"""DuckDB connector — embedded analytic database, local-file backed."""

from __future__ import annotations

import time
from typing import Any

import duckdb

from open_navicat.dal.base_connector import BaseConnector
from open_navicat.models import (
    ColumnInfo,
    ColumnMeta,
    ConnectionInfo,
    DatabaseInfo,
    QueryResult,
    TableInfo,
)


class DuckDBConnector(BaseConnector):
    """Embedded DuckDB connector for local analytic queries."""

    def __init__(self, info: ConnectionInfo) -> None:
        self._info = info
        self._db: duckdb.DuckDBPyConnection | None = None

    async def connect(self) -> bool:
        try:
            path = self._info.database or ":memory:"
            self._db = duckdb.connect(path)
            return True
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._db:
            self._db.close()
            self._db = None

    async def is_connected(self) -> bool:
        return self._db is not None

    async def ping(self) -> bool:
        try:
            if self._db:
                self._db.execute("SELECT 1")
                return True
            return False
        except Exception:
            return False

    async def list_databases(self) -> list[DatabaseInfo]:
        return [DatabaseInfo(name=f"duckdb_{id(self)}")]

    async def list_tables(self, database: str) -> list[str]:
        if not self._db:
            return []
        rows = self._db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        return [r[0] for r in rows]

    async def list_views(self, database: str) -> list[str]:
        return []

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        return []

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        info = TableInfo(name=table, database=database)
        if not self._db:
            return info
        try:
            cols = self._db.execute(f"DESCRIBE {table}").fetchall()
            for col in cols:
                info.columns.append(ColumnInfo(name=col[0], data_type=col[1]))
        except Exception:
            pass
        return info

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        start = time.monotonic()
        if not self._db:
            return QueryResult(success=False, error_message="Not connected")
        try:
            stmt = sql.strip().upper().split()[0] if sql.strip() else ""
            if stmt in ("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN"):
                result = self._db.execute(sql)
                desc = result.description
                columns = []
                for d in desc:
                    col_name = d[0]
                    col_type = str(d[1]) if len(d) > 1 else ""
                    columns.append(ColumnMeta(name=col_name, data_type=col_type))
                rows = [list(r) for r in result.fetchall()]
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(
                    success=True, columns=columns, rows=rows,
                    row_count=len(rows), execution_time_ms=elapsed,
                )
            else:
                self._db.execute(sql)
                elapsed = (time.monotonic() - start) * 1000
                return QueryResult(
                    success=True, row_count=0, execution_time_ms=elapsed,
                )
        except Exception as e:
            return QueryResult(success=False, error_message=str(e))

    async def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        if not self._db:
            return 0
        count = 0
        for params in params_list:
            self._db.execute(sql, params)
            count += 1
        return count

    async def fetch_page(self, database: str, table: str, offset: int, limit: int,
                         order_by: str | None = None, ascending: bool = True) -> QueryResult:
        sql = f"SELECT * FROM {table}"
        if order_by:
            sql += f" ORDER BY {order_by} {'ASC' if ascending else 'DESC'}"
        sql += f" LIMIT {limit} OFFSET {offset}"
        return await self.execute(sql)

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if not self._db or not rows:
            return 0
        cols = ", ".join(rows[0].keys())
        placeholders = ", ".join("?" for _ in rows[0])
        values = [tuple(r.values()) for r in rows]
        self._db.executemany(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", values)
        return len(rows)

    async def update_row(self, database: str, table: str, row: dict, pk_column: str, pk_value: Any) -> bool:
        set_clause = ", ".join(f"{k} = ?" for k in row if k != pk_column)
        vals = [v for k, v in row.items() if k != pk_column]
        vals.append(pk_value)
        self._db.execute(f"UPDATE {table} SET {set_clause} WHERE {pk_column} = ?", vals)
        return True

    async def delete_row(self, database: str, table: str, pk_column: str, pk_value: Any) -> bool:
        self._db.execute(f"DELETE FROM {table} WHERE {pk_column} = ?", [pk_value])
        return True
