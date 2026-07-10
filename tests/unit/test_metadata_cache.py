from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

from open_navicat.models.table_schema import DatabaseInfo
from open_navicat.services.metadata_service import MetadataService


class TestMetadataServiceCache:
    def setup_method(self) -> None:
        self._svc = MetadataService()
        self._svc._cache.clear()

    def test_cache_hits(self) -> None:
        self._svc._cache["cid:list_databases"] = (time.monotonic(), [DatabaseInfo(name="db1")])
        result = self._svc.list_databases("cid")
        assert len(result) == 1
        assert result[0].name == "db1"

    def test_cache_miss_calls_connector(self) -> None:
        with patch.object(self._svc, "_exec", return_value=[DatabaseInfo(name="db1")]):
            result = self._svc.list_databases("cid")
        assert len(result) == 1

    def test_cache_expiry(self) -> None:
        old_ts = time.monotonic() - 120
        self._svc._cache["cid:list_databases"] = (old_ts, [DatabaseInfo(name="stale")])
        with patch.object(self._svc, "_exec", return_value=[DatabaseInfo(name="fresh")]):
            result = self._svc.list_databases("cid")
        assert result[0].name == "fresh"

    def test_invalidate_connection(self) -> None:
        self._svc._cache["cid:list_databases"] = (time.monotonic(), [])
        self._svc._cache["cid:list_tables:db1"] = (time.monotonic(), ["t1"])
        self._svc._cache["other:list_databases"] = (time.monotonic(), [])
        self._svc.invalidate(connection_id="cid")
        assert "cid:list_databases" not in self._svc._cache
        assert "other:list_databases" in self._svc._cache

    def test_invalidate_all(self) -> None:
        self._svc._cache["a"] = (time.monotonic(), 1)
        self._svc._cache["b"] = (time.monotonic(), 2)
        self._svc.invalidate()
        assert len(self._svc._cache) == 0

    def test_no_connector_returns_empty(self) -> None:
        with patch.object(self._svc, "_connector", return_value=None):
            result = self._svc.list_tables("cid", "db")
        assert result == []

    def test_get_table_info_no_connector(self) -> None:
        with patch.object(self._svc, "_connector", return_value=None):
            result = self._svc.get_table_info("cid", "db", "t")
        assert result is None
