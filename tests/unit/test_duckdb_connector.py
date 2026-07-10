"""Tests for DuckDB connector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from open_navicat.dal.duckdb_connector import DuckDBConnector
from open_navicat.models import ConnectionInfo


@pytest.fixture
def conn_info() -> ConnectionInfo:
    return ConnectionInfo(
        id="d1",
        name="test_duck",
        engine="duckdb",
        database=":memory:",
    )


class TestDuckDBConnector:
    async def test_connect_in_memory(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        result = await c.connect()
        assert result is True

    async def test_disconnect(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        await c.disconnect()
        assert await c.is_connected() is False

    async def test_ping(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        assert await c.ping() is True

    async def test_list_databases(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        dbs = await c.list_databases()
        assert len(dbs) > 0

    async def test_execute_select(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        result = await c.execute("SELECT 1 AS x")
        assert result.success is True
        assert result.is_select is True
        assert len(result.rows) == 1
        assert result.columns is not None

    async def test_execute_invalid(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        result = await c.execute("BROKEN SQL")
        assert result.success is False

    async def test_fetch_page(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        await c.execute("CREATE TABLE test_page (id INTEGER, name VARCHAR)")
        await c.execute("INSERT INTO test_page VALUES (1, 'a'), (2, 'b'), (3, 'c')")
        result = await c.fetch_page("", "test_page", 0, 2)
        assert len(result.rows) == 2

    async def test_batch_insert(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        await c.execute("CREATE TABLE test_batch (id INTEGER, name VARCHAR)")
        count = await c.batch_insert("", "test_batch", [{"id": 1, "name": "x"}, {"id": 2, "name": "y"}])
        assert count == 2

    async def test_update_row(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        await c.execute("CREATE TABLE test_upd (id INTEGER, name VARCHAR)")
        await c.execute("INSERT INTO test_upd VALUES (1, 'old')")
        ok = await c.update_row("", "test_upd", {"name": "new"}, "id", 1)
        assert ok is True
        result = await c.execute("SELECT name FROM test_upd WHERE id = 1")
        assert result.rows[0][0] == "new"

    async def test_delete_row(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        await c.execute("CREATE TABLE test_del (id INTEGER)")
        await c.execute("INSERT INTO test_del VALUES (1)")
        ok = await c.delete_row("", "test_del", "id", 1)
        assert ok is True
        result = await c.execute("SELECT COUNT(*) FROM test_del")
        assert result.rows[0][0] == 0

    async def test_get_table_info(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        await c.execute("CREATE TABLE test_info (id INTEGER, name VARCHAR)")
        info = await c.get_table_info("", "test_info")
        assert info.name == "test_info"
        assert len(info.columns) == 2

    async def test_execute_many(self, conn_info) -> None:
        c = DuckDBConnector(conn_info)
        await c.connect()
        await c.execute("CREATE TABLE test_many (id INTEGER)")
        count = await c.execute_many("INSERT INTO test_many VALUES (?)", [(1,), (2,)])
        assert count == 2
