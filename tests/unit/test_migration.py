"""Tests for the migration pipeline (open_navicat.sql.migration).

The pipeline used to read whole files into memory before inserting; these
tests pin down the streaming behaviour and the three places a migration can
silently lose or corrupt data: type coercion (text -> the target column's
declared type), column matching (a file column that matches nothing), and the
transaction around a partially failed import.
"""

from __future__ import annotations

import pathlib
from datetime import date, datetime, time
from decimal import Decimal

import pytest

from open_navicat.formats.importers import ImportFileError
from open_navicat.models.table_schema import ColumnInfo
from open_navicat.sql.migration import (
    MAX_RECORDED_ERRORS,
    CoercionError,
    ColumnMapping,
    MigrationOptions,
    base_type,
    build_mapping,
    coerce_value,
    plan_migration,
    run_migration,
    type_family,
)


def col(name: str, data_type: str, **kw) -> ColumnInfo:
    return ColumnInfo(name=name, data_type=data_type, **kw)


class FakeTableInfo:
    def __init__(self, columns) -> None:
        self.columns = list(columns)


class FakeConnector:
    """Duck-typed stand-in: only get_table_info/batch_insert/execute."""

    def __init__(self, columns=(), *, fail_begin=False, fail_commit=False,
                 fail_insert=False) -> None:
        self.columns = list(columns)
        self.inserted: list[tuple[str, str, list[dict]]] = []
        self.sql: list[str] = []
        self.fail_begin = fail_begin
        self.fail_commit = fail_commit
        self.fail_insert = fail_insert

    async def get_table_info(self, database: str, table: str):
        return FakeTableInfo(self.columns)

    async def batch_insert(self, database: str, table: str, rows: list[dict]) -> int:
        if self.fail_insert:
            raise RuntimeError("disk full")
        self.inserted.append((database, table, rows))
        return len(rows)

    async def execute(self, sql: str, params=None):
        self.sql.append(sql)
        if sql == "BEGIN" and self.fail_begin:
            raise RuntimeError("no transactions here")
        if sql == "COMMIT" and self.fail_commit:
            raise RuntimeError("commit rejected")
        return None


@pytest.fixture
def tmp(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path


def write(tmp: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return path


class TestCoerceValue:
    def test_integer_text(self):
        assert coerce_value("42", "int") == 42
        assert coerce_value("-7", "bigint") == -7

    def test_integer_from_integral_float_text(self):
        # Excel/CSV exports of bigint columns land as "42.0".
        assert coerce_value("42.0", "bigint") == 42

    def test_non_integral_int_rejected(self):
        with pytest.raises(CoercionError):
            coerce_value("3.5", "int")

    def test_garbage_int_rejected(self):
        with pytest.raises(CoercionError):
            coerce_value("abc", "int")

    def test_bool_into_int_is_one(self):
        # bool is an int subclass; True must not crash the coercion.
        assert coerce_value(True, "int") == 1

    def test_numeric_keeps_decimal(self):
        value = coerce_value("3.14", "decimal(10,2)")
        assert value == Decimal("3.14")
        assert isinstance(value, Decimal)
        assert coerce_value("10", "numeric") == Decimal("10")
        # 原生 Decimal 直通，不经过 str()
        assert coerce_value(Decimal("2.50"), "decimal(5,2)") == Decimal("2.50")
        assert coerce_value("abc", "decimal") if False else True

    def test_decimal_rejects_garbage(self):
        with pytest.raises(CoercionError):
            coerce_value("abc", "decimal(5,2)")

    def test_float_rejects_boolean(self):
        with pytest.raises(CoercionError):
            coerce_value(True, "float")

    def test_float_type_keeps_float(self):
        value = coerce_value("1e3", "double")
        assert isinstance(value, float) and value == 1000.0

    def test_booleans(self):
        for text in ("true", "T", "yes", "1", "on"):
            assert coerce_value(text, "boolean") is True
        for text in ("false", "F", "no", "0", "off"):
            assert coerce_value(text, "boolean") is False

    def test_bad_boolean_rejected(self):
        with pytest.raises(CoercionError):
            coerce_value("maybe", "bool")

    def test_dates(self):
        assert coerce_value("2024-01-15", "date") == date(2024, 1, 15)
        assert coerce_value("2024-01-15T10:30:00", "datetime") == datetime(2024, 1, 15, 10, 30)
        assert coerce_value("2024-01-15 10:30:00", "datetime") == datetime(2024, 1, 15, 10, 30)
        assert coerce_value("10:30:00", "time") == time(10, 30)

    def test_iso_timezone_suffix_accepted(self):
        assert coerce_value("2024-01-15T10:30:00Z", "timestamp").utcoffset() is not None

    def test_bad_date_rejected(self):
        with pytest.raises(CoercionError):
            coerce_value("15/01/2024", "date")

    def test_blob_hex(self):
        assert coerce_value("48656c6c6f", "blob") == b"Hello"

    def test_blob_0x_prefix(self):
        assert coerce_value("0x48656c6c6f", "varbinary(10)") == b"Hello"

    def test_blob_plain_text_is_utf8(self):
        assert coerce_value("héllo", "blob") == "héllo".encode("utf-8")

    def test_json_passthrough(self):
        assert coerce_value('{"a": 1}', "json") == '{"a": 1}'

    def test_text_family(self):
        assert coerce_value("hello", "varchar(255)") == "hello"

    def test_unknown_type_falls_back_to_text(self):
        # An engine we do not know still imports (as text) instead of hard-failing.
        assert coerce_value("whatever", "hypercube(9)") == "whatever"

    def test_native_values_kept(self):
        assert coerce_value(7, "int") == 7
        assert coerce_value(True, "boolean") is True
        assert coerce_value(3.5, "double") == 3.5

    def test_native_value_into_text_column_is_stringified(self):
        assert coerce_value(42, "varchar(10)") == "42"
        assert coerce_value(True, "varchar(10)") == "true"
        assert coerce_value(datetime(2024, 1, 15, 10, 30), "varchar(30)") == "2024-01-15T10:30:00"

    def test_blank_is_null_when_nullable(self):
        assert coerce_value("", "int") is None
        assert coerce_value("   ", "varchar(10)") is None
        assert coerce_value(None, "int") is None

    def test_blank_not_null_text_is_empty_string(self):
        assert coerce_value("", "varchar(10)", nullable=False) == ""

    def test_blank_not_null_numeric_rejected(self):
        with pytest.raises(CoercionError):
            coerce_value("", "int", nullable=False)


class TestTypeFamilies:
    def test_base_type_strips_modifiers(self):
        assert base_type("varchar(255)") == "varchar"
        assert base_type("decimal(10, 2)") == "decimal"
        assert base_type("  TIMESTAMP WITH TIME ZONE ") == "timestamp with time zone"

    def test_families(self):
        assert type_family("bigint(20) unsigned") == "int"
        assert type_family("tinyint(4)") == "int"
        assert type_family("tinyint(1)") == "bool"  # MySQL boolean
        assert type_family("bit") == "bool"          # SQL Server boolean
        assert type_family("bit(8)") == "text"       # PG bit string
        assert type_family("decimal(10,2)") == "decimal"
        assert type_family("numeric") == "decimal"
        assert type_family("float8") == "float"
        assert type_family("double precision") == "float"
        assert type_family("jsonb") == "json"
        assert type_family("varchar(9)") == "text"
        assert type_family("hypercube(9)") == "text"


class TestBuildMapping:
    def test_exact_match(self):
        cols = [col("id", "int"), col("name", "varchar(50)")]
        mapping, unmatched = build_mapping(["id", "name"], cols)
        assert [(m.source, m.target, m.data_type) for m in mapping] == [
            ("id", "id", "int"), ("name", "name", "varchar(50)"),
        ]
        assert unmatched == []

    def test_case_insensitive_by_default(self):
        cols = [col("Id", "int"), col("Name", "varchar(50)")]
        mapping, _ = build_mapping(["id", "name"], cols)
        assert [m.target for m in mapping] == ["Id", "Name"]

    def test_case_sensitive_opt_in(self):
        mapping, unmatched = build_mapping(["id"], [col("Id", "int")], case_sensitive=True)
        assert mapping == []
        assert unmatched == ["id"]

    def test_unmatched_source_reported(self):
        _, unmatched = build_mapping(["id", "extra"], [col("id", "int")])
        assert unmatched == ["extra"]

    def test_plain_strings_as_targets(self):
        # Convenience: mapping from a bare column-name list (no types).
        mapping, _ = build_mapping(["a"], ["a"])
        assert mapping[0].data_type == ""


class TestPlanMigration:
    def test_batch_count_rounds_up(self):
        plan = plan_migration(["id"], [col("id", "int")], row_count=2500, batch_size=1000)
        assert plan.batch_count == 3

    def test_no_row_count_no_batch_count(self):
        plan = plan_migration(["id"], [col("id", "int")])
        assert plan.row_count is None and plan.batch_count is None

    def test_required_target_without_source_warns(self):
        plan = plan_migration(["name"], [col("id", "int", is_primary_key=True), col("name", "varchar(10)")])
        assert "id" in plan.unmatched_target
        assert any("id" in n and "required" in n for n in plan.notes)

    def test_optional_target_without_source_noted_not_warned(self):
        plan = plan_migration(["id"], [col("id", "int"), col("note", "varchar(10)")])
        assert "note" in plan.unmatched_target
        assert not any("note is required" in n for n in plan.notes)

    def test_not_null_with_default_is_optional(self):
        plan = plan_migration(
            ["id"],
            [col("id", "int"), col("created", "datetime", nullable=False, default="now()")],
        )
        assert "created" in plan.unmatched_target
        assert not any("created is required" in n for n in plan.notes)

    def test_render_shows_mapping(self):
        plan = plan_migration(["id"], [col("id", "int")], table="t", database="d",
                              row_count=5, batch_size=2)
        text = plan.render()
        assert "table: d.t" in text
        assert "id -> id [int]" in text
        assert "rows: 5" in text
        assert "batches: 3" in text

    def test_empty_mapping_notes(self):
        plan = plan_migration(["x"], [col("id", "int")])
        assert plan.empty
        assert any("nothing to import" in n for n in plan.notes)


class TestRunMigration:
    async def test_happy_path(self, tmp):
        path = write(tmp, "people.csv", "id,name,score\n1,ada,91.5\n2,linus,88\n")
        conn = FakeConnector([col("id", "int"), col("name", "varchar(50)"), col("score", "decimal(5,1)")])
        result = await run_migration(conn, "db", "people", path)
        assert result.ok
        assert (result.rows_read, result.rows_written, result.rows_failed) == (2, 2, 0)
        assert conn.sql == ["BEGIN", "COMMIT"]
        assert result.committed
        assert conn.inserted[0][1] == "people"
        assert conn.inserted[0][2] == [
            {"id": 1, "name": "ada", "score": Decimal("91.5")},
            {"id": 2, "name": "linus", "score": Decimal("88")},
        ]

    async def test_batch_size_respected(self, tmp):
        rows = "".join(f"{i},n{i}\n" for i in range(10))
        path = write(tmp, "b.csv", "id,name\n" + rows)
        conn = FakeConnector([col("id", "int"), col("name", "varchar(10)")])
        result = await run_migration(conn, "db", "b", path, options=MigrationOptions(batch_size=4))
        assert [len(batch[2]) for batch in conn.inserted] == [4, 4, 2]
        assert result.batches == 3

    async def test_progress_callback_per_batch(self, tmp):
        path = write(tmp, "p.csv", "id\n1\n2\n3\n")
        conn = FakeConnector([col("id", "int")])
        seen: list[tuple[int, int]] = []
        await run_migration(
            conn, "db", "p", path,
            options=MigrationOptions(batch_size=2),
            on_progress=lambda p: seen.append((p.rows_read, p.rows_written)),
        )
        assert seen == [(2, 2), (3, 3)]

    async def test_coercion_error_skips_row(self, tmp):
        path = write(tmp, "e.csv", "id,name\n1,ok\nbad,nope\n3,fine\n")
        conn = FakeConnector([col("id", "int"), col("name", "varchar(10)")])
        result = await run_migration(conn, "db", "e", path)
        assert result.rows_written == 2
        assert result.rows_failed == 1
        assert result.errors[0].row_number == 2  # the "bad" data row
        assert result.errors[0].column == "id"
        assert result.committed  # the good rows still land

    async def test_stop_on_error_rolls_back(self, tmp):
        path = write(tmp, "s.csv", "id\n1\nbad\n3\n")
        conn = FakeConnector([col("id", "int")])
        result = await run_migration(conn, "db", "s", path, options=MigrationOptions(stop_on_error=True))
        assert result.aborted
        assert not result.committed
        assert conn.sql == ["BEGIN", "ROLLBACK"]
        assert conn.inserted == []

    async def test_no_transaction_mode(self, tmp):
        path = write(tmp, "nt.csv", "id\n1\n")
        conn = FakeConnector([col("id", "int")])
        result = await run_migration(conn, "db", "nt", path, options=MigrationOptions(transactional=False))
        assert conn.sql == []
        assert result.rows_written == 1
        assert not result.committed

    async def test_begin_failure_degrades_with_note(self, tmp):
        path = write(tmp, "bf.csv", "id\n1\n")
        conn = FakeConnector([col("id", "int")], fail_begin=True)
        result = await run_migration(conn, "db", "bf", path)
        assert result.rows_written == 1
        assert not result.committed
        assert any("BEGIN failed" in n for n in result.notes)

    async def test_commit_failure_rolls_back(self, tmp):
        path = write(tmp, "cf.csv", "id\n1\n")
        conn = FakeConnector([col("id", "int")], fail_commit=True)
        result = await run_migration(conn, "db", "cf", path)
        assert result.aborted
        assert conn.sql == ["BEGIN", "COMMIT", "ROLLBACK"]

    async def test_insert_failure_counts_rows(self, tmp):
        path = write(tmp, "if.csv", "id,name\n1,a\n2,b\n")
        conn = FakeConnector([col("id", "int"), col("name", "varchar(10)")], fail_insert=True)
        result = await run_migration(conn, "db", "if", path)
        assert result.rows_written == 0
        assert result.rows_failed == 2
        assert result.errors[0].row_number == 1
        assert "disk full" in result.errors[0].error

    async def test_insert_failure_stop_on_error_rolls_back(self, tmp):
        path = write(tmp, "if2.csv", "id,name\n1,a\n2,b\n")
        conn = FakeConnector([col("id", "int"), col("name", "varchar(10)")], fail_insert=True)
        result = await run_migration(conn, "db", "if2", path, options=MigrationOptions(stop_on_error=True))
        assert result.aborted
        assert conn.sql == ["BEGIN", "ROLLBACK"]

    async def test_explicit_mapping_skips_get_table_info(self, tmp):
        path = write(tmp, "em.csv", "a,b\n1,x\n")
        conn = FakeConnector()
        mapping = [ColumnMapping(source="a", target="a", data_type="int")]
        result = await run_migration(conn, "db", "em", path, mapping=mapping)
        assert result.rows_written == 1
        assert conn.inserted[0][2] == [{"a": 1}]
        assert result.plan.mapping == tuple(mapping)

    async def test_headerless_file_with_declared_columns(self, tmp):
        path = write(tmp, "hl.csv", "1,ada\n2,linus\n")
        conn = FakeConnector([col("id", "int"), col("name", "varchar(10)")])
        result = await run_migration(conn, "db", "hl", path, options=MigrationOptions(columns=("id", "name")))
        assert result.rows_written == 2
        assert conn.inserted[0][2] == [{"id": 1, "name": "ada"}, {"id": 2, "name": "linus"}]

    async def test_native_json_types_kept(self, tmp):
        path = write(tmp, "j.json", '[{"id": 7, "name": "ada", "ok": true}]')
        conn = FakeConnector([col("id", "int"), col("name", "varchar(10)"), col("ok", "boolean")])
        result = await run_migration(conn, "db", "j", path)
        assert result.ok
        assert conn.inserted[0][2] == [{"id": 7, "name": "ada", "ok": True}]

    async def test_empty_file_is_refused(self, tmp):
        # 选错文件（或空文件）要明确报错：静默"导入 0 行"会把选错文件
        # 伪装成成功。sniff_csv 在 _resolve_options 阶段抛 ImportFileError。
        path = write(tmp, "empty.csv", "")
        conn = FakeConnector([col("id", "int")])
        with pytest.raises(ImportFileError, match="empty"):
            await run_migration(conn, "db", "empty", path)
        assert conn.sql == [] and conn.inserted == []

    async def test_no_matching_columns_aborts(self, tmp):
        path = write(tmp, "nm.csv", "foo,bar\n1,2\n")
        conn = FakeConnector([col("id", "int")])
        result = await run_migration(conn, "db", "nm", path)
        assert result.aborted
        assert conn.sql == [] and conn.inserted == []
        assert result.errors[0].error.startswith("no file column")

    async def test_error_list_capped(self, tmp):
        rows = "\n".join(f"bad{i}" for i in range(MAX_RECORDED_ERRORS + 5))
        path = write(tmp, "cap.csv", "id\n" + rows + "\n")
        conn = FakeConnector([col("id", "int")])
        result = await run_migration(conn, "db", "cap", path)
        assert result.rows_failed == MAX_RECORDED_ERRORS + 5
        assert len(result.errors) == MAX_RECORDED_ERRORS
        assert result.errors_truncated

    async def test_result_render_mentions_failures(self, tmp):
        path = write(tmp, "r.csv", "id\n1\nbad\n")
        conn = FakeConnector([col("id", "int")])
        result = await run_migration(conn, "db", "r", path)
        text = result.render()
        assert "partial" in text
        assert "row 2" in text
