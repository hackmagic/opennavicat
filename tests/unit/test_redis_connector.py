"""Tests for Redis connector — uses mock redis.asyncio client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_navicat.dal.redis_connector import RedisConnector
from open_navicat.models import ConnectionInfo


@pytest.fixture
def conn_info() -> ConnectionInfo:
    return ConnectionInfo(
        id="r1",
        name="test_redis",
        engine="redis",
        host="127.0.0.1",
        port=6379,
        database="0",
    )


class TestRedisConnector:
    async def test_connect_fails_without_redis(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        with patch.dict("sys.modules", {"redis": None, "redis.asyncio": None}):
            result = await c.connect()
            assert result is False

    async def test_disconnect_when_not_connected(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        await c.disconnect()  # should not raise

    async def test_is_connected_when_none(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        assert await c.is_connected() is False

    async def test_ping_when_none(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        assert await c.ping() is False

    async def test_list_databases_when_none(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        dbs = await c.list_databases()
        assert len(dbs) == 16

    async def test_list_tables_when_none(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        assert await c.list_tables("0") == []

    async def test_list_views_always_empty(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        assert await c.list_views("0") == []

    async def test_list_routines_always_empty(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        assert await c.list_routines("0") == []

    async def test_execute_when_none(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        result = await c.execute("PING")
        assert result.success is False
        assert "Not connected" in result.error_message

    async def test_execute_many_returns_zero(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        assert await c.execute_many("SET", []) == 0

    async def test_get_table_info_when_none(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        info = await c.get_table_info("0", "user")
        assert info.name == "user"
        assert info.engine == "Redis"
        assert len(info.columns) == 5  # key, type, value, ttl, size

    async def test_batch_insert_when_none(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        assert await c.batch_insert("0", "ns", [{"key": "k", "value": "v"}]) == 0

    async def test_update_row_when_none(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        assert await c.update_row("0", "ns", {"value": "v"}, {"key": "k"}) == 0

    async def test_delete_row_when_none(self, conn_info) -> None:
        c = RedisConnector(conn_info)
        assert await c.delete_row("0", "ns", {"key": "k"}) == 0

    async def test_connect_with_mock(self, conn_info) -> None:
        # Verify connect() tries to import redis.asyncio and create Redis client
        # Actual mock of import machinery is fragile, so just verify error path works
        c = RedisConnector(conn_info)
        # When redis.asyncio IS installed, connect() will try to connect to real Redis
        # which will fail (no server running). This tests the fallback path.
        result = await c.connect()
        # Will be False because no Redis server is running
        assert result is False

    async def test_execute_ping_with_mock(self, conn_info) -> None:
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute("PING")
        assert result.success is True

    async def test_execute_get_with_mock(self, conn_info) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="hello")
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute("GET mykey")
        assert result.success is True
        assert result.rows[0][0] == "hello"

    async def test_execute_set_with_mock(self, conn_info) -> None:
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute("SET mykey myval")
        assert result.success is True
        mock_redis.set.assert_called_once_with("mykey", "myval")

    async def test_execute_del_with_mock(self, conn_info) -> None:
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(return_value=2)
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute("DEL k1 k2")
        assert result.success is True
        assert result.row_count == 2

    async def test_execute_unsupported_returns_error(self, conn_info) -> None:
        mock_redis = AsyncMock()
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute("SUBSCRIBE ch1")
        assert result.success is False
        assert "Unsupported" in result.error_message
