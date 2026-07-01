"""Unit tests for DataSyncEngine."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from open_navicat.models.table_schema import ColumnInfo
from open_navicat.services.data_sync_engine import DataCompareResult, DataSyncEngine, RowDiff


def _mock_connector(rows, columns_meta, pk_cols=None):
    """Create a mock connector whose `execute` returns synchronously (tests wrap in pool_loop)."""
    conn = MagicMock()
    col_result = MagicMock()
    col_result.rows = columns_meta
    col_result.success = True
    pk_result = MagicMock()
    pk_result.rows = pk_cols or [["id"]]
    pk_result.success = True
    data_result = MagicMock()
    data_result.rows = rows
    data_result.success = True
    data_result.is_select = True

    def execute_side_effect(sql, params=None):
        if "information_schema.COLUMNS" in sql:
            return col_result
        if "KEY_COLUMN_USAGE" in sql:
            return pk_result
        return data_result

    conn.execute = MagicMock(side_effect=execute_side_effect)
    return conn


class TestDataSyncEngine:
    def test_identical_tables(self):
        engine = DataSyncEngine()
        cols = [
            ["id", "INT", "NO", None, None, None, None, "", ""],
        ]
        rows = [(1,), (2,), (3,)]
        with patch("open_navicat.services.data_sync_engine.connection_pool") as pool:
            pool.get = MagicMock(side_effect=[
                _mock_connector(rows, cols),
                _mock_connector(rows, cols),
            ])
            with patch("open_navicat.services.data_sync_engine.pool_loop") as loop:
                loop.run_until_complete = MagicMock(side_effect=lambda c: c)
                result = engine.compare_tables("src", "db", "t", "tgt", "db", "t")
        assert result.source_rows == 3
        assert result.target_rows == 3
        assert result.total_diffs == 0

    def test_inserts_detected(self):
        engine = DataSyncEngine()
        cols = [
            ["id", "INT", "NO", None, None, None, None, "", ""],
            ["name", "VARCHAR", "YES", 255, None, None, None, "", ""],
        ]
        src_rows = [(1, "a"), (2, "b"), (3, "c")]
        tgt_rows = [(1, "a")]
        with patch("open_navicat.services.data_sync_engine.connection_pool") as pool:
            pool.get = MagicMock(side_effect=[
                _mock_connector(src_rows, cols),
                _mock_connector(tgt_rows, cols),
            ])
            with patch("open_navicat.services.data_sync_engine.pool_loop") as loop:
                loop.run_until_complete = MagicMock(side_effect=lambda c: c)
                result = engine.compare_tables("src", "db", "t", "tgt", "db", "t")
        assert len(result.inserts) == 2
        assert len(result.deletes) == 0
        assert len(result.updates) == 0
        assert result.inserts[0].pk_values["id"] == 2
        assert result.inserts[1].pk_values["id"] == 3

    def test_updates_detected(self):
        engine = DataSyncEngine()
        cols = [
            ["id", "INT", "NO", None, None, None, None, "", ""],
            ["name", "VARCHAR", "YES", 255, None, None, None, "", ""],
        ]
        src_rows = [(1, "new_name"), (2, "b")]
        tgt_rows = [(1, "old_name"), (2, "b")]
        with patch("open_navicat.services.data_sync_engine.connection_pool") as pool:
            pool.get = MagicMock(side_effect=[
                _mock_connector(src_rows, cols),
                _mock_connector(tgt_rows, cols),
            ])
            with patch("open_navicat.services.data_sync_engine.pool_loop") as loop:
                loop.run_until_complete = MagicMock(side_effect=lambda c: c)
                result = engine.compare_tables("src", "db", "t", "tgt", "db", "t")
        assert len(result.updates) == 1
        assert result.updates[0].set_values["name"] == "new_name"
        assert result.updates[0].old_values["name"] == "old_name"

    def test_deletes_detected(self):
        engine = DataSyncEngine()
        cols = [["id", "INT", "NO", None, None, None, None, "", ""]]
        src_rows = [(1,)]
        tgt_rows = [(1,), (2,), (3,)]
        with patch("open_navicat.services.data_sync_engine.connection_pool") as pool:
            pool.get = MagicMock(side_effect=[
                _mock_connector(src_rows, cols),
                _mock_connector(tgt_rows, cols),
            ])
            with patch("open_navicat.services.data_sync_engine.pool_loop") as loop:
                loop.run_until_complete = MagicMock(side_effect=lambda c: c)
                result = engine.compare_tables("src", "db", "t", "tgt", "db", "t")
        assert len(result.deletes) == 2

    def test_generate_sync_script(self):
        result = DataCompareResult(
            columns=[ColumnInfo(name="id", data_type="INT"),
                     ColumnInfo(name="name", data_type="VARCHAR")],
            pk_columns=["id"],
            inserts=[RowDiff(action="insert", pk_values={"id": 3},
                             set_values={"id": 3, "name": "c"})],
            updates=[RowDiff(action="update", pk_values={"id": 1},
                             set_values={"name": "new"}, old_values={"name": "old"})],
            deletes=[RowDiff(action="delete", pk_values={"id": 2})],
            target_table="t",
        )
        engine = DataSyncEngine()
        script = engine.generate_sync_script(result)
        assert "INSERT INTO" in script
        assert "UPDATE" in script
        assert "DELETE FROM" in script
        assert "'c'" in script
        assert "'new'" in script
