"""Tests for the object browser's index and search wiring.

The browser used to filter only the item text already rendered in the tree, so a
table in an unexpanded database could not be found.  These tests drive the real
widget against a fake connector and assert that a search reaches objects that were
never opened by hand.
"""

from __future__ import annotations

import pytest

# The rest of the suite only import-checks UI modules because CI may run without
# PySide6.  These tests drive a real widget, so they need the real thing: when
# PySide6 is mocked they are skipped rather than asserting against MagicMocks.
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

if not isinstance(QApplication, type):  # pragma: no cover - mocked environment
    pytest.skip("PySide6 is mocked in this environment", allow_module_level=True)

from open_navicat.models.connection import ConnectionInfo  # noqa: E402
from open_navicat.models.table_schema import (  # noqa: E402
    ColumnInfo,
    IndexInfo,
    TableInfo,
)
from open_navicat.services.object_catalog import (  # noqa: E402
    Catalog,
    ObjectKind,
    objects_from_names,
)


@pytest.fixture(scope="module")
def qt_app():
    """A QApplication is required before any widget can be constructed."""
    app = QApplication.instance() or QApplication([])
    yield app


class FakeConnector:
    """Stand-in connector exposing only what the browser reads."""

    def __init__(self) -> None:
        self._info = ConnectionInfo(id="c1", name="Fake", engine="mysql")
        self.trigger_calls = 0

    async def list_databases(self):
        from open_navicat.models import DatabaseInfo

        return [DatabaseInfo(name="shop", charset="utf8", collation="")]

    async def list_tables(self, database: str) -> list[str]:
        return ["orders", "customers"]

    async def list_views(self, database: str) -> list[str]:
        return ["v_orders"]

    async def list_routines(self, database: str):
        return [("do_report", "PROCEDURE"), ("calc_tax", "FUNCTION")]

    async def list_triggers(self, database: str):
        self.trigger_calls += 1
        return [("trg_audit", "orders")]

    async def get_table_info(self, database: str, table: str) -> TableInfo:
        return TableInfo(
            name=table,
            database=database,
            columns=[ColumnInfo(name="id", data_type="int", is_primary_key=True)],
            indexes=[IndexInfo(name="idx_id", columns=["id"], is_unique=True)],
        )


@pytest.fixture
def browser(monkeypatch, qt_app):
    """A real ObjectBrowser with the connection pool replaced by a fake.

    ``import open_navicat.dal.connection_pool as x`` would bind the *pool
    singleton* rather than the module, because ``dal/__init__`` re-exports it, so
    the module is fetched through importlib to be patched unambiguously.
    """
    import importlib

    pool_module = importlib.import_module("open_navicat.dal.connection_pool")
    module = importlib.import_module("open_navicat.ui.widgets.object_browser")

    fake = FakeConnector()
    monkeypatch.setattr(pool_module.connection_pool, "get", lambda cid: fake)
    monkeypatch.setattr(module.connection_pool, "get", lambda cid: fake)

    widget = module.ObjectBrowser()
    yield widget, fake
    widget.deleteLater()


class TestCatalogIndexing:
    def test_catalogs_start_empty(self, browser) -> None:
        widget, _ = browser
        assert widget._catalogs == {}

    def test_search_is_empty_before_anything_is_expanded(self, browser) -> None:
        widget, _ = browser
        assert widget.search_objects("orders") == {}

    def test_query_shorter_than_two_characters_is_ignored(self, browser) -> None:
        widget, _ = browser
        widget._catalogs[("c1", "shop")] = __import__(
            "open_navicat.services.object_catalog", fromlist=["Catalog"]
        ).Catalog()
        assert widget.search_objects("o") == {}


class TestExpansionPopulatesTheIndex:
    def _expand(self, widget, database: str = "shop") -> None:
        """Expand a database the way the tree would."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem

        item = QTreeWidgetItem(widget)
        item.setText(0, database)
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "type": "database",
                "name": database,
                "connection_id": "c1",
            },
        )
        for key in (
            "browser.category_tables",
            "browser.category_views",
            "browser.category_procedures",
            "browser.category_functions",
            "browser.category_triggers",
        ):
            child = QTreeWidgetItem(item)
            child.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {
                    "type": "category",
                    "category": key,
                    "connection_id": "c1",
                    "database": database,
                },
            )
        widget._expand_database(item)
        return item

    def test_tables_views_and_routines_are_indexed(self, browser) -> None:
        widget, _ = browser
        self._expand(widget)
        catalog = widget._catalogs[("c1", "shop")]
        names = {o.name for o in catalog}
        assert {"orders", "customers", "v_orders", "do_report", "calc_tax"} <= names

    def test_procedures_and_functions_are_distinguished(self, browser) -> None:
        widget, _ = browser
        self._expand(widget)
        kinds = {o.name: o.kind for o in widget._catalogs[("c1", "shop")]}
        assert kinds["do_report"] is ObjectKind.PROCEDURE
        assert kinds["calc_tax"] is ObjectKind.FUNCTION

    def test_triggers_are_listed_and_record_their_table(self, browser) -> None:
        widget, fake = browser
        self._expand(widget)
        triggers = [o for o in widget._catalogs[("c1", "shop")] if o.kind is ObjectKind.TRIGGER]
        assert len(triggers) == 1
        assert triggers[0].parent == "orders"

    def test_category_rows_carry_a_count(self, browser) -> None:
        widget, _ = browser
        item = self._expand(widget)
        labels = [item.child(i).text(0) for i in range(item.childCount())]
        # The tables category has two objects and shows the count.
        assert any("(2)" in label for label in labels)

    def test_search_finds_objects_after_expansion(self, browser) -> None:
        widget, _ = browser
        self._expand(widget)
        found = widget.search_objects("orders")
        assert found
        names = {o.name for refs in found.values() for o in refs}
        assert "orders" in names
        assert "v_orders" in names

    def test_search_can_match_by_kind(self, browser) -> None:
        widget, _ = browser
        self._expand(widget)
        found = widget.search_objects("trigger")
        names = {o.name for refs in found.values() for o in refs}
        assert names == {"trg_audit"}


class TestTableDetail:
    def test_placeholder_nodes_are_added_under_a_table(self, browser) -> None:
        widget, _ = browser
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem

        table = QTreeWidgetItem(widget)
        table.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "type": "table",
                "name": "orders",
                "database": "shop",
                "connection_id": "c1",
            },
        )
        widget._add_table_children(table, "c1", "shop", "orders")
        kinds = [
            table.child(i).data(0, Qt.ItemDataRole.UserRole)["kind"]
            for i in range(table.childCount())
        ]
        assert kinds == ["column", "index", "constraint"]

    def test_expanding_detail_indexes_columns_and_indexes(self, browser) -> None:
        widget, _ = browser
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem

        node = QTreeWidgetItem(widget)
        node.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "type": "table_detail",
                "kind": "column",
                "table": "orders",
                "database": "shop",
                "connection_id": "c1",
            },
        )
        widget._expand_table_detail(node)
        catalog = widget._catalogs[("c1", "shop")]
        names = {o.name for o in catalog}
        assert "id" in names
        assert "idx_id" in names


class TestSearchResultRendering:
    def test_results_are_rendered_as_a_flat_list(self, browser) -> None:
        widget, _ = browser
        catalog = widget._catalog_for("c1", "shop")

        catalog.add_all(objects_from_names(["orders"], ObjectKind.TABLE, database="shop"))
        widget._show_search_results("orders")

        root = widget._search_results_item
        assert root is not None
        assert root.childCount() == 1  # one connection group
        assert root.child(0).childCount() == 1

    def test_normal_tree_is_hidden_while_searching(self, browser) -> None:
        widget, _ = browser
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem

        other = QTreeWidgetItem(widget)
        other.setData(0, Qt.ItemDataRole.UserRole, {"type": "connection"})
        widget._show_search_results("nothing-matches")
        assert other.isHidden() is True

    def test_search_results_are_cleared(self, browser) -> None:
        widget, _ = browser
        widget._catalog_for("c1", "shop")
        widget._show_search_results("nothing")
        widget._clear_search_results()
        assert widget._search_results_item is None

    def test_no_match_is_reported_in_the_tree(self, browser) -> None:
        widget, _ = browser
        widget._catalog_for("c1", "shop")
        widget._show_search_results("zzz")
        root = widget._search_results_item
        assert root is not None
        assert "zzz" in root.text(0)


class TestLoopAccessor:
    """Regression: the widgets used to capture a possibly-None event loop.

    ``from ...connection_pool import _loop as pool_loop`` bound the module global
    at import time, and that global stays None until something calls
    ``_get_loop()``.  Expanding a database before the first connection therefore
    raised AttributeError.  The accessor resolves the loop when it is used.
    """

    def test_expanding_a_database_works_without_a_prior_connection(
        self, browser, monkeypatch
    ) -> None:
        widget, _ = browser
        import importlib

        pool_module = importlib.import_module("open_navicat.dal.connection_pool")
        # Simulate a fresh process: no loop has been created yet.
        monkeypatch.setattr(pool_module, "_loop", None)

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem

        item = QTreeWidgetItem(widget)
        item.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "type": "database",
                "name": "shop",
                "connection_id": "c1",
            },
        )
        child = QTreeWidgetItem(item)
        child.setData(
            0,
            Qt.ItemDataRole.UserRole,
            {
                "type": "category",
                "category": "browser.category_tables",
                "connection_id": "c1",
                "database": "shop",
            },
        )
        widget._expand_database(item)

        # Tables were listed, so the loop was obtained rather than dereferenced.
        assert child.childCount() == 2

    def test_no_module_binds_the_loop_global_directly(self) -> None:
        import pathlib

        offenders = []
        for path in pathlib.Path("open_navicat").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "import _loop as pool_loop" in text:
                offenders.append(str(path))
        assert offenders == [], f"fragile loop import still present in {offenders}"
