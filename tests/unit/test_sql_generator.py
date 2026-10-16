"""Tests for the DDL/DML generator (open_navicat.utils.sql_generator).

These lock in the engine-aware quoting: ``sync_engine`` generates DDL for a
*target* engine, and the statements used to hard-code MySQL backticks and
MySQL-only table options.
"""

from __future__ import annotations

import pytest

from open_navicat.models import ColumnInfo, ForeignKeyInfo, IndexInfo, TableInfo
from open_navicat.utils.sql_generator import (
    generate_alter_table,
    generate_alter_table_add_column,
    generate_alter_table_drop_column,
    generate_create_table,
    generate_drop_table,
    generate_insert,
    generate_select,
)


@pytest.fixture
def table() -> TableInfo:
    return TableInfo(
        name="users",
        database="app",
        engine="InnoDB",
        charset="utf8mb4",
        comment="people",
        columns=[
            ColumnInfo(name="id", data_type="int", is_primary_key=True, nullable=False),
            ColumnInfo(name="email", data_type="varchar", char_max_length=255, nullable=True),
        ],
        indexes=[IndexInfo(name="idx_email", columns=["email"], is_unique=True)],
        foreign_keys=[
            ForeignKeyInfo(
                name="fk_org",
                column="org_id",
                ref_table="orgs",
                ref_column="id",
                on_delete="CASCADE",
                on_update="NO ACTION",
            )
        ],
    )


class TestCreateTableQuoting:
    def test_mysql_uses_backticks_and_mysql_options(self, table) -> None:
        sql = generate_create_table(table, engine="mysql")
        assert "CREATE TABLE IF NOT EXISTS `users`" in sql
        assert "`id` int NOT NULL" in sql
        assert "PRIMARY KEY (`id`)" in sql
        assert "UNIQUE KEY `idx_email` (`email`)" in sql
        assert "ENGINE=InnoDB" in sql
        assert "DEFAULT CHARSET=utf8mb4" in sql

    def test_postgres_uses_double_quotes(self, table) -> None:
        sql = generate_create_table(table, engine="postgresql")
        assert 'CREATE TABLE IF NOT EXISTS "users"' in sql
        assert 'PRIMARY KEY ("id")' in sql

    def test_sqlserver_uses_brackets(self, table) -> None:
        sql = generate_create_table(table, engine="sqlserver")
        assert "CREATE TABLE IF NOT EXISTS [users]" in sql
        assert "PRIMARY KEY ([id])" in sql

    def test_if_not_exists_can_be_suppressed(self, table) -> None:
        assert "IF NOT EXISTS" not in generate_create_table(table, False, "mysql")


class TestEngineSpecificSyntax:
    @pytest.mark.parametrize("engine", ["postgresql", "sqlserver", "sqlite", "clickhouse"])
    def test_non_mysql_omits_mysql_table_options(self, table, engine) -> None:
        sql = generate_create_table(table, engine=engine)
        assert "ENGINE=" not in sql
        assert "DEFAULT CHARSET=" not in sql

    def test_non_mysql_unique_index_uses_constraint_form(self, table) -> None:
        # "UNIQUE \"name\" (cols)" is not valid PostgreSQL.
        assert 'CONSTRAINT "idx_email" UNIQUE ("email")' in generate_create_table(
            table, engine="postgresql"
        )

    def test_non_mysql_table_comment_becomes_a_sql_comment(self, table) -> None:
        assert "-- people" in generate_create_table(table, engine="postgresql")

    def test_mysql_comment_is_an_option(self, table) -> None:
        assert "COMMENT='people'" in generate_create_table(table, engine="mysql")


class TestForeignKeys:
    def test_mysql(self, table) -> None:
        sql = generate_create_table(table, engine="mysql")
        assert (
            "CONSTRAINT `fk_org` FOREIGN KEY (`org_id`) "
            "REFERENCES `orgs` (`id`) ON DELETE CASCADE ON UPDATE NO ACTION" in sql
        )

    def test_standard_quoting(self, table) -> None:
        sql = generate_create_table(table, engine="postgresql")
        assert '"fk_org"' in sql and '"org_id"' in sql and '"orgs"' in sql


class TestAlterTable:
    def test_added_column_uses_engine_quoting(self) -> None:
        col = ColumnInfo(name="nickname", data_type="varchar", char_max_length=50)
        assert "ADD COLUMN [nickname]" in generate_alter_table_add_column(
            "users", col, engine="sqlserver"
        )
        assert 'ADD COLUMN "nickname"' in generate_alter_table_add_column(
            "users", col, engine="postgresql"
        )

    def test_dropped_column(self) -> None:
        assert generate_alter_table_drop_column("users", "nickname", "mysql") == (
            "ALTER TABLE `users` DROP COLUMN `nickname`;"
        )

    def test_diff_generates_statements(self, table) -> None:
        from dataclasses import replace

        new = replace(table)
        new.columns = list(table.columns) + [
            ColumnInfo(name="nickname", data_type="varchar", char_max_length=50)
        ]
        sql = generate_alter_table(table, new, engine="postgresql")
        assert 'ADD COLUMN "nickname"' in sql
        assert "AFTER" in sql or "FIRST" in sql


class TestDml:
    def test_insert_quotes_and_escapes(self) -> None:
        sql = generate_insert(
            "users", ["name", "age"], [["O'Brien", 30], [None, 7]], engine="postgresql"
        )
        assert 'INSERT INTO "users" ("name", "age") VALUES' in sql
        assert "'O''Brien'" in sql
        assert "NULL" in sql

    def test_insert_keeps_numbers_unquoted(self) -> None:
        sql = generate_insert("t", ["n"], [[42]], engine="mysql")
        assert "(42)" in sql
        assert "'42'" not in sql

    def test_select(self) -> None:
        assert generate_select("users", ["id"], limit=5, engine="postgresql") == (
            'SELECT "id" FROM "users" LIMIT 5;'
        )

    def test_select_star(self) -> None:
        assert generate_select("users", engine="mysql").startswith("SELECT * FROM `users`")

    def test_select_with_where_and_order(self) -> None:
        sql = generate_select("users", ["id"], where="id > 1", order_by="id", engine="mysql")
        assert "WHERE id > 1" in sql
        assert "ORDER BY id" in sql

    def test_drop_table(self) -> None:
        assert generate_drop_table("users", engine="sqlserver") == ("DROP TABLE IF EXISTS [users];")

    def test_defaults_stay_mysql_compatible(self) -> None:
        # Callers that do not pass an engine keep the previous behaviour.
        assert "`users`" in generate_drop_table("users")
