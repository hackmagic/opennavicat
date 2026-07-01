"""Shared test fixtures for OpenNavicat tests."""

from __future__ import annotations

import pytest
from open_navicat.models.connection import ConnectionInfo
from open_navicat.models.table_schema import TableInfo, ColumnInfo, IndexInfo


@pytest.fixture
def sample_connection() -> ConnectionInfo:
    return ConnectionInfo(
        name="Test DB",
        host="localhost",
        port=3306,
        user="root",
        password="test",
        database="testdb",
    )


@pytest.fixture
def sample_table() -> TableInfo:
    return TableInfo(
        name="users",
        database="testdb",
        engine="InnoDB",
        charset="utf8mb4",
        columns=[
            ColumnInfo(name="id", data_type="INT", is_primary_key=True, is_auto_increment=True, nullable=False),
            ColumnInfo(name="username", data_type="VARCHAR", length="50", nullable=False),
            ColumnInfo(name="email", data_type="VARCHAR", length="100", nullable=True),
            ColumnInfo(name="created_at", data_type="DATETIME", nullable=True),
        ],
        indexes=[
            IndexInfo(name="PRIMARY", columns=["id"], index_type="PRIMARY"),
            IndexInfo(name="idx_email", columns=["email"], index_type="UNIQUE"),
        ],
    )


@pytest.fixture
def sample_ddl() -> str:
    return (
        "CREATE TABLE `users` ("
        "  `id` INT NOT NULL AUTO_INCREMENT,"
        "  `username` VARCHAR(50) NOT NULL,"
        "  `email` VARCHAR(100),"
        "  `created_at` DATETIME,"
        "  PRIMARY KEY (`id`),"
        "  UNIQUE KEY `idx_email` (`email`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
