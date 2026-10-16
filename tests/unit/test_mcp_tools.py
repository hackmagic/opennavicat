# ruff: noqa: F811
#
# The fixtures in ``mcp_fakes`` are imported here so pytest can see them, and
# the same names appear as test parameters - that is precisely how a test
# requests a fixture, so every F811 on those parameters is intentional.

"""Tests for the MCP tool layer.

No MCP client, no database and no service thread here: ``_submit`` runs
inline and the three service singletons are the fakes from ``mcp_fakes``, so
each tool is exercised as the plain function it is.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

# The fakes live in ``mcp_fakes`` so the protocol test exercises the same
# stand-ins; importing the fixtures into this module is what makes them visible
# to pytest here.
from mcp_fakes import (  # noqa: F401
    FakeConnector,
    FakeManager,
    engine,
    inline,
    manager,
    metadata,
    saved_connection,
    wired,
)

from open_navicat.errors import ERR_POLICY_DENIED
from open_navicat.mcp import safety, tools
from open_navicat.models import ColumnMeta, QueryResult, TableInfo
from open_navicat.models.table_schema import ColumnInfo, ForeignKeyInfo, IndexInfo

# ---- JSON coercion ---------------------------------------------------------


class TestCells:
    def test_amounts_stay_exact(self) -> None:
        assert tools._cell(Decimal("10.50")) == "10.50"

    def test_dates_become_iso_text(self) -> None:
        assert tools._cell(datetime(2026, 9, 30, 8, 0)) == "2026-09-30T08:00:00"

    def test_binary_decodes_or_hexes(self) -> None:
        assert tools._cell(b"hello") == "hello"
        assert tools._cell(b"\xff\xfe") == "fffe"

    def test_nested_structures_survive(self) -> None:
        assert tools._cell({"tags": ["a", b"b"]}) == {"tags": ["a", "b"]}

    def test_unknown_types_are_redacted(self) -> None:
        class Secretive:
            def __repr__(self) -> str:
                return "password=hunter2"

        assert "hunter2" not in tools._cell(Secretive())


class TestEnvelopes:
    def test_ok_carries_the_payload(self) -> None:
        assert tools.ok(a=1) == {"ok": True, "a": 1}

    def test_failure_wraps_a_plain_exception(self) -> None:
        out = tools.failure(ValueError("boom"))
        assert out["ok"] is False
        assert out["error"]["code"]
        assert "boom" in out["error"]["detail"]

    def test_refusal_exposes_the_policy(self) -> None:
        decision = safety.check("DELETE FROM users", tier=safety.TIER_FULL)
        out = tools._refused(decision)
        assert out["ok"] is False
        assert out["error"]["code"] == ERR_POLICY_DENIED
        assert out["policy"]["needsConfirm"] is True


# ---- sessions --------------------------------------------------------------


class TestSessions:
    def test_list_connections_omits_credentials(self, wired) -> None:
        out = tools.list_connections()
        assert out["ok"] is True
        assert out["connections"][0]["user"] == "root"
        assert out["activeIds"] == ["c1"]
        blob = repr(out)
        assert "hunter2" not in blob
        assert "password" not in blob.lower()

    def test_open_session_needs_a_target(self, wired) -> None:
        out = tools.open_session()
        assert out["ok"] is False
        assert out["error"]["code"] == "ONV-CFG-001"

    def test_dsn_session_is_not_persisted(self, wired) -> None:
        manager: FakeManager = wired[0]
        out = tools.open_session(dsn="mysql://bob:pw@db.internal:3306/shop")
        assert out["ok"] is True, out
        assert out["connectionId"]
        assert manager.connect_calls == [(out["connectionId"], False)]
        assert manager.saved == [saved_connection()]  # the DSN target was not saved

    def test_already_open_session_is_reused(self, wired) -> None:
        out = tools.open_session(connection_id="c1")
        assert out["ok"] is True
        assert out["alreadyOpen"] is True
        assert wired[0].connect_calls == []

    def test_failed_open_reports_the_structured_error(self, wired) -> None:
        from open_navicat.errors import DatabaseConnectionError

        manager: FakeManager = wired[0]
        manager.sessions.pop("c1")
        manager.open_ok = False
        manager.last_error = DatabaseConnectionError("host refused")
        out = tools.open_session(connection_id="c1")
        assert out["ok"] is False
        assert out["error"]["source"] == "connection"

    def test_close_session(self, wired) -> None:
        assert tools.close_session("c1")["closed"] is True
        assert wired[0].active_ids == []

    def test_status_lists_sessions_and_tiers(self, wired) -> None:
        out = tools.session_status()
        assert out["sessions"] == [{"connectionId": "c1", "engine": "mysql", "database": "app"}]
        assert out["accessTiers"] == list(safety.TIERS)
        assert any(e["engine"] == "mysql" for e in out["engines"])

    def test_ambiguous_session_is_an_error_not_a_guess(self, wired) -> None:
        wired[0].sessions["c2"] = FakeConnector("mysql", "other")
        out = tools.execute_query("SELECT 1")
        assert out["ok"] is False
        assert out["error"]["code"] == "ONV-CNN-002"
        assert "connection_id" in out["error"]["detail"]

    def test_no_session_open(self, wired) -> None:
        wired[0].sessions.clear()
        out = tools.execute_query("SELECT 1")
        assert out["ok"] is False
        assert "open_session" in out["error"]["detail"]

    def test_a_crash_inside_a_tool_is_still_a_response(self, wired) -> None:
        # An exception on the wire is a protocol error the model cannot read.
        def boom(connection_id: str) -> None:
            raise RuntimeError("the driver exploded")

        wired[0].get_connector = boom
        out = tools.execute_query("SELECT 1")
        assert out["ok"] is False
        assert "the driver exploded" in out["error"]["detail"]


# ---- metadata --------------------------------------------------------------


class TestMetadata:
    def test_list_databases(self, wired) -> None:
        out = tools.list_databases()
        assert out["databases"][0]["name"] == "app"
        assert out["context"]["connectionId"] == "c1"

    def test_tables_views_and_routines(self, wired) -> None:
        out = tools.list_tables(database="app")
        assert out["tables"] == ["users", "orders"]
        assert out["views"] == ["active_users"]
        assert out["routines"] == [{"name": "refresh", "type": "PROCEDURE"}]

    def test_database_defaults_to_the_session(self, wired) -> None:
        assert tools.list_tables()["context"]["database"] == "app"

    def test_missing_database_is_reported(self, wired, metadata) -> None:
        wired[0].sessions = {"c9": FakeConnector("mysql", "")}
        wired[0].saved = [saved_connection("c9", database="")]
        out = tools.list_tables(connection_id="c9")
        assert out["ok"] is False
        assert out["error"]["stage"] == "resolve"

    def test_describe_table_reports_keys_and_ddl(self, wired, metadata) -> None:
        metadata.table_info = TableInfo(
            name="users",
            database="app",
            row_count=12,
            columns=[
                ColumnInfo(name="id", data_type="INT", is_primary_key=True, is_auto_increment=True),
                ColumnInfo(name="email", data_type="VARCHAR", nullable=False, is_unique=True),
            ],
            indexes=[IndexInfo(name="PRIMARY", columns=["id"], is_primary=True)],
            foreign_keys=[
                ForeignKeyInfo(name="fk_o", column="id", ref_table="orders", ref_column="id")
            ],
        )
        out = tools.describe_table("users")
        assert out["ok"] is True, out
        assert out["rowCount"] == 12
        assert out["columns"][0] == {
            "name": "id",
            "type": "INT",
            "nullable": True,
            "primaryKey": True,
            "unique": False,
            "autoIncrement": True,
            "default": None,
            "comment": "",
        }
        assert out["indexes"][0]["primary"] is True
        assert out["foreignKeys"][0]["refTable"] == "orders"
        assert out["createSql"] == "CREATE TABLE users (id INT)"
        assert out["context"] == {
            "connectionId": "c1",
            "engine": "mysql",
            "database": "app",
            "accessTier": "read",
            "risk": "read",
        }

    def test_unknown_table(self, wired, metadata) -> None:
        metadata.table_info = None
        out = tools.describe_table("nope")
        assert out["ok"] is False
        assert "does not exist" in out["error"]["detail"]


# ---- execution -------------------------------------------------------------


class TestExecuteQuery:
    def test_read_runs_and_carries_provenance(self, wired, engine) -> None:
        out = tools.execute_query("SELECT id, total FROM orders")
        assert out["ok"] is True
        assert out["rows"] == [[1, "10.50"]]
        assert out["columns"][0]["name"] == "id"
        assert out["rowCount"] == 1
        assert out["executionTimeMs"] == 1.5
        assert engine.calls == [("c1", "SELECT id, total FROM orders", 30.0)]
        assert out["context"]["engine"] == "mysql"
        assert out["context"]["risk"] == "read"

    def test_personal_columns_are_masked_by_default(self, wired, engine) -> None:
        engine.result = QueryResult(
            success=True,
            columns=[
                ColumnMeta(name="email", data_type="text"),
                ColumnMeta(name="phone", data_type="text"),
            ],
            rows=[["ada@example.com", "12345"]],
            row_count=1,
        )
        out = tools.execute_query("SELECT email, phone FROM users")
        assert out["rows"] == [["redacted@example.com", "xxxxx"]]

    def test_masking_can_be_turned_off(self, wired, engine) -> None:
        engine.result = QueryResult(
            success=True,
            columns=[ColumnMeta(name="email", data_type="text")],
            rows=[["ada@example.com"]],
            row_count=1,
        )
        out = tools.execute_query("SELECT email FROM users", mask=False)
        assert out["rows"] == [["ada@example.com"]]

    def test_rows_are_capped(self, wired, engine) -> None:
        engine.result = QueryResult(
            success=True,
            columns=[ColumnMeta(name="id", data_type="int")],
            rows=[[i] for i in range(5)],
            row_count=5,
        )
        out = tools.execute_query("SELECT id FROM t", limit=2)
        assert out["rows"] == [[0], [1]]
        assert out["truncated"] is True

    def test_limit_is_capped_at_the_maximum(self, wired, engine) -> None:
        engine.result = QueryResult(
            success=True,
            columns=[ColumnMeta(name="id", data_type="int")],
            rows=[[i] for i in range(tools.MAX_ROW_LIMIT + 5)],
            row_count=tools.MAX_ROW_LIMIT + 5,
        )
        out = tools.execute_query("SELECT id FROM t", limit=999999)
        assert len(out["rows"]) == tools.MAX_ROW_LIMIT

    def test_write_is_refused_by_the_default_tier(self, wired, engine) -> None:
        out = tools.execute_query("DELETE FROM users WHERE id = 5")
        assert out["ok"] is False
        assert out["error"]["code"] == "ONV-SEC-001"
        assert "read" in out["error"]["detail"]
        assert out["policy"]["risk"] == "write"
        assert engine.calls == []

    def test_write_at_a_permitted_tier_still_needs_confirmation(self, wired, engine) -> None:
        out = tools.execute_query("DELETE FROM users WHERE id = 5", tier=safety.TIER_SAFE_WRITE)
        assert out["ok"] is False
        assert out["policy"]["needsConfirm"] is True
        assert engine.calls == []

    def test_safe_write_tier_plus_confirm_executes(self, wired, engine) -> None:
        out = tools.execute_query(
            "DELETE FROM users WHERE id = 5", tier=safety.TIER_SAFE_WRITE, confirm=True
        )
        assert out["ok"] is True
        assert out["context"]["accessTier"] == "safe-write"
        assert len(engine.calls) == 1

    def test_unbounded_delete_needs_the_full_tier(self, wired) -> None:
        out = tools.execute_query("DELETE FROM users", tier=safety.TIER_SAFE_WRITE, confirm=True)
        assert out["ok"] is False
        assert out["policy"]["risk"] == "high-risk"

    def test_full_tier_still_needs_a_confirmation(self, wired, engine) -> None:
        out = tools.execute_query("DROP TABLE users", tier=safety.TIER_FULL)
        assert out["ok"] is False
        assert engine.calls == []

    def test_dry_run_previews_without_writing(self, wired, engine) -> None:
        engine.result = QueryResult(
            success=True,
            columns=[ColumnMeta(name="n", data_type="int")],
            rows=[[7]],
            row_count=1,
        )
        out = tools.execute_query("UPDATE users SET vip = 1 WHERE tier = 'gold'", dry_run=True)
        assert out["ok"] is True
        assert out["executed"] is False
        assert out["preview"]["rows"] == [[7]]
        assert engine.calls[0][1].upper().startswith("SELECT COUNT(*)")
        assert "vip = 1" not in engine.calls[0][1]

    def test_dry_run_of_a_statement_with_no_preview(self, wired, engine) -> None:
        out = tools.execute_query("DROP TABLE users", tier=safety.TIER_FULL, dry_run=True)
        assert out["executed"] is False
        assert "preview" not in out
        assert "no static preview" in out["note"]
        assert engine.calls == []

    def test_statement_failure_is_reported_as_data(self, wired, engine) -> None:
        engine.result = QueryResult(success=False, error_message="no such column: nope")
        out = tools.execute_query("SELECT nope FROM t")
        assert out["ok"] is False
        assert out["error"]["code"] == "ONV-SQL-001"
        assert "no such column" in out["error"]["detail"]

    def test_password_in_an_error_never_leaves(self, wired, engine) -> None:
        engine.result = QueryResult(
            success=False, error_message="access denied for password=hunter2"
        )
        out = tools.execute_query("SELECT 1")
        assert "hunter2" not in repr(out)


# ---- commands --------------------------------------------------------------


class TestExecuteCommand:
    @pytest.fixture(autouse=True)
    def _redis(self, manager) -> None:
        manager.sessions = {"r1": FakeConnector("redis", "0")}
        manager.saved = [saved_connection("r1", engine="redis", database="0")]

    def test_known_read_command_runs(self, wired, engine) -> None:
        out = tools.execute_command("GET user:1", connection_id="r1")
        assert out["ok"] is True
        assert engine.calls[0][1] == "GET user:1"
        assert out["context"]["engine"] == "redis"

    def test_sql_via_query_is_gated_as_a_command(self, wired, engine) -> None:
        # A Redis session cannot speak SQL, so ``execute_query`` follows the
        # engine rather than the argument name.
        out = tools.execute_command("GET user:1", connection_id="r1")
        assert out["ok"] is True
        assert tools.execute_query("GET user:1", connection_id="r1")["ok"] is True

    def test_write_command_needs_confirmation(self, wired, engine) -> None:
        assert tools.execute_command("SET user:1 x", connection_id="r1")["ok"] is False
        out = tools.execute_command("SET user:1 x", connection_id="r1", tier=safety.TIER_SAFE_WRITE)
        assert out["ok"] is False
        assert out["policy"]["needsConfirm"] is True
        assert engine.calls == []

    def test_command_dry_run_changes_nothing(self, wired, engine) -> None:
        out = tools.execute_command("SET user:1 x", connection_id="r1", dry_run=True)
        assert out["ok"] is True
        assert out["executed"] is False
        assert "no static preview" in out["note"]
        assert engine.calls == []

    def test_dangerous_command_needs_the_full_tier(self, wired) -> None:
        assert tools.execute_command("FLUSHALL", connection_id="r1")["ok"] is False
        out = tools.execute_command(
            "FLUSHALL", connection_id="r1", tier=safety.TIER_FULL, confirm=True
        )
        assert out["ok"] is True

    def test_unknown_command_fails_closed(self, wired) -> None:
        out = tools.execute_command("DEBUG sleep 1", connection_id="r1")
        assert out["ok"] is False
        assert out["policy"]["risk"] == "high-risk"

    def test_sql_is_not_gated_as_a_command(self, wired) -> None:
        out = tools.execute_command("SELECT 1", connection_id="r1")
        assert out["ok"] is False


class TestSurface:
    def test_exposed_tools_are_documented(self) -> None:
        for tool in tools.TOOLS:
            assert tool.__doc__, tool.__name__
            assert tool.__name__ in tools.__all__

    def test_row_limit_defaults(self) -> None:
        assert tools.DEFAULT_ROW_LIMIT < tools.MAX_ROW_LIMIT
