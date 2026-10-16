"""Tests for the SQLite connector.

These run against a real temporary database rather than a mock: the connector
builds model objects field by field, and a wrong field name only shows up when
aiosqlite actually hands back rows.
"""

from __future__ import annotations

import pytest

from open_navicat.drivers.sqlite_connector import SQLiteConnector
from open_navicat.models import ConnectionInfo


@pytest.fixture
async def connector(tmp_path):
    info = ConnectionInfo(
        id="s1",
        name="test_sqlite",
        engine="sqlite",
        database=str(tmp_path / "demo.db"),
    )
    c = SQLiteConnector(info)
    assert await c.connect() is True
    yield c
    await c.disconnect()


class TestLifecycle:
    async def test_connect_creates_the_file(self, tmp_path) -> None:
        path = tmp_path / "fresh.db"
        c = SQLiteConnector(
            ConnectionInfo(id="s2", name="fresh", engine="sqlite", database=str(path))
        )
        assert await c.connect() is True
        assert await c.ping() is True
        assert path.exists()
        await c.disconnect()
        assert await c.is_connected() is False

    async def test_connect_bad_path_reports_error(self) -> None:
        c = SQLiteConnector(
            ConnectionInfo(id="s3", name="bad", engine="sqlite", database="/no/such/dir/x.db")
        )
        assert await c.connect() is False
        assert c._last_error is not None


class TestQuery:
    async def test_select_returns_named_columns(self, connector) -> None:
        result = await connector.execute("SELECT 1 AS one, 'x' AS label")
        assert result.success is True
        assert [c.name for c in result.columns] == ["one", "label"]
        assert list(result.rows[0]) == [1, "x"]
        assert result.is_select is True
        assert result.row_count == 1

    async def test_write_reports_affected_rows(self, connector) -> None:
        created = await connector.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        assert created.success is True
        assert created.is_select is False

        inserted = await connector.execute("INSERT INTO t (name) VALUES ('alice')")
        assert inserted.success is True
        assert inserted.affected_rows == 1
        assert inserted.insert_id == 1

    async def test_failed_statement_is_data_not_an_exception(self, connector) -> None:
        result = await connector.execute("SELECT * FROM missing_table")
        assert result.success is False
        assert "missing_table" in result.error_message

    async def test_parametrised_statement(self, connector) -> None:
        await connector.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        await connector.execute("INSERT INTO t (name) VALUES (?)", ("bob",))
        result = await connector.execute("SELECT name FROM t WHERE id = ?", (1,))
        assert result.rows[0][0] == "bob"

    async def test_execute_without_connection(self) -> None:
        c = SQLiteConnector(
            ConnectionInfo(id="s4", name="idle", engine="sqlite", database=":memory:")
        )
        result = await c.execute("SELECT 1")
        assert result.success is False


class TestMetadata:
    async def test_list_tables_and_databases(self, connector) -> None:
        await connector.execute("CREATE TABLE alpha (id INTEGER)")
        await connector.execute("CREATE VIEW beta AS SELECT 1 AS one")
        assert await connector.list_tables("main") == ["alpha"]
        assert await connector.list_views("main") == ["beta"]
        dbs = await connector.list_databases()
        assert dbs and dbs[0].name.endswith(".db")
        assert await connector.list_routines("main") == []

    async def test_get_table_info_reads_the_pragma(self, connector) -> None:
        await connector.execute(
            "CREATE TABLE parent (id INTEGER PRIMARY KEY, note TEXT DEFAULT 'x')"
        )
        await connector.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER, "
            "CONSTRAINT fk_p FOREIGN KEY (parent_id) REFERENCES parent (id) ON DELETE CASCADE)"
        )
        await connector.execute("CREATE INDEX idx_parent ON child (parent_id)")

        info = await connector.get_table_info("main", "parent")
        assert info.name == "parent"
        assert info.database == "main"
        by_name = {c.name: c for c in info.columns}
        assert by_name["id"].is_primary_key is True
        assert by_name["note"].default == "'x'"
        assert by_name["note"].nullable is True

        child = await connector.get_table_info("main", "child")
        fk = child.foreign_keys[0]
        assert (fk.column, fk.ref_table, fk.ref_column) == ("parent_id", "parent", "id")
        assert fk.on_delete == "CASCADE"
        assert [i.name for i in child.indexes if not i.name.startswith("sqlite_")] == ["idx_parent"]


class TestDataHelpers:
    async def test_pages_inserts_and_edits(self, connector) -> None:
        await connector.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        written = await connector.execute_many(
            "INSERT INTO t (name) VALUES (?)", [("a",), ("b",), ("c",)]
        )
        assert written == 3

        page = await connector.fetch_page("main", "t", offset=1, limit=1, order_by="id")
        assert [r[1] for r in page.rows] == ["b"]

        added = await connector.batch_insert("main", "t", [{"name": "d"}])
        assert added == 1
        updated = await connector.update_row("main", "t", {"name": "z"}, {"id": 1})
        assert updated == 1
        assert await connector.delete_row("main", "t", {"id": 1}) == 1

        left = await connector.execute("SELECT COUNT(*) FROM t")
        assert left.rows[0][0] == 3
