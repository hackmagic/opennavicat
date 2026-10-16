"""Streaming file readers for data import.

The importer used to read whole files into memory -- ``list(csv.DictReader(...))``,
``json.load``, a fully materialised workbook -- so importing a large file was
bounded by RAM rather than by disk.  This module yields rows in batches instead.

Two properties matter for the caller:

* :func:`iter_batches` never holds more than one batch, except for formats that
  genuinely cannot be streamed (a plain JSON array).  :attr:`FilePreview.is_streaming`
  says which case a file is, so the UI can warn instead of silently loading a
  gigabyte.
* Everything comes back as **text**.  Type coercion needs the target column
  types, which only the migration layer knows, so it happens there.

Parquet support is optional: ``pyarrow`` is not a hard dependency of this project,
so asking for a parquet file without it installed raises a clear error rather than
an ImportError from three frames down.
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterator, Sequence


class ImportFormat(str, Enum):
    """Formats the importer understands."""

    CSV = "csv"
    TSV = "tsv"
    JSON = "json"
    JSONL = "jsonl"
    XLSX = "xlsx"
    PARQUET = "parquet"


#: Extension -> format.  ``auto`` detection walks this table.
_EXTENSIONS: dict[str, ImportFormat] = {
    ".csv": ImportFormat.CSV,
    ".tsv": ImportFormat.TSV,
    ".txt": ImportFormat.CSV,
    ".json": ImportFormat.JSON,
    ".jsonl": ImportFormat.JSONL,
    ".ndjson": ImportFormat.JSONL,
    ".xlsx": ImportFormat.XLSX,
    ".xlsm": ImportFormat.XLSX,
    ".parquet": ImportFormat.PARQUET,
    ".pq": ImportFormat.PARQUET,
}

#: Formats read one batch at a time.  JSON arrays cannot be: finding the end of
#: an array requires parsing the whole document.
_STREAMING: frozenset[ImportFormat] = frozenset(
    {
        ImportFormat.CSV,
        ImportFormat.TSV,
        ImportFormat.JSONL,
        ImportFormat.XLSX,
        ImportFormat.PARQUET,
    }
)


class ImportFileError(Exception):
    """Raised when a file cannot be read at all.

    Distinct from a per-row failure: this aborts the import, while a bad row is
    reported and skipped by the migration layer.
    """


@dataclass(frozen=True)
class ReadOptions:
    """How to interpret the file."""

    encoding: str = "utf-8-sig"
    #: ``None`` means "sniff it"; a single-character string forces a delimiter.
    delimiter: str | None = None
    #: ``None`` lets the sniffer decide; ``True``/``False`` is the caller's
    #: explicit word.  The sniffer is a heuristic that fails on small files,
    #: and overriding an explicit choice with it turns a header row into data.
    has_header: bool | None = None
    #: Sheet name or index for workbooks; ignored elsewhere.
    sheet: str | int | None = None
    #: Overrides the header row with these names, positionally.
    columns: tuple[str, ...] | None = None
    #: Rows per yielded batch.
    batch_size: int = 1000


@dataclass(frozen=True)
class BatchedRows:
    """One batch of parsed rows plus the header they belong to."""

    columns: list[str]
    rows: list[list[str]]

    def __len__(self) -> int:
        return len(self.rows)

    def as_dicts(self) -> list[dict[str, str]]:
        """Rows keyed by column name, for connectors that want mappings."""
        return [dict(zip(self.columns, row)) for row in self.rows]


@dataclass
class FilePreview:
    """What the file looks like before anything is imported."""

    path: str
    fmt: ImportFormat
    columns: list[str] = field(default_factory=list)
    sample_rows: list[list[str]] = field(default_factory=list)
    encoding: str = "utf-8"
    delimiter: str | None = None
    has_header: bool = True
    sheet: str = ""
    #: True when :func:`iter_batches` will stream rather than load everything.
    streaming: bool = True
    #: Reader warnings worth showing the user (sniffed delimiter, skipped rows...).
    notes: list[str] = field(default_factory=list)

    @property
    def sampled(self) -> int:
        return len(self.sample_rows)

    @property
    def column_count(self) -> int:
        return len(self.columns)

    def summary(self) -> str:
        """One-line description for a preview panel."""
        scope = "streaming" if self.streaming else "loaded into memory"
        kind = self.fmt.value
        note = f" -- {self.notes[0]}" if self.notes else ""
        return f"{kind}, {self.column_count} column(s), {scope}{note}"


# ---- format detection ----

def detect_format(path: str | pathlib.Path) -> ImportFormat:
    """Guess the format from the extension.

    Raises :class:`ImportFileError` for an unknown extension so the caller can
    ask the user instead of silently treating everything as CSV.
    """
    suffix = pathlib.Path(path).suffix.lower()
    fmt = _EXTENSIONS.get(suffix)
    if fmt is None:
        known = ", ".join(sorted({e for e in _EXTENSIONS}))
        raise ImportFileError(
            f"cannot determine the format of {path!r} from its extension; "
            f"known extensions: {known}"
        )
    return fmt


def is_streaming(fmt: ImportFormat) -> bool:
    """True when the format can be read one batch at a time."""
    return fmt in _STREAMING


def sniff_csv(
    path: str | pathlib.Path,
    encoding: str = "utf-8-sig",
    sample_bytes: int = 65536,
) -> tuple[str, bool, list[str]]:
    """Sniff a delimited file's dialect.

    Returns ``(delimiter, has_header, notes)``.  Sniffing only looks at the first
    ``sample_bytes``, so a file whose first lines are unrepresentative can still
    be mis-detected -- the caller may override both values, and the notes say when
    a guess was made.
    """
    notes: list[str] = []
    try:
        with open(path, "r", encoding=encoding, errors="replace") as handle:
            sample = handle.read(sample_bytes)
    except OSError as exc:
        raise ImportFileError(f"cannot read {path!r}: {exc}") from exc

    if not sample.strip():
        raise ImportFileError(f"{path!r} is empty")

    delimiter = ","
    has_header = True
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        # Single-column files have no delimiter to find; that is not an error.
        notes.append("could not detect a delimiter, assuming comma")

    try:
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        notes.append("could not detect a header row, assuming there is one")

    # A file whose first row looks like data would be truncated by treating it as
    # a header, so say so rather than guessing silently.
    if not has_header:
        notes.append("no header detected; the first row is treated as data")
    return delimiter, has_header, notes


def _resolve_options(
    path: str | pathlib.Path,
    fmt: ImportFormat,
    options: ReadOptions | None,
) -> tuple[ReadOptions, list[str]]:
    """Fill in the option fields the user left unset.

    ``has_header=None`` is sniffed; an explicit ``True``/``False`` wins.
    """
    opts = options or ReadOptions()
    notes: list[str] = []

    if fmt in (ImportFormat.CSV, ImportFormat.TSV) and opts.delimiter is None:
        delimiter, sniffed_header, sniff_notes = sniff_csv(path, opts.encoding)
        notes.extend(sniff_notes)
        if fmt is ImportFormat.TSV:
            delimiter = "\t"
        opts = ReadOptions(
            encoding=opts.encoding,
            delimiter=delimiter,
            has_header=sniffed_header if opts.has_header is None else opts.has_header,
            sheet=opts.sheet,
            columns=opts.columns,
            batch_size=opts.batch_size,
        )
    elif fmt is ImportFormat.TSV and opts.delimiter is None:
        opts = ReadOptions(
            encoding=opts.encoding,
            delimiter="\t",
            has_header=True if opts.has_header is None else opts.has_header,
            sheet=opts.sheet,
            columns=opts.columns,
            batch_size=opts.batch_size,
        )
    elif opts.has_header is None:
        # No sniffing happens on this path (delimiter forced, or a format like
        # xlsx/json that never sniffs); keep the historical "has a header".
        opts = replace(opts, has_header=True)

    return opts, notes


def _column_names(raw: Sequence[str], opts: ReadOptions, index: int) -> list[str]:
    """Name the columns, filling blanks so every row has a stable key.

    An empty header cell would otherwise produce a ``""`` key that collides with
    the next one, and duplicate names would silently drop columns when the rows
    are turned into dicts.
    """
    if opts.columns:
        names = list(opts.columns)
    else:
        names = [str(c).strip() for c in raw]

    seen: dict[str, int] = {}
    out: list[str] = []
    for position, name in enumerate(names):
        candidate = name or f"column_{index + position + 1}"
        if candidate in seen:
            seen[candidate] += 1
            candidate = f"{candidate}_{seen[candidate]}"
        else:
            seen[candidate] = 0
        out.append(candidate)
    return out


def _union_keys(records: Sequence[dict]) -> list[str]:
    """Every key seen across ``records``, in first-seen order."""
    seen: dict[str, None] = {}
    for record in records:
        for key in record:
            seen.setdefault(str(key), None)
    return list(seen)


def _stringify(value: Any) -> str:
    """Render a cell as text, mapping None to the empty string."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.hex()
    return str(value)



# ---- readers ----

def _iter_csv_batches(path, opts: ReadOptions) -> Iterator[BatchedRows]:
    """Read a delimited file one batch at a time.

    ``csv.reader`` pulls from the file handle lazily, so memory stays at one
    batch even for a multi-gigabyte file.
    """
    delimiter = opts.delimiter or ","
    with open(path, "r", encoding=opts.encoding, errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        columns: list[str] | None = None
        pending: list[list[str]] = []

        for index, raw in enumerate(reader):
            if index == 0:
                if opts.has_header:
                    columns = _column_names(raw, opts, 0)
                    continue
                columns = _column_names([], opts, 0) if opts.columns else [
                    f"column_{i + 1}" for i in range(len(raw))
                ]
                # No header: the first row is data.
                pending.append([_stringify(c) for c in raw])
                continue
            pending.append([_stringify(c) for c in raw])
            if len(pending) >= opts.batch_size:
                yield BatchedRows(columns=list(columns or []), rows=pending)
                pending = []

        if pending:
            yield BatchedRows(columns=list(columns or []), rows=pending)
        elif columns is not None and not pending:
            # A header-only file still reports its columns so the UI can show them.
            yield BatchedRows(columns=list(columns), rows=[])


def _iter_jsonl_batches(path, opts: ReadOptions) -> Iterator[BatchedRows]:
    """Read newline-delimited JSON objects, one line at a time."""
    columns: list[str] = []
    batch: list[list[str]] = []

    with open(path, "r", encoding=opts.encoding, errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ImportFileError(
                    f"{path}:{line_number} is not valid JSON: {exc.msg}"
                ) from exc
            if not isinstance(record, dict):
                raise ImportFileError(
                    f"{path}:{line_number} is a {type(record).__name__}, "
                    "expected a JSON object per line"
                )
            if not columns:
                columns = _column_names(list(record), opts, 0)
            elif not opts.columns:
                unexpected = [k for k in record if k not in columns]
                if unexpected:
                    # Earlier rows are already emitted, so the only honest
                    # options are to stop or to lose data.  Stop.
                    raise ImportFileError(
                        f"{path}:{line_number} has key(s) {unexpected} that are "
                        f"not in the first record ({columns}); pass columns= to "
                        "declare the schema, or use .json to union them"
                    )
            batch.append([_stringify(record.get(name)) for name in columns])
            if len(batch) >= opts.batch_size:
                yield BatchedRows(columns=list(columns), rows=batch)
                batch = []

    if batch or columns:
        yield BatchedRows(columns=list(columns), rows=batch)


def _load_json(path, opts: ReadOptions) -> list:
    """Parse a whole JSON document.

    Only used for a JSON array, which cannot be streamed without a streaming
    parser; the preview reports this so the caller can warn.
    """
    try:
        with open(path, "r", encoding=opts.encoding, errors="replace") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ImportFileError(f"{path} is not valid JSON: {exc.msg}") from exc
    except OSError as exc:
        raise ImportFileError(f"cannot read {path!r}: {exc}") from exc


def _iter_json_batches(path, opts: ReadOptions) -> Iterator[BatchedRows]:
    """Read a JSON array of objects.

    Buffered by necessity: locating the end of a JSON array means parsing the
    document.  ``.jsonl`` exists for files that need to stream.
    """
    data = _load_json(path, opts)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ImportFileError(
            f"{path} must contain a JSON array of objects, found "
            f"{type(data).__name__}"
        )
    records = [r for r in data if isinstance(r, dict)]
    if len(records) != len(data):
        raise ImportFileError(
            f"{path} contains {len(data) - len(records)} non-object entr(ies); "
            "expected every element to be an object"
        )
    if not records:
        yield BatchedRows(columns=[], rows=[])
        return

    # Union of every record's keys, in first-seen order.  Using only the first
    # record's keys would silently drop any column that appears later, and a JSON
    # file is the one format where ragged records are normal.
    columns = _column_names(_union_keys(records), opts, 0)
    for start in range(0, len(records), opts.batch_size):
        chunk = records[start : start + opts.batch_size]
        yield BatchedRows(
            columns=list(columns),
            rows=[[_stringify(r.get(name)) for name in columns] for r in chunk],
        )


def _open_sheet(path, opts: ReadOptions):
    """Open a workbook in read-only mode and return the requested sheet."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - openpyxl is a base dependency
        raise ImportFileError(
            "reading .xlsx needs openpyxl; install it with: pip install openpyxl"
        ) from exc

    try:
        # read_only keeps openpyxl from building the whole grid in memory.
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises several types
        raise ImportFileError(f"cannot open {path!r}: {exc}") from exc

    if opts.sheet is None:
        sheet = workbook.worksheets[0]
    elif isinstance(opts.sheet, int):
        sheet = workbook.worksheets[opts.sheet]
    else:
        if opts.sheet not in workbook.sheetnames:
            raise ImportFileError(
                f"{path} has no sheet named {opts.sheet!r}; "
                f"available: {', '.join(workbook.sheetnames)}"
            )
        sheet = workbook[opts.sheet]
    return workbook, sheet


def _iter_xlsx_batches(path, opts: ReadOptions) -> Iterator[BatchedRows]:
    """Read a worksheet one batch at a time using openpyxl's read-only mode."""
    workbook, sheet = _open_sheet(path, opts)
    try:
        columns: list[str] | None = None
        batch: list[list[str]] = []
        for index, raw in enumerate(sheet.iter_rows(values_only=True)):
            row = [_stringify(c) for c in raw]
            if index == 0 and opts.has_header:
                columns = _column_names(row, opts, 0)
                continue
            if columns is None:
                columns = (
                    list(opts.columns)
                    if opts.columns
                    else [f"column_{i + 1}" for i in range(len(row))]
                )
            batch.append(row)
            if len(batch) >= opts.batch_size:
                yield BatchedRows(columns=list(columns), rows=batch)
                batch = []
        if batch or columns:
            yield BatchedRows(columns=list(columns or []), rows=batch)
        elif columns is None:
            yield BatchedRows(columns=[], rows=[])
    finally:
        workbook.close()


def _iter_parquet_batches(path, opts: ReadOptions) -> Iterator[BatchedRows]:
    """Read a Parquet file in row batches.

    ``pyarrow`` is optional: it is not a dependency of this project, so a missing
    install is reported as a readable message instead of an ImportError.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ImportFileError(
            "reading .parquet needs pyarrow; install it with: pip install pyarrow"
        ) from exc

    try:
        parquet_file = pq.ParquetFile(path)
    except Exception as exc:  # noqa: BLE001 - pyarrow raises several types
        raise ImportFileError(f"cannot open {path!r}: {exc}") from exc

    schema_names = list(parquet_file.schema_arrow.names)
    columns = _column_names(schema_names, opts, 0)
    for batch in parquet_file.iter_batches(batch_size=opts.batch_size):
        table = batch.to_pydict()
        rows = [
            [_stringify(table[name][i]) for name in schema_names]
            for i in range(batch.num_rows)
        ]
        yield BatchedRows(columns=list(columns), rows=rows)


_READERS = {
    ImportFormat.CSV: _iter_csv_batches,
    ImportFormat.TSV: _iter_csv_batches,
    ImportFormat.JSON: _iter_json_batches,
    ImportFormat.JSONL: _iter_jsonl_batches,
    ImportFormat.XLSX: _iter_xlsx_batches,
    ImportFormat.PARQUET: _iter_parquet_batches,
}


def iter_batches(
    path: str | pathlib.Path,
    options: ReadOptions | None = None,
    fmt: ImportFormat | str | None = None,
) -> Iterator[BatchedRows]:
    """Yield the file's rows in batches.

    ``fmt`` defaults to what the extension says.  The generator is lazy for every
    format except a JSON array, so the caller can stop early without reading the
    rest of the file.
    """
    resolved = ImportFormat(fmt) if isinstance(fmt, str) else fmt
    if resolved is None:
        resolved = detect_format(path)
    opts, _notes = _resolve_options(path, resolved, options)
    reader = _READERS.get(resolved)
    if reader is None:  # pragma: no cover - the enum covers every format
        raise ImportFileError(f"no reader for format {resolved.value!r}")
    return reader(path, opts)


def read_all(
    path: str | pathlib.Path,
    options: ReadOptions | None = None,
    fmt: ImportFormat | str | None = None,
) -> BatchedRows:
    """Read the whole file into one batch.

    For small files and for tests; a real import should use :func:`iter_batches`.
    """
    columns: list[str] = []
    rows: list[list[str]] = []
    for batch in iter_batches(path, options, fmt):
        if not columns:
            columns = list(batch.columns)
        rows.extend(batch.rows)
    return BatchedRows(columns=columns, rows=rows)



# ---- preview ----

def preview(
    path: str | pathlib.Path,
    options: ReadOptions | None = None,
    fmt: ImportFormat | str | None = None,
    *,
    limit: int = 20,
) -> FilePreview:
    """Describe a file without reading all of it.

    Reads at most the first ``limit`` rows, so previewing a huge file is cheap.
    """
    resolved = ImportFormat(fmt) if isinstance(fmt, str) else fmt
    if resolved is None:
        resolved = detect_format(path)
    opts, notes = _resolve_options(path, resolved, options)

    sheet_name = ""
    if opts.sheet is not None:
        sheet_name = str(opts.sheet)

    result = FilePreview(
        path=str(path),
        fmt=resolved,
        encoding=opts.encoding,
        delimiter=opts.delimiter,
        has_header=opts.has_header,
        sheet=sheet_name,
        streaming=is_streaming(resolved),
        notes=list(notes),
    )

    if not is_streaming(resolved):
        result.notes.append("this format is read into memory as a whole")

    try:
        for batch in iter_batches(path, opts, resolved):
            result.columns = list(batch.columns)
            result.sample_rows = [list(r) for r in batch.rows[:limit]]
            break
    except ImportFileError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface a readable message
        raise ImportFileError(f"cannot preview {path!r}: {exc}") from exc

    if resolved is ImportFormat.XLSX and not sheet_name:
        try:
            _workbook, sheet = _open_sheet(path, opts)
            result.sheet = getattr(sheet, "title", "")
            _workbook.close()
        except Exception:  # noqa: BLE001 - the name is cosmetic
            pass

    return result


def list_sheets(path: str | pathlib.Path) -> list[str]:
    """Sheet names in a workbook, for a sheet picker."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - base dependency
        raise ImportFileError("reading .xlsx needs openpyxl") from exc
    try:
        workbook = load_workbook(path, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ImportFileError(f"cannot open {path!r}: {exc}") from exc
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def count_rows(
    path: str | pathlib.Path,
    options: ReadOptions | None = None,
    fmt: ImportFormat | str | None = None,
) -> int | None:
    """Count data rows, or ``None`` when that would mean reading the whole file.

    Delimited files and JSONL can be counted cheaply enough to be worth it; a
    JSON array is already in memory by then, and a workbook costs a full scan for
    a number the caller usually does not need.
    """
    resolved = ImportFormat(fmt) if isinstance(fmt, str) else fmt
    if resolved is None:
        resolved = detect_format(path)

    if resolved not in (ImportFormat.CSV, ImportFormat.TSV, ImportFormat.JSONL):
        return None

    opts, _notes = _resolve_options(path, resolved, options)
    try:
        if resolved is ImportFormat.JSONL:
            with open(path, "r", encoding=opts.encoding, errors="replace") as handle:
                return sum(1 for line in handle if line.strip())
        with open(path, "r", encoding=opts.encoding, errors="replace", newline="") as handle:
            reader = csv.reader(handle, delimiter=opts.delimiter or ",")
            total = sum(1 for _row in reader)
        return max(0, total - (1 if opts.has_header else 0))
    except OSError as exc:
        raise ImportFileError(f"cannot read {path!r}: {exc}") from exc

