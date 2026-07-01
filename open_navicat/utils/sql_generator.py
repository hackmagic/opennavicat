"""SQL DDL/DML code generator — produces SQL from schema objects."""

from __future__ import annotations

from open_navicat.models.table_schema import ColumnInfo, TableInfo


def generate_create_table(table: TableInfo, include_if_not_exists: bool = True) -> str:
    """Generate a complete CREATE TABLE statement from a TableInfo object."""
    lines: list[str] = []
    if_exists = "IF NOT EXISTS " if include_if_not_exists else ""
    lines.append(f"CREATE TABLE {if_exists}`{table.name}` (")

    # Columns
    col_defs: list[str] = []
    for col in table.columns:
        col_defs.append(f"  {_column_sql(col)}")
    lines.append(",\n".join(col_defs))

    # Primary key
    pk_cols = [c.name for c in table.columns if c.is_primary_key]
    if pk_cols:
        pk_quoted = ", ".join(f"`{c}`" for c in pk_cols)
        lines.append(f",\n  PRIMARY KEY ({pk_quoted})")

    # Unique indexes
    for idx in table.indexes:
        if idx.is_unique and not idx.is_primary:
            cols = ", ".join(f"`{c}`" for c in idx.columns)
            lines.append(f",\n  UNIQUE KEY `{idx.name}` ({cols})")
        elif not idx.is_unique and not idx.is_primary:
            cols = ", ".join(f"`{c}`" for c in idx.columns)
            lines.append(f",\n  KEY `{idx.name}` ({cols})")

    # Foreign keys
    for fk in table.foreign_keys:
        lines.append(
            f",\n  CONSTRAINT `{fk.name}` FOREIGN KEY (`{fk.column}`) "
            f"REFERENCES `{fk.ref_table}` (`{fk.ref_column}`) "
            f"ON DELETE {fk.on_delete} ON UPDATE {fk.on_update}"
        )

    lines.append("\n) ")

    # Table options
    options: list[str] = []
    if table.engine:
        options.append(f"ENGINE={table.engine}")
    if table.charset:
        options.append(f"DEFAULT CHARSET={table.charset}")
    if table.collation:
        options.append(f"COLLATE={table.collation}")
    if table.comment:
        options.append(f"COMMENT='{table.comment}'")
    if table.auto_increment:
        options.append(f"AUTO_INCREMENT={table.auto_increment}")

    lines.append(" ".join(options))
    lines.append(";")

    return "".join(lines)


def generate_alter_table(old: TableInfo, new: TableInfo) -> str:
    """Generate ALTER TABLE statement from differences between old and new schema."""
    stmts: list[str] = []
    table_ref = f"`{new.name}`"

    old_cols = {c.name: c for c in old.columns}
    new_cols = {c.name: c for c in new.columns}

    # Dropped columns
    for name in old_cols:
        if name not in new_cols:
            stmts.append(f"ALTER TABLE {table_ref} DROP COLUMN `{name}`;")

    # Added columns (after the last matching column or at end)
    prev_col = list(old_cols.keys())[-1] if old_cols else ""
    for i, col in enumerate(new.columns):
        if col.name not in old_cols:
            after = f" AFTER `{prev_col}`" if prev_col else " FIRST"
            stmts.append(f"ALTER TABLE {table_ref} ADD COLUMN {_column_sql(col)}{after};")
        prev_col = col.name

    # Modified columns
    for name, new_col in new_cols.items():
        if name in old_cols:
            old_col = old_cols[name]
            if (_column_sql(old_col) != _column_sql(new_col) or
                old_col.nullable != new_col.nullable or
                old_col.is_primary_key != new_col.is_primary_key):
                stmts.append(f"ALTER TABLE {table_ref} MODIFY COLUMN {_column_sql(new_col)};")

    return "\n".join(stmts)


def generate_alter_table_add_column(table_name: str, column: ColumnInfo) -> str:
    """Generate ALTER TABLE … ADD COLUMN."""
    return f"ALTER TABLE `{table_name}` ADD COLUMN {_column_sql(column)};"


def generate_alter_table_drop_column(table_name: str, column_name: str) -> str:
    return f"ALTER TABLE `{table_name}` DROP COLUMN `{column_name}`;"


def generate_insert(table: str, columns: list[str], values: list[list]) -> str:
    """Generate INSERT statements for given data."""
    col_str = ", ".join(f"`{c}`" for c in columns)
    value_strs: list[str] = []
    for row in values:
        escaped = []
        for v in row:
            if v is None:
                escaped.append("NULL")
            elif isinstance(v, (int, float)):
                escaped.append(str(v))
            else:
                escaped.append(f"'{str(v).replace(chr(39), chr(39)*2)}'")
        value_strs.append("(" + ", ".join(escaped) + ")")

    return f"INSERT INTO `{table}` ({col_str}) VALUES\n" + ",\n".join(value_strs) + ";"


def generate_select(table: str, columns: list[str] | None = None,
                    where: str | None = None,
                    order_by: str | None = None,
                    limit: int | None = None) -> str:
    cols = ", ".join(f"`{c}`" for c in columns) if columns else "*"
    sql = f"SELECT {cols} FROM `{table}`"
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    if limit:
        sql += f" LIMIT {limit}"
    return sql + ";"


def generate_drop_table(table_name: str) -> str:
    return f"DROP TABLE IF EXISTS `{table_name}`;"


# ---- internal helpers ----

def _column_sql(col: ColumnInfo) -> str:
    parts = [f"`{col.name}`", col.data_type]

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
        if isinstance(col.default, str):
            parts.append(f"DEFAULT '{col.default}'")
        else:
            parts.append(f"DEFAULT {col.default}")
    else:
        parts.append("DEFAULT NULL")

    if col.comment:
        parts.append(f"COMMENT '{col.comment}'")

    return " ".join(parts)
