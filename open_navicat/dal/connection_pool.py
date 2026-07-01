"""Connection pool manager — creates, caches, and reuses connectors."""

from __future__ import annotations

import asyncio
import logging

from open_navicat.dal.base_connector import BaseConnector
from open_navicat.dal.ssh_tunnel import SSHTunnel
from open_navicat.models.connection import ConnectionInfo

logger = logging.getLogger("opennavicat.pool")

_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)


class ConnectionPool:
    """Manages active database connector instances, keyed by connection ID."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}
        self._tunnels: dict[str, SSHTunnel] = {}

    def open(self, info: ConnectionInfo) -> bool:
        """Open a connection, optionally via SSH tunnel, and cache the connector."""
        logger.info("ConnectionPool.open(%s) id=%s host=%s:%d user=%s db=%s",
                     info.name, info.id, info.host, info.port, info.user, info.database)
        # SSH tunnel
        tunnel: SSHTunnel | None = None
        host = info.host
        port = info.port

        if info.use_ssh:
            tunnel = SSHTunnel(info)
            if not tunnel.connect():
                logger.warning("SSH tunnel connection failed for %s", info.name)
                return False
            host = "127.0.0.1"
            port = tunnel.local_port

        # Adjust connection info for the connector
        conn_info = ConnectionInfo(
            id=info.id,
            name=info.name,
            engine=info.engine,
            host=host,
            port=port,
            user=info.user,
            password=info.password,
            database=info.database,
            charset=info.charset,
            connect_timeout=info.connect_timeout,
            pool_min=info.pool_min,
            pool_max=info.pool_max,
            use_ssl=info.use_ssl,
            ssl_ca=info.ssl_ca,
            ssl_cert=info.ssl_cert,
            ssl_key=info.ssl_key,
        )

        if info.engine == "postgresql":
            from open_navicat.dal.postgresql_connector import PostgreSQLConnector
            connector_cls = PostgreSQLConnector
        elif info.engine == "sqlite":
            from open_navicat.dal.sqlite_connector import SQLiteConnector
            connector_cls = SQLiteConnector
        else:
            from open_navicat.dal.mysql_connector import MySQLConnector
            connector_cls = MySQLConnector
        connector = connector_cls(conn_info)
        try:
            success = _loop.run_until_complete(connector.connect())
        except Exception as e:
            logger.error("ConnectionPool.open(%s) EXCEPTION: %s", info.name, e, exc_info=True)
            return False
        if success:
            self._connectors[info.id] = connector
            if tunnel:
                self._tunnels[info.id] = tunnel
            logger.info("ConnectionPool.open(%s) SUCCESS — connectors cache has %d entry(s), keys=%s",
                         info.name, len(self._connectors), list(self._connectors.keys()))
        else:
            logger.warning("ConnectionPool.open(%s) FAILED — connect() returned False", info.name)
        return success

    def get(self, connection_id: str) -> BaseConnector | None:
        connector = self._connectors.get(connection_id)
        logger.debug("ConnectionPool.get(%s) → %s, all keys=%s",
                     connection_id, "FOUND" if connector else "NOT FOUND",
                     list(self._connectors.keys()))
        return connector

    def close(self, connection_id: str) -> None:
        connector = self._connectors.pop(connection_id, None)
        if connector:
            _loop.run_until_complete(connector.disconnect())
        tunnel = self._tunnels.pop(connection_id, None)
        if tunnel:
            tunnel.close()

    def close_all(self) -> None:
        for cid in list(self._connectors.keys()):
            self.close(cid)

    @property
    def active_connections(self) -> list[str]:
        return list(self._connectors.keys())


# Module-level singleton
connection_pool = ConnectionPool()
