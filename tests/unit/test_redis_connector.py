"""Tests for Redis connector — uses mock redis.asyncio client."""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_navicat.drivers.redis_connector import RedisConnector
from open_navicat.errors import DriverNotFoundError
from open_navicat.models import ConnectionInfo


@contextmanager
def _fake_redis_module(*, side_effect: BaseException | None = None):
    """Install a fake ``redis`` package exposing ``redis.asyncio.Redis``.

    ``import redis.asyncio as x`` resolves the submodule as an *attribute* of the
    parent package, so patching ``sys.modules["redis.asyncio"]`` alone is not
    enough: the parent module must expose it too.

    Yields the fake client module so callers can inspect the constructor kwargs.
    """
    client = AsyncMock()
    if side_effect is not None:
        client.ping = AsyncMock(side_effect=side_effect)
    else:
        client.ping = AsyncMock(return_value=True)

    aioredis = MagicMock()
    aioredis.Redis = MagicMock(return_value=client)

    package = types.ModuleType("redis")
    package.asyncio = aioredis
    # The real redis package is usually already imported, and `import` hits the
    # cache before sys.modules patching can matter — so shadow it explicitly by
    # saving the originals and restoring them afterwards.
    saved = {
        name: sys.modules.get(name) for name in ("redis", "redis.asyncio", "redis.asyncio.client")
    }
    for name in list(saved):
        sys.modules.pop(name, None)

    sys.modules["redis"] = package
    sys.modules["redis.asyncio"] = aioredis
    try:
        yield aioredis
    finally:
        for name in ("redis", "redis.asyncio", "redis.asyncio.client"):
            sys.modules.pop(name, None)
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module


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
    async def test_connect_without_redis_is_a_typed_driver_error(self, conn_info) -> None:
        # Returning False hid the reason behind "Could not connect to the server.";
        # a missing driver must raise DriverNotFoundError (AGENTS.md contract).
        c = RedisConnector(conn_info)
        with patch.dict("sys.modules", {"redis": None, "redis.asyncio": None}):
            with pytest.raises(DriverNotFoundError):
                await c.connect()

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
        """connect() reaches Redis client construction and reports failure.

        The client itself is mocked: connecting to a real 127.0.0.1:6379 made
        this test depend on whether a server happened to be listening, and the
        failure then waited for the full socket timeout.
        """
        with _fake_redis_module(side_effect=ConnectionError("refused")):
            c = RedisConnector(conn_info)
            assert await c.connect() is False
        assert c.last_error is not None
        assert c._redis is None

    async def test_connect_succeeds_with_mock(self, conn_info) -> None:
        with _fake_redis_module():
            c = RedisConnector(conn_info)
            assert await c.connect() is True
            assert await c.is_connected() is True
            assert await c.ping() is True
            await c.disconnect()
        assert await c.is_connected() is False

    async def test_connect_maps_database_index(self, conn_info) -> None:
        """info.database carries the Redis db number, not a database name."""
        with _fake_redis_module() as client:
            c = RedisConnector(conn_info)
            await c.connect()
        assert client.Redis.call_args.kwargs["db"] == 0
        assert client.Redis.call_args.kwargs["decode_responses"] is True

    async def test_connect_passes_credentials(self, conn_info) -> None:
        with _fake_redis_module() as client:
            info = conn_info
            info.user = "appuser"
            info.password = "sekret"
            c = RedisConnector(info)
            await c.connect()
        kwargs = client.Redis.call_args.kwargs
        assert kwargs["username"] == "appuser"
        assert kwargs["password"] == "sekret"

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

    async def test_execute_unrouted_command_goes_to_server(self, conn_info) -> None:
        # Only a handful of commands have a shaped route; everything else is
        # forwarded, so the server answers it rather than this driver.
        mock_redis = AsyncMock()
        mock_redis.execute_command = AsyncMock(return_value={"field": "value", "n": "1"})
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute("HGETALL myhash")
        assert result.success is True
        mock_redis.execute_command.assert_called_once_with("HGETALL", "myhash")
        assert result.rows == [["field", "value"], ["n", "1"]]

    async def test_execute_command_error_surfaces_as_failure(self, conn_info) -> None:
        mock_redis = AsyncMock()
        mock_redis.execute_command = AsyncMock(side_effect=RuntimeError("ERR unknown command"))
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute("SUBSCRIBE ch1")
        assert result.success is False
        assert "unknown command" in result.error_message

    async def test_quoted_argument_keeps_its_spaces(self, conn_info) -> None:
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute('SET note "see you friday"')
        assert result.success is True
        mock_redis.set.assert_called_once_with("note", "see you friday")

    async def test_execute_list_reply(self, conn_info) -> None:
        mock_redis = AsyncMock()
        mock_redis.execute_command = AsyncMock(return_value=[b"alpha", b"beta"])
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute("LRANGE list 0 -1")
        assert result.rows == [["alpha"], ["beta"]]

    async def test_execute_empty_reply(self, conn_info) -> None:
        mock_redis = AsyncMock()
        mock_redis.execute_command = AsyncMock(return_value=None)
        c = RedisConnector(conn_info)
        c._redis = mock_redis
        result = await c.execute("SETNX missing yes")
        assert result.success is True
        assert result.row_count == 0
