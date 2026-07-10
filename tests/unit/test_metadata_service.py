"""Unit tests for MetadataService."""
from __future__ import annotations

from unittest.mock import patch

from open_navicat.models.table_schema import DatabaseInfo
from open_navicat.services.metadata_service import MetadataService, metadata_service


class TestMetadataService:
    def setup_method(self) -> None:
        self._svc = MetadataService()

    def test_singleton(self) -> None:
        assert metadata_service is not None

    def test_list_databases(self) -> None:
        dbs = [DatabaseInfo(name="testdb")]
        with (
            patch("open_navicat.services.metadata_service.connection_pool") as mock_pool,
            patch("open_navicat.services.metadata_service._pool_loop") as mock_loop,
        ):
            mock_pool.get.return_value = mock_pool
            mock_loop.return_value.run_until_complete.return_value = dbs
            result = self._svc.list_databases("c1")
            assert result == dbs

    def test_list_databases_no_connector(self) -> None:
        with patch("open_navicat.services.metadata_service.connection_pool") as mock_pool:
            mock_pool.get.return_value = None
            assert self._svc.list_databases("c1") == []

    def test_list_tables(self) -> None:
        tables = ["t1", "t2"]
        with (
            patch("open_navicat.services.metadata_service.connection_pool") as mock_pool,
            patch("open_navicat.services.metadata_service._pool_loop") as mock_loop,
        ):
            mock_pool.get.return_value = mock_pool
            mock_loop.return_value.run_until_complete.return_value = tables
            result = self._svc.list_tables("c1", "db")
            assert result == tables

    def test_get_table_schema(self) -> None:
        from open_navicat.models.table_schema import TableInfo

        schema = TableInfo(name="t", database="db", columns=[])
        with (
            patch("open_navicat.services.metadata_service.connection_pool") as mock_pool,
            patch("open_navicat.services.metadata_service._pool_loop") as mock_loop,
        ):
            mock_pool.get.return_value = mock_pool
            mock_loop.return_value.run_until_complete.return_value = schema
            result = self._svc.get_table_info("c1", "db", "t")
            assert result == schema

    def test_get_table_schema_no_connector(self) -> None:
        with patch("open_navicat.services.metadata_service.connection_pool") as mock_pool:
            mock_pool.get.return_value = None
            assert self._svc.get_table_info("c1", "db", "t") is None

    def test_list_views(self) -> None:
        with (
            patch("open_navicat.services.metadata_service.connection_pool") as mock_pool,
            patch("open_navicat.services.metadata_service._pool_loop") as mock_loop,
        ):
            mock_pool.get.return_value = mock_pool
            mock_loop.return_value.run_until_complete.return_value = ["v1"]
            assert self._svc.list_views("c1", "db") == ["v1"]

    def test_list_routines(self) -> None:
        with (
            patch("open_navicat.services.metadata_service.connection_pool") as mock_pool,
            patch("open_navicat.services.metadata_service._pool_loop") as mock_loop,
        ):
            mock_pool.get.return_value = mock_pool
            mock_loop.return_value.run_until_complete.return_value = [("sp1", "PROCEDURE")]
            assert self._svc.list_routines("c1", "db") == [("sp1", "PROCEDURE")]

    def test_invalidate(self) -> None:
        svc = MetadataService()
        svc._cache["c1:list_databases"] = (99999.0, [])
        svc.invalidate("c1")
        assert svc._cache == {}

    def test_invalidate_all(self) -> None:
        svc = MetadataService()
        svc._cache["x"] = (99999.0, [])
        svc.invalidate()
        assert svc._cache == {}
