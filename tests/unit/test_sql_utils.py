"""Unit tests for SQL utilities."""

from __future__ import annotations

from open_navicat.models.table_schema import ColumnInfo, TableInfo
from open_navicat.utils.sql_formatter import (
    beautify,
    classify_sql,
    extract_table_names,
    is_ddl,
    is_dml,
    is_select,
    minify,
)
from open_navicat.utils.sql_generator import generate_create_table, generate_insert, generate_select


class TestSQLFormatter:
    def test_beautify_simple(self) -> None:
        raw = "SELECT * FROM users WHERE id = 1"
        result = beautify(raw)
        assert "SELECT" in result
        assert "FROM" in result
        assert "WHERE" in result

    def test_minify(self) -> None:
        raw = "SELECT   *   \n  FROM  users  WHERE  id = 1"
        compact = minify(raw)
        assert "   " not in compact
        assert "\n" not in compact

    def test_is_select(self) -> None:
        assert is_select("SELECT * FROM users") is True
        assert is_select("INSERT INTO users VALUES (1)") is False

    def test_is_ddl(self) -> None:
        assert is_ddl("CREATE TABLE t (id INT)") is True
        assert is_ddl("SELECT 1") is False

    def test_extract_table_names(self) -> None:
        tables = extract_table_names("SELECT * FROM users JOIN orders ON users.id = orders.user_id")
        assert "users" in tables
        assert "orders" in tables

    def test_classify_sql_select(self) -> None:
        assert classify_sql("SELECT * FROM users") == "select"
        assert classify_sql("select 1") == "select"

    def test_classify_sql_ddl(self) -> None:
        assert classify_sql("CREATE TABLE t (id INT)") == "ddl"
        assert classify_sql("DROP TABLE t") == "ddl"
        assert classify_sql("ALTER TABLE t ADD COLUMN x INT") == "ddl"
        assert classify_sql("TRUNCATE TABLE t") == "ddl"

    def test_classify_sql_dml(self) -> None:
        assert classify_sql("INSERT INTO t VALUES (1)") == "dml"
        assert classify_sql("UPDATE t SET x=1") == "dml"
        assert classify_sql("DELETE FROM t") == "dml"

    def test_classify_sql_unknown(self) -> None:
        assert classify_sql("") == "unknown"
        assert classify_sql("   ") == "unknown"

    def test_is_dml(self) -> None:
        assert is_dml("INSERT INTO t VALUES (1)") is True
        assert is_dml("SELECT 1") is False


class TestSQLGenerator:
    def test_generate_create_table(self) -> None:
        table = TableInfo(
            name="employees",
            database="test",
            engine="InnoDB",
            charset="utf8mb4",
            columns=[
                ColumnInfo(
                    name="id", data_type="INT", char_max_length=11,
                    nullable=False, is_primary_key=True, is_auto_increment=True,
                ),
                ColumnInfo(name="name", data_type="VARCHAR", char_max_length=255, nullable=False),
                ColumnInfo(name="email", data_type="VARCHAR", char_max_length=255, nullable=True),
            ],
        )
        sql = generate_create_table(table)
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "`employees`" in sql
        assert "`id` INT(11)" in sql
        assert "AUTO_INCREMENT" in sql
        assert "PRIMARY KEY" in sql
        assert "ENGINE=InnoDB" in sql
        assert "DEFAULT CHARSET=utf8mb4" in sql
        assert sql.endswith(";")

    def test_generate_select_default(self) -> None:
        sql = generate_select("users", limit=100)
        assert "SELECT * FROM `users`" in sql
        assert "LIMIT 100" in sql

    def test_generate_insert(self) -> None:
        sql = generate_insert(
            "users",
            ["name", "email"],
            [["Alice", "alice@test.com"], ["Bob", "bob@test.com"]],
        )
        assert "INSERT INTO `users`" in sql
        assert "Alice" in sql
        assert "alice@test.com" in sql
        assert sql.endswith(";")
