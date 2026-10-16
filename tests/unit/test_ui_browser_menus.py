"""Tests for the object browser's engine-aware maintenance and object menus.

Phase 5 added new node types (procedure, function, trigger, table_detail,
column, index, constraint) that had no context menu at all, and the maintenance
and routine actions hard-coded MySQL backticks / ``DROP PROCEDURE`` for every
engine.  These tests pin the per-engine behaviour.  QMessageBox is stubbed at
module level (the handlers no longer re-import it locally) so no modal dialog
can block the suite.
"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

if not isinstance(QApplication, type):  # pragma: no cover - mocked environment
    pytest.skip("PySide6 is mocked in this environment", allow_module_level=True)

from open_navicat.models.connection import ConnectionInfo  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class _StubMessageBox:
    """Non-blocking stand-in for QMessageBox; questions always answer Yes."""

    class StandardButton:
        Yes = 1
        No = 0

    def __init__(self) -> None:
        self.info_calls: list[tuple] = []
        self.warn_calls: list[tuple] = []

    def question(self, *args, **kwargs):
        return self.StandardButton.Yes

    def information(self, *args, **kwargs):
        self.info_calls.append(args)

    def warning(self, *args, **kwargs):
        self.warn_calls.append(args)


class _StubWindow:
    def __init__(self):
        self.tabs: list[tuple[str, str, str]] = []

    def open_query_tab(self, conn_id, database, sql):
        self.tabs.append((conn_id, database, sql))


class FakeConnector:
    def __init__(self, engine="mysql"):
        self._info = ConnectionInfo(id="c1", name="Fake", engine=engine)
        self.executed: list[str] = []

    async def execute(self, sql, *args, **kwargs):
        self.executed.append(sql)


def _module():
    return importlib.import_module("open_navicat.ui.widgets.object_browser")


@pytest.fixture
def browser(monkeypatch, qt_app):
    """A real ObjectBrowser over a fake pool, with message boxes stubbed out."""
    module = _module()
    fake = FakeConnector()
    pool_module = importlib.import_module("open_navicat.dal.connection_pool")
    monkeypatch.setattr(pool_module.connection_pool, "get", lambda cid: fake)
    monkeypatch.setattr(module.connection_pool, "get", lambda cid: fake)
    boxes = _StubMessageBox()
    monkeypatch.setattr(module, "QMessageBox", boxes)
    widget = module.ObjectBrowser()
    yield widget, fake, boxes
    widget.deleteLater()


def _node(widget, data):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QTreeWidgetItem

    item = QTreeWidgetItem(widget)
    item.setData(0, Qt.ItemDataRole.UserRole, data)
    return item


def _maintenance(engine, op, db, table):
    return _module()._maintenance_sql(engine, op, db, table)


def _actions(engine):
    return _module()._maintenance_actions(engine)


class TestMaintenanceSql:
    """_maintenance_sql: the statement each engine actually accepts."""

    def test_mysql_keeps_all_four_operations(self) -> None:
        assert _maintenance("mysql", "check", "shop", "orders") == "CHECK TABLE `shop`.`orders`"
        assert _maintenance("mysql", "optimize", "shop", "orders") == "OPTIMIZE TABLE `shop`.`orders`"
        assert _maintenance("mysql", "repair", "shop", "orders") == "REPAIR TABLE `shop`.`orders`"
        assert _maintenance("mysql", "analyze", "shop", "orders") == "ANALYZE TABLE `shop`.`orders`"

    def test_postgresql_has_no_check_or_repair(self) -> None:
        assert _maintenance("postgresql", "check", "shop", "orders") is None
        assert _maintenance("postgresql", "repair", "shop", "orders") is None
        assert _maintenance("postgresql", "analyze", "shop", "orders") == 'ANALYZE "shop"."orders"'
        assert _maintenance("postgresql", "vacuum", "shop", "orders") == 'VACUUM (ANALYZE) "shop"."orders"'

    def test_sqlite_analyze_and_reindex(self) -> None:
        assert _maintenance("sqlite", "analyze", "shop", "orders") == 'ANALYZE "orders"'
        assert _maintenance("sqlite", "reindex", "shop", "orders") == 'REINDEX "orders"'
        assert _maintenance("sqlite", "check", "shop", "orders") is None

    def test_sqlserver_uses_dbcc_and_update_statistics(self) -> None:
        assert _maintenance("sqlserver", "check", "shop", "orders") == "DBCC CHECKTABLE ('shop.orders')"
        assert _maintenance("sqlserver", "analyze", "shop", "orders") == "UPDATE STATISTICS [shop].[orders]"
        assert _maintenance("sqlserver", "optimize", "shop", "orders") is None

    def test_clickhouse_and_oracle(self) -> None:
        assert _maintenance("clickhouse", "optimize", "shop", "orders") == "OPTIMIZE TABLE `shop`.`orders`"
        assert _maintenance("oracle", "analyze", "SHOP", "ORDERS") == 'ANALYZE TABLE "SHOP"."ORDERS" COMPUTE STATISTICS'

    def test_unknown_operation_is_refused(self) -> None:
        assert _maintenance("mysql", "vacuum", "shop", "orders") is None


class TestMaintenanceActions:
    def test_menu_offers_what_the_engine_supports(self) -> None:
        assert [op for op, _ in _actions("mysql")] == ["check", "optimize", "repair", "analyze"]
        assert [op for op, _ in _actions("postgresql")] == ["analyze", "vacuum"]
        assert [op for op, _ in _actions("sqlite")] == ["analyze", "reindex"]
        assert [op for op, _ in _actions("mongodb")] == []

    def test_every_action_has_a_statement(self) -> None:
        for engine in ("mysql", "postgresql", "sqlite", "sqlserver", "clickhouse", "oracle"):
            for op, _ in _actions(engine):
                assert _maintenance(engine, op, "shop", "orders") is not None, (
                    f"{engine}/{op} advertised but unsupported"
                )


class TestShowCreateSql:
    """_show_create_sql picks the right catalogue query per engine."""

    @pytest.mark.parametrize(
        "engine,kind,expected",
        [
            ("mysql", "procedure", "SHOW CREATE PROCEDURE `shop`.`do_report`;"),
            ("mariadb", "function", "SHOW CREATE FUNCTION `shop`.`calc_tax`;"),
            ("postgresql", "function", "pg_get_functiondef"),
            ("sqlserver", "procedure", "sys.sql_modules"),
            ("mysql", "trigger", "SHOW CREATE TRIGGER `shop`.`trg_audit`;"),
            ("postgresql", "trigger", "pg_get_triggerdef"),
            ("sqlite", "trigger", "sqlite_master"),
            ("sqlserver", "trigger", "sys.triggers"),
        ],
    )
    def test_definition_query_per_engine(self, browser, monkeypatch, engine, kind, expected) -> None:
        widget, fake, _ = browser
        fake._info = ConnectionInfo(id="c1", name="Fake", engine=engine)
        stub = _StubWindow()
        monkeypatch.setattr(type(widget), "window", lambda self: stub, raising=False)
        data = {
            "type": kind,
            "name": {"procedure": "do_report", "function": "calc_tax", "trigger": "trg_audit"}[kind],
            "database": "shop",
            "connection_id": "c1",
            "parent": "orders",
        }
        widget._show_create_sql(_node(widget, data), kind)
        assert stub.tabs, "no query tab opened"
        assert expected in stub.tabs[0][2]

    def test_type_suffix_is_stripped(self, browser, monkeypatch) -> None:
        widget, fake, _ = browser
        stub = _StubWindow()
        monkeypatch.setattr(type(widget), "window", lambda self: stub, raising=False)
        widget._show_create_sql(
            _node(
                widget,
                {"type": "function", "name": "calc_tax (FUNCTION)", "database": "shop", "connection_id": "c1"},
            ),
            "function",
        )
        assert "`calc_tax`" in stub.tabs[0][2]

    def test_unsupported_engine_reports_instead_of_sending_sql(self, browser, monkeypatch) -> None:
        widget, fake, boxes = browser
        fake._info = ConnectionInfo(id="c1", name="Fake", engine="mongodb")
        stub = _StubWindow()
        monkeypatch.setattr(type(widget), "window", lambda self: stub, raising=False)
        widget._show_create_sql(
            _node(widget, {"type": "trigger", "name": "trg", "database": "shop", "connection_id": "c1"}),
            "trigger",
        )
        assert stub.tabs == []
        # the formatted message interpolates the engine name in every locale
        assert boxes.info_calls and "mongodb" in boxes.info_calls[0][2]


class TestDropObjects:
    def test_drop_function_uses_function_verb(self, browser) -> None:
        widget, fake, _ = browser
        widget._drop_routine(
            _node(
                widget,
                {"type": "function", "name": "calc_tax", "database": "shop", "connection_id": "c1"},
            )
        )
        assert fake.executed == ["DROP FUNCTION IF EXISTS `shop`.`calc_tax`"]

    def test_drop_procedure_uses_procedure_verb(self, browser) -> None:
        widget, fake, _ = browser
        widget._drop_routine(
            _node(
                widget,
                {"type": "procedure", "name": "do_report", "database": "shop", "connection_id": "c1"},
            )
        )
        assert fake.executed == ["DROP PROCEDURE IF EXISTS `shop`.`do_report`"]

    def test_drop_trigger_postgresql_needs_the_table(self, browser) -> None:
        widget, fake, _ = browser
        fake._info = ConnectionInfo(id="c1", name="Fake", engine="postgresql")
        widget._drop_trigger(
            _node(
                widget,
                {
                    "type": "trigger",
                    "name": "trg_audit",
                    "parent": "orders",
                    "database": "shop",
                    "connection_id": "c1",
                },
            )
        )
        assert fake.executed == ['DROP TRIGGER IF EXISTS "trg_audit" ON "shop"."orders"']

    def test_drop_trigger_without_table_is_refused(self, browser) -> None:
        widget, fake, boxes = browser
        fake._info = ConnectionInfo(id="c1", name="Fake", engine="postgresql")
        widget._drop_trigger(
            _node(
                widget,
                {"type": "trigger", "name": "trg_audit", "parent": "", "database": "shop", "connection_id": "c1"},
            )
        )
        assert fake.executed == []
        assert boxes.warn_calls and "DROP" in boxes.warn_calls[0][2]

    def test_drop_trigger_sqlite_needs_no_table(self, browser) -> None:
        widget, fake, _ = browser
        fake._info = ConnectionInfo(id="c1", name="Fake", engine="sqlite")
        widget._drop_trigger(
            _node(
                widget,
                {"type": "trigger", "name": "trg_audit", "database": "shop", "connection_id": "c1"},
            )
        )
        assert fake.executed == ['DROP TRIGGER IF EXISTS "trg_audit"']


class TestCopyObjectName:
    def test_name_lands_on_the_clipboard(self, browser, qt_app) -> None:
        widget, _, _ = browser
        widget._copy_object_name(
            _node(widget, {"type": "column", "name": "order_id", "connection_id": "c1"})
        )
        assert qt_app.clipboard().text() == "order_id"


class TestMaintenanceDispatch:
    def test_engine_aware_statement_is_executed(self, browser) -> None:
        widget, fake, _ = browser
        fake._info = ConnectionInfo(id="c1", name="Fake", engine="postgresql")
        widget._maintenance("analyze", "orders", "c1", "shop")
        assert fake.executed == ['ANALYZE "shop"."orders"']

    def test_unsupported_operation_warns_and_does_not_run_sql(self, browser) -> None:
        widget, fake, boxes = browser
        fake._info = ConnectionInfo(id="c1", name="Fake", engine="sqlite")
        widget._maintenance("repair", "orders", "c1", "shop")
        assert fake.executed == []
        assert boxes.warn_calls and "repair" in boxes.warn_calls[0][2]

