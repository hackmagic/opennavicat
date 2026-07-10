"""Tests for MongoDB connector — uses mock motor client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_navicat.dal.mongo_connector import MongoConnector, _python_type_to_str
from open_navicat.models import ConnectionInfo


@pytest.fixture
def conn_info() -> ConnectionInfo:
    return ConnectionInfo(
        id="m1",
        name="test_mongo",
        engine="mongodb",
        host="127.0.0.1",
        port=27017,
        database="testdb",
    )


class TestPythonTypeToStr:
    def test_none(self) -> None:
        assert _python_type_to_str(None) == "null"

    def test_bool(self) -> None:
        assert _python_type_to_str(True) == "bool"

    def test_int(self) -> None:
        assert _python_type_to_str(42) == "int64"

    def test_float(self) -> None:
        assert _python_type_to_str(3.14) == "double"

    def test_str(self) -> None:
        assert _python_type_to_str("hello") == "string"

    def test_list(self) -> None:
        assert _python_type_to_str([1, 2]) == "array"

    def test_dict(self) -> None:
        assert _python_type_to_str({"a": 1}) == "object"


class TestMongoConnector:
    async def test_connect_fails_without_motor(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        with patch.dict("sys.modules", {"motor": None, "motor.motor_asyncio": None}):
            result = await c.connect()
            assert result is False

    async def test_disconnect_when_not_connected(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        await c.disconnect()  # should not raise

    async def test_is_connected_when_none(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.is_connected() is False

    async def test_ping_when_none(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.ping() is False

    async def test_list_databases_when_none(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.list_databases() == []

    async def test_list_tables_when_none(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.list_tables("db") == []

    async def test_list_views_when_none(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.list_views("db") == []

    async def test_list_routines_always_empty(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.list_routines("db") == []

    async def test_execute_returns_error(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        result = await c.execute("SELECT 1")
        assert result.success is False
        assert "SQL" in result.error_message or "not support" in result.error_message.lower()

    async def test_execute_many_returns_zero(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.execute_many("INSERT", []) == 0

    async def test_get_table_info_when_none(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        info = await c.get_table_info("db", "coll")
        assert info.name == "coll"
        assert info.engine == "MongoDB"

    async def test_batch_insert_when_none(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.batch_insert("db", "coll", [{"k": "v"}]) == 0

    async def test_update_row_when_none(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.update_row("db", "coll", {"a": 1}, {"_id": "x"}) == 0

    async def test_delete_row_when_none(self, conn_info) -> None:
        c = MongoConnector(conn_info)
        assert await c.delete_row("db", "coll", {"_id": "x"}) == 0
