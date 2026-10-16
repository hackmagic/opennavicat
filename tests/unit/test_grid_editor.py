"""Tests for the data-grid edit planner (open_navicat.ui.widgets.grid_editor).

These cover the three defects the old inline grid code had: the primary key was
assumed to be column 0, every value was sent as a string, and the SQL was
MySQL-only backticks.
"""

from __future__ import annotations

import datetime
import decimal

import pytest

from open_navicat.ui.widgets.grid_editor import (
    MAX_PINNED_COLUMNS,
    NULL_SPELLINGS,
    ChangeKind,
    PendingChange,
    build_delete,
    build_insert,
    build_preview,
    build_update,
    cell_value_from_text,
    coerce_like,
    copy_as_insert,
    copy_as_update,
    copy_as_where,
    merge_cell_edits,
    order_columns,
    plan_changes,
    selected_rows,
    toggle_pin,
)


def update(**overrides) -> PendingChange:
    base = dict(
        kind=ChangeKind.UPDATE,
        table="users",
        database="app",
        key_columns=("id",),
        key_values={"id": 7},
        values={"email": "new@example.com"},
    )
    base.update(overrides)
    return PendingChange(**base)


class TestSafety:
    def test_update_without_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="key_columns"):
            PendingChange(ChangeKind.UPDATE, "users", "app", (), {}, {"a": 1})

    def test_delete_without_key_is_refused(self) -> None:
        # A DELETE with no WHERE would empty the table; refuse to build it.
        with pytest.raises(ValueError, match="key_columns"):
            PendingChange(ChangeKind.DELETE, "users", "app", (), {})

    def test_insert_needs_no_key(self) -> None:
        change = PendingChange(ChangeKind.INSERT, "users", values={"a": 1})
        assert change.key_columns == ()

    def test_update_without_values_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one column"):
            build_update(update(values={}))

    def test_insert_without_values_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one column"):
            build_insert(PendingChange(ChangeKind.INSERT, "users", values={}))

    def test_unknown_kind_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unsupported"):
            build_preview(update(kind="truncate"))  # type: ignore[arg-type]


class TestQuotingPerEngine:
    @pytest.mark.parametrize(
        "engine,expected",
        [
            ("mysql", "UPDATE `app`.`users` SET `email` = %s WHERE `id` = %s"),
            ("postgresql", 'UPDATE "app"."users" SET "email" = %s WHERE "id" = %s'),
            ("sqlserver", "UPDATE [app].[users] SET [email] = %s WHERE [id] = %s"),
            ("clickhouse", "UPDATE `app`.`users` SET `email` = %s WHERE `id` = %s"),
        ],
    )
    def test_update_uses_the_engine_identifier_style(self, engine, expected) -> None:
        assert build_update(update(), engine).sql == expected

    def test_table_without_database_is_not_qualified(self) -> None:
        preview = build_update(update(database=""), "postgresql")
        assert preview.sql.startswith('UPDATE "users" SET')

    def test_dotted_table_name_is_quoted_per_part(self) -> None:
        preview = build_update(update(table="sales.orders", database=""), "mysql")
        assert "`sales`.`orders`" in preview.sql

    def test_key_column_is_not_assumed_to_be_first(self) -> None:
        """The old code read the key from column 0; now it comes from the change."""
        change = update(key_columns=("uuid",), key_values={"uuid": "abc-123"})
        preview = build_update(change, "mysql")
        assert "WHERE `uuid` = %s" in preview.sql
        assert preview.params[-1] == "abc-123"


class TestCompositeKeys:
    def test_all_key_columns_are_anded(self) -> None:
        change = PendingChange(
            ChangeKind.DELETE,
            "orders",
            "sales",
            key_columns=("tenant_id", "id"),
            key_values={"tenant_id": 9, "id": 3},
        )
        preview = build_delete(change, "postgresql")
        assert preview.sql == ('DELETE FROM "sales"."orders" WHERE "tenant_id" = %s AND "id" = %s')
        assert preview.params == (9, 3)

    def test_extra_safety_predicate_is_appended(self) -> None:
        change = PendingChange(
            ChangeKind.UPDATE,
            "orders",
            "sales",
            key_columns=("id",),
            key_values={"id": 3},
            values={"status": "shipped"},
        )
        preview = build_update(change, "mysql", where_extra={"version": 4})
        assert preview.sql.endswith("WHERE `id` = %s AND `version` = %s")
        assert preview.params == ("shipped", 3, 4)


class TestParameters:
    def test_update_params_are_set_values_then_key(self) -> None:
        preview = build_update(update(values={"a": 1, "b": "two"}), "mysql")
        assert preview.params == (1, "two", 7)

    def test_key_values_keep_their_python_type(self) -> None:
        # The defect this fixes: the old grid sent WHERE id = '7'.
        change = update(key_columns=("id",), key_values={"id": 7}, values={"name": "x"})
        assert build_update(change, "mysql").params == ("x", 7)
        assert isinstance(build_update(change, "mysql").params[-1], int)

    def test_insert_params_follow_column_order(self) -> None:
        change = PendingChange(
            ChangeKind.INSERT,
            "users",
            "app",
            values={"name": "O'Brien", "age": 30},
        )
        preview = build_insert(change, "postgresql")
        assert preview.params == ("O'Brien", 30)

    def test_delete_has_no_set_params(self) -> None:
        change = PendingChange(ChangeKind.DELETE, "users", "app", ("id",), {"id": 5})
        assert build_delete(change, "mysql").params == (5,)


class TestMergingEdits:
    def test_repeated_edits_to_one_cell_keep_the_last(self) -> None:
        edits = [
            update(values={"name": "a"}),
            update(values={"name": "b"}),
            update(values={"name": "c"}),
        ]
        merged = merge_cell_edits(edits)
        assert len(merged) == 1
        assert merged[0].values == {"name": "c"}

    def test_different_columns_merge_into_one_statement(self) -> None:
        edits = [
            update(values={"name": "b"}),
            update(values={"age": 5}),
        ]
        merged = merge_cell_edits(edits)
        assert len(merged) == 1
        sql = build_update(merged[0], "mysql").sql
        assert sql.count("UPDATE") == 1
        assert "`name` = %s, `age` = %s" in sql

    def test_different_rows_stay_separate(self) -> None:
        edits = [
            update(key_values={"id": 1}, values={"a": 1}),
            update(key_values={"id": 2}, values={"a": 2}),
        ]
        assert len(merge_cell_edits(edits)) == 2

    def test_plan_changes_deduplicates_identical_edits(self) -> None:
        previews = plan_changes([update(values={"a": 1}), update(values={"a": 1})])
        assert len(previews) == 1

    def test_plan_changes_renders_every_kind(self) -> None:
        changes = [
            update(values={"a": 1}),
            PendingChange(ChangeKind.INSERT, "users", "app", values={"b": 2}),
            PendingChange(ChangeKind.DELETE, "logs", "app", ("id",), {"id": 3}),
        ]
        sqls = [p.sql.split()[0] for p in plan_changes(changes)]
        assert sqls == ["UPDATE", "INSERT", "DELETE"]


class TestCoercion:
    @pytest.mark.parametrize(
        "text,reference,expected",
        [
            ("7", 7, 7),
            (" 7 ", 7, 7),
            ("-3", 0, -3),
            ("3.5", 0.0, 3.5),
        ],
    )
    def test_numeric_columns(self, text, reference, expected) -> None:
        assert coerce_like(text, reference) == expected

    def test_bool_column(self) -> None:
        assert coerce_like("true", False) is True
        assert coerce_like("0", True) is False
        assert coerce_like("no", True) is False

    def test_datetime_column(self) -> None:
        got = coerce_like("2026-01-02 03:04:05", datetime.datetime(2026, 1, 1))
        assert got == datetime.datetime(2026, 1, 2, 3, 4, 5)

    def test_date_column(self) -> None:
        assert coerce_like("2026-01-02", datetime.date(2026, 1, 1)) == datetime.date(2026, 1, 2)

    def test_decimal_column_keeps_scale(self) -> None:
        assert coerce_like("1.50", decimal.Decimal("1")) == decimal.Decimal("1.50")

    def test_unparseable_text_is_left_alone(self) -> None:
        # Better a clear type error from the driver than a silent 0.
        assert coerce_like("abc", 7) == "abc"

    def test_text_column_untouched(self) -> None:
        assert coerce_like("007", "x") == "007"

    @pytest.mark.parametrize("text", sorted(NULL_SPELLINGS))
    def test_null_spellings(self, text) -> None:
        assert cell_value_from_text(text, "x") is None

    def test_blank_cell_means_null(self) -> None:
        assert cell_value_from_text("   ", 7) is None

    def test_non_string_passes_through(self) -> None:
        assert cell_value_from_text(5, "x") == 5  # type: ignore[arg-type]


class TestPreviewRendering:
    def test_sql_with_values_inlines_for_display(self) -> None:
        preview = build_update(update(values={"name": "O'Brien"}), "mysql")
        rendered = preview.sql_with_values
        assert "''Brien" in rendered
        assert "%s" not in rendered

    def test_target_is_human_readable(self) -> None:
        assert update().target == "id=7"

    def test_new_row_target(self) -> None:
        assert PendingChange(ChangeKind.INSERT, "t", values={"a": 1}).target == "(new row)"

    def test_identity_distinguishes_rows_and_kinds(self) -> None:
        assert update(key_values={"id": 1}).identity() != update(key_values={"id": 2}).identity()
        ins = PendingChange(ChangeKind.INSERT, "users", "app", values={"a": 1})
        assert ins.identity() != update().identity()


class TestColumnPinning:
    def test_pinned_columns_move_to_the_front(self) -> None:
        cols = ["id", "name", "email"]
        assert order_columns(cols, ["email"]) == ["email", "id", "name"]

    def test_pinned_order_is_preserved(self) -> None:
        cols = ["a", "b", "c", "d"]
        assert order_columns(cols, ["c", "a"]) == ["c", "a", "b", "d"]

    def test_unpinned_columns_keep_their_relative_order(self) -> None:
        cols = ["a", "b", "c", "d"]
        assert order_columns(cols, ["b"]) == ["b", "a", "c", "d"]

    def test_unknown_pinned_name_is_ignored(self) -> None:
        assert order_columns(["a", "b"], ["ghost"]) == ["a", "b"]

    def test_empty_pinned_list_changes_nothing(self) -> None:
        cols = ["a", "b", "c"]
        assert order_columns(cols, []) == cols

    def test_toggle_adds_and_removes(self) -> None:
        assert toggle_pin([], "id") == ["id"]
        assert toggle_pin(["id"], "id") == []

    def test_toggle_keeps_insertion_order(self) -> None:
        pinned = toggle_pin(toggle_pin([], "b"), "a")
        assert pinned == ["b", "a"]

    def test_toggle_refuses_beyond_the_cap(self) -> None:
        pinned = ["a", "b", "c"]
        assert toggle_pin(pinned, "d") == pinned

    def test_toggle_can_still_remove_at_the_cap(self) -> None:
        assert toggle_pin(["a", "b", "c"], "b") == ["a", "c"]


class TestBulkSelection:
    ROWS = [[1, "a"], [2, "b"], [3, "c"]]

    def test_distinct_rows_from_cells(self) -> None:
        got = selected_rows(self.ROWS, [(0, 0), (0, 1), (2, 0)])
        assert got == [[1, "a"], [3, "c"]]

    def test_rows_come_back_in_display_order(self) -> None:
        got = selected_rows(self.ROWS, [(2, 0), (0, 0)])
        assert got == [[1, "a"], [3, "c"]]

    def test_out_of_range_is_ignored(self) -> None:
        assert selected_rows(self.ROWS, [(99, 0)]) == []

    def test_empty_selection(self) -> None:
        assert selected_rows(self.ROWS, []) == []


class TestCopyRendering:
    COLS = ["id", "name"]
    ROWS = [[1, "O'Brien"], [2, None]]

    def test_insert_per_engine(self) -> None:
        sql = copy_as_insert("users", self.COLS, self.ROWS, "postgresql")
        assert sql.count("INSERT INTO") == 2
        assert 'INSERT INTO "users" ("id", "name") VALUES (1, \'O\'\'Brien\');' in sql
        assert '"id" = ' not in sql

    def test_insert_mysql_quoting_and_null(self) -> None:
        sql = copy_as_insert("users", self.COLS, self.ROWS, "mysql")
        assert "`users`" in sql
        assert "'O''Brien'" in sql
        assert "(2, NULL)" in sql

    def test_insert_empty_rows_gives_empty_string(self) -> None:
        assert copy_as_insert("users", self.COLS, [], "mysql") == ""

    def test_update_uses_key_in_where(self) -> None:
        sql = copy_as_update("users", ["id", "name"], [[7, "x"]], ["id"], "mysql")
        assert sql == "UPDATE `users` SET `name` = 'x' WHERE `id` = 7;"

    def test_update_refuses_without_a_key(self) -> None:
        # An UPDATE with no WHERE would hit every row.
        assert copy_as_update("users", self.COLS, self.ROWS, [], "mysql") == ""

    def test_update_refuses_when_key_is_not_in_the_columns(self) -> None:
        assert copy_as_update("users", ["name"], [["x"]], ["id"], "mysql") == ""

    def test_update_refuses_when_only_keys_are_present(self) -> None:
        assert copy_as_update("users", ["id"], [[1]], ["id"], "mysql") == ""

    def test_update_composite_key(self) -> None:
        sql = copy_as_update(
            "orders",
            ["tenant", "id", "status"],
            [[9, 3, "shipped"]],
            ["tenant", "id"],
            "postgresql",
        )
        assert sql == (
            'UPDATE "orders" SET "status" = \'shipped\' WHERE "tenant" = 9 AND "id" = 3;'
        )

    def test_where_single_row(self) -> None:
        assert copy_as_where(["id"], [[5]], ["id"], "mysql") == "`id` = 5"

    def test_where_multiple_rows_are_ored(self) -> None:
        got = copy_as_where(["id"], [[1], [2]], ["id"], "mysql")
        assert got == "(`id` = 1) OR (`id` = 2)"

    def test_where_without_key_is_empty(self) -> None:
        assert copy_as_where(["id"], [[1]], [], "mysql") == ""
