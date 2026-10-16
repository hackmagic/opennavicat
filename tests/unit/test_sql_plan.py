"""Tests for dry-run planning (open_navicat.sql.plan)."""

from __future__ import annotations

import pytest

from open_navicat.sql.plan import (
    Plan,
    PlannedStatement,
    StatementKind,
    classify,
    first_keyword,
    plan_from_statements,
)


class TestFirstKeyword:
    @pytest.mark.parametrize(
        "sql,expected",
        [
            ("CREATE TABLE t (id int);", "CREATE"),
            ("  drop table t;  ", "DROP"),
            ("-- generated\nCREATE TABLE x (id int);", "CREATE"),
            ("# hash\nDELETE FROM t;", "DELETE"),
            ("/* block */ DROP TABLE t;", "DROP"),
            ("/* multi\nline */ ALTER TABLE t ADD COLUMN a int;", "ALTER"),
            ("", ""),
            ("   \n  ", ""),
        ],
    )
    def test_skips_comments_and_blanks(self, sql, expected) -> None:
        assert first_keyword(sql) == expected


class TestClassify:
    @pytest.mark.parametrize(
        "sql,expected",
        [
            ("CREATE TABLE t (id int);", StatementKind.CREATE),
            ("INSERT INTO t VALUES (1);", StatementKind.CREATE),
            ("ALTER TABLE t ADD COLUMN a int;", StatementKind.ALTER),
            ("RENAME TABLE a TO b;", StatementKind.ALTER),
            ("DROP TABLE IF EXISTS t;", StatementKind.DROP),
            ("TRUNCATE TABLE t;", StatementKind.DROP),
            ("DELETE FROM t WHERE id = 1;", StatementKind.DATA),
        ],
    )
    def test_by_keyword(self, sql, expected) -> None:
        assert classify(sql) is expected

    def test_alter_drop_column_counts_as_destructive(self) -> None:
        # The keyword says ALTER, but the effect is data loss.
        assert classify("ALTER TABLE t DROP COLUMN a;") is StatementKind.DROP

    def test_unknown_statement_defaults_to_alter(self) -> None:
        assert classify("VACUUM FULL;") is StatementKind.ALTER


class TestPlannedStatement:
    def test_drop_is_destructive(self) -> None:
        s = PlannedStatement("DROP TABLE t;", StatementKind.DROP)
        assert s.is_destructive is True
        assert s.needs_confirmation is True

    def test_create_is_not_destructive(self) -> None:
        s = PlannedStatement("CREATE TABLE t (id int);", StatementKind.CREATE)
        assert s.is_destructive is False
        assert s.needs_confirmation is False

    def test_delete_counts_as_destructive(self) -> None:
        s = PlannedStatement("DELETE FROM t;", StatementKind.DATA)
        assert s.is_destructive is True

    def test_marker_flags_the_risky_lines(self) -> None:
        assert PlannedStatement("DROP TABLE t;", StatementKind.DROP).marker == "!! "
        assert PlannedStatement("SELECT 1;", StatementKind.ALTER).marker == "   "


class TestPlan:
    def plan(self) -> Plan:
        return plan_from_statements(
            [
                "CREATE TABLE sales (id int);",
                "ALTER TABLE sales ADD COLUMN note text;",
                "DROP TABLE old_sales;",
            ]
        )

    def test_length_and_iteration(self) -> None:
        plan = self.plan()
        assert len(plan) == 3
        assert [s.kind for s in plan] == [
            StatementKind.CREATE,
            StatementKind.ALTER,
            StatementKind.DROP,
        ]

    def test_destructive_count(self) -> None:
        assert self.plan().destructive_count == 1

    def test_requires_confirmation_when_destructive(self) -> None:
        assert self.plan().requires_confirmation is True

    def test_non_destructive_plan_needs_no_confirmation(self) -> None:
        plan = plan_from_statements(["CREATE TABLE t (id int);"])
        assert plan.requires_confirmation is False

    def test_summary_reports_the_count(self) -> None:
        assert self.plan().summary() == "3 statement(s), 1 destructive"

    def test_summary_for_safe_plan(self) -> None:
        assert plan_from_statements(["CREATE TABLE t (id int);"]).summary() == "1 statement(s)"

    def test_empty_summary(self) -> None:
        plan = plan_from_statements([])
        assert plan.summary() == "no changes"
        assert bool(plan) is False
        assert plan.destructive_count == 0

    def test_preview_marks_destructive_lines(self) -> None:
        text = self.plan().preview_text()
        lines = text.splitlines()
        assert lines[0].startswith("   CREATE")
        assert lines[2].startswith("!! DROP")

    def test_preview_is_empty_for_an_empty_plan(self) -> None:
        assert plan_from_statements([]).preview_text() == ""

    def test_by_kind_groups_statements(self) -> None:
        groups = self.plan().by_kind()
        assert sorted(groups) == ["alter", "create", "drop"]
        assert len(groups["drop"]) == 1

    def test_transactional_defaults_true(self) -> None:
        assert self.plan().transactional is True

    def test_transactional_can_be_refused(self) -> None:
        plan = plan_from_statements(["CREATE TABLE t (id int);"], transactional=False)
        assert plan.transactional is False
