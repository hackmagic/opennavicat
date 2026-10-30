"""Utilities package."""

from __future__ import annotations

from open_navicat.utils.output_formatter import format_output
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


def __getattr__(name: str) -> object:
    if name in ("encrypt_password", "decrypt_password", "mask_password"):
        from open_navicat.utils import safe_password

        return getattr(safe_password, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    "format_output",
