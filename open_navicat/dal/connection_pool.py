"""Connection pool manager — creates, caches, and reuses connectors.

Engine selection goes through :mod:`open_navicat.drivers.registry` so adding a
driver means one registry entry instead of another branch here.  Every failure
path records a structured :class:`NavicatError` on ``last_error`` while still
returning ``bool``, so existing callers keep working.
"""

from __future__ import annotations

import asyncio
import logging

from open_navicat.dal.ssh_tunnel import SSHTunnel
from open_navicat.drivers.base_connector import BaseConnector
from open_navicat.drivers.registry import get_connector_class, get_spec
from open_navicat.errors import (
    SOURCE_CONNECTION,
    STAGE_CONNECT,
    DatabaseConnectionError,
    NavicatError,
    SSHTunnelError,
    redact,
)
from open_navicat.models.connection import ConnectionInfo

logger = logging.getLogger("opennavicat.pool")

#: Used when a connection profile omits its timeout.
CONNECT_TIMEOUT_FALLBACK = 10

_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


class ConnectionPool:
    """Manages active database connector instances, keyed by connection ID."""

    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}
        self._tunnels: dict[str, SSHTunnel] = {}
        #: Structured error from the most recent failed :meth:`open`, if any.
        self.last_error: NavicatError | None = None

    # ---- failure helper ----

    def _fail(self, err: NavicatError, name: str) -> bool:
        self.last_error = err
        logger.error("ConnectionPool.open(%s) FAILED %s", redact(name), err.render())
        return False

    def _engine_spec(self, info: ConnectionInfo):
        """Resolve the engine; raises :class:`NavicatError` on unknown keys."""
        return get_connector_class(info.engine), get_spec(info.engine)

    # ---- public API ----

    def open(self, info: ConnectionInfo) -> bool:
        """Open a connection, optionally via SSH tunnel, and cache the connector."""
        self.last_error = None
        # `info.name` may be a DSN the user typed (``conn test <dsn>``), so it
        # can carry a password; redact it before it reaches the log.
        logger.info(
            "ConnectionPool.open(%s) id=%s host=%s:%d user=%s db=%s",
            redact(info.name),
            info.id,
            info.host,
            info.port,
            info.user,
            info.database,
        )

        try:
            connector_cls, spec = self._engine_spec(info)
        except NavicatError as err:
            return self._fail(err, info.name)

        host, port = info.host, info.port
        if not port and spec.default_port:
            port = spec.default_port

        # SSH tunnel
        tunnel: SSHTunnel | None = None
        if info.use_ssh:
            tunnel = SSHTunnel(info)
            try:
                if not tunnel.connect():
                    raw = getattr(tunnel, "last_error", None)
                    return self._fail(
                        SSHTunnelError(
                            f"ssh tunnel to {info.ssh_host}:{info.ssh_port} failed",
                            from_exc=raw,
                        ),
                        info.name,
                    )
            except Exception as exc:  # noqa: BLE001 - boundary with sync ssh code
                raw = getattr(tunnel, "last_error", None) or exc
                return self._fail(
                    SSHTunnelError(
                        f"ssh tunnel to {info.ssh_host}:{info.ssh_port} failed",
                        from_exc=raw,
                    ),
                    info.name,
                )
            host, port = "127.0.0.1", tunnel.local_port

        # Adjust connection info for the connector — apply config pool overrides
        from open_navicat.config import config as _cfg

        pool_min = _cfg.get("pool.min_size", info.pool_min)
        pool_max = _cfg.get("pool.max_size", info.pool_max)
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
            pool_min=pool_min,
            pool_max=pool_max,
            use_ssl=info.use_ssl,
            ssl_ca=info.ssl_ca,
            ssl_cert=info.ssl_cert,
            ssl_key=info.ssl_key,
        )

        try:
            connector = connector_cls(conn_info)
        except Exception as exc:  # noqa: BLE001 - a broken connector must not crash the pool
            return self._fail(
                NavicatError.from_exception(exc, source=SOURCE_CONNECTION, stage=STAGE_CONNECT),
                info.name,
            )
        timeout = max(1, int(info.connect_timeout or CONNECT_TIMEOUT_FALLBACK))
        try:
            success = _get_loop().run_until_complete(asyncio.wait_for(connector.connect(), timeout))
        except asyncio.TimeoutError:
            return self._fail(
                DatabaseConnectionError(
                    f"connection to {spec.display_name} at {host}:{port} "
                    f"timed out after {timeout}s",
                    source=SOURCE_CONNECTION,
                    stage=STAGE_CONNECT,
                ),
                info.name,
            )
        except NavicatError as err:
            return self._fail(err, info.name)
        except Exception as exc:  # noqa: BLE001 - connector boundary
            return self._fail(
                NavicatError.from_exception(exc, source=SOURCE_CONNECTION, stage=STAGE_CONNECT),
                info.name,
            )

        if success:
            self._connectors[info.id] = connector
            if tunnel:
                self._tunnels[info.id] = tunnel
            logger.info(
                "ConnectionPool.open(%s) SUCCESS — connectors cache has %d entry(s), keys=%s",
                redact(info.name),
                len(self._connectors),
                list(self._connectors.keys()),
            )
            return True

        # Connectors report failure as ``False``; surface the captured cause if
        # they kept one, otherwise describe what was attempted.
        raw = getattr(connector, "last_error", None)
        if isinstance(raw, NavicatError):
            err: NavicatError = raw
        elif raw is not None:
            err = NavicatError.from_exception(raw, source=SOURCE_CONNECTION, stage=STAGE_CONNECT)
        else:
            err = DatabaseConnectionError(
                f"could not connect to {spec.display_name} at {host}:{port} as {info.user}",
                source=SOURCE_CONNECTION,
                stage=STAGE_CONNECT,
            )
        return self._fail(err, info.name)

    def get(self, connection_id: str) -> BaseConnector | None:
        connector = self._connectors.get(connection_id)
        logger.debug(
            "ConnectionPool.get(%s) -> %s, all keys=%s",
            connection_id,
            "FOUND" if connector else "NOT FOUND",
            list(self._connectors.keys()),
        )
        return connector

    def close(self, connection_id: str) -> None:
        connector = self._connectors.pop(connection_id, None)
        if connector:
            try:
                _get_loop().run_until_complete(connector.disconnect())
            except Exception as exc:  # noqa: BLE001 - never block teardown
                logger.warning("disconnect(%s) raised: %s", connection_id, exc)
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
