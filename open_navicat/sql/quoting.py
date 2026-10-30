"""SQL literal and identifier quoting, per engine.

Every generated statement in the codebase used to hard-code MySQL backticks
and ``'string'`` quoting.  That is fine on MySQL and wrong everywhere else:
PostgreSQL wants ``"ident"``, SQL Server wants ``[ident]``, ClickHouse wants
backticks but with different escaping, SQLite accepts both.

Keeping this in one place is what lets the grid, the schema tools and the
migration pipeline share statement building without each reinventing it.
"""

from __future__ import annotations

import datetime
import decimal
from typing import Any

#: Engines whose identifier quoting we know.  Unknown engines fall back to the
#: ANSI double-quote form, which is what ``sqlglot`` and most tooling assume.
_IDENT_STYLE: dict[str, str] = {
    "mysql": "backtick",
    "mariadb": "backtick",
    "duckdb": "backtick",
    "clickhouse": "backtick",
    "postgresql": "double",
    "sqlite": "double",
    "sqlserver": "bracket",
    "oracle": "double",
    "mongodb": "double",
    "redis": "double",
}

#: Engines that take ``LIMIT n`` / ``LIMIT n OFFSET m``.
_LIMIT_OFFSET_STYLE: dict[str, str] = {
    "mysql": "limit_offset",
    "mariadb": "limit_offset",
    "sqlite": "limit_offset",
    "postgresql": "limit_offset",
    "duckdb": "limit_offset",
    "clickhouse": "limit_offset",
    "sqlserver": "offset_fetch",
    "oracle": "offset_fetch",
}


def normalize_engine(engine: str | None) -> str:
    """Lower-case an engine key for lookup in the style tables."""
    return (engine or "").strip().lower()


def quote_identifier(name: str | None, engine: str = "mysql") -> str:
    """Quote an identifier for ``engine``.

    Escaping is doubled-quote (the SQL standard) rather than backslash-escaped,
    because SQLite and ClickHouse do not honour backslash escapes inside
    backticks the way MySQL does.
    """
    style = _IDENT_STYLE.get(normalize_engine(engine), "double")
    text = str(name or "")
    if style == "backtick":
        return "`" + text.replace("`", "``") + "`"
    if style == "bracket":
        return "[" + text.replace("]", "]]") + "]"
    return '"' + text.replace('"', '""') + '"'


def _quote_postgresql_qualified(name: str | None, engine: str) -> str:
    """Render a PostgreSQL object reference, database prefix stripped.

    PostgreSQL has no cross-database references: a statement naming
    ``"mydb"."table"`` is rejected outright with *"cross-database references are
    not implemented"*.  Objects are qualified by **schema** instead, so the
    ``database`` argument is meaningless here and must be dropped.

    A name that already carries a schema is rendered ``"schema"."table"``, which
    is what makes objects outside the default schema addressable.  A *bare*
    name is deliberately left unqualified: PostgreSQL resolves unqualified
    names through ``search_path`` (typically ``"$user", public``), so pinning
    ``"public"."table"`` would break every table a connection legitimately
    reaches through a custom or per-user search path.  Prepending ``public``
    was measured on PostgreSQL 18.6 to turn a working
    ``select * from "custom_t"`` into *relation "public.custom_t" does not
    exist*, which is why the bare-name shape is preserved unchanged.

    Only the first ``.`` is treated as the separator: it is the schema/table
    boundary, and any further dots belong to the (unusual) table name itself.
    ``None`` and the empty string are bare names, so they keep the historical
    ``""`` rendering and this function stays total (callers pass unvalidated
    tree-node labels straight in).
    """
    text = str(name or "")
    schema, separator, table = text.partition(".")
    if not separator:
        # Bare name: keep it unqualified so search_path still applies.
        return quote_identifier(text, engine)
    return f"{quote_identifier(schema, engine)}.{quote_identifier(table, engine)}"


def quote_qualified(name: str | None, engine: str = "mysql", database: str | None = None) -> str:
    """Quote a possibly-qualified name, quoting each part separately.

    ``database`` is only a *database* qualifier on engines that have one
    (MySQL, SQL Server, ...), where ``db.table`` is valid and often required.
    PostgreSQL resolves objects through schemas and rejects a database prefix,
    so it takes a dedicated branch: ``database`` is ignored entirely and any
    schema is taken from ``name`` itself (see
    :func:`_quote_postgresql_qualified`).  Every other engine keeps the
    historical ``if database:`` short-circuit unchanged, because moving them
    would silently retarget statements on those servers.
    """
    if normalize_engine(engine) == "postgresql":
        return _quote_postgresql_qualified(name, engine)
    if database:
        return f"{quote_identifier(database, engine)}.{quote_identifier(name, engine)}"
    text = str(name or "")
    if "." in text:
        return ".".join(quote_identifier(part, engine) for part in text.split("."))
    return quote_identifier(text, engine)


def quote_literal(value: Any, engine: str = "mysql") -> str:
    """Render ``value`` as a SQL literal.

    Used only where parameters cannot be bound (DDL defaults, preview text,
    engines that reject placeholders in a given position).  For actual data
    changes, prefer bound parameters — see
    :mod:`open_navicat.ui.widgets.grid_editor`.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        # Checked before int: bool is a subclass of int.
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, decimal.Decimal)):
        return str(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return "NULL"
        if value in (float("inf"), float("-inf")):
            return "NULL"
        return repr(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        style = _IDENT_STYLE.get(normalize_engine(engine), "double")
        if style == "bracket":
            return "0x" + bytes(value).hex()
        return "'" + bytes(value).hex() + "'"
    if isinstance(value, datetime.datetime):
        return "'" + value.isoformat(sep=" ") + "'"
    if isinstance(value, datetime.date):
        return "'" + value.isoformat() + "'"
    if isinstance(value, datetime.time):
        return "'" + value.isoformat() + "'"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(quote_literal(v, engine) for v in value) + "]"

    text = str(value)
    # Standard SQL escapes a quote by doubling it.  MySQL additionally has to
    # cope with backslashes, which are escape characters there.
    escaped = text.replace("'", "''")
    if normalize_engine(engine) in ("mysql", "mariadb"):
        escaped = escaped.replace("\\", "\\\\")
    return "'" + escaped + "'"


def limit_clause(limit: int | None, offset: int | None, engine: str = "mysql") -> str:
    """Build the engine-appropriate row-limiting clause.

    SQL Server has no ``LIMIT``; it needs ``OFFSET n ROWS FETCH NEXT m ROWS
    ONLY`` *and* requires an ``ORDER BY`` before it.  Oracle 12c+ is the same
    shape with a comma instead of ``FETCH NEXT``.
    """
    style = _LIMIT_OFFSET_STYLE.get(normalize_engine(engine), "limit_offset")
    if style == "offset_fetch":
        if not limit:
            return ""
        parts = ""
        if offset:
            parts += f"OFFSET {int(offset)} ROWS "
        return parts + f"FETCH NEXT {int(limit)} ROWS ONLY"
    if not limit and not offset:
        return ""
    if not limit:
        # No LIMIT but an OFFSET: the portable spelling is "LIMIT -1 OFFSET n".
        return f"LIMIT -1 OFFSET {int(offset)}"
    if not offset:
        return f"LIMIT {int(limit)}"
    return f"LIMIT {int(limit)} OFFSET {int(offset)}"
