"""Utilities package."""

from __future__ import annotations

from open_navicat.utils.output_formatter import format_output
from open_navicat.utils.safe_password import decrypt_password, encrypt_password, mask_password
from open_navicat.utils.sql_formatter import (
    beautify,
    extract_table_names,
    is_ddl,
    is_dml,
    is_select,
    minify,
    split_statements,
)
from open_navicat.utils.sql_generator import (
    generate_alter_table_add_column,
    generate_alter_table_drop_column,
    generate_create_table,
    generate_drop_table,
    generate_insert,
    generate_select,
)

__all__ = [
    "beautify", "minify", "extract_table_names", "split_statements",
    "is_select", "is_ddl", "is_dml",
    "generate_create_table", "generate_alter_table_add_column",
    "generate_alter_table_drop_column", "generate_insert",
    "generate_select", "generate_drop_table",
    "encrypt_password", "decrypt_password", "mask_password",
    "format_output",
]
