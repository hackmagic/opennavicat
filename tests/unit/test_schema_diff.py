"""Tests for schema-diff planning and DDL generation.

Covers the two defects the inline implementation had: ``generate_sync_script``
only understood MySQL and PostgreSQL quoting (so SQLite/ClickHouse/SQL Server
targets got unparseable DDL), and it emitted DROP TABLE in discovery order, which
fails when one table still references another.
"""

from __future__ import annotations

import pytest

from open_navicat.models.table_schema import (
    ColumnInfo,
    ForeignKeyInfo,
    IndexInfo,
    TableInfo,
)
from open_navicat.services.sync_engine import (
    ColumnDiff,
    SyncDiff,
    SyncEngine,
    TableDiff,
)
from open_navicat.sql.schema_diff import (
    drop_table_statements,
    order_creates,
    order_drops,
    table_ref,
)


def table(name: str, *, fks=None, columns=None) -> TableInfo:
    return TableInfo(
        name=name,
        database="app",
        columns=columns
        or [
            ColumnInfo(name="id", data_type="int", is_primary_key=True, nullable=False),
            ColumnInfo(name="name", data_type="varchar", char_max_length=50),
        ],
        foreign_keys=list(fks or []),
    )


def fk(name: str, column: str, ref: str) -> ForeignKeyInfo:
    return ForeignKeyInfo(
        name=name,
        column=column,
        ref_table=ref,
        ref_column="id",
        on_delete="CASCADE",
        on_update="NO ACTION",
    )


class TestDependencyOrdering:
    def test_creates_parent_before_child(self) -> None:
        refs = {"orders": {"users"}, "items": {"orders"}, "users": set()}
        assert order_creates(["items", "users", "orders"], refs) == [
            "users",
            "orders",
            "items",
        ]

    def test_drops_child_before_parent(self) -> None:
        refs = {"orders": {"users"}, "items": {"orders"}, "users": set()}
        assert order_drops(["users", "orders", "items"], refs) == [
            "items",
            "orders",
            "users",
        ]

    def test_independent_tables_keep_their_order(self) -> None:
        assert order_creates(["b", "a"], {"a": set(), "b": set()}) == ["b", "a"]

    def test_cycle_does_not_hang(self) -> None:
        refs = {"a": {"b"}, "b": {"a"}}
        assert sorted(order_drops(["a", "b"], refs)) == ["a", "b"]
        assert sorted(order_creates(["a", "b"], refs)) == ["a", "b"]

    def test_self_reference_is_ignored(self) -> None:
        # A table with a self-referencing FK must not block its own creation.
        assert order_creates(["tree"], {"tree": {"tree"}}) == ["tree"]

    def test_empty_input(self) -> None:
        assert order_creates([], {}) == []
        assert order_drops([], {}) == []


class TestTableRef:
    @pytest.mark.parametrize(
        "engine,expected",
        [
            ("mysql", "`app`.`users`"),
            ("postgresql", '"app"."users"'),
            ("sqlserver", "[app].[users]"),
            ("clickhouse", "`app`.`users`"),
            ("sqlite", '"app"."users"'),
        ],
    )
    def test_qualified_quoting(self, engine, expected) -> None:
        assert table_ref("users", engine, "app") == expected

    def test_no_database(self) -> None:
        assert table_ref("users", "mysql") == "`users`"


class TestDropStatements:
    def test_per_engine(self) -> None:
        assert drop_table_statements(["t"], "mysql", "app") == ["DROP TABLE IF EXISTS `app`.`t`;"]
        assert drop_table_statements(["t"], "sqlserver", "app") == [
            "DROP TABLE IF EXISTS [app].[t];"
        ]

    def test_preserves_the_given_order(self) -> None:
        got = drop_table_statements(["b", "a"], "mysql")
        assert got == ["DROP TABLE IF EXISTS `b`;", "DROP TABLE IF EXISTS `a`;"]


class TestGenerateSyncScript:
    def engine(self) -> SyncEngine:
        return SyncEngine()

    def test_added_table_uses_the_target_engine(self) -> None:
        diff = SyncDiff(added_tables=[table("users")])
        sql = "\n".join(self.engine().generate_sync_script(diff, engine="postgresql"))
        assert 'CREATE TABLE IF NOT EXISTS "users"' in sql
        assert "`" not in sql

    def test_added_tables_are_created_in_dependency_order(self) -> None:
        users = table("users")
        orders = table("orders", fks=[fk("fk_u", "user_id", "users")])
        diff = SyncDiff(added_tables=[orders, users])
        statements = self.engine().generate_sync_script(diff, engine="mysql")
        text = "\n".join(statements)
        assert text.index("`users`") < text.index("`orders`")

    def test_removed_tables_are_dropped_in_reverse_order(self) -> None:
        diff = SyncDiff(
            removed_tables=["users", "orders"],
            target_references={"orders": {"users"}},
        )
        statements = self.engine().generate_sync_script(diff, engine="mysql")
        text = "\n".join(statements)
        assert text.index("DROP TABLE IF EXISTS `orders`") < text.index(
            "DROP TABLE IF EXISTS `users`"
        )

    def test_added_column(self) -> None:
        td = TableDiff(
            table_name="users",
            added_columns=[ColumnInfo(name="nick", data_type="varchar", char_max_length=20)],
        )
        sql = self.engine().generate_sync_script(
            SyncDiff(modified_tables=[td]), engine="postgresql"
        )
        assert sql == ['ALTER TABLE "users" ADD COLUMN "nick" varchar(20) DEFAULT NULL;']

    def test_removed_column_per_engine(self) -> None:
        td = TableDiff(table_name="users", removed_columns=["nick"])
        assert self.engine().generate_sync_script(
            SyncDiff(modified_tables=[td]), engine="sqlserver"
        ) == ["ALTER TABLE [users] DROP COLUMN [nick];"]

    def test_modified_column_mysql_uses_modify(self) -> None:
        source = ColumnInfo(name="age", data_type="bigint")
        td = TableDiff(
            table_name="users",
            modified_columns=[ColumnDiff(column_name="age", source_column=source)],
        )
        sql = self.engine().generate_sync_script(SyncDiff(modified_tables=[td]), engine="mysql")
        assert sql[0].startswith("ALTER TABLE `users` MODIFY COLUMN `age` bigint")

    def test_modified_column_postgres_uses_type(self) -> None:
        source = ColumnInfo(name="age", data_type="bigint")
        td = TableDiff(
            table_name="users",
            modified_columns=[ColumnDiff(column_name="age", source_column=source)],
        )
        sql = self.engine().generate_sync_script(
            SyncDiff(modified_tables=[td]), engine="postgresql"
        )
        assert sql == ['ALTER TABLE "users" ALTER COLUMN "age" TYPE bigint;']

    def test_added_primary_key(self) -> None:
        td = TableDiff(
            table_name="users",
            added_indexes=[IndexInfo(name="pk", columns=["id"], is_primary=True)],
        )
        sql = self.engine().generate_sync_script(SyncDiff(modified_tables=[td]), engine="mysql")
        assert sql == ["ALTER TABLE `users` ADD PRIMARY KEY (`id`);"]

    def test_added_unique_index(self) -> None:
        td = TableDiff(
            table_name="users",
            added_indexes=[IndexInfo(name="uq_email", columns=["email"], is_unique=True)],
        )
        sql = self.engine().generate_sync_script(
            SyncDiff(modified_tables=[td]), engine="postgresql"
        )
        assert sql == ['CREATE UNIQUE INDEX "uq_email" ON "users" ("email");']

    def test_dropped_index_differs_by_engine(self) -> None:
        td = TableDiff(table_name="users", removed_indexes=["idx_a"])
        mysql = self.engine().generate_sync_script(SyncDiff(modified_tables=[td]), engine="mysql")
        assert mysql == ["ALTER TABLE `users` DROP INDEX `idx_a`;"]
        mssql = self.engine().generate_sync_script(
            SyncDiff(modified_tables=[td]), engine="sqlserver"
        )
        assert mssql == ["DROP INDEX [idx_a] ON [users];"]

    def test_added_foreign_key(self) -> None:
        td = TableDiff(
            table_name="orders",
            added_foreign_keys=[fk("fk_user", "user_id", "users")],
        )
        sql = self.engine().generate_sync_script(
            SyncDiff(modified_tables=[td]), engine="postgresql"
        )
        assert sql == [
            'ALTER TABLE "orders" ADD CONSTRAINT "fk_user" FOREIGN KEY ("user_id") '
            'REFERENCES "users" ("id") ON DELETE CASCADE ON UPDATE NO ACTION;'
        ]

    def test_dropped_foreign_key_mysql_uses_drop_foreign_key(self) -> None:
        td = TableDiff(table_name="orders", removed_foreign_keys=["fk_user"])
        sql = self.engine().generate_sync_script(SyncDiff(modified_tables=[td]), engine="mysql")
        assert sql == ["ALTER TABLE `orders` DROP FOREIGN KEY `fk_user`;"]

    def test_dropped_foreign_key_postgres_uses_drop_constraint(self) -> None:
        td = TableDiff(table_name="orders", removed_foreign_keys=["fk_user"])
        sql = self.engine().generate_sync_script(
            SyncDiff(modified_tables=[td]), engine="postgresql"
        )
        assert sql == ['ALTER TABLE "orders" DROP CONSTRAINT "fk_user";']

    def test_no_changes_generates_nothing(self) -> None:
        assert self.engine().generate_sync_script(SyncDiff(), engine="mysql") == []

    def test_target_database_qualifies_modified_tables(self) -> None:
        td = TableDiff(table_name="users", removed_columns=["a"])
        sql = self.engine().generate_sync_script(
            SyncDiff(modified_tables=[td]), target_db="app", engine="mysql"
        )
        assert sql == ["ALTER TABLE `app`.`users` DROP COLUMN `a`;"]
