"""Cross-engine migration pipeline: file -> target table.

Pure orchestration layer over :mod:`open_navicat.formats.importers` and the
driver connectors. Four independently testable pieces:

1. :func:`coerce_value` -- text (or native JSON) -> the target column's type,
   driven by ``ColumnInfo.data_type`` so the mapping works across engines.
2. :func:`build_mapping` -- match file columns to table columns by name.
3. :func:`plan_migration` -- dry-run preview before anything is written.
4. :func:`run_migration` -- the executor: batches in, rows out, with progress,
   per-row error accumulation, optional transaction and rollback.

Everything database-facing goes through an injected connector object
(``get_table_info`` / ``batch_insert`` / ``execute``), so the executor is
tested end to end without a live database.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

__all__ = [
    "CoercionError",
    "MigrationPlan",
    "MigrationResult",
    "MigrationOptions",
    "MigrationProgress",
    "MigrationError",
    "ColumnMapping",
    "coerce_value",
    "base_type",
    "type_family",
    "build_mapping",
    "plan_migration",
    "run_migration",
]

# ---------------------------------------------------------------------------
# type coercion
# ---------------------------------------------------------------------------


class CoercionError(ValueError):
    """A value could not be converted to the target column's type."""


#: Values treated as NULL when the cell is blank. Deliberately small: an
#: import that silently turns "NULL" into a 4-character string is worse than
#: one that refuses to guess.
NULL_TOKENS = {"null", "nil", "\\n"}

_TYPE_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("int", ("int", "integer", "bigint", "smallint", "tinyint", "mediumint",
             "serial", "int2", "int4", "int8", "long")),
    ("float", ("float", "double", "double precision", "real", "float4", "float8")),
    ("decimal", ("numeric", "decimal", "money", "number", "dec", "fixed")),
    ("bool", ("bool", "boolean", "bit")),
    ("date", ("date",)),
    ("datetime", ("datetime", "timestamp", "timestamptz", "timestamp with time zone",
                  "timestamp without time zone", "smalldatetime", "datetime2", "datetimeoffset")),
    ("time", ("time", "timetz")),
    ("blob", ("blob", "binary", "varbinary", "bytea", "tinyblob", "mediumblob",
              "longblob", "image", "raw", "graphic", "vargraphic")),
    ("json", ("json", "jsonb")),
    ("text", ("char", "varchar", "character", "character varying", "nchar",
              "nvarchar", "text", "tinytext", "mediumtext", "longtext",
              "string", "uuid", "enum", "set", "citext", "clob", "nclob", "xml",
              "inet", "cidr", "macaddr", "interval", "array", "hstore", "geometry",
              "point", "line", "polygon", "geography")),
)


def base_type(data_type: str) -> str:
    """``"varchar(255)" -> "varchar"``; ``"decimal(10,2)" -> "decimal"``."""
    return data_type.strip().lower().split("(", 1)[0].strip()


def _width_of(data_type: str) -> str | None:
    """``"tinyint(1)" -> "1"``; ``"int" -> None``."""
    if "(" not in data_type:
        return None
    return data_type[data_type.find("(") + 1:].split(")", 1)[0].strip()


def type_family(data_type: str) -> str:
    """Map a declared column type onto a coercion family.

    Unknown types fall back to ``"text"``: writing the string through is the
    least surprising failure mode, and it keeps engines whose type vocabulary
    we do not know (and future ones) importable instead of hard-failing.
    """
    base = base_type(data_type)
    if base in ("tinyint", "bit") and _width_of(data_type) == "1":
        # MySQL stores booleans as tinyint(1); a 1-wide bit column likewise.
        return "bool"
    if base == "bit" and _width_of(data_type) not in (None, "1"):
        # PG bit(n) is a bit string ("10110"), not a boolean; pass it through.
        return "text"
    for family, names in _TYPE_FAMILIES:
        if base in names:
            return family
    return "text"


def _is_blank(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip() == "")


def _is_hex(raw: str) -> bool:
    s = raw[2:] if raw[:2].lower() == "0x" else raw
    return bool(s) and len(s) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in s)


_TRUE_TOKENS = {"true", "t", "yes", "y", "1", "on"}
_FALSE_TOKENS = {"false", "f", "no", "n", "0", "off"}


def _to_int(raw: Any, family_hint: str) -> int:
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, (float, Decimal)):
        if float(raw).is_integer():
            return int(raw)
        raise CoercionError(f"expected {family_hint}, got non-integral {raw!r}")
    if isinstance(raw, str):
        text = raw.strip()
        # "42" and also "42.0" (Excel/CSV exports of bigint columns).
        try:
            return int(text, 10)
        except ValueError:
            try:
                number = Decimal(text)
            except InvalidOperation:
                raise CoercionError(f"expected {family_hint}, got {raw!r}") from None
            if number == number.to_integral_value():
                return int(number)
            raise CoercionError(f"expected {family_hint}, got non-integral {raw!r}") from None
    raise CoercionError(f"expected {family_hint}, got {type(raw).__name__}")


def _to_float(raw: Any, family: str) -> float:
    if isinstance(raw, bool):
        raise CoercionError(f"expected {family}, got boolean {raw!r}")
    if isinstance(raw, (int, float, Decimal)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except ValueError:
            raise CoercionError(f"expected {family}, got {raw!r}") from None
    raise CoercionError(f"expected {family}, got {type(raw).__name__}")


def _to_decimal(raw: Any, family: str) -> Decimal:
    if isinstance(raw, bool):
        raise CoercionError(f"expected {family}, got boolean {raw!r}")
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)):
        return Decimal(str(raw))
    if isinstance(raw, str):
        try:
            return Decimal(raw.strip())
        except InvalidOperation:
            raise CoercionError(f"expected {family}, got {raw!r}") from None
    raise CoercionError(f"expected {family}, got {type(raw).__name__}")


def _to_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        if raw in (0, 1):
            return bool(raw)
        raise CoercionError(f"expected boolean, got {raw!r}")
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in _TRUE_TOKENS:
            return True
        if text in _FALSE_TOKENS:
            return False
        raise CoercionError(f"expected boolean, got {raw!r}")
    raise CoercionError(f"expected boolean, got {type(raw).__name__}")


def _to_datetime(raw: Any, family: str) -> Any:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date) and family == "datetime":
        return datetime(raw.year, raw.month, raw.day)
    if isinstance(raw, date) and family == "date":
        return raw
    if isinstance(raw, time) and family == "time":
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        try:
            if family == "date":
                return date.fromisoformat(text[:10])
            if family == "time":
                return time.fromisoformat(text)
            return datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
        except ValueError:
            raise CoercionError(f"expected {family}, got {raw!r}") from None
    raise CoercionError(f"expected {family}, got {type(raw).__name__}")


def _to_blob(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return bytes(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if _is_hex(text):
            return bytes.fromhex(text[2:] if text[:2].lower() == "0x" else text)
        return text.encode("utf-8")
    raise CoercionError(f"expected binary, got {type(raw).__name__}")


def _to_text(raw: Any) -> Any:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, (datetime, date, time)):
        return raw.isoformat()
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return bytes(raw).hex()
    return str(raw)


def coerce_value(raw: Any, data_type: str, *, column: str = "", nullable: bool = True) -> Any:
    """Coerce one imported cell to the target column's declared type.

    ``raw`` may be text (CSV/TSV) or already-native (JSON/JSONL). Returns the
    value to insert; raises :class:`CoercionError` when the text cannot be
    converted -- callers record the error and skip the row rather than
    inserting garbage.
    """
    if _is_blank(raw):
        if nullable:
            return None
        family = type_family(data_type)
        if family == "text":
            return ""
        raise CoercionError(f"column {column or '?'!r} is NOT NULL")

    family = type_family(data_type)
    if family == "int":
        return _to_int(raw, "an integer")
    if family == "float":
        return _to_float(raw, family)
    if family == "decimal":
        return _to_decimal(raw, family)
    if family == "bool":
        return _to_bool(raw)
    if family in ("date", "datetime", "time"):
        return _to_datetime(raw, family)
    if family == "blob":
        return _to_blob(raw)
    if family == "json":
        return raw
    return _to_text(raw)


# ---------------------------------------------------------------------------
# column mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnMapping:
    """One file column bound to one table column."""

    source: str
    target: str
    data_type: str = ""

    def coerce(self, raw: Any, *, nullable: bool = True) -> Any:
        return coerce_value(raw, self.data_type, column=self.target, nullable=nullable)


def _column_name_of(column: Any) -> str:
    return column.name if hasattr(column, "name") else str(column)


def build_mapping(
    source_columns: Sequence[str],
    target_columns: Sequence[Any],
    *,
    case_sensitive: bool = False,
) -> tuple[list[ColumnMapping], list[str]]:
    """Match file columns onto table columns by name.

    Returns ``(mapping, unmatched_source)`` -- the caller decides whether
    unmatched file columns are a warning or an error. Matching is
    case-insensitive by default because MySQL column names are, and an
    export/import round trip through different cases is common; PG users can
    pass ``case_sensitive=True``.
    """
    by_name: dict[str, Any] = {}
    for column in target_columns:
        name = _column_name_of(column)
        by_name[name if case_sensitive else name.lower()] = column

    mapping: list[ColumnMapping] = []
    unmatched: list[str] = []
    for source in source_columns:
        key = source if case_sensitive else source.lower()
        column = by_name.get(key)
        if column is None:
            unmatched.append(source)
            continue
        mapping.append(ColumnMapping(
            source=source,
            target=_column_name_of(column),
            data_type=getattr(column, "data_type", "") or "",
        ))
    return mapping, unmatched


# ---------------------------------------------------------------------------
# planning (dry run)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrationPlan:
    """What a migration will do, computed before writing anything."""

    table: str
    database: str
    mapping: tuple[ColumnMapping, ...]
    unmatched_source: tuple[str, ...] = ()
    unmatched_target: tuple[str, ...] = ()
    row_count: int | None = None
    batch_size: int = 1000
    notes: tuple[str, ...] = ()

    @property
    def batch_count(self) -> int | None:
        if self.row_count is None or self.batch_size <= 0:
            return None
        return max(1, -(-self.row_count // self.batch_size))

    @property
    def empty(self) -> bool:
        return not self.mapping

    def render(self) -> str:
        lines = [f"table: {self.database}.{self.table}" if self.database else f"table: {self.table}"]
        if self.row_count is not None:
            lines.append(f"rows: {self.row_count}")
        if self.batch_count is not None:
            lines.append(f"batches: {self.batch_count} (size {self.batch_size})")
        lines.append("columns:")
        for item in self.mapping:
            lines.append(f"  {item.source} -> {item.target} [{item.data_type or 'text'}]")
        if self.unmatched_source:
            lines.append(f"ignored file columns: {', '.join(self.unmatched_source)}")
        if self.unmatched_target:
            lines.append(f"table columns with no file match: {', '.join(self.unmatched_target)}")
        for note in self.notes:
            lines.append(f"note: {note}")
        return "\n".join(lines)


def plan_migration(
    source_columns: Sequence[str],
    target_columns: Sequence[Any],
    *,
    table: str = "",
    database: str = "",
    row_count: int | None = None,
    batch_size: int = 1000,
) -> MigrationPlan:
    """Dry-run preview: matched columns, orphans both ways, warnings."""
    mapping, unmatched = build_mapping(source_columns, target_columns)
    matched_targets = {item.target for item in mapping}
    notes: list[str] = []
    unmatched_target: list[str] = []
    for column in target_columns:
        name = _column_name_of(column)
        if name in matched_targets:
            continue
        required = bool(getattr(column, "is_primary_key", False)) or (
            not getattr(column, "nullable", True)
            and getattr(column, "default", None) is None
        )
        if required:
            unmatched_target.append(name)
            notes.append(f"{name} is required but has no file column: rows will fail")
        else:
            unmatched_target.append(name)

    if unmatched:
        notes.append("unmatched file columns will be ignored")
    if not mapping:
        notes.append("no file column matches the table: nothing to import")

    return MigrationPlan(
        table=table,
        database=database,
        mapping=tuple(mapping),
        unmatched_source=tuple(unmatched),
        unmatched_target=tuple(unmatched_target),
        row_count=row_count,
        batch_size=batch_size,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrationError:
    """One row that could not be imported, with enough context to fix it."""

    row_number: int
    column: str
    value: str
    error: str

    def render(self) -> str:
        where = f"row {self.row_number}"
        if self.column:
            return f"{where} ({self.column}={self.value!r}): {self.error}"
        return f"{where}: {self.error}"


@dataclass
class MigrationProgress:
    """Running counters, handed to the progress callback after each batch."""

    rows_read: int = 0
    rows_written: int = 0
    rows_failed: int = 0
    batches: int = 0


@dataclass
class MigrationOptions:
    """Knobs for :func:`run_migration`."""

    batch_size: int = 1000
    transactional: bool = True
    #: Stop at the first error instead of recording it and continuing.
    stop_on_error: bool = False
    #: Case-insensitive column matching (MySQL default).
    case_sensitive: bool = False
    #: Columns of the file when it has no header row.
    columns: tuple[str, ...] | None = None
    #: ``None`` (the default) means "has a header, unless columns= was given";
    #: pass ``False`` for a headerless file, ``True`` to force a header read.
    has_header: bool | None = None
    #: Passed straight to the importer (CSV delimiter, xlsx sheet, ...).
    delimiter: str | None = None
    sheet: str | int | None = None
    encoding: str = "utf-8-sig"


@dataclass
class MigrationResult:
    """Outcome of a completed or aborted migration."""

    rows_read: int = 0
    rows_written: int = 0
    rows_failed: int = 0
    batches: int = 0
    errors: list[MigrationError] = field(default_factory=list)
    committed: bool = False
    aborted: bool = False
    plan: MigrationPlan | None = None
    notes: list[str] = field(default_factory=list)
    errors_truncated: bool = False

    @property
    def ok(self) -> bool:
        return not self.aborted and not self.errors

    def render(self) -> str:
        state = "aborted" if self.aborted else ("ok" if self.ok else "partial")
        head = f"{state}: {self.rows_written}/{self.rows_read} rows written in {self.batches} batches"
        if self.errors:
            shown = self.errors[:10]
            lines = [head] + [f"  {e.render()}" for e in shown]
            if len(self.errors) > len(shown):
                lines.append(f"  ... and {len(self.errors) - len(shown)} more")
            return "\n".join(lines)
        return head


def _mapping_for_row(
    mapping: Sequence[ColumnMapping], row: dict, row_number: int
) -> tuple[dict, MigrationError | None]:
    """Coerce one file row; returns the insert payload and the first error."""
    out: dict[str, Any] = {}
    for item in mapping:
        raw = row.get(item.source)
        try:
            out[item.target] = item.coerce(raw)
        except CoercionError as exc:
            return {}, MigrationError(
                row_number=row_number,
                column=item.target,
                value="" if raw is None else str(raw),
                error=str(exc),
            )
    return out, None

#: Errors are recorded per row; this caps memory on a pathologically bad file
#: (``rows_failed`` still counts every failure, only the list is truncated).
MAX_RECORDED_ERRORS = 1000


def _record_error(result: MigrationResult, error: MigrationError) -> None:
    if len(result.errors) < MAX_RECORDED_ERRORS:
        result.errors.append(error)
    else:
        result.errors_truncated = True


async def _maybe_await(value: Any) -> Any:
    """Support both async connectors and synchronous test doubles."""
    if inspect.isawaitable(value):
        return await value
    return value


async def run_migration(
    connector: Any,
    database: str,
    table: str,
    path: str | Path,
    *,
    mapping: Sequence[ColumnMapping] | None = None,
    options: MigrationOptions | None = None,
    on_progress: Callable[[MigrationProgress], None] | None = None,
    fmt: Any = None,
) -> MigrationResult:
    """Import one file into one table, streaming in batches.

    ``connector`` only needs ``get_table_info``, ``batch_insert`` and
    ``execute`` -- the same surface every driver exposes, so this is unit
    tested against a fake rather than a live database.

    ``mapping`` defaults to name-matching the file header against the table
    schema fetched from the connector. With ``options.transactional`` the
    whole import runs in one transaction: an abort rolls back everything, so
    a half-imported file is never left behind. If the connector rejects
    ``BEGIN`` the import proceeds un-transacted and says so in
    ``result.notes``.

    Rows that fail coercion are counted in ``rows_failed`` and listed in
    ``errors`` (capped at :data:`MAX_RECORDED_ERRORS`); the rest of the file
    still imports unless ``options.stop_on_error`` is set.
    """
    from open_navicat.formats import importers as _importers

    opts = options or MigrationOptions()
    result = MigrationResult()
    progress = MigrationProgress()

    read_options = _importers.ReadOptions(
        encoding=opts.encoding,
        delimiter=opts.delimiter,
        sheet=opts.sheet,
        columns=opts.columns,
        has_header=opts.has_header if opts.has_header is not None else (opts.columns is None),
        batch_size=max(1, opts.batch_size),
    )
    batches = _importers.iter_batches(path, read_options, fmt)

    first = next(batches, None)
    if first is None:
        # Empty file: nothing read, nothing written, nothing to commit.
        return result

    if mapping is None:
        info = await _maybe_await(connector.get_table_info(database, table))
        target_columns = list(getattr(info, "columns", []) or [])
        plan = plan_migration(
            first.columns,
            target_columns,
            table=table,
            database=database,
            batch_size=opts.batch_size,
        )
        if not plan.mapping:
            result.plan = plan
            result.aborted = True
            result.errors.append(MigrationError(
                row_number=1, column="", value=first.columns[0] if first.columns else "",
                error=(
                    "no file column matches the target table "
                    "(headerless file? pass has_header=False or columns=...)"
                ),
            ))
            return result
        mapping = list(plan.mapping)
        result.plan = plan
    else:
        result.plan = MigrationPlan(
            table=table,
            database=database,
            mapping=tuple(mapping),
            batch_size=opts.batch_size,
        )

    in_transaction = False
    if opts.transactional:
        try:
            await _maybe_await(connector.execute("BEGIN"))
            in_transaction = True
        except Exception as exc:  # engine without transactions (or already in one)
            result.notes.append(
                f"BEGIN failed ({exc}); importing without a transaction"
            )

    row_number = 0
    aborted = False

    def _iter_all():
        yield first
        yield from batches

    try:
        for batch in _iter_all():
            result.batches += 1
            progress.batches = result.batches
            rows = batch.as_dicts()
            good: list[dict[str, Any]] = []

            for row in rows:
                row_number += 1
                progress.rows_read += 1
                result.rows_read += 1
                payload, error = _mapping_for_row(mapping, row, row_number)
                if error is not None:
                    result.rows_failed += 1
                    progress.rows_failed += 1
                    _record_error(result, error)
                    if opts.stop_on_error:
                        aborted = True
                        break
                    continue
                good.append(payload)

            if good and not aborted:
                try:
                    written = await _maybe_await(
                        connector.batch_insert(database, table, good)
                    )
                    count = written if isinstance(written, int) else len(good)
                    result.rows_written += count
                    progress.rows_written = result.rows_written
                except Exception as exc:
                    # The batch is the connector's atomic unit; treat the whole
                    # batch as failed rather than guessing how many rows landed.
                    result.rows_failed += len(good)
                    progress.rows_failed += len(good)
                    _record_error(result, MigrationError(
                        row_number=row_number - len(good) + 1,
                        column="",
                        value=f"batch of {len(good)}",
                        error=str(exc),
                    ))
                    if opts.stop_on_error:
                        aborted = True

            if on_progress is not None:
                on_progress(progress)
            if aborted:
                break

        if in_transaction:
            if aborted:
                await _maybe_await(connector.execute("ROLLBACK"))
            else:
                try:
                    await _maybe_await(connector.execute("COMMIT"))
                    result.committed = True
                except Exception as exc:
                    result.notes.append(f"COMMIT failed ({exc}); rolling back")
                    try:
                        await _maybe_await(connector.execute("ROLLBACK"))
                    except Exception:
                        pass
                    aborted = True
    except Exception:
        if in_transaction:
            try:
                await _maybe_await(connector.execute("ROLLBACK"))
            except Exception:
                pass
        raise

    result.aborted = aborted
    return result
