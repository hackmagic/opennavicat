"""Data model for SQL query execution results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ColumnMeta:
    """Metadata for a single result column."""
    name: str
    data_type: str  # e.g. VARCHAR, INT
    table_name: str = ""
    nullable: bool = True


@dataclass
class QueryResult:
    """Represents the result of executing a SQL query."""

    success: bool = True
    error_message: str = ""

    # For SELECT / SHOW / DESCRIBE
    columns: list[ColumnMeta] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    affected_rows: int = 0
    execution_time_ms: float = 0.0

    # For INSERT/UPDATE/DELETE
    insert_id: int | None = None

    # For EXPLAIN
    plan: str = ""
    plan_format: str = "text"  # text, json, visual

    # Warnings
    warnings: list[str] = field(default_factory=list)

    @property
    def is_select(self) -> bool:
        return len(self.columns) > 0
