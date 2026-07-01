"""Integration tests for PostgreSQL connector — runs against a live PostgreSQL container."""

from __future__ import annotations

import pytest


@pytest.mark.integration
class TestPostgreSQLConnector:
    """Test PostgreSQLConnector against a real PostgreSQL instance."""

    @pytest.fixture(autouse=True)
    def setup(self, pg_conn_info):
        try:
            import asyncpg
        except ImportError:
            pytest.skip("asyncpg not installed")

        from open_navicat.dal.connection_pool import _loop
        from open_navicat.dal.postgresql_connector import PostgreSQLConnector

        self.info = pg_conn_info
        self.connector = PostgreSQLConnector(pg_conn_info)
        _loop.run_until_complete(self.connector.connect())
        yield
        _loop.run_until_complete(self.connector.disconnect())

    def test_connect(self):
        from open_navicat.dal.connection_pool import _loop
        assert _loop.run_until_complete(self.connector.is_connected())

    def test_ping(self):
        from open_navicat.dal.connection_pool import _loop
        assert _loop.run_until_complete(self.connector.ping())

    def test_list_databases(self):
        from open_navicat.dal.connection_pool import _loop
        dbs = _loop.run_until_complete(self.connector.list_databases())
        names = [db.name for db in dbs]
        assert "testdb" in names

    def test_list_tables(self):
        from open_navicat.dal.connection_pool import _loop
        _loop.run_until_complete(self.connector.execute(
            "CREATE TABLE IF NOT EXISTS test_table ("
            "id SERIAL PRIMARY KEY, "
            "name VARCHAR(50) NOT NULL, "
            "email VARCHAR(100)"
            ")"
        ))
        tables = _loop.run_until_complete(self.connector.list_tables("testdb"))
        assert "test_table" in tables

    def test_execute_select(self):
        from open_navicat.dal.connection_pool import _loop
        _loop.run_until_complete(self.connector.execute(
            "CREATE TABLE IF NOT EXISTS t_select (id INT PRIMARY KEY, val INT)"
        ))
        _loop.run_until_complete(self.connector.execute(
            "INSERT INTO t_select VALUES (1, 100), (2, 200) ON CONFLICT (id) DO UPDATE SET val=EXCLUDED.val"
        ))
        result = _loop.run_until_complete(self.connector.execute("SELECT * FROM t_select ORDER BY id"))
        assert result.rows
        assert len(result.rows) == 2

    def test_execute_insert_update_delete(self):
        from open_navicat.dal.connection_pool import _loop
        _loop.run_until_complete(self.connector.execute(
            "CREATE TABLE IF NOT EXISTS t_crud (id INT PRIMARY KEY, val INT)"
        ))
        # Insert
        _loop.run_until_complete(self.connector.execute(
            "INSERT INTO t_crud VALUES (1, 10) ON CONFLICT (id) DO UPDATE SET val=EXCLUDED.val"
        ))
        # Update
        _loop.run_until_complete(self.connector.execute(
            "UPDATE t_crud SET val=20 WHERE id=1"
        ))
        result = _loop.run_until_complete(self.connector.execute("SELECT val FROM t_crud WHERE id=1"))
        assert result.rows[0][0] == 20
        # Delete
        _loop.run_until_complete(self.connector.execute("DELETE FROM t_crud WHERE id=1"))
        result = _loop.run_until_complete(self.connector.execute("SELECT * FROM t_crud"))
        assert len(result.rows) == 0

    def test_get_table_info(self):
        from open_navicat.dal.connection_pool import _loop
        _loop.run_until_complete(self.connector.execute(
            "CREATE TABLE IF NOT EXISTS t_info ("
            "id SERIAL PRIMARY KEY, "
            "name VARCHAR(50) NOT NULL"
            ")"
        ))
        info = _loop.run_until_complete(
            self.connector.get_table_info("testdb", "t_info")
        )
        assert info is not None
        assert info.name == "t_info"
        assert len(info.columns) >= 2

    def test_fetch_page(self):
        from open_navicat.dal.connection_pool import _loop
        _loop.run_until_complete(self.connector.execute(
            "CREATE TABLE IF NOT EXISTS t_page (id INT PRIMARY KEY, val INT)"
        ))
        for i in range(10):
            _loop.run_until_complete(self.connector.execute(
                f"INSERT INTO t_page VALUES ({i}, {i*10}) ON CONFLICT (id) DO UPDATE SET val=EXCLUDED.val"
            ))
        result = _loop.run_until_complete(
            self.connector.fetch_page("testdb", "t_page", offset=0, limit=5)
        )
        assert len(result.rows) == 5
