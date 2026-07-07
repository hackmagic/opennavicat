"""Metadata service — provides access to database structure information."""

from __future__ import annotations

import time
from typing import Any, Optional

from open_navicat.dal.base_connector import BaseConnector
from open_navicat.dal.connection_pool import _loop as pool_loop
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.models.table_schema import (
    DatabaseInfo,
    TableInfo,
)


class MetadataService:
    """Service layer for reading database schema metadata.

    Public methods use a simple TTL cache (default 60 s) to reduce
    round-trips for data that rarely changes mid-session.
    """

    CACHE_TTL = 60

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}

    def _connector(self, connection_id: str) -> BaseConnector | None:
        return connection_pool.get(connection_id)

    def _exec(self, connection_id: str, method: str, *args) -> Any:
        connector = self._connector(connection_id)
        if not connector:
            return None
        return pool_loop.run_until_complete(getattr(connector, method)(*args))

    def _cached(self, key: str, connection_id: str, method: str, *args) -> Any:
        now = time.monotonic()
        if key in self._cache:
            ts, val = self._cache[key]
            if now - ts < self.CACHE_TTL:
                return val
        val = self._exec(connection_id, method, *args)
        if val is not None:
            self._cache[key] = (now, val)
        return val or []

    def invalidate(self, connection_id: str = "", database: str = "", table: str = "") -> None:
        if not connection_id:
            self._cache.clear()
            return
        self._cache = {
            k: v for k, v in self._cache.items()
            if not k.startswith(connection_id)
        }

    # ---- databases ----

    def list_databases(self, connection_id: str) -> list[DatabaseInfo]:
        key = f"{connection_id}:list_databases"
        return self._cached(key, connection_id, "list_databases")

    # ---- tables ----

    def list_tables(self, connection_id: str, database: str) -> list[str]:
        key = f"{connection_id}:list_tables:{database}"
        return self._cached(key, connection_id, "list_tables", database)

    def get_table_info(self, connection_id: str, database: str, table: str) -> Optional[TableInfo]:
        key = f"{connection_id}:get_table_info:{database}:{table}"
        now = time.monotonic()
        if key in self._cache:
            ts, val = self._cache[key]
            if now - ts < self.CACHE_TTL:
                return val
        val = self._exec(connection_id, "get_table_info", database, table)
        if val is not None:
            self._cache[key] = (now, val)
        return val

    # ---- views ----

    def list_views(self, connection_id: str, database: str) -> list[str]:
        key = f"{connection_id}:list_views:{database}"
        return self._cached(key, connection_id, "list_views", database)

    # ---- routines ----

    def list_routines(self, connection_id: str, database: str) -> list[tuple[str, str]]:
        key = f"{connection_id}:list_routines:{database}"
        return self._cached(key, connection_id, "list_routines", database)

    # ---- helpers ----

    @staticmethod
    def _engine_of(connector: BaseConnector) -> str:
        info = getattr(connector, "_info", None)
        return getattr(info, "engine", "mysql") if info else "mysql"

    @staticmethod
    def _quote(name: str, engine: str) -> str:
        q = '"' if engine == "postgresql" else "`"
        return f"{q}{name}{q}"

    def get_create_table_sql(self, connection_id: str, database: str, table: str) -> str:
        connector = self._connector(connection_id)
        if not connector:
            return ""
        engine = self._engine_of(connector)
        if engine == "postgresql":
            sql = (
                "SELECT pg_get_tabledef(c.oid) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relname = %s"
            )
            result = pool_loop.run_until_complete(connector.execute(sql, (database, table)))
            if result.success and result.rows:
                return result.rows[0][0] or ""
            # Fallback: use pg_dump-style DDL
            qtn = f'{self._quote(database, engine)}.{self._quote(table, engine)}'
            result = pool_loop.run_until_complete(
                connector.execute(f"SELECT pg_get_tabledef('{database}', '{table}')")
            )
            if result.success and result.rows:
                return result.rows[0][0] or ""
            return f"-- PostgreSQL table: {qtn}\n-- Use pg_dump for full DDL"
        result = pool_loop.run_until_complete(
            connector.execute(f"SHOW CREATE TABLE `{database}`.`{table}`")
        )
        if result.success and result.rows:
            return result.rows[0][1]
        return ""


# Module-level singleton
metadata_service = MetadataService()
