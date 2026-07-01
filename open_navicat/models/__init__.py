"""Data models shared across the application."""

from __future__ import annotations

from open_navicat.models.connection import ConnectionInfo
from open_navicat.models.query_result import ColumnMeta, QueryResult
from open_navicat.models.table_schema import (
    ColumnInfo,
    DatabaseInfo,
    ForeignKeyInfo,
    IndexInfo,
    TableInfo,
)

__all__ = [
    "ConnectionInfo",
    "DatabaseInfo",
    "ColumnInfo",
    "IndexInfo",
    "ForeignKeyInfo",
    "TableInfo",
    "QueryResult",
    "ColumnMeta",
]
