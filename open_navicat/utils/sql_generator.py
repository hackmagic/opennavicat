"""SQL DDL/DML code generator — produces SQL from schema objects.

Every generator takes an optional ``engine`` and routes identifier/literal
quoting through :mod:`open_navicat.sql.quoting`.  Statements used to hard-code
MySQL backticks, which produced DDL that would not parse on PostgreSQL, SQLite
or SQL Server — while ``sync_engine`` happily generates cross-engine DDL.
"""

from __future__ import annotations

from open_navicat.models.table_schema import ColumnInfo, TableInfo
from open_navicat.sql.quoting import (
    normalize_engine,
    quote_identifier,
    quote_literal,
    quote_qualified,
)


def generate_create_table(
    table: TableInfo, include_if_not_exists: bool = True, engine: str = "mysql"
) -> str:
    """Generate a complete CREATE TABLE statement from a TableInfo object."""
    lines: list[str] = []
    if_exists = "IF NOT EXISTS " if include_if_not_exists else ""
    lines.append(f"CREATE TABLE {if_exists}{quote_identifier(table.name, engine)} (")

    # Columns
    col_defs: list[str] = []
    for col in table.columns:
        col_defs.append(f"  {_column_sql(col, engine)}")
    lines.append(",\n".join(col_defs))

    # Primary key
    pk_cols = [c.name for c in table.columns if c.is_primary_key]
    if pk_cols:
        pk_quoted = ", ".join(quote_identifier(c, engine) for c in pk_cols)
        lines.append(f",\n  PRIMARY KEY ({pk_quoted})")

    # Unique / plain indexes.  MySQL spells these "UNIQUE KEY name (cols)"; the
    # standard engines want "UNIQUE (cols)" plus a separate index name, so the
    # keyword form is only used where it is valid.
    mysql_only = normalize_engine(engine) in ("mysql", "mariadb")
    for idx in table.indexes:
        if idx.is_primary:
            continue
        cols = ", ".join(quote_identifier(c, engine) for c in idx.columns)
        if idx.is_unique:
            keyword = "UNIQUE KEY" if mysql_only else "UNIQUE"
        else:
            if not mysql_only:
                # Non-MySQL engines cannot declare a plain index inline.
                continue
            keyword = "KEY"
        if mysql_only:
            lines.append(f",\n  {keyword} {quote_identifier(idx.name, engine)} ({cols})")
        elif idx.is_unique:
            # The standard form is "CONSTRAINT name UNIQUE (cols)"; an index name
            # cannot be inlined after UNIQUE on PostgreSQL or SQL Server.
            lines.append(f",\n  CONSTRAINT {quote_identifier(idx.name, engine)} UNIQUE ({cols})")

    # Foreign keys
    for fk in table.foreign_keys:
        lines.append(
            f",\n  CONSTRAINT {quote_identifier(fk.name, engine)} "
            f"FOREIGN KEY ({quote_identifier(fk.column, engine)}) "
            f"REFERENCES {quote_identifier(fk.ref_table, engine)} "
            f"({quote_identifier(fk.ref_column, engine)}) "
            f"ON DELETE {fk.on_delete} ON UPDATE {fk.on_update}"
        )

    lines.append("\n")

    # Table options.  ENGINE / CHARSET / AUTO_INCREMENT are MySQL-only spellings;
    # emitting them for another engine produces DDL that does not parse, which
    # is exactly what cross-engine schema sync used to generate.
    options: list[str] = []
    if mysql_only:
        if table.engine:
            options.append(f"ENGINE={table.engine}")
        if table.charset:
            options.append(f"DEFAULT CHARSET={table.charset}")
        if table.collation:
            options.append(f"COLLATE={table.collation}")
        if table.auto_increment:
            options.append(f"AUTO_INCREMENT={table.auto_increment}")
    if table.comment:
        # A trailing COMMENT works only on MySQL; elsewhere it becomes a comment.
        if mysql_only:
            options.append(f"COMMENT={quote_literal(table.comment, engine)}")
        else:
            lines.append(f"\n-- {table.comment}")
    # Close the column list, then append the engine options if there are any.
    # Without the guard a statement with no options came out as ") ;".
    lines.append(")")
    if options:
        lines.append(" " + " ".join(options))
    lines.append(";")

    return "".join(lines)


def generate_alter_table(old: TableInfo, new: TableInfo, engine: str = "mysql") -> str:
    """Generate ALTER TABLE statement from differences between old and new schema."""
    stmts: list[str] = []
    table_ref = quote_identifier(new.name, engine)

    old_cols = {c.name: c for c in old.columns}
    new_cols = {c.name: c for c in new.columns}

    # Dropped columns
    for name in old_cols:
        if name not in new_cols:
            stmts.append(f"ALTER TABLE {table_ref} DROP COLUMN {quote_identifier(name, engine)};")

    # Added columns (after the last matching column or at end)
    prev_col = list(old_cols.keys())[-1] if old_cols else ""
    for i, col in enumerate(new.columns):
        if col.name not in old_cols:
            after = f" AFTER {quote_identifier(prev_col, engine)}" if prev_col else " FIRST"
            stmts.append(f"ALTER TABLE {table_ref} ADD COLUMN {_column_sql(col, engine)}{after};")
        prev_col = col.name

    # Modified columns
    for name, new_col in new_cols.items():
        if name in old_cols:
            old_col = old_cols[name]
            if (
                _column_sql(old_col) != _column_sql(new_col)
                or old_col.nullable != new_col.nullable
                or old_col.is_primary_key != new_col.is_primary_key
            ):
                stmts.append(
                    f"ALTER TABLE {table_ref} MODIFY COLUMN {_column_sql(new_col, engine)};"
                )

    return "\n".join(stmts)


def generate_alter_table_add_column(
    table_name: str, column: ColumnInfo, engine: str = "mysql"
) -> str:
    """Generate ALTER TABLE ... ADD COLUMN."""
    ref = quote_identifier(table_name, engine)
    return f"ALTER TABLE {ref} ADD COLUMN {_column_sql(column, engine)};"


def generate_alter_table_drop_column(
    table_name: str, column_name: str, engine: str = "mysql"
) -> str:
    ref = quote_identifier(table_name, engine)
    return f"ALTER TABLE {ref} DROP COLUMN {quote_identifier(column_name, engine)};"


def generate_insert(
    table: str,
    columns: list[str],
    values: list[list],
    engine: str = "mysql",
) -> str:
    """Generate INSERT statements for given data."""
    col_str = ", ".join(quote_identifier(c, engine) for c in columns)
    value_strs: list[str] = []
    for row in values:
        escaped = [quote_literal(v, engine) for v in row]
        value_strs.append("(" + ", ".join(escaped) + ")")

    ref = quote_identifier(table, engine)
    return f"INSERT INTO {ref} ({col_str}) VALUES\n" + ",\n".join(value_strs) + ";"


def generate_select(
    table: str,
    columns: list[str] | None = None,
    where: str | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    engine: str = "mysql",
) -> str:
    cols = ", ".join(quote_identifier(c, engine) for c in columns) if columns else "*"
    ref = quote_identifier(table, engine)
    sql = f"SELECT {cols} FROM {ref}"
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit:
        sql += f" LIMIT {limit}"
    return sql + ";"


def generate_drop_table(table_name: str, engine: str = "mysql") -> str:
    return f"DROP TABLE IF EXISTS {quote_identifier(table_name, engine)};"


# ---- internal helpers ----


def _column_sql(col: ColumnInfo, engine: str = "mysql") -> str:
    parts = [quote_identifier(col.name, engine), col.data_type]

    if col.char_max_length:
        parts[1] = f"{col.data_type}({col.char_max_length})"
    elif col.numeric_precision is not None:
        if col.numeric_scale and col.numeric_scale > 0:
            parts[1] = f"{col.data_type}({col.numeric_precision},{col.numeric_scale})"
        else:
            parts[1] = f"{col.data_type}({col.numeric_precision})"

    if not col.nullable:
        parts.append("NOT NULL")
    if col.is_auto_increment:
        parts.append("AUTO_INCREMENT")
    if col.default is not None:
        parts.append(f"DEFAULT {quote_literal(col.default, engine)}")
    else:
        parts.append("DEFAULT NULL")

    if col.comment:
        parts.append(f"COMMENT {quote_literal(col.comment, engine)}")

    return " ".join(parts)
