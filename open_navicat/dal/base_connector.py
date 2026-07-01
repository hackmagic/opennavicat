"""Abstract base connector and concrete MySQL connector implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from open_navicat.models import ConnectionInfo, DatabaseInfo, TableInfo, QueryResult


class BaseConnector(ABC):
    """Abstract interface for all database connectors."""

    @abstractmethod
    async def connect(self) -> bool: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def is_connected(self) -> bool: ...

    @abstractmethod
    async def ping(self) -> bool: ...

    # ---- metadata ----

    @abstractmethod
    async def list_databases(self) -> list[DatabaseInfo]: ...

    @abstractmethod
    async def list_tables(self, database: str) -> list[str]: ...

    async def list_tables_with_info(self, database: str) -> list[dict]:
        """Return table list with metadata. Default: simple name list."""
        names = await self.list_tables(database)
        return [{"name": n, "auto_increment": None, "update_time": "", "data_length": 0, "engine": ""} for n in names]

    @abstractmethod
    async def list_views(self, database: str) -> list[str]: ...

    @abstractmethod
    async def list_routines(self, database: str) -> list[tuple[str, str]]: ...

    @abstractmethod
    async def get_table_info(self, database: str, table: str) -> TableInfo: ...

    # ---- query ----

    @abstractmethod
    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult: ...

    @abstractmethod
    async def execute_many(self, sql: str, params_list: list[tuple]) -> int: ...

    @abstractmethod
    async def fetch_page(
        self, database: str, table: str,
        offset: int, limit: int,
        order_by: str | None = None,
        order_dir: str = "ASC",
    ) -> QueryResult: ...

    @abstractmethod
    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int: ...

    @abstractmethod
    async def update_row(
        self, database: str, table: str,
        values: dict, where: dict,
    ) -> int: ...

    @abstractmethod
    async def delete_row(self, database: str, table: str, where: dict) -> int: ...
