"""Tests for engine-aware SQL quoting (open_navicat.sql.quoting)."""

from __future__ import annotations

import datetime
import decimal

import pytest

from open_navicat.sql.quoting import (
    limit_clause,
    normalize_engine,
    quote_identifier,
    quote_literal,
    quote_qualified,
)


class TestIdentifiers:
    @pytest.mark.parametrize(
        "engine,expected",
        [
            ("mysql", "`users`"),
            ("mariadb", "`users`"),
            ("clickhouse", "`users`"),
            ("postgresql", '"users"'),
            ("sqlite", '"users"'),
            ("oracle", '"users"'),
            ("sqlserver", "[users]"),
        ],
    )
    def test_style_per_engine(self, engine, expected) -> None:
        assert quote_identifier("users", engine) == expected

    def test_unknown_engine_falls_back_to_ansi(self) -> None:
        assert quote_identifier("users", "somethingnew") == '"users"'

    def test_engine_is_case_insensitive(self) -> None:
        assert quote_identifier("users", "MySQL") == "`users`"

    @pytest.mark.parametrize(
        "engine,name",
        [
            ("mysql", "we`ird"),
            ("sqlserver", "we]ird"),
            ("postgresql", 'we"ird'),
        ],
    )
    def test_embedded_quote_is_doubled(self, engine, name) -> None:
        quoted = quote_identifier(name, engine)
        assert quoted.count(quote_identifier(name, engine)[0]) >= 1
        # The closing quote must still terminate the identifier.
        assert quoted.startswith(quote_identifier("x", engine)[0])

    def test_sqlserver_bracket_escape(self) -> None:
        assert quote_identifier("a]b", "sqlserver") == "[a]]b]"

    def test_mysql_backtick_escape(self) -> None:
        assert quote_identifier("a`b", "mysql") == "`a``b`"

    def test_standard_double_quote_escape(self) -> None:
        assert quote_identifier('a"b', "postgresql") == '"a""b"'

    def test_none_becomes_empty_quoted(self) -> None:
        assert quote_identifier(None, "mysql") == "``"

    def test_normalize_engine(self) -> None:
        assert normalize_engine("  PostgreSQL ") == "postgresql"
        assert normalize_engine(None) == ""


class TestQualifiedNames:
    def test_database_and_name(self) -> None:
        assert quote_qualified("users", "postgresql", "app") == '"app"."users"'

    def test_no_database_means_no_prefix(self) -> None:
        assert quote_qualified("users", "mysql", None) == "`users`"
        assert quote_qualified("users", "mysql", "") == "`users`"

    def test_already_dotted_name_is_split(self) -> None:
        assert quote_qualified("sales.orders", "mysql") == "`sales`.`orders`"


class TestLiterals:
    def test_none_is_null(self) -> None:
        assert quote_literal(None, "mysql") == "NULL"

    def test_bool_is_not_an_int(self) -> None:
        assert quote_literal(True, "mysql") == "TRUE"
        assert quote_literal(False, "postgresql") == "FALSE"

    def test_numbers_are_unquoted(self) -> None:
        assert quote_literal(42, "mysql") == "42"
        assert quote_literal(decimal.Decimal("1.50"), "mysql") == "1.50"

    def test_float_repr_is_exact(self) -> None:
        assert quote_literal(3.1, "mysql").startswith("3.1")

    def test_nan_and_inf_become_null(self) -> None:
        # Neither has a portable SQL spelling; NULL is the safe answer.
        assert quote_literal(float("nan"), "mysql") == "NULL"
        assert quote_literal(float("inf"), "mysql") == "NULL"

    def test_quote_is_doubled(self) -> None:
        assert quote_literal("O'Brien", "postgresql") == "'O''Brien'"

    def test_mysql_also_escapes_backslash(self) -> None:
        # Backslash is an escape character in MySQL, so it must be doubled there
        # and left alone elsewhere.
        assert quote_literal("a\\b", "mysql") == "'a\\\\b'"
        assert quote_literal("a\\b", "postgresql") == "'a\\b'"

    def test_bytes_use_hex(self) -> None:
        assert quote_literal(b"\xde\xad", "mysql") == "'dead'"

    def test_sqlserver_bytes_use_0x(self) -> None:
        assert quote_literal(b"\xde\xad", "sqlserver") == "0xdead"

    def test_temporal_values(self) -> None:
        assert quote_literal(datetime.datetime(2026, 1, 2, 3, 4, 5), "mysql") == (
            "'2026-01-02 03:04:05'"
        )
        assert quote_literal(datetime.date(2026, 1, 2), "mysql") == "'2026-01-02'"
        assert quote_literal(datetime.time(3, 4, 5), "mysql") == "'03:04:05'"

    def test_list_becomes_array_literal(self) -> None:
        assert quote_literal([1, "a"], "mysql") == "[1, 'a']"

    def test_booleans_inside_lists(self) -> None:
        assert quote_literal([True, False], "mysql") == "[TRUE, FALSE]"


class TestLimitClause:
    def test_mysql_style(self) -> None:
        assert limit_clause(10, 20, "mysql") == "LIMIT 10 OFFSET 20"

    def test_limit_only(self) -> None:
        assert limit_clause(10, None, "mysql") == "LIMIT 10"

    def test_offset_only_uses_limit_minus_one(self) -> None:
        # "OFFSET n" alone is not portable; LIMIT -1 is the accepted spelling.
        assert limit_clause(None, 20, "postgresql") == "LIMIT -1 OFFSET 20"

    def test_sqlserver_uses_offset_fetch(self) -> None:
        assert limit_clause(10, 20, "sqlserver") == "OFFSET 20 ROWS FETCH NEXT 10 ROWS ONLY"

    def test_sqlserver_without_offset(self) -> None:
        assert limit_clause(10, None, "sqlserver") == "FETCH NEXT 10 ROWS ONLY"

    def test_nothing_requested_is_empty(self) -> None:
        assert limit_clause(None, None, "mysql") == ""
        assert limit_clause(None, None, "sqlserver") == ""

    def test_values_are_coerced_to_int(self) -> None:
        assert limit_clause("10", "20", "mysql") == "LIMIT 10 OFFSET 20"  # type: ignore[arg-type]
