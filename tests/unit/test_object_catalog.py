"""Tests for the object catalog (open_navicat.services.object_catalog).

The browser had no index: each category was rendered lazily into widget items, so
"where is the table called orders?" could only be answered by expanding branches
by hand, and never across databases.
"""

from __future__ import annotations

import pytest

from open_navicat.models.table_schema import ColumnInfo, ForeignKeyInfo, IndexInfo, TableInfo
from open_navicat.services.object_catalog import (
    KIND_ORDER,
    Catalog,
    ObjectKind,
    ObjectRef,
    objects_from_names,
    objects_from_routines,
    objects_from_table_info,
    objects_from_triggers,
    search_across,
)


class TestObjectRef:
    def test_qualified_name(self) -> None:
        assert ObjectRef(ObjectKind.TABLE, "orders", database="sales").qualified_name == (
            "sales.orders"
        )

    def test_qualified_name_without_database(self) -> None:
        assert ObjectRef(ObjectKind.TABLE, "orders").qualified_name == "orders"

    def test_display_shows_the_parent(self) -> None:
        ref = ObjectRef(ObjectKind.INDEX, "idx_a", parent="orders")
        assert ref.display == "idx_a  (orders)"

    def test_display_without_parent(self) -> None:
        assert ObjectRef(ObjectKind.TABLE, "orders").display == "orders"

    @pytest.mark.parametrize(
        "needle",
        ["orders", "ORDERS", "sales.orders", "table", " sales "],
    )
    def test_matches_name_case_kind_and_qualified_form(self, needle) -> None:
        ref = ObjectRef(ObjectKind.TABLE, "orders", database="sales")
        assert ref.matches(needle) is True

    def test_non_match(self) -> None:
        ref = ObjectRef(ObjectKind.TABLE, "orders")
        assert ref.matches("customers") is False

    def test_blank_needle_matches_everything(self) -> None:
        # The catalog's own search() decides that a blank query means "no
        # results"; at this level it is a plain predicate.
        assert ObjectRef(ObjectKind.TABLE, "x").matches("") is True


class TestGrouping:
    def catalog(self) -> Catalog:
        cat = Catalog()
        cat.add_all(objects_from_names(["b", "a"], ObjectKind.TABLE, database="db"))
        cat.add_all(objects_from_names(["v"], ObjectKind.VIEW, database="db"))
        return cat

    def test_len_and_bool(self) -> None:
        assert len(self.catalog()) == 3
        assert bool(self.catalog()) is True
        assert bool(Catalog()) is False

    def test_by_kind_keeps_kind_order(self) -> None:
        groups = self.catalog().by_kind()
        assert list(groups) == [ObjectKind.TABLE, ObjectKind.VIEW]

    def test_objects_are_sorted_within_a_kind(self) -> None:
        assert [o.name for o in self.catalog().by_kind()[ObjectKind.TABLE]] == ["a", "b"]

    def test_empty_kinds_are_omitted(self) -> None:
        assert ObjectKind.TRIGGER not in self.catalog().by_kind()

    def test_by_kind_can_filter(self) -> None:
        groups = self.catalog().by_kind(ObjectKind.VIEW)
        assert list(groups) == [ObjectKind.VIEW]

    def test_counts(self) -> None:
        assert self.catalog().counts() == {"table": 2, "view": 1}

    def test_summary_mentions_everything(self) -> None:
        cat = self.catalog()
        cat.databases = [("c1", "db")]
        text = cat.summary()
        assert "2 tables" in text
        assert "1 view" in text
        assert "1 database(s)" in text

    def test_summary_of_an_empty_catalog(self) -> None:
        assert Catalog().summary() == "no objects"


class TestSearch:
    def catalog(self) -> Catalog:
        cat = Catalog()
        cat.add_all(
            objects_from_names(["orders", "order_items"], ObjectKind.TABLE, database="sales")
        )
        cat.add_all(objects_from_names(["orders_view"], ObjectKind.VIEW, database="sales"))
        cat.add(ObjectRef(ObjectKind.TABLE, "users", database="auth"))
        return cat

    def test_finds_substring(self) -> None:
        names = {o.name for o in self.catalog().search("order")}
        assert names == {"orders", "order_items", "orders_view"}

    def test_is_case_insensitive(self) -> None:
        assert len(self.catalog().search("ORDERS")) == 2

    def test_tables_sort_before_other_kinds(self) -> None:
        hits = self.catalog().search("orders")
        assert hits[0].kind is ObjectKind.TABLE

    def test_qualified_search_targets_one_database(self) -> None:
        hits = self.catalog().search("auth.users")
        assert [o.name for o in hits] == ["users"]

    def test_search_by_kind_word(self) -> None:
        # "view" finds views, which is how a user narrows a long list.
        hits = self.catalog().search("view")
        assert [o.kind for o in hits] == [ObjectKind.VIEW]

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    def test_blank_query_returns_nothing(self, blank) -> None:
        assert self.catalog().search(blank) == []

    def test_limit_is_respected(self) -> None:
        assert len(self.catalog().search("order", limit=2)) == 2

    def test_no_match(self) -> None:
        assert self.catalog().search("zzz") == []


class TestBuilders:
    def test_routines_split_into_procedures_and_functions(self) -> None:
        refs = objects_from_routines(
            [("do_thing", "PROCEDURE"), ("calc", "FUNCTION")], database="db"
        )
        kinds = {r.name: r.kind for r in refs}
        assert kinds == {"do_thing": ObjectKind.PROCEDURE, "calc": ObjectKind.FUNCTION}

    @pytest.mark.parametrize("label", ["FUNCTION", "function", "FUNC", "F"])
    def test_function_spellings(self, label) -> None:
        refs = objects_from_routines([("f", label)])
        assert refs[0].kind is ObjectKind.FUNCTION

    def test_unknown_routine_type_defaults_to_procedure(self) -> None:
        refs = objects_from_routines([("x", "")])
        assert refs[0].kind is ObjectKind.PROCEDURE

    def test_triggers_record_their_table_as_parent(self) -> None:
        refs = objects_from_triggers([("trg_audit", "orders")], database="db")
        assert refs[0].kind is ObjectKind.TRIGGER
        assert refs[0].parent == "orders"

    def test_trigger_without_table(self) -> None:
        refs = objects_from_triggers([("trg", "")])
        assert refs[0].parent == ""

    def test_names_become_entries(self) -> None:
        refs = objects_from_names(["a", "b"], ObjectKind.VIEW, database="db")
        assert [(r.name, r.kind, r.database) for r in refs] == [
            ("a", ObjectKind.VIEW, "db"),
            ("b", ObjectKind.VIEW, "db"),
        ]

    def test_table_info_yields_indexes_constraints_and_columns(self) -> None:
        info = TableInfo(
            name="orders",
            database="db",
            columns=[
                ColumnInfo(name="id", data_type="int", is_primary_key=True),
                ColumnInfo(name="user_id", data_type="int"),
            ],
            indexes=[IndexInfo(name="idx_user", columns=["user_id"], is_unique=True)],
            foreign_keys=[
                ForeignKeyInfo(name="fk_user", column="user_id", ref_table="users", ref_column="id")
            ],
        )
        refs = objects_from_table_info(info, database="db")
        by_kind = {}
        for ref in refs:
            by_kind.setdefault(ref.kind, []).append(ref)

        assert [r.name for r in by_kind[ObjectKind.COLUMN]] == ["id", "user_id"]
        assert [r.name for r in by_kind[ObjectKind.INDEX]] == ["idx_user"]
        assert by_kind[ObjectKind.INDEX][0].detail == "user_id"
        assert [r.name for r in by_kind[ObjectKind.CONSTRAINT]] == ["fk_user"]
        assert by_kind[ObjectKind.CONSTRAINT][0].detail == "user_id -> users"

    def test_table_info_objects_carry_the_table_as_parent(self) -> None:
        info = TableInfo(
            name="orders",
            database="db",
            columns=[ColumnInfo(name="id", data_type="int")],
        )
        refs = objects_from_table_info(info, database="db")
        assert all(r.parent == "orders" for r in refs)

    def test_table_info_with_nothing_extra(self) -> None:
        assert objects_from_table_info(TableInfo(name="t", database="db")) == []


class TestCrossConnectionSearch:
    def catalogs(self):
        prod = Catalog()
        prod.add_all(objects_from_names(["orders"], ObjectKind.TABLE, database="sales"))
        staging = Catalog()
        staging.add_all(
            objects_from_names(["orders", "orders_v2"], ObjectKind.TABLE, database="sales")
        )
        return [("Production", prod), ("Staging", staging)]

    def test_results_stay_grouped_by_connection(self) -> None:
        found = search_across(self.catalogs(), "orders")
        assert set(found) == {"Production", "Staging"}
        assert len(found["Production"]) == 1
        assert len(found["Staging"]) == 2

    def test_connections_without_matches_are_omitted(self) -> None:
        found = search_across(self.catalogs(), "orders_v2")
        assert set(found) == {"Staging"}

    def test_blank_query_returns_nothing(self) -> None:
        assert search_across(self.catalogs(), "") == {}

    def test_no_matches_anywhere(self) -> None:
        assert search_across(self.catalogs(), "zzz") == {}


class TestKindOrder:
    def test_tables_come_first(self) -> None:
        assert KIND_ORDER[0] is ObjectKind.TABLE

    def test_every_kind_is_listed_once(self) -> None:
        assert len(set(KIND_ORDER)) == len(KIND_ORDER)

    def test_order_covers_all_kinds(self) -> None:
        assert set(KIND_ORDER) == set(ObjectKind)
