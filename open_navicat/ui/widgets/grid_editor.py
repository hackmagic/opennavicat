"""Grid edit intent: what the user changed, and the SQL that would apply it.

The data grid used to build its own UPDATE/DELETE statements inline, with three
problems that this module exists to remove:

1. **The primary key was assumed to be column 0.**  Any table whose first
   column is not the key had its edits and deletes applied to the wrong rows.
2. **Every value was a string.**  ``WHERE id = '7'`` does not match an integer
   key, and an ISO timestamp string is not what a ``DATE`` column wants.
3. **Backticks everywhere.**  The statements only parsed on MySQL.

Here a :class:`PendingChange` records *what* changed, :func:`plan_changes`
turns a set of changes into previewable statements, and the caller executes
them with bound parameters.  Nothing in this module imports Qt, so all of it is
unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from open_navicat.sql.quoting import (
    quote_identifier,
    quote_literal,
    quote_qualified,
)


class ChangeKind(str, Enum):
    """What a pending change does to the row."""

    UPDATE = "update"
    INSERT = "insert"
    DELETE = "delete"


@dataclass(frozen=True)
class PendingChange:
    """One pending row-level change, as the user expressed it.

    ``key_values`` is the primary-key mapping that identifies the row; it is
    kept structured (not pre-formatted) so the executor can bind it.
    ``values`` holds only the columns that actually changed.
    """

    kind: ChangeKind
    table: str
    database: str = ""
    key_columns: tuple[str, ...] = ()
    key_values: dict[str, Any] = field(default_factory=dict)
    values: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind in (ChangeKind.UPDATE, ChangeKind.DELETE) and not self.key_columns:
            raise ValueError(
                f"{self.kind.value} needs key_columns to identify the row; "
                "refusing to build a statement that could match every row"
            )

    @property
    def target(self) -> str:
        """The row this change addresses, for logs and conflict messages."""
        if not self.key_values:
            return "(new row)"
        return ", ".join(f"{k}={v!r}" for k, v in self.key_values.items())

    def identity(self) -> tuple[Any, ...]:
        """A hashable identity used to merge edits to the same cell."""
        return (
            self.kind.value,
            self.table,
            self.database,
            tuple(sorted(self.key_columns)),
            tuple(sorted((k, str(v)) for k, v in self.key_values.items())),
        )


@dataclass(frozen=True)
class ChangePreview:
    """A change rendered for review, plus the parameter set to run it."""

    change: PendingChange
    sql: str
    params: tuple[Any, ...] = ()

    @property
    def sql_with_values(self) -> str:
        """The statement with values inlined, for read-only display.

        Never execute this: it exists so a human can see what will happen in a
        preview pane.  Values are quoted by
        :func:`open_navicat.sql.quoting.quote_literal`.
        """
        from open_navicat.sql.quoting import quote_literal

        out = self.sql
        for param in self.params:
            out = out.replace(
                "%s", quote_literal(param, self.change.table and "mysql" or "mysql"), 1
            )
        return out


def build_update(
    change: PendingChange,
    engine: str = "mysql",
    *,
    where_extra: dict[str, Any] | None = None,
) -> ChangePreview:
    """Render an UPDATE for ``change`` with bound parameters."""
    if not change.values:
        raise ValueError("UPDATE needs at least one column to set")
    table = quote_qualified(change.table, engine, change.database or None)
    assignments = ", ".join(f"{quote_identifier(col, engine)} = %s" for col in change.values)
    where = _where_clause(change, engine, where_extra)
    sql = f"UPDATE {table} SET {assignments} WHERE {where}"
    return ChangePreview(
        change=change,
        sql=sql,
        params=tuple(change.values.values()) + tuple(_where_params(change, where_extra)),
    )


def build_delete(
    change: PendingChange,
    engine: str = "mysql",
    *,
    where_extra: dict[str, Any] | None = None,
) -> ChangePreview:
    """Render a DELETE for ``change`` with bound parameters."""
    table = quote_qualified(change.table, engine, change.database or None)
    where = _where_clause(change, engine, where_extra)
    return ChangePreview(
        change=change,
        sql=f"DELETE FROM {table} WHERE {where}",
        params=tuple(_where_params(change, where_extra)),
    )


def build_insert(change: PendingChange, engine: str = "mysql") -> ChangePreview:
    """Render an INSERT for ``change`` with bound parameters."""
    if not change.values:
        raise ValueError("INSERT needs at least one column to set")
    table = quote_qualified(change.table, engine, change.database or None)
    columns = ", ".join(quote_identifier(c, engine) for c in change.values)
    placeholders = ", ".join("%s" for _ in change.values)
    return ChangePreview(
        change=change,
        sql=f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        params=tuple(change.values.values()),
    )


def build_preview(change: PendingChange, engine: str = "mysql") -> ChangePreview:
    """Dispatch to the right builder for ``change.kind``."""
    if change.kind is ChangeKind.UPDATE:
        return build_update(change, engine)
    if change.kind is ChangeKind.DELETE:
        return build_delete(change, engine)
    if change.kind is ChangeKind.INSERT:
        return build_insert(change, engine)
    raise ValueError(f"unsupported change kind: {change.kind!r}")


def plan_changes(changes: Iterable[PendingChange], engine: str = "mysql") -> list[ChangePreview]:
    """Render every change, keeping only the newest edit per cell.

    A grid lets the user overwrite the same cell repeatedly; only the final
    value should reach the database, so later changes supersede earlier ones
    that touch the same cell.
    """
    merged: dict[tuple[Any, ...], PendingChange] = {}
    for change in changes:
        merged[change.identity()] = change
    return [build_preview(change, engine) for change in merged.values()]


def merge_cell_edits(edits: Iterable[PendingChange]) -> list[PendingChange]:
    """Collapse repeated edits to the same cell into the last one.

    ``edits`` may contain several changes for one cell (the user typed, undid,
    retyped).  Changes to *different* columns of the same row are merged into one
    UPDATE so it costs a single round trip.
    """
    by_row: dict[tuple[Any, ...], PendingChange] = {}
    order: list[tuple[Any, ...]] = []
    for change in edits:
        ident = change.identity()
        if ident not in by_row:
            order.append(ident)
            by_row[ident] = change
            continue
        existing = by_row[ident]
        merged_values = dict(existing.values)
        merged_values.update(change.values)
        by_row[ident] = PendingChange(
            kind=existing.kind,
            table=existing.table,
            database=existing.database,
            key_columns=existing.key_columns,
            key_values=existing.key_values,
            values=merged_values,
        )
    return [by_row[ident] for ident in order]


# ---- internals ----


def _where_clause(change: PendingChange, engine: str, where_extra: dict[str, Any] | None) -> str:
    """Build the WHERE clause for a keyed change.

    A composite key gets every column ANDed.  ``where_extra`` exists so a
    caller can add a safety net such as ``updated_at = ...`` (optimistic
    locking) without changing the change itself.
    """
    if not change.key_columns:
        raise ValueError("cannot build a WHERE clause without key columns")
    columns = list(change.key_columns)
    values = list(change.key_values.values())
    if where_extra:
        columns += list(where_extra)
        values += list(where_extra.values())
    return " AND ".join(f"{quote_identifier(col, engine)} = %s" for col in columns)


def _where_params(change: PendingChange, where_extra: dict[str, Any] | None) -> list[Any]:
    values = list(change.key_values.values())
    if where_extra:
        values += list(where_extra.values())
    return values


def coerce_like(text: str, reference: Any) -> Any:
    """Coerce text typed into a cell to the type the column already holds.

    The grid receives values as strings, but a cell holding ``7`` must go back
    as an int or the key comparison fails.  When the reference value gives no
    hint (a ``None`` in a new column) the text is kept as typed.
    """
    if not isinstance(text, str):
        return text
    stripped = text.strip()

    if isinstance(reference, bool):
        lowered = stripped.lower()
        if lowered in ("1", "true", "yes", "y", "t"):
            return True
        if lowered in ("0", "false", "no", "n", "f", ""):
            return False
        return text

    if isinstance(reference, int) and not isinstance(reference, bool):
        try:
            return int(stripped)
        except ValueError:
            return text

    if isinstance(reference, float):
        try:
            return float(stripped)
        except ValueError:
            return text

    import datetime as _dt

    if isinstance(reference, _dt.datetime):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return _dt.datetime.strptime(stripped, fmt)
            except ValueError:
                continue
        return text

    if isinstance(reference, _dt.date):
        try:
            return _dt.datetime.strptime(stripped, "%Y-%m-%d").date()
        except ValueError:
            return text

    import decimal

    if isinstance(reference, decimal.Decimal):
        try:
            return decimal.Decimal(stripped)
        except decimal.InvalidOperation:
            return text

    return text


#: Spellings a user may type to mean "empty this cell".
NULL_SPELLINGS = frozenset({"null", "none", "nil", "\\n", ""})


def cell_value_from_text(text: str, reference: Any) -> Any:
    """Public entry point for :func:`coerce_like`, with the NULL spelling.

    A cell the user emptied arrives as an empty string.  Treating that as the
    literal "" would write an empty value where they meant SQL NULL, so the
    usual NULL spellings (and a blank cell) become ``None`` instead.
    """
    if isinstance(text, str) and text.strip().lower() in NULL_SPELLINGS:
        return None
    return coerce_like(text, reference)


# ---- column pinning and bulk selection ----

#: Hard cap on how many columns may be pinned: beyond a couple of key columns
#: the grid would spend all its width on frozen cells and none on the data.
MAX_PINNED_COLUMNS = 3


def order_columns(columns: Sequence[str], pinned: Sequence[str]) -> list[str]:
    """Return ``columns`` with the pinned ones moved to the front.

    QTableWidget has no frozen-pane support (that needs two synchronised views),
    so "pinning" here means keeping the column at the leading edge where it stays
    visible during horizontal scrolling.  The relative order of the pinned
    columns follows ``pinned``, and everything else keeps its original order.
    """
    pinned_set = [name for name in pinned if name in columns]
    rest = [name for name in columns if name not in set(pinned_set)]
    return pinned_set + rest


def toggle_pin(pinned: Sequence[str], name: str) -> list[str]:
    """Add or remove ``name`` from the pinned list.

    Refuses to grow past :data:`MAX_PINNED_COLUMNS`, and keeps insertion order so
    the leading-edge order is stable and predictable.
    """
    current = list(pinned)
    if name in current:
        current.remove(name)
        return current
    if len(current) >= MAX_PINNED_COLUMNS:
        return current
    current.append(name)
    return current


def selected_rows(
    rows: Sequence[Sequence[Any]],
    selected: Iterable[tuple[int, int]],
) -> list[Sequence[Any]]:
    """Distinct rows touched by the given ``(row, column)`` selection cells.

    A grid selection is a set of cells; callers that act per row (delete, export,
    copy) need the distinct rows behind them, in display order.
    """
    indices = sorted({row for row, _col in selected})
    return [rows[i] for i in indices if 0 <= i < len(rows)]


def copy_as_insert(
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    engine: str = "mysql",
) -> str:
    """Render the selected rows as INSERT statements.

    Useful for moving a handful of rows between environments without a dump.
    """
    if not rows or not columns:
        return ""
    ref = quote_qualified(table, engine)
    col_list = ", ".join(quote_identifier(c, engine) for c in columns)
    lines = []
    for row in rows:
        values = ", ".join(quote_literal(v, engine) for v in row)
        lines.append(f"INSERT INTO {ref} ({col_list}) VALUES ({values});")
    return "\n".join(lines)


def copy_as_update(
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    key_columns: Sequence[str],
    engine: str = "mysql",
) -> str:
    """Render the selected rows as keyed UPDATE statements.

    Columns named in ``key_columns`` form the WHERE clause; the rest become the
    SET list.  Returns an empty string when no key is known, because an UPDATE
    without a WHERE would affect every row.
    """
    if not rows or not columns or not key_columns:
        return ""
    key_set = [c for c in key_columns if c in columns]
    if not key_set:
        return ""
    set_cols = [c for c in columns if c not in set(key_set)]
    if not set_cols:
        return ""

    ref = quote_qualified(table, engine)
    lines = []
    for row in rows:
        mapping = dict(zip(columns, row))
        assignments = ", ".join(
            f"{quote_identifier(c, engine)} = {quote_literal(mapping.get(c), engine)}"
            for c in set_cols
        )
        where = " AND ".join(
            f"{quote_identifier(c, engine)} = {quote_literal(mapping.get(c), engine)}"
            for c in key_set
        )
        lines.append(f"UPDATE {ref} SET {assignments} WHERE {where};")
    return "\n".join(lines)


def copy_as_where(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    key_columns: Sequence[str],
    engine: str = "mysql",
) -> str:
    """Render the selected rows' keys as a WHERE clause, one predicate per row."""
    if not rows or not key_columns:
        return ""
    key_set = [c for c in key_columns if c in columns]
    if not key_set:
        return ""
    clauses = []
    for row in rows:
        mapping = dict(zip(columns, row))
        clauses.append(
            " AND ".join(
                f"{quote_identifier(c, engine)} = {quote_literal(mapping.get(c), engine)}"
                for c in key_set
            )
        )
    if len(clauses) == 1:
        return clauses[0]
    return "(" + ") OR (".join(clauses) + ")"
