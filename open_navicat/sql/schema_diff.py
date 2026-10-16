"""Schema-diff planning: turn a SyncDiff into ordered DDL and a dry-run view.

``sync_engine.generate_sync_script`` used to hold this inline with
``is_pg = engine == "postgresql"`` and a two-way quote choice, so SQLite,
ClickHouse and SQL Server targets produced DDL that could not parse.  It also
emitted DROP TABLE in the order the tables happened to be discovered, which
fails when one of them still has a foreign key pointing at it.

Extracted here so the ordering rules and per-engine syntax are unit-testable
without a database.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from open_navicat.sql.quoting import (
    normalize_engine,
    quote_identifier,
    quote_qualified,
)
from open_navicat.utils.sql_generator import _column_sql, generate_create_table


def _is_mysql(engine: str) -> bool:
    return normalize_engine(engine) in ("mysql", "mariadb")


def table_ref(name: str, engine: str, database: str = "") -> str:
    """``db.table`` for engines that want it, otherwise just ``table``."""
    return quote_qualified(name, engine, database or None)


def drop_table_statements(names: Iterable[str], engine: str, database: str = "") -> list[str]:
    """DROP TABLE statements for ``names``.

    Callers are responsible for passing them in dependency order; see
    :func:`order_drops`.
    """
    return [f"DROP TABLE IF EXISTS {table_ref(name, engine, database)};" for name in names]


def order_creates(names: Sequence[str], references: dict[str, set[str]]) -> list[str]:
    """Order tables so a referenced table is created before its dependants.

    ``references`` maps a table to the set of tables *it* points at, so a table
    must come after everything in its own reference set.  Cycles are emitted in
    the given order.
    """
    remaining = list(names)
    ordered: list[str] = []
    placed: set[str] = set()

    while remaining:
        ready = [
            name
            for name in remaining
            if all(
                target not in remaining or target == name or target in placed
                for target in references.get(name, set())
            )
        ]
        if not ready:
            ordered.extend(remaining)
            break
        for name in ready:
            ordered.append(name)
            placed.add(name)
            remaining.remove(name)

    return ordered


def order_drops(names: Sequence[str], references: dict[str, set[str]]) -> list[str]:
    """Order tables so a referenced table is dropped after its dependants.

    ``references`` maps a table to the set of tables *it* points at.  A table
    that others point at must outlive them, so it goes later in the list.  Cycles
    (mutually referencing tables) are broken arbitrarily rather than looping
    forever — the caller is told, because it may want to drop the constraints
    first.
    """
    remaining = list(names)
    ordered: list[str] = []
    dropped: set[str] = set()

    while remaining:
        # A table is safe to drop once nothing left in the list points at it.
        safe = [
            name
            for name in remaining
            if not any(
                name in references.get(other, set())
                for other in remaining
                if other != name and other not in dropped
            )
        ]
        if not safe:
            # Every remaining table is referenced by another one still present:
            # a cycle.  Drop them in the given order.
            ordered.extend(remaining)
            break
        for name in safe:
            ordered.append(name)
            dropped.add(name)
            remaining.remove(name)

    return ordered


def _fk_clauses(engine: str) -> tuple[str, str]:
    """How to add and drop a foreign key on ``engine``."""
    if _is_mysql(engine):
        return ("ADD CONSTRAINT", "DROP FOREIGN KEY")
    if normalize_engine(engine) == "sqlserver":
        return ("ADD CONSTRAINT", "DROP CONSTRAINT")
    return ("ADD CONSTRAINT", "DROP CONSTRAINT")


def _modify_column_statement(ref: str, column_name: str, source_column, engine: str) -> str:
    """Render the ALTER that changes a column's definition."""
    column = quote_identifier(column_name, engine)
    engine_key = normalize_engine(engine)
    if engine_key in ("mysql", "mariadb"):
        # MySQL can change everything in one MODIFY COLUMN.
        return f"ALTER TABLE {ref} MODIFY COLUMN {_column_sql(source_column, engine)};"
    if engine_key == "sqlserver":
        # SQL Server wants the type and nullability separately.
        parts = [f"ALTER TABLE {ref} ALTER COLUMN {_column_sql(source_column, engine)};"]
        if not source_column.nullable:
            parts.append(
                f"ALTER TABLE {ref} ALTER COLUMN {column} {source_column.data_type} NOT NULL;"
            )
        return "\n".join(parts)
    # PostgreSQL, Oracle, SQLite (12+), ClickHouse.
    return f"ALTER TABLE {ref} ALTER COLUMN {column} TYPE {source_column.data_type};"


def _drop_index_statement(ref: str, index_name: str, engine: str) -> str:
    name = quote_identifier(index_name, engine)
    if _is_mysql(engine):
        return f"ALTER TABLE {ref} DROP INDEX {name};"
    if normalize_engine(engine) == "sqlserver":
        return f"DROP INDEX {name} ON {ref};"
    if normalize_engine(engine) == "clickhouse":
        return f"ALTER TABLE {ref} DROP INDEX {name};"
    return f"DROP INDEX {name};"


def _add_index_statements(ref: str, index, engine: str) -> list[str]:
    columns = ", ".join(quote_identifier(c, engine) for c in index.columns)
    name = quote_identifier(index.name, engine)
    if index.is_primary:
        return [f"ALTER TABLE {ref} ADD PRIMARY KEY ({columns});"]
    if index.is_unique:
        return [f"CREATE UNIQUE INDEX {name} ON {ref} ({columns});"]
    return [f"CREATE INDEX {name} ON {ref} ({columns});"]
