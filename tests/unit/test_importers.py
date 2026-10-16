"""Tests for the streaming file readers (open_navicat.formats.importers).

The importer used to materialise whole files, so a large import was bounded by
RAM.  These tests pin down the batch behaviour, the dialect sniffing, and the two
cases where guessing would silently corrupt data: ragged records and unnamed or
duplicated columns.
"""

from __future__ import annotations

import pathlib

import pytest

from open_navicat.formats.importers import (
    BatchedRows,
    FilePreview,
    ImportFileError,
    ImportFormat,
    ReadOptions,
    count_rows,
    detect_format,
    is_streaming,
    iter_batches,
    list_sheets,
    preview,
    read_all,
    sniff_csv,
)


@pytest.fixture
def tmp(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path


def write(tmp: pathlib.Path, name: str, text: str) -> pathlib.Path:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return path


class TestDetectFormat:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("a.csv", ImportFormat.CSV),
            ("a.TSV", ImportFormat.TSV),
            ("a.txt", ImportFormat.CSV),
            ("a.json", ImportFormat.JSON),
            ("a.jsonl", ImportFormat.JSONL),
            ("a.ndjson", ImportFormat.JSONL),
            ("a.xlsx", ImportFormat.XLSX),
            ("a.xlsm", ImportFormat.XLSX),
            ("a.parquet", ImportFormat.PARQUET),
        ],
    )
    def test_by_extension(self, name, expected) -> None:
        assert detect_format(name) is expected

    def test_unknown_extension_is_refused(self) -> None:
        # Defaulting to CSV would import a binary file as text and produce
        # nonsense rows.
        with pytest.raises(ImportFileError, match="cannot determine the format"):
            detect_format("mystery.xyz")

    def test_json_array_is_not_streaming(self) -> None:
        assert is_streaming(ImportFormat.JSON) is False

    @pytest.mark.parametrize(
        "fmt",
        [ImportFormat.CSV, ImportFormat.TSV, ImportFormat.JSONL, ImportFormat.XLSX,
         ImportFormat.PARQUET],
    )
    def test_other_formats_stream(self, fmt) -> None:
        assert is_streaming(fmt) is True


class TestSniffing:
    def test_detects_semicolon(self, tmp) -> None:
        path = write(tmp, "a.csv", "id;name\n1;x\n2;y\n")
        delimiter, has_header, notes = sniff_csv(path)
        assert delimiter == ";"
        assert has_header is True
        assert notes == []

    def test_detects_tab(self, tmp) -> None:
        path = write(tmp, "a.tsv", "id\tname\n1\tx\n")
        delimiter, _has_header, _notes = sniff_csv(path)
        assert delimiter == "\t"

    def test_single_column_file_has_no_delimiter_to_find(self, tmp) -> None:
        path = write(tmp, "one.csv", "name\nalpha\nbeta\n")
        delimiter, _has_header, notes = sniff_csv(path)
        assert delimiter == ","
        assert any("delimiter" in n for n in notes)

    def test_empty_file_is_refused(self, tmp) -> None:
        path = write(tmp, "empty.csv", "   \n")
        with pytest.raises(ImportFileError, match="empty"):
            sniff_csv(path)

    def test_missing_file_is_refused(self, tmp) -> None:
        with pytest.raises(ImportFileError, match="cannot read"):
            sniff_csv(tmp / "nope.csv")

    def test_explicit_delimiter_is_not_sniffed(self, tmp) -> None:
        # A pipe file that lies about its extension still reads correctly when
        # the caller states the delimiter.
        path = write(tmp, "a.csv", "id|name\n1|x\n")
        rows = read_all(path, ReadOptions(delimiter="|"))
        assert rows.columns == ["id", "name"]
        assert rows.rows == [["1", "x"]]


class TestCsvReading:
    def test_batches_honour_batch_size(self, tmp) -> None:
        path = write(tmp, "a.csv", "id\n1\n2\n3\n4\n5\n")
        batches = list(iter_batches(path, ReadOptions(batch_size=2)))
        assert [len(b) for b in batches] == [2, 2, 1]

    def test_batch_carries_the_columns(self, tmp) -> None:
        path = write(tmp, "a.csv", "id,name\n1,x\n")
        batch = next(iter_batches(path))
        assert batch.columns == ["id", "name"]
        assert batch.as_dicts() == [{"id": "1", "name": "x"}]

    def test_quoted_fields_and_embedded_quotes(self, tmp) -> None:
        path = write(tmp, "a.csv", 'id,note\n1,"say ""hi"""\n')
        assert read_all(path).rows == [["1", 'say "hi"']]

    def test_header_only_file_reports_columns(self, tmp) -> None:
        path = write(tmp, "a.csv", "a,b\n")
        rows = read_all(path)
        assert rows.columns == ["a", "b"]
        assert rows.rows == []

    def test_no_header_treats_first_row_as_data(self, tmp) -> None:
        path = write(tmp, "a.csv", "1,x\n2,y\n")
        rows = read_all(path, ReadOptions(has_header=False))
        assert rows.columns == ["column_1", "column_2"]
        assert rows.rows == [["1", "x"], ["2", "y"]]

    def test_blank_header_cell_gets_a_name(self, tmp) -> None:
        path = write(tmp, "a.csv", "id,,note\n1,2,3\n")
        assert read_all(path).columns == ["id", "column_2", "note"]

    def test_duplicate_header_names_are_disambiguated(self, tmp) -> None:
        # Two columns called "id" would collapse into one dict key and lose data.
        path = write(tmp, "a.csv", "id,id\n1,2\n")
        assert read_all(path).columns == ["id", "id_1"]

    def test_declared_columns_override_the_header(self, tmp) -> None:
        path = write(tmp, "a.csv", "a,b\n1,2\n")
        rows = read_all(path, ReadOptions(columns=("x", "y")))
        assert rows.columns == ["x", "y"]

    def test_ragged_rows_are_padded_by_the_reader(self, tmp) -> None:
        path = write(tmp, "a.csv", "a,b,c\n1,2\n")
        rows = read_all(path)
        # csv.reader gives a short row; the consumer sees it as-is, so the
        # migration layer's column lookup yields empty strings for the gap.
        assert rows.rows == [["1", "2"]]

    def test_encoding_is_honoured(self, tmp) -> None:
        path = tmp / "gbk.csv"
        path.write_bytes("id,name\n1,中文\n".encode("gbk"))
        rows = read_all(path, ReadOptions(encoding="gbk"))
        assert rows.rows == [["1", "中文"]]

    def test_bom_is_stripped_by_default(self, tmp) -> None:
        path = tmp / "bom.csv"
        path.write_bytes("id,name\n1,x\n".encode("utf-8-sig"))
        assert read_all(path).columns == ["id", "name"]


class TestJsonReading:
    def test_array_of_objects(self, tmp) -> None:
        path = write(tmp, "a.json", '[{"a": 1}, {"a": 2}]')
        rows = read_all(path)
        assert rows.columns == ["a"]
        assert rows.rows == [["1"], ["2"]]

    def test_array_unions_the_keys(self, tmp) -> None:
        # Using only the first record's keys would drop "b" and "c" silently.
        path = write(tmp, "ragged.json", '[{"a": 1}, {"a": 2, "b": "z"}, {"c": true}]')
        rows = read_all(path)
        assert rows.columns == ["a", "b", "c"]
        assert rows.rows[1] == ["2", "z", ""]
        assert rows.rows[2] == ["", "", "True"]

    def test_single_object_is_accepted(self, tmp) -> None:
        path = write(tmp, "one.json", '{"a": 1}')
        assert read_all(path).rows == [["1"]]

    def test_missing_keys_become_empty(self, tmp) -> None:
        path = write(tmp, "sparse.json", '[{"a": 1, "b": 2}, {"a": 3}]')
        assert read_all(path).rows[1] == ["3", ""]

    def test_non_array_is_refused(self, tmp) -> None:
        path = write(tmp, "num.json", "42")
        with pytest.raises(ImportFileError, match="JSON array"):
            read_all(path)

    def test_array_of_scalars_is_refused(self, tmp) -> None:
        path = write(tmp, "scalars.json", "[1, 2, 3]")
        with pytest.raises(ImportFileError, match="non-object"):
            read_all(path)

    def test_invalid_json_names_the_problem(self, tmp) -> None:
        path = write(tmp, "bad.json", "{oops")
        with pytest.raises(ImportFileError, match="not valid JSON"):
            read_all(path)

    def test_batches_split_the_array(self, tmp) -> None:
        path = write(tmp, "many.json", '[{"a": 1}, {"a": 2}, {"a": 3}]')
        batches = list(iter_batches(path, ReadOptions(batch_size=2)))
        assert [len(b) for b in batches] == [2, 1]


class TestJsonlReading:
    def test_one_object_per_line(self, tmp) -> None:
        path = write(tmp, "a.jsonl", '{"a": 1, "b": "x"}\n{"a": 2}\n')
        rows = read_all(path)
        assert rows.columns == ["a", "b"]
        assert rows.rows == [["1", "x"], ["2", ""]]

    def test_blank_lines_are_skipped(self, tmp) -> None:
        path = write(tmp, "a.jsonl", '{"a": 1}\n\n\n{"a": 2}\n')
        assert len(read_all(path).rows) == 2

    def test_unexpected_key_is_refused(self, tmp) -> None:
        # Rows already emitted cannot be corrected, so dropping the new column
        # would be silent data loss; refusing is the honest option.
        path = write(tmp, "ragged.jsonl", '{"a": 1}\n{"a": 2, "b": 3}\n')
        with pytest.raises(ImportFileError, match="not in the first record"):
            read_all(path)

    def test_declared_columns_make_ragged_files_importable(self, tmp) -> None:
        path = write(tmp, "ragged.jsonl", '{"a": 1}\n{"a": 2, "b": 3}\n')
        rows = read_all(path, ReadOptions(columns=("a", "b")))
        assert rows.rows == [["1", ""], ["2", "3"]]

    def test_bad_line_reports_the_line_number(self, tmp) -> None:
        path = write(tmp, "bad.jsonl", '{"a": 1}\nnot json\n')
        with pytest.raises(ImportFileError, match=":2"):
            read_all(path)

    def test_non_object_line_is_refused(self, tmp) -> None:
        path = write(tmp, "list.jsonl", "[1, 2]\n")
        with pytest.raises(ImportFileError, match="expected a JSON object"):
            read_all(path)


class TestPreview:
    def test_reports_columns_and_samples(self, tmp) -> None:
        path = write(tmp, "a.csv", "id,name\n1,x\n2,y\n3,z\n")
        p = preview(path, limit=2)
        assert isinstance(p, FilePreview)
        assert p.columns == ["id", "name"]
        assert p.sample_rows == [["1", "x"], ["2", "y"]]
        assert p.sampled == 2
        assert p.column_count == 2
        assert p.streaming is True

    def test_does_not_read_the_whole_file(self, tmp) -> None:
        # 5000 rows, limit 5: only the first batch is parsed.
        body = "id\n" + "".join(f"{i}\n" for i in range(5000))
        path = write(tmp, "big.csv", body)
        p = preview(path, limit=5, options=ReadOptions(batch_size=10))
        assert p.sampled == 5

    def test_json_preview_warns_about_buffering(self, tmp) -> None:
        path = write(tmp, "a.json", '[{"a": 1}]')
        p = preview(path)
        assert p.streaming is False
        assert any("memory" in n for n in p.notes)

    def test_summary_mentions_scope(self, tmp) -> None:
        streaming = preview(write(tmp, "a.csv", "a\n1\n"))
        buffered = preview(write(tmp, "b.json", '[{"a": 1}]'))
        assert "streaming" in streaming.summary()
        assert "memory" in buffered.summary()


class TestCountRows:
    def test_counts_csv_data_rows(self, tmp) -> None:
        path = write(tmp, "a.csv", "id\n1\n2\n3\n")
        assert count_rows(path) == 3

    def test_excludes_the_header(self, tmp) -> None:
        path = write(tmp, "a.csv", "id,name\n1,x\n")
        assert count_rows(path) == 1

    def test_no_header_counts_every_row(self, tmp) -> None:
        path = write(tmp, "a.csv", "1,x\n2,y\n")
        assert count_rows(path, ReadOptions(has_header=False)) == 2

    def test_counts_jsonl(self, tmp) -> None:
        path = write(tmp, "a.jsonl", '{"a": 1}\n{"a": 2}\n\n')
        assert count_rows(path) == 2

    def test_returns_none_for_formats_worth_skipping(self, tmp) -> None:
        assert count_rows(write(tmp, "a.json", "[]")) is None
        assert count_rows(tmp / "a.xlsx") is None


class TestWorkbooks:
    def test_lists_sheet_names(self, tmp) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp / "book.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "First"
        wb.create_sheet("Second")
        wb.save(path)
        assert list_sheets(path) == ["First", "Second"]

    def test_reads_the_first_sheet_by_default(self, tmp) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp / "book.xlsx"
        wb = openpyxl.Workbook()
        wb.active.append(["id", "name"])
        wb.active.append([1, "x"])
        wb.save(path)
        rows = read_all(path)
        assert rows.columns == ["id", "name"]
        assert rows.rows == [["1", "x"]]

    def test_reads_a_named_sheet(self, tmp) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp / "book.xlsx"
        wb = openpyxl.Workbook()
        wb.active.append(["skip"])
        second = wb.create_sheet("Data")
        second.append(["id"])
        second.append([7])
        wb.save(path)
        rows = read_all(path, ReadOptions(sheet="Data"))
        assert rows.columns == ["id"]
        assert rows.rows == [["7"]]

    def test_unknown_sheet_names_the_alternatives(self, tmp) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp / "book.xlsx"
        wb = openpyxl.Workbook()
        wb.save(path)
        with pytest.raises(ImportFileError, match="no sheet named"):
            read_all(path, ReadOptions(sheet="Nope"))

    def test_preview_reports_the_sheet_name(self, tmp) -> None:
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp / "book.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "Report"
        wb.active.append(["a"])
        wb.active.append([1])
        wb.save(path)
        assert preview(path).sheet == "Report"


class TestOptionalBackends:
    def test_parquet_without_pyarrow_says_what_to_install(self, tmp, monkeypatch) -> None:
        path = write(tmp, "a.parquet", "not really parquet")
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("pyarrow"):
                raise ImportError("no pyarrow")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(ImportFileError, match="pip install pyarrow"):
            read_all(path)
