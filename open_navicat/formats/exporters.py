"""Streaming data export.

Two problems this addresses:

1. **Memory.**  Exporting a large table used to run one ``SELECT *`` and build
   the whole result set in RAM before writing a byte.  :func:`export_rows` writes
   batch by batch, so a million-row export costs one batch of memory.
2. **Injection in the filter clause.**  The grid built ``WHERE`` fragments by
   string-interpolating filter values.  :func:`build_filter_clause` quotes
   identifiers and literals for the target engine instead, and leaves an
   operator-supplied expression alone when it is already complete SQL.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Iterator, Sequence

from open_navicat.sql.quoting import quote_identifier, quote_literal


class ExportFormat(str, Enum):
    """Supported export formats."""

    CSV = "csv"
    TSV = "tsv"
    JSON = "json"
    MARKDOWN = "markdown"
    XLSX = "xlsx"
    SQL = "sql"


#: Key the visual filter panel uses for an already-complete SQL fragment.
PANEL_KEY = "__panel__"


@dataclass(frozen=True)
class Filter:
    """One filter condition coming from the grid's filter row."""

    column: str
    value: str
    operator: str = "="

    def is_raw_sql(self) -> bool:
        """True when this entry is already a finished SQL expression.

        The visual filter panel stores a complete ``a = 1 AND b LIKE 'x'``
        fragment, so it must not be quoted again.  The grid signals that by
        using a panel key or the ``RAW`` operator, in which case the fragment
        lives in ``value``.
        """
        return self.operator.strip().upper() in {"RAW", "SQL"} or self.column == PANEL_KEY


def build_filter_clause(filters, engine: str = "mysql") -> str:
    """Render filters as a ``WHERE`` body (no WHERE keyword) for ``engine``."""
    parts = []
    for flt in filters:
        if flt.is_raw_sql():
            # `value` holds the expression; `operator` is only the marker.
            expression = flt.value.strip()
            if expression:
                parts.append("(" + expression + ")")
            continue
        column = quote_identifier(flt.column, engine)
        operator = (flt.operator.strip() or "=").upper()
        if operator in {"IN", "BETWEEN"}:
            items = [v.strip() for v in flt.value.split(",") if v.strip()]
            rendered = ", ".join(quote_literal(v, engine) for v in items)
            parts.append(column + " " + operator + " (" + rendered + ")")
        else:
            parts.append(column + " " + operator + " " + quote_literal(flt.value, engine))
    return " AND ".join(parts)


def render_csv_chunk(header, rows, *, dialect: str = "excel", with_header: bool = True) -> str:
    """Render one CSV chunk to a string."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, dialect=dialect, lineterminator="\r\n")
    if with_header:
        writer.writerow(list(header))
    for row in rows:
        writer.writerow(["" if v is None else _stringify(v) for v in row])
    return buffer.getvalue()


def render_markdown_table(header, rows) -> str:
    """Render rows as a Markdown table."""

    def cell(value):
        if value is None:
            return ""
        return _stringify(value).replace("|", "\\|").replace("\n", " ")

    lines = [
        "| " + " | ".join(cell(h) for h in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    return "\n".join(lines) + "\n"


def render_json_chunk(header, rows) -> str:
    """Render one chunk as a pretty-printed JSON array of objects."""
    records = [dict(zip(header, [_jsonable(v) for v in row])) for row in rows]
    return json.dumps(records, ensure_ascii=False, indent=2)


def iter_csv_chunks(header, row_batches, *, with_header: bool = True) -> Iterator[str]:
    """Yield CSV text per batch, emitting the header only on the first one."""
    first = True
    for batch in row_batches:
        yield render_csv_chunk(header, batch, with_header=with_header and first)
        first = False


def _tsv_text(header, rows, *, with_header: bool) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, dialect="excel-tab", lineterminator="\r\n")
    if with_header:
        writer.writerow(list(header))
    for row in rows:
        writer.writerow(["" if v is None else _stringify(v) for v in row])
    return buffer.getvalue()


def _json_records(header, rows) -> str:
    """Render rows as comma-separated JSON objects (no surrounding brackets)."""
    records = [dict(zip(header, [_jsonable(v) for v in row])) for row in rows]
    return ",\n".join(json.dumps(r, ensure_ascii=False, indent=2) for r in records)


def export_rows(
    path: str,
    header,
    row_batches,
    fmt: ExportFormat | str = ExportFormat.CSV,
    *,
    table: str = "exported_table",
) -> int:
    """Stream rows to ``path``; returns the row count.

    Written incrementally so peak memory is one batch, not the whole result set.
    """
    kind = fmt if isinstance(fmt, ExportFormat) else ExportFormat(fmt)

    if kind is ExportFormat.XLSX:
        # An xlsx part cannot be appended to, so the caller's batches are
        # materialised; the UI therefore pages before calling this.
        batches = [list(b) for b in row_batches]
        _write_xlsx(path, header, batches)
        return sum(len(b) for b in batches)

    if kind is ExportFormat.SQL:
        return _write_sql(path, header, row_batches, table)

    if kind is ExportFormat.JSON:
        return _write_json(path, header, row_batches)

    # csv and tsv get a BOM so Excel opens them with the right encoding;
    # json does not, because a BOM makes json.loads fail on some readers.
    encoding = "utf-8-sig" if kind in (ExportFormat.CSV, ExportFormat.TSV) else "utf-8"
    written = 0
    with open(path, "w", newline="", encoding=encoding) as handle:
        first = True
        for batch in row_batches:
            if kind is ExportFormat.CSV:
                text = render_csv_chunk(header, batch, with_header=first)
            elif kind is ExportFormat.TSV:
                text = _tsv_text(header, batch, with_header=first)
            else:
                text = render_markdown_table(header, batch)
            handle.write(text)
            written += len(batch)
            first = False
    return written


def _write_json(path, header, row_batches) -> int:
    """Write one JSON array, streamed batch by batch.

    The brackets are written once around the whole file: emitting a complete
    array per batch produced a file that was not valid JSON as soon as a table
    needed more than one page.
    """
    written = 0
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("[")
        first = True
        for batch in row_batches:
            if not batch:
                continue
            body = _json_records(header, batch)
            handle.write(("\n" if first else ",\n") + body)
            first = False
            written += len(batch)
        handle.write("\n]\n" if written else "]\n")
    return written


def _write_sql(path, header, row_batches, table: str) -> int:
    """Write one INSERT per row, batch by batch."""
    columns = ", ".join(quote_identifier(h, "mysql") for h in header)
    ref = quote_identifier(table, "mysql")
    written = 0
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("-- Exported from " + table + "\n")
        for batch in row_batches:
            for row in batch:
                values = ", ".join(quote_literal(v, "mysql") for v in row)
                handle.write("INSERT INTO " + ref + " (" + columns + ") VALUES (" + values + ");\n")
                written += 1
    return written


def _write_xlsx(path, header, batches) -> None:
    """Write a minimal xlsx workbook using only the standard library."""
    import zipfile

    body = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
        "<sheetData>",
    ]
    row_index = 1
    all_rows = [list(header)] + [list(row) for batch in batches for row in batch]
    for values in all_rows:
        cells = []
        for col, value in enumerate(values):
            ref = _cell_ref(col, row_index)
            if _is_numeric(value):
                cells.append('<c r="' + ref + '"><v>' + str(value) + "</v></c>")
            else:
                text = "" if value is None else _xml_escape(_stringify(value))
                cells.append('<c r="' + ref + '" t="inlineStr"><is><t>' + text + "</t></is></c>")
        body.append('<row r="' + str(row_index) + '">' + "".join(cells) + "</row>")
        row_index += 1
    body += ["</sheetData>", "</worksheet>"]
    sheet = "".join(body)

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)


def _is_numeric(value) -> bool:
    """True for values Excel should store as numbers rather than text.

    ``Decimal`` is included: the connectors hand back Decimal for NUMERIC and
    MONEY columns, and writing those as strings would turn a spreadsheet column
    of amounts into text that no longer sums.
    """
    import decimal

    return isinstance(value, (int, float, decimal.Decimal)) and not isinstance(value, bool)


def _cell_ref(col: int, row: int) -> str:
    """0-based column index -> spreadsheet column letters."""
    letters = ""
    col += 1
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return letters + str(row)


def _stringify(value) -> str:
    import datetime as _dt
    import decimal

    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    return str(value)


def _jsonable(value):
    import datetime as _dt
    import decimal

    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    return value


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
