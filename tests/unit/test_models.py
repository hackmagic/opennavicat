"""Unit tests for models."""

from __future__ import annotations

from open_navicat.models.connection import ConnectionInfo
from open_navicat.models.table_schema import (
    TableInfo, ColumnInfo, IndexInfo, ForeignKeyInfo, DatabaseInfo,
)
from open_navicat.models.query_result import QueryResult, ColumnMeta


class TestConnectionInfo:
    def test_display_name(self) -> None:
        info = ConnectionInfo(name="My Server", host="10.0.0.1")
        assert info.display_name == "My Server"

    def test_display_name_fallback(self) -> None:
        info = ConnectionInfo(host="10.0.0.1", port=3306, user="admin")
        assert "admin@10.0.0.1:3306" in info.dsn

    def test_defaults(self) -> None:
        info = ConnectionInfo()
        assert info.host == "127.0.0.1"
        assert info.port == 3306
        assert info.charset == "utf8mb4"
        assert info.use_ssh is False
        assert info.use_ssl is False
        assert info.pool_min == 1
        assert info.pool_max == 10

    def test_ssh_tunnel(self) -> None:
        info = ConnectionInfo(
            use_ssh=True,
            ssh_host="bastion.example.com",
            ssh_port=2222,
            ssh_user="jump",
        )
        assert info.use_ssh is True
        assert info.ssh_host == "bastion.example.com"
        assert info.ssh_port == 2222


class TestTableSchema:
    def test_table_info_defaults(self) -> None:
        table = TableInfo(name="test", database="db")
        assert table.engine == "InnoDB"
        assert table.charset == "utf8mb4"
        assert len(table.columns) == 0
        assert len(table.indexes) == 0

    def test_column_info_minimal(self) -> None:
        col = ColumnInfo(name="id", data_type="INT")
        assert col.nullable is True
        assert col.is_primary_key is False

    def test_database_info(self) -> None:
        db = DatabaseInfo(name="mydb", charset="utf8", table_count=15)
        assert db.name == "mydb"
        assert db.table_count == 15


class TestQueryResult:
    def test_select_result(self) -> None:
        result = QueryResult(
            columns=[ColumnMeta(name="id", data_type="INT")],
            rows=[[1]],
            row_count=1,
        )
        assert result.is_select is True
        assert result.success is True

    def test_dml_result(self) -> None:
        result = QueryResult(success=True, affected_rows=5, insert_id=100)
        assert result.is_select is False
        assert result.affected_rows == 5
        assert result.insert_id == 100

    def test_error_result(self) -> None:
        result = QueryResult(success=False, error_message="Table not found")
        assert result.success is False
        assert "Table not found" in result.error_message
