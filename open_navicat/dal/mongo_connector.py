"""MongoDB connector — async driver backed by motor."""

from __future__ import annotations

import time
from typing import Any

from open_navicat.dal.base_connector import BaseConnector
from open_navicat.models import (
    ColumnInfo,
    ColumnMeta,
    ConnectionInfo,
    DatabaseInfo,
    IndexInfo,
    QueryResult,
    TableInfo,
)

# ponytail: motor is optional — import guarded, fails at connect() if missing


def _python_type_to_str(val: Any) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "bool"
    if isinstance(val, int):
        return "int64"
    if isinstance(val, float):
        return "double"
    if isinstance(val, str):
        return "string"
    if isinstance(val, list):
        return "array"
    if isinstance(val, dict):
        return "object"
    return type(val).__name__


class MongoConnector(BaseConnector):
    """Async MongoDB connector using motor."""

    def __init__(self, info: ConnectionInfo) -> None:
        self._info = info
        self._client: Any = None  # motor.motor_asyncio.AsyncIOMotorClient

    async def connect(self) -> bool:
        try:
            import motor.motor_asyncio as _motor  # noqa: F811
        except ImportError:
            return False
        try:
            auth = ""
            if self._info.user:
                auth = f"{self._info.user}:{self._info.password}@"
            db_part = self._info.database or ""
            uri = f"mongodb://{auth}{self._info.host}:{self._info.port}/{db_part}"
            self._client = _motor.AsyncIOMotorClient(
                uri,
                serverSelectionTimeoutMS=self._info.connect_timeout * 1000,
            )
            await self._client.admin.command("ping")
            return True
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    async def is_connected(self) -> bool:
        if not self._client:
            return False
        try:
            await self._client.admin.command("ping")
            return True
        except Exception:
            return False

    async def ping(self) -> bool:
        return await self.is_connected()

    # ---- metadata ----

    async def list_databases(self) -> list[DatabaseInfo]:
        if not self._client:
            return []
        dbs = await self._client.list_database_names()
        result = []
        for name in dbs:
            if name in ("admin", "local", "config"):
                continue
            try:
                stats = await self._client[name].command("dbStats")
                size = stats.get("dataSize", 0)
            except Exception:
                size = 0
            result.append(DatabaseInfo(name=name, size_bytes=size))
        return result

    async def list_tables(self, database: str) -> list[str]:
        if not self._client:
            return []
        colls = await self._client[database].list_collection_names()
        return sorted(colls)

    async def list_views(self, database: str) -> list[str]:
        if not self._client:
            return []
        try:
            views = []
            async for coll in self._client[database].list_collections():
                if coll.get("type") == "view":
                    views.append(coll["name"])
            return views
        except Exception:
            return []

    async def list_routines(self, database: str) -> list[tuple[str, str]]:
        return []

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        info = TableInfo(name=table, database=database, engine="MongoDB")
        if not self._client:
            return info
        coll = self._client[database][table]
        # Infer schema from sample documents
        fields: dict[str, str] = {}
        async for doc in coll.find().limit(100):
            for key, val in doc.items():
                if key == "_id":
                    continue
                t = _python_type_to_str(val)
                if key not in fields:
                    fields[key] = t
        # _id is always present
        info.columns.append(ColumnInfo(name="_id", data_type="objectId", is_primary_key=True))
        for name, dtype in sorted(fields.items()):
            info.columns.append(ColumnInfo(name=name, data_type=dtype))
        try:
            info.row_count = await coll.count_documents({})
        except Exception:
            pass
        # Indexes
        async for idx in coll.list_indexes():
            cols = [k for k in idx["key"]]
            info.indexes.append(
                IndexInfo(
                    name=idx["name"], columns=cols, is_unique=idx.get("unique", False),
                )
            )
        return info

    # ---- query ----

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        # MongoDB doesn't support raw SQL — return hint
        return QueryResult(
            success=False,
            error_message="MongoDB does not support SQL. Use the data browser or collection methods instead.",
        )

    async def execute_many(self, sql: str, params_list: list[tuple]) -> int:
        return 0

    async def fetch_page(
        self, database: str, table: str,
        offset: int, limit: int,
        order_by: str | None = None,
        order_dir: str = "ASC",
    ) -> QueryResult:
        if not self._client:
            return QueryResult(success=False, error_message="Not connected")
        start = time.monotonic()
        try:
            coll = self._client[database][table]
            cursor = coll.find()
            if order_by:
                direction = 1 if order_dir.upper() == "ASC" else -1
                cursor = cursor.sort(order_by, direction)
            cursor = cursor.skip(offset).limit(limit)
            docs = await cursor.to_list(length=limit)
            if not docs:
                return QueryResult(success=True, row_count=0)
            # Collect all field names across docs
            field_set: dict[str, int] = {}
            for doc in docs:
                for k in doc:
                    if k not in field_set:
                        field_set[k] = len(field_set)
            columns = [ColumnMeta(name=k, data_type="dynamic") for k in sorted(field_set, key=field_set.get)]
            rows = []
            for doc in docs:
                row = [doc.get(c.name) for c in columns]
                rows.append(row)
            elapsed = (time.monotonic() - start) * 1000
            return QueryResult(
                success=True, columns=columns, rows=rows,
                row_count=len(rows), execution_time_ms=elapsed,
            )
        except Exception as e:
            return QueryResult(success=False, error_message=str(e))

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if not self._client or not rows:
            return 0
        try:
            result = await self._client[database][table].insert_many(rows)
            return len(result.inserted_ids)
        except Exception:
            return 0

    async def update_row(
        self, database: str, table: str,
        values: dict, where: dict,
    ) -> int:
        if not self._client:
            return 0
        try:
            result = await self._client[database][table].update_one(where, {"$set": values})
            return result.modified_count
        except Exception:
            return 0

    async def delete_row(self, database: str, table: str, where: dict) -> int:
        if not self._client:
            return 0
        try:
            result = await self._client[database][table].delete_one(where)
            return result.deleted_count
        except Exception:
            return 0
