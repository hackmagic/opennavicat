"""Tests for streaming export (open_navicat.formats.exporters).

Covers the two defects the old inline export had: one unbounded ``SELECT *``
held the whole result set in memory, and filter values were interpolated into
the ``WHERE`` clause as raw text.
"""

from __future__ import annotations

import csv
import datetime
import decimal
import json
import pathlib
import zipfile

import pytest

from open_navicat.formats import (
    ExportFormat,
    Filter,
    build_filter_clause,
    export_rows,
    iter_csv_chunks,
    render_csv_chunk,
    render_markdown_table,
)
from open_navicat.formats.exporters import PANEL_KEY

HEADER = ["id", "note", "amount"]
BATCHES = [
    [[1, "O'Brien", decimal.Decimal("3.5")], [2, None, 10]],
    [[3, "line\nbreak", 0]],
]


@pytest.fixture
def out(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path


class TestFilterClause:
    @pytest.mark.parametrize(
        "engine,expected",
        [
            ("mysql", "`note` = 'x'"),
            ("postgresql", "\"note\" = 'x'"),
            ("sqlserver", "[note] = 'x'"),
            ("clickhouse", "`note` = 'x'"),
        ],
    )
    def test_identifier_quoting_follows_the_engine(self, engine, expected) -> None:
        assert build_filter_clause([Filter("note", "x")], engine) == expected

    def test_value_is_quoted_not_interpolated(self) -> None:
        # The old code produced `note` = 'O'Brien' — a broken statement.
        clause = build_filter_clause([Filter("note", "O'Brien")], "mysql")
        assert clause == "`note` = 'O''Brien'"

    def test_injection_attempt_stays_a_literal(self) -> None:
        clause = build_filter_clause([Filter("note", "x'; DROP TABLE t; --")], "mysql")
        # The dangerous text ends up inside one string literal: the embedded
        # quote is doubled, so the statement cannot be split in two.
        assert clause == "`note` = 'x''; DROP TABLE t; --'"
        assert clause.startswith("`note` = '")
        assert clause.endswith("--'")

    def test_panel_fragment_is_not_quoted_again(self) -> None:
        # The visual panel stores a finished expression under a marker key.
        clause = build_filter_clause([Filter(PANEL_KEY, "a = 1 AND b LIKE 'x'")], "mysql")
        assert clause == "(a = 1 AND b LIKE 'x')"

    def test_raw_operator_also_marks_a_fragment(self) -> None:
        clause = build_filter_clause([Filter("", "1 = 1", "RAW")], "mysql")
        assert clause == "(1 = 1)"

    def test_empty_raw_fragment_is_skipped(self) -> None:
        assert build_filter_clause([Filter(PANEL_KEY, "")], "mysql") == ""

    def test_operators_are_preserved(self) -> None:
        clause = build_filter_clause([Filter("amount", "5", ">=")], "mysql")
        assert clause == "`amount` >= '5'"

    def test_in_list_is_split_and_quoted(self) -> None:
        clause = build_filter_clause([Filter("id", "1, 2,3", "IN")], "mysql")
        assert clause == "`id` IN ('1', '2', '3')"

    def test_multiple_filters_are_anded(self) -> None:
        clause = build_filter_clause([Filter("a", "1"), Filter("b", "2", "!=")], "postgresql")
        assert clause == "\"a\" = '1' AND \"b\" != '2'"

    def test_no_filters_gives_empty_string(self) -> None:
        assert build_filter_clause([], "mysql") == ""


class TestCsvRendering:
    def test_header_and_rows(self) -> None:
        text = render_csv_chunk(HEADER, [HEADER and [1, "a", 2]])
        assert text.splitlines()[0] == "id,note,amount"
        assert "1,a,2" in text

    def test_none_becomes_empty_field(self) -> None:
        text = render_csv_chunk(["a", "b"], [[None, "x"]])
        assert ",x" in text

    def test_embedded_comma_and_quote_are_escaped(self) -> None:
        text = render_csv_chunk(["a"], [["x,y"]])
        assert '"x,y"' in text
        text = render_csv_chunk(["a"], [['say "hi"']])
        assert '""hi""' in text

    def test_decimal_and_datetime_render_readably(self) -> None:
        text = render_csv_chunk(
            ["d", "t"],
            [[decimal.Decimal("1.50"), datetime.date(2026, 1, 2)]],
        )
        assert "1.50" in text
        assert "2026-01-02" in text

    def test_header_can_be_suppressed(self) -> None:
        text = render_csv_chunk(HEADER, [[1, "a", 2]], with_header=False)
        assert "id,note,amount" not in text


class TestStreamingCsv:
    def test_header_emitted_once(self) -> None:
        chunks = list(iter_csv_chunks(HEADER, BATCHES))
        assert len(chunks) == 2
        assert sum("id,note,amount" in c for c in chunks) == 1

    def test_every_row_is_present(self) -> None:
        text = "".join(iter_csv_chunks(HEADER, BATCHES))
        rows = list(csv.reader(text.splitlines()))
        assert len(rows) == 4  # header + 3


class TestMarkdown:
    def test_structure(self) -> None:
        text = render_markdown_table(["a", "b"], [[1, 2]])
        lines = text.strip().splitlines()
        assert lines[0] == "| a | b |"
        assert lines[1] == "| --- | --- |"
        assert lines[2] == "| 1 | 2 |"

    def test_pipe_in_value_is_escaped(self) -> None:
        assert "\\|" in render_markdown_table(["a"], [["x|y"]])

    def test_newline_in_value_is_flattened(self) -> None:
        text = render_markdown_table(["a"], [["x\ny"]])
        assert text.count("\n") == 3  # header, separator, one data row

    def test_none_becomes_empty(self) -> None:
        assert "|  |" in render_markdown_table(["a"], [[None]])


class TestExportRows:
    @pytest.mark.parametrize(
        "fmt",
        [
            ExportFormat.CSV,
            ExportFormat.TSV,
            ExportFormat.MARKDOWN,
            ExportFormat.JSON,
            ExportFormat.SQL,
            ExportFormat.XLSX,
        ],
    )
    def test_every_format_counts_rows(self, out, fmt) -> None:
        path = out / ("f." + fmt.value)
        assert export_rows(path, HEADER, BATCHES, fmt) == 3
        assert path.stat().st_size > 0

    def test_json_is_one_valid_array(self, out) -> None:
        """Regression: each batch used to emit its own complete array."""
        path = out / "many.json"
        export_rows(path, HEADER, BATCHES, ExportFormat.JSON)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 3
        assert data[0]["id"] == 1

    def test_json_single_batch_is_valid(self, out) -> None:
        path = out / "one.json"
        export_rows(path, HEADER, [[[1, "a", 2]]], ExportFormat.JSON)
        assert json.loads(path.read_text(encoding="utf-8")) == [{"id": 1, "note": "a", "amount": 2}]

    def test_json_empty_is_an_empty_array(self, out) -> None:
        path = out / "empty.json"
        export_rows(path, HEADER, [], ExportFormat.JSON)
        assert json.loads(path.read_text(encoding="utf-8")) == []

    def test_json_is_utf8_not_bom(self, out) -> None:
        # A BOM would make json.loads fail on some readers.
        path = out / "nb.json"
        export_rows(path, HEADER, [[[1, "a", 2]]], ExportFormat.JSON)
        assert not path.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_csv_has_bom_for_excel(self, out) -> None:
        path = out / "bom.csv"
        export_rows(path, HEADER, BATCHES, ExportFormat.CSV)
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_sql_emits_one_insert_per_row(self, out) -> None:
        path = out / "d.sql"
        export_rows(path, HEADER, BATCHES, ExportFormat.SQL, table="users")
        text = path.read_text(encoding="utf-8")
        assert text.count("INSERT INTO") == 3
        assert "`users`" in text
        assert "'O''Brien'" in text

    def test_xlsx_opens_as_a_workbook(self, out) -> None:
        path = out / "d.xlsx"
        export_rows(path, HEADER, BATCHES, ExportFormat.XLSX)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            sheet = zf.read("xl/worksheets/sheet1.xml").decode()
        assert "xl/workbook.xml" in names
        assert "xl/worksheets/sheet1.xml" in names
        assert sheet.count("<row ") == 4  # header + 3 data rows

    def test_xlsx_keeps_numbers_numeric(self, out) -> None:
        path = out / "n.xlsx"
        export_rows(path, ["n"], [[[42], [decimal.Decimal("1.5")]]], ExportFormat.XLSX)
        with zipfile.ZipFile(path) as zf:
            sheet = zf.read("xl/worksheets/sheet1.xml").decode()
        assert "<v>42</v>" in sheet
        assert "<v>1.5</v>" in sheet

    def test_xlsx_escapes_xml(self, out) -> None:
        path = out / "e.xlsx"
        export_rows(path, ["a"], [[['<tag> & "q"']]], ExportFormat.XLSX)
        with zipfile.ZipFile(path) as zf:
            sheet = zf.read("xl/worksheets/sheet1.xml").decode()
        assert "&lt;tag&gt;" in sheet
        assert "<tag>" not in sheet

    def test_accepts_a_string_format(self, out) -> None:
        path = out / "s.csv"
        assert export_rows(path, HEADER, BATCHES, "csv") == 3

    def test_rejects_unknown_format(self, out) -> None:
        with pytest.raises(ValueError):
            export_rows(out / "x.nope", HEADER, BATCHES, "parquet")


class TestMemoryBehaviour:
    def test_batches_are_consumed_lazily(self, out) -> None:
        """A generator source must not be fully materialised for CSV."""
        seen = []

        def batches():
            for i in range(3):
                seen.append(i)
                yield [[i, "x", i]]

        path = out / "lazy.csv"
        export_rows(path, HEADER, batches(), ExportFormat.CSV)
        assert seen == [0, 1, 2]
        assert len(path.read_text(encoding="utf-8-sig").strip().splitlines()) == 4
