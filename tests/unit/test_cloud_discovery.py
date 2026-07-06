"""Unit tests for CloudDiscoveryService."""
from __future__ import annotations

from unittest.mock import patch

from open_navicat.services.cloud_discovery import (
    CLOUD_PATTERNS,
    CloudDBInstance,
    CloudDiscoveryService,
    cloud_discovery,
)


class TestCloudDiscovery:
    def setup_method(self) -> None:
        self._svc = CloudDiscoveryService()

    def test_singleton(self) -> None:
        assert cloud_discovery is not None

    def test_discover_aws_returns_empty(self) -> None:
        assert self._svc.discover_aws() == []

    def test_discover_all_no_connections(self) -> None:
        with patch("open_navicat.dal.local_config.local_db") as mock_db:
            mock_db.list_connections.return_value = []
            result = self._svc.discover_all()
            assert result == []

    def test_discover_all_matches_aws_rds(self) -> None:
        from open_navicat.models.connection import ConnectionInfo

        conn = ConnectionInfo(
            name="prod",
            host="mydb.cluster-xxx.rds.amazonaws.com",
            engine="mysql",
            port=3306,
        )
        with patch("open_navicat.dal.local_config.local_db") as mock_db:
            mock_db.list_connections.return_value = [conn]
            result = self._svc.discover_all()
            assert len(result) >= 1
            assert result[0].provider == "AWS"

    def test_discover_all_matches_google_cloud(self) -> None:
        from open_navicat.models.connection import ConnectionInfo

        conn = ConnectionInfo(
            name="gcp-db",
            host="proj:region:inst.cloudsql.googleapis.com",
            engine="postgresql",
            port=5432,
        )
        with patch("open_navicat.dal.local_config.local_db") as mock_db:
            mock_db.list_connections.return_value = [conn]
            result = self._svc.discover_all()
            assert any(i.provider == "Google Cloud" for i in result)

    def test_discover_all_matches_azure(self) -> None:
        from open_navicat.models.connection import ConnectionInfo

        conn = ConnectionInfo(name="az", host="myserver.database.windows.net")
        with patch("open_navicat.dal.local_config.local_db") as mock_db:
            mock_db.list_connections.return_value = [conn]
            result = self._svc.discover_all()
            assert any(i.provider == "Azure" for i in result)

    def test_discover_all_unmatched_host(self) -> None:
        from open_navicat.models.connection import ConnectionInfo

        conn = ConnectionInfo(name="local", host="127.0.0.1")
        with patch("open_navicat.dal.local_config.local_db") as mock_db:
            mock_db.list_connections.return_value = [conn]
            result = self._svc.discover_all()
            assert result == []

    def test_cloud_patterns_present(self) -> None:
        assert len(CLOUD_PATTERNS) >= 9
        providers = {p for p, _ in CLOUD_PATTERNS}
        assert "AWS" in providers
        assert "Azure" in providers
        assert "Google Cloud" in providers
