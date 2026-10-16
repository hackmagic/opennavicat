"""Tests for the MCP / AI access policy (open_navicat.mcp.safety)."""

from __future__ import annotations

import pytest

from open_navicat.errors import ERR_POLICY_DENIED, PolicyDeniedError
from open_navicat.mcp import safety as s


class TestNormalizeTier:
    def test_canonical_names(self) -> None:
        assert s.normalize_tier("read") == s.TIER_READ
        assert s.normalize_tier("safe-write") == s.TIER_SAFE_WRITE
        assert s.normalize_tier("full") == s.TIER_FULL

    def test_aliases_and_case(self) -> None:
        assert s.normalize_tier("Read-Only") == s.TIER_READ
        assert s.normalize_tier("  SAFE_WRITE ") == s.TIER_SAFE_WRITE
        assert s.normalize_tier("UNRESTRICTED") == s.TIER_FULL

    def test_empty_falls_back_to_default(self) -> None:
        assert s.normalize_tier(None) == s.TIER_READ
        assert s.normalize_tier("", default=s.TIER_FULL) == s.TIER_FULL

    def test_unknown_spelling_raises_instead_of_widening(self) -> None:
        # A typo in a config file must not silently grant `full`.
        with pytest.raises(PolicyDeniedError) as exc:
            s.normalize_tier("fullish")
        assert exc.value.code == ERR_POLICY_DENIED
        assert "read" in exc.value.detail

    def test_tiers_are_in_widening_order(self) -> None:
        assert s.TIERS == (s.TIER_READ, s.TIER_SAFE_WRITE, s.TIER_FULL)
        assert [s.RISK_ORDER[s.TIER_CEILING[t]] for t in s.TIERS] == [0, 1, 2]


class TestClassifyReads:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 1",
            "select id from users where id = 7",
            "WITH c AS (SELECT 1) SELECT * FROM c",
            "SHOW TABLES",
            "DESCRIBE users",
            "EXPLAIN SELECT * FROM users",
            "SELECT * FROM t /* a comment with DELETE FROM x */",
        ],
    )
    def test_read_only(self, sql: str) -> None:
        assert s.analyze(sql).risk == s.RISK_READ


class TestClassifyWrites:
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO t (a) VALUES (1)",
            "UPDATE t SET a = 1 WHERE id = 2",
            "DELETE FROM logs WHERE created < '2026-01-01'",
            "REPLACE INTO t VALUES (1)",
            "CREATE TABLE t (id INT)",
        ],
    )
    def test_write(self, sql: str) -> None:
        assert s.analyze(sql).risk == s.RISK_WRITE

    @pytest.mark.parametrize(
        "sql",
        [
            "UPDATE t SET a = 1",
            "DELETE FROM logs",
            "TRUNCATE TABLE logs",
            "DROP TABLE users",
            "DROP DATABASE app",
            "ALTER TABLE users DROP COLUMN email",
            "GRANT ALL ON *.* TO app",
            "CALL rebuild_orders()",
            "CREATE OR REPLACE FUNCTION f() RETURNS int AS $$ BEGIN RETURN 1; END $$ LANGUAGE plpgsql",
            "SET GLOBAL max_connections = 999",
            "SOMETHING_NEW t",
            "",
            "-- nothing but a comment",
        ],
    )
    def test_high_risk(self, sql: str) -> None:
        assert s.analyze(sql).risk == s.RISK_HIGH

    def test_unqualified_write_explains_itself(self) -> None:
        analysis = s.analyze("UPDATE accounts SET balance = 0")
        assert "without a WHERE clause" in " ".join(analysis.reasons)

    def test_unknown_verb_is_not_a_read(self) -> None:
        # Fail closed: a verb nobody added to the tables must not inherit `read`.
        assert s.analyze("CLUSTER users USING users_pkey").risk == s.RISK_HIGH


class TestClassificationEdges:
    def test_literal_cannot_fake_a_where_clause(self) -> None:
        # The classic false negative: a value containing "where" would make an
        # unbounded UPDATE look row-scoped.
        assert s.analyze("UPDATE t SET note = 'where ever you go'").risk == s.RISK_HIGH

    def test_literal_cannot_hide_a_write(self) -> None:
        # And the false positive side: a value mentioning DROP stays a write.
        assert s.analyze("DELETE FROM logs WHERE note = 'DROP TABLE x'").risk == s.RISK_WRITE

    def test_comment_cannot_hide_a_write(self) -> None:
        assert s.analyze("SELECT 1;\n-- harmless\nDROP TABLE users").risk == s.RISK_HIGH

    def test_insert_into_is_not_select_into(self) -> None:
        analysis = s.analyze("INSERT INTO logs (a) VALUES ('SELECT x INTO y')")
        assert analysis.risk == s.RISK_WRITE
        assert "`SELECT ... INTO`" not in " ".join(analysis.reasons)

    def test_select_into_creates_a_table(self) -> None:
        assert s.analyze("SELECT * INTO backup_t FROM t").risk == s.RISK_WRITE

    def test_cte_ending_in_a_write(self) -> None:
        sql = "WITH c AS (SELECT id FROM t) DELETE FROM logs WHERE id IN (SELECT id FROM c)"
        assert s.analyze(sql).risk == s.RISK_WRITE

    def test_explain_analyze_inherits_the_inner_statement(self) -> None:
        assert s.analyze("EXPLAIN ANALYZE SELECT 1").risk == s.RISK_READ
        assert s.analyze("EXPLAIN ANALYZE DELETE FROM logs WHERE id = 1").risk == s.RISK_WRITE
        assert s.analyze("EXPLAIN ANALYZE DELETE FROM logs").risk == s.RISK_HIGH

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT load_file('/etc/passwd')",
            "SELECT * FROM t INTO OUTFILE '/tmp/dump.csv'",
            "SELECT dblink('host=x', 'SELECT 1')",
            "SELECT xp_cmdshell('dir')",
        ],
    )
    def test_escape_hatches_are_high_risk(self, sql: str) -> None:
        assert s.analyze(sql).risk == s.RISK_HIGH

    def test_multi_statement_with_a_write_is_high_risk(self) -> None:
        analysis = s.analyze("SELECT 1; UPDATE t SET a = 1 WHERE id = 2")
        assert analysis.risk == s.RISK_HIGH
        assert "rollback" in " ".join(analysis.reasons)

    def test_multi_statement_reads_stay_read(self) -> None:
        assert s.analyze("SELECT 1; SELECT 2").risk == s.RISK_READ

    def test_trailing_semicolon_does_not_make_it_a_batch(self) -> None:
        assert len(s.analyze("SELECT 1;").statements) == 1

    def test_table_extraction_normalises_qualified_names(self) -> None:
        assert s.analyze("UPDATE [dbo].[users] SET a = 1 WHERE id = 2").tables == ("dbo.users",)


class TestCommandClassification:
    @pytest.mark.parametrize("cmd", ["GET k", "HGETALL h", "TTL k", "lrange l 0 -1", "DBSIZE"])
    def test_reads(self, cmd: str) -> None:
        assert s.analyze_command(cmd).risk == s.RISK_READ

    @pytest.mark.parametrize("cmd", ["SET k v", "DEL k", "EXPIRE k 10", "LPUSH l x", "HSET h f v"])
    def test_writes(self, cmd: str) -> None:
        assert s.analyze_command(cmd).risk == s.RISK_WRITE

    @pytest.mark.parametrize("cmd", ["FLUSHALL", "FLUSHDB", "KEYS *", "CONFIG GET *", "EVAL x 0"])
    def test_high_risk(self, cmd: str) -> None:
        assert s.analyze_command(cmd).risk == s.RISK_HIGH

    def test_unknown_command_is_a_write_not_a_read(self) -> None:
        assert s.analyze_command("SOMETHINGNEW k").risk == s.RISK_WRITE

    def test_sort_writes_only_with_store(self) -> None:
        assert s.analyze_command("SORT mylist").risk == s.RISK_READ
        assert s.analyze_command("SORT mylist STORE dst").risk == s.RISK_WRITE

    def test_semicolon_in_a_value_is_not_a_batch(self) -> None:
        # Redis commands are not SQL; a statement splitter would invent a
        # second command out of the value.
        assert len(s.analyze_command('SET k "a;b"').statements) == 1

    def test_empty_command_is_high_risk(self) -> None:
        assert s.analyze_command("   ").risk == s.RISK_HIGH


class TestDryRunPreview:
    def test_qualified_update_previews_the_same_row_set(self) -> None:
        analysis = s.analyze("UPDATE users SET verified = 1 WHERE last_login < '2025-01-01'")
        preview = s.dry_run_preview(analysis)
        assert preview is not None
        assert preview.startswith("SELECT COUNT(*)")
        assert "FROM users" in preview
        assert "last_login" in preview

    def test_unqualified_write_has_no_preview(self) -> None:
        assert s.dry_run_preview(s.analyze("DELETE FROM logs")) is None

    def test_insert_has_no_preview(self) -> None:
        # Returning an empty preview would read as "verified, nothing to do".
        assert s.dry_run_preview(s.analyze("INSERT INTO t VALUES (1)")) is None

    def test_batch_has_no_preview(self) -> None:
        analysis = s.analyze("SELECT 1; DELETE FROM logs WHERE id = 1")
        assert s.dry_run_preview(analysis) is None


class TestGate:
    def test_read_passes_at_every_tier(self) -> None:
        for tier in s.TIERS:
            assert s.check("SELECT 1", tier=tier).allowed is True

    def test_read_tier_blocks_writes(self) -> None:
        decision = s.check("UPDATE t SET a = 1 WHERE id = 2", tier=s.TIER_READ)
        assert decision.allowed is False
        assert decision.error is not None
        assert decision.error.code == ERR_POLICY_DENIED
        assert "read" in decision.error.detail

    def test_write_needs_confirmation(self) -> None:
        decision = s.check("UPDATE t SET a = 1 WHERE id = 2", tier=s.TIER_SAFE_WRITE)
        assert decision.allowed is False
        assert decision.needs_confirm is True
        assert decision.error is not None
        assert "dry_run=true" in decision.error.detail

    def test_confirmed_write_is_allowed(self) -> None:
        decision = s.check("UPDATE t SET a = 1 WHERE id = 2", tier=s.TIER_SAFE_WRITE, confirm=True)
        assert decision.allowed is True
        assert decision.needs_confirm is False

    def test_dry_run_is_allowed_and_carries_a_preview(self) -> None:
        decision = s.check("DELETE FROM logs WHERE id = 3", tier=s.TIER_SAFE_WRITE, dry_run=True)
        assert decision.allowed is True
        assert decision.dry_run is True
        assert decision.preview_sql is not None
        assert "matching_rows" in decision.preview_sql

    def test_dry_run_previews_at_the_read_tier(self) -> None:
        # A preview changes nothing, so it does not need write permission.
        for tier in s.TIERS:
            decision = s.check("DROP TABLE users", tier=tier, dry_run=True)
            assert decision.allowed is True, tier
            assert decision.risk == s.RISK_HIGH
            assert decision.preview_sql is None

    def test_dry_run_wins_over_confirmation(self) -> None:
        # Asking not to change something and to change it in one call must not
        # silently write.
        decision = s.check(
            "DELETE FROM logs WHERE id = 3", tier=s.TIER_SAFE_WRITE, dry_run=True, confirm=True
        )
        assert decision.dry_run is True
        assert decision.allowed is True

    def test_safe_write_tier_blocks_high_risk(self) -> None:
        decision = s.check("DROP TABLE users", tier=s.TIER_SAFE_WRITE, confirm=True)
        assert decision.allowed is False
        assert "high-risk" in decision.error.detail

    def test_full_tier_allows_high_risk_only_with_confirmation(self) -> None:
        assert s.check("DROP TABLE users", tier=s.TIER_FULL).allowed is False
        assert s.check("DROP TABLE users", tier=s.TIER_FULL, confirm=True).allowed is True

    def test_full_tier_still_requires_confirmation(self) -> None:
        # `full` widens what may run; it never removes the requirement to say so.
        decision = s.check("TRUNCATE logs", tier=s.TIER_FULL)
        assert decision.allowed is False
        assert decision.needs_confirm is True

    def test_unbounded_update_needs_full_tier(self) -> None:
        for tier in (s.TIER_READ, s.TIER_SAFE_WRITE):
            assert s.check("DELETE FROM logs", tier=tier, confirm=True).allowed is False
        assert s.check("DELETE FROM logs", tier=s.TIER_FULL, confirm=True).allowed is True

    def test_command_gate(self) -> None:
        assert s.check("GET k", tier=s.TIER_READ, command=True).allowed is True
        assert s.check("SET k v", tier=s.TIER_READ, command=True).allowed is False
        assert (
            s.check("SET k v", tier=s.TIER_SAFE_WRITE, confirm=True, command=True).allowed is True
        )
        assert (
            s.check("FLUSHALL", tier=s.TIER_SAFE_WRITE, confirm=True, command=True).allowed is False
        )

    def test_sql_is_not_gated_as_a_command(self) -> None:
        # `command=True` skips SQL parsing; SQL fed through it would be read as
        # one opaque verb, so the two paths stay explicit.
        assert s.check("SELECT 1", tier=s.TIER_READ, command=True).allowed is False

    def test_invalid_tier_raises_from_the_gate(self) -> None:
        with pytest.raises(PolicyDeniedError):
            s.check("SELECT 1", tier="danger")


class TestPayloads:
    def test_decision_dict_is_json_friendly_and_self_describing(self) -> None:
        decision = s.check("DROP TABLE users", tier=s.TIER_READ)
        payload = decision.to_dict()
        assert payload["allowed"] is False
        assert payload["risk"] == s.RISK_HIGH
        assert payload["error"]["code"] == ERR_POLICY_DENIED
        assert payload["error"]["recoverable"] is True

    def test_allowed_dict_omits_the_error(self) -> None:
        payload = s.check("SELECT 1", tier=s.TIER_READ).to_dict()
        assert "error" not in payload
        assert payload["reasons"] == []

    def test_analysis_dict_lists_each_statement(self) -> None:
        payload = s.analyze("SELECT 1; DROP TABLE t").to_dict()
        assert len(payload["statements"]) == 2
        assert payload["statements"][1]["verb"] == "DROP"

    def test_refusal_detail_is_ascii_and_punctuated(self) -> None:
        error = s.check("CREATE INDEX i ON t (a)", tier=s.TIER_READ).error
        assert error is not None
        assert error.detail.encode("gbk")  # Windows consoles print this verbatim
        assert not error.detail.endswith((": ", ";", "— "))
        assert error.detail.endswith(".")

    def test_refusal_without_reasons_still_reads_as_a_sentence(self) -> None:
        error = s.check("DROP TABLE users", tier=s.TIER_READ).error
        assert error is not None
        assert "high-risk" in error.detail
        assert error.recoverable is True
