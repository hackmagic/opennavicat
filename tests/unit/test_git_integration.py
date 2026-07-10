"""Tests for git/schema integration features."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from open_navicat.models.table_schema import ColumnInfo, IndexInfo, TableInfo

runner = CliRunner()


class TestSchemaSnapshot:
    def test_snapshot_generates_ddl(self) -> None:
        from open_navicat.cli.schema_cmd import schema_app
        info = TableInfo(name="users", database="testdb")
        info.columns = [
            ColumnInfo(name="id", data_type="INT", nullable=False, is_primary_key=True, is_auto_increment=True),
            ColumnInfo(name="name", data_type="VARCHAR(255)", nullable=False),
        ]
        info.indexes = [
            IndexInfo(name="idx_name", columns=["name"], is_primary=False, is_unique=True),
        ]

        mock_meta = MagicMock()
        mock_meta.list_tables.return_value = ["users"]
        mock_meta.get_table_info.return_value = info

        with patch("open_navicat.cli.schema_cmd.metadata_service", mock_meta):
            with patch("open_navicat.cli.schema_cmd._get_active_conn", return_value="c1"):
                result = runner.invoke(schema_app, ["snapshot", "testdb"])
                assert result.exit_code == 0
                assert "CREATE TABLE" in result.output

    def test_snapshot_writes_to_file(self, tmp_path) -> None:
        from open_navicat.cli.schema_cmd import schema_app
        info = TableInfo(name="t", database="d")
        info.columns = [ColumnInfo(name="id", data_type="INT")]

        mock_meta = MagicMock()
        mock_meta.list_tables.return_value = ["t"]
        mock_meta.get_table_info.return_value = info

        out = tmp_path / "schema.sql"
        with patch("open_navicat.cli.schema_cmd.metadata_service", mock_meta):
            with patch("open_navicat.cli.schema_cmd._get_active_conn", return_value="c1"):
                result = runner.invoke(schema_app, ["snapshot", "d", "--output", str(out)])
                assert result.exit_code == 0
                assert out.exists()
                content = out.read_text()
                assert "CREATE TABLE" in content

    def test_snapshot_no_tables(self) -> None:
        from open_navicat.cli.schema_cmd import schema_app
        mock_meta = MagicMock()
        mock_meta.list_tables.return_value = []

        with patch("open_navicat.cli.schema_cmd.metadata_service", mock_meta):
            with patch("open_navicat.cli.schema_cmd._get_active_conn", return_value="c1"):
                result = runner.invoke(schema_app, ["snapshot", "testdb"])
                assert "No tables found" in result.output
