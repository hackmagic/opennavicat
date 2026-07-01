"""Utilities package."""

from __future__ import annotations

from open_navicat.utils.sql_formatter import (
    beautify,
    minify,
    extract_table_names,
    split_statements,
    is_select,
    is_ddl,
    is_dml,
)
from open_navicat.utils.sql_generator import (
    generate_create_table,
    generate_alter_table_add_column,
    generate_alter_table_drop_column,
    generate_insert,
    generate_select,
    generate_drop_table,
)
from open_navicat.utils.safe_password import encrypt_password, decrypt_password, mask_password
from open_navicat.utils.output_formatter import format_output

__all__ = [
    "beautify", "minify", "extract_table_names", "split_statements",
    "is_select", "is_ddl", "is_dml",
    "generate_create_table", "generate_alter_table_add_column",
    "generate_alter_table_drop_column", "generate_insert",
    "generate_select", "generate_drop_table",
    "encrypt_password", "decrypt_password", "mask_password",
    "format_output",
]
