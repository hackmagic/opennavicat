"""Tests for SQL dialect translation."""

from __future__ import annotations

from open_navicat.utils.sql_dialect import optimize_sql, translate_sql


class TestTranslateSQL:
    def test_mysql_to_pg_basic(self) -> None:
        sql = "SELECT * FROM users WHERE id = 1 LIMIT 10"
        result = translate_sql(sql, "mysql", "postgresql")
        assert "LIMIT" in result
        assert "users" in result

    def test_pg_to_mysql_basic(self) -> None:
        sql = "SELECT * FROM users ORDER BY name OFFSET 5 LIMIT 10"
        result = translate_sql(sql, "postgresql", "mysql")
        assert "LIMIT" in result
        assert "OFFSET" in result or "users" in result

    def test_unknown_source_dialect(self) -> None:
        sql = "SELECT 1"
        result = translate_sql(sql, "unknown", "mysql")
        assert "SELECT" in result

    def test_translate_invalid_does_not_crash(self) -> None:
        """Translate gracefully handles garbage input."""
        sql = "\x00\x01\x02"
        result = translate_sql(sql, "mysql", "postgresql")
        assert isinstance(result, str)


class TestOptimizeSQL:
    def test_optimize_subquery(self) -> None:
        sql = "SELECT * FROM (SELECT * FROM users) AS sub"
        result = optimize_sql(sql, "mysql")
        assert "users" in result

    def test_optimize_invalid_does_not_crash(self) -> None:
        """Optimize gracefully handles garbage input."""
        sql = "\x00\x01\x02"
        result = optimize_sql(sql, "mysql")
        assert isinstance(result, str)
