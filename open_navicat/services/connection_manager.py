"""Connection management service — orchestrates opening/closing connections."""

from __future__ import annotations

from typing import Optional

from open_navicat.dal.connection_pool import connection_pool
from open_navicat.dal.local_config import local_db
from open_navicat.models.connection import ConnectionInfo


class ConnectionManager:
    """High-level API for managing database connections."""

    def connect(self, info: ConnectionInfo, *, persist: bool = True) -> bool:
        """Open a connection and, unless ``persist`` is false, save it locally.

        Ad-hoc targets (e.g. ``conn test <dsn>``) must pass ``persist=False`` so
        a throwaway connection string never ends up in the user's config.
        """
        success = connection_pool.open(info)
        if success and persist:
            local_db.save_connection(info)
        return success

    @property
    def last_error(self):
        """Structured :class:`NavicatError` from the most recent failed connect."""
        return connection_pool.last_error

    def disconnect(self, connection_id: str) -> None:
        """Close and remove a connection."""
        connection_pool.close(connection_id)

    def list_saved(self) -> list[ConnectionInfo]:
        """Return all saved connection profiles."""
        return local_db.list_connections()

    def get_saved(self, connection_id: str) -> Optional[ConnectionInfo]:
        return local_db.get_connection(connection_id)

    def delete_saved(self, connection_id: str) -> None:
        self.disconnect(connection_id)
        local_db.delete_connection(connection_id)

    def get_connector(self, connection_id: str):
        return connection_pool.get(connection_id)

    @property
    def active_ids(self) -> list[str]:
        return connection_pool.active_connections


# Module-level singleton
connection_manager = ConnectionManager()
