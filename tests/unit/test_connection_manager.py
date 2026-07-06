"""Unit tests for ConnectionManager."""
from __future__ import annotations

from unittest.mock import PropertyMock, patch

from open_navicat.models.connection import ConnectionInfo
from open_navicat.services.connection_manager import ConnectionManager, connection_manager


class TestConnectionManager:
    def setup_method(self) -> None:
        self._mgr = ConnectionManager()

    def test_singleton(self) -> None:
        assert connection_manager is not None

    def test_list_saved(self) -> None:
        with patch("open_navicat.services.connection_manager.local_db") as mock_db:
            mock_db.list_connections.return_value = []
            assert self._mgr.list_saved() == []

        with patch("open_navicat.services.connection_manager.local_db") as mock_db:
            expected = [ConnectionInfo(name="test", host="localhost")]
            mock_db.list_connections.return_value = expected
            assert self._mgr.list_saved() == expected

    def test_get_saved(self) -> None:
        with patch("open_navicat.services.connection_manager.local_db") as mock_db:
            conn = ConnectionInfo(name="test", host="localhost")
            mock_db.get_connection.return_value = conn
            assert self._mgr.get_saved("abc") == conn
            mock_db.get_connection.assert_called_once_with("abc")

    def test_get_saved_none(self) -> None:
        with patch("open_navicat.services.connection_manager.local_db") as mock_db:
            mock_db.get_connection.return_value = None
            assert self._mgr.get_saved("nonexistent") is None

    def test_active_ids(self) -> None:
        with patch("open_navicat.services.connection_manager.connection_pool") as mock_pool:
            mock_pool.active_connections = ["conn1"]
            assert self._mgr.active_ids == ["conn1"]

    def test_connect(self) -> None:
        with (
            patch("open_navicat.services.connection_manager.connection_pool") as mock_pool,
            patch("open_navicat.services.connection_manager.local_db") as mock_db,
        ):
            mock_pool.open.return_value = True
            info = ConnectionInfo(host="localhost")
            assert self._mgr.connect(info) is True
            mock_pool.open.assert_called_once_with(info)
            mock_db.save_connection.assert_called_once_with(info)

    def test_disconnect(self) -> None:
        with patch("open_navicat.services.connection_manager.connection_pool") as mock_pool:
            self._mgr.disconnect("c1")
            mock_pool.close.assert_called_once_with("c1")

    def test_delete_saved(self) -> None:
        with (
            patch("open_navicat.services.connection_manager.connection_pool") as mock_pool,
            patch("open_navicat.services.connection_manager.local_db") as mock_db,
        ):
            self._mgr.delete_saved("c1")
            mock_pool.close.assert_called_once_with("c1")
            mock_db.delete_connection.assert_called_once_with("c1")

    def test_get_connector(self) -> None:
        with patch("open_navicat.services.connection_manager.connection_pool") as mock_pool:
            self._mgr.get_connector("c1")
            mock_pool.get.assert_called_once_with("c1")
