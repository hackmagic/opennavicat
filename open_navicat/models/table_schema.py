"""Data model for database schema objects — tables, views, routines, etc."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ObjectType(Enum):
    DATABASE = auto()
    TABLE = auto()
    VIEW = auto()
    FUNCTION = auto()
    PROCEDURE = auto()
    EVENT = auto()
    TRIGGER = auto()
    INDEX = auto()
    COLUMN = auto()


@dataclass
class DatabaseInfo:
    """Represents a database within a connection."""
    name: str
    charset: str = "utf8mb4"
    collation: str = "utf8mb4_general_ci"
    size_bytes: int = 0
    table_count: int = 0


@dataclass
class ColumnInfo:
    """Column (field) metadata."""
    name: str
    data_type: str  # e.g. VARCHAR, INT, TEXT
    char_max_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    nullable: bool = True
    default: Any = None
    is_primary_key: bool = False
    is_unique: bool = False
    is_auto_increment: bool = False
    comment: str = ""
    character_set: str = ""
    collation: str = ""


@dataclass
class IndexInfo:
    """Index metadata."""
    name: str
    columns: list[str] = field(default_factory=list)
    is_unique: bool = False
    is_primary: bool = False
    index_type: str = "BTREE"  # BTREE, HASH, FULLTEXT, SPATIAL
    comment: str = ""


@dataclass
class ForeignKeyInfo:
    """Foreign key constraint metadata."""
    name: str
    column: str
    ref_table: str
    ref_column: str
    on_delete: str = "RESTRICT"  # RESTRICT, CASCADE, SET NULL, NO ACTION
    on_update: str = "RESTRICT"


@dataclass
class TableInfo:
    """Complete table schema."""
    name: str
    database: str
    engine: str = "InnoDB"
    charset: str = "utf8mb4"
    collation: str = "utf8mb4_general_ci"
    comment: str = ""
    row_count: int = 0
    auto_increment: int | None = None
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    create_time: str = ""
    update_time: str = ""
