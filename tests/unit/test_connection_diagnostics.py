"""Regression tests for issue #2 — "Could not connect to the server." with no cause.

The reporter saw a warning with no detail while the real reason (the driver was
absent from the frozen build, or ``asyncpg`` refused the connection) was thrown
away.  These tests pin the diagnostic chain: a missing driver is a typed
``DriverNotFoundError`` carrying an install hint, a failing connector keeps its
cause in ``last_error``, and the pool turns that into a structured
``NavicatError`` instead of a generic message — including when the connector
itself cannot even be constructed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from open_navicat.dal.connection_pool import ConnectionPool
from open_navicat.drivers import registry
from open_navicat.drivers.base_connector import BaseConnector
from open_navicat.drivers.postgresql_connector import PostgreSQLConnector
from open_navicat.errors import ERR_DRIVER_MISSING, DriverNotFoundError
from open_navicat.models.connection import ConnectionInfo

POOL = "open_navicat.dal.connection_pool"


def _info(**overrides) -> ConnectionInfo:
    base = dict(
        id="p1",
        name="pg",
        engine="postgresql",
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password="secret",
        connect_timeout=5,
    )
    base.update(overrides)
    return ConnectionInfo(**base)


class TestConnectorContract:
    @pytest.mark.parametrize("engine", sorted(registry.DRIVER_REGISTRY))
    def test_constructor_initializes_last_error(self, engine: str) -> None:
        # AGENTS.md: subclasses must call super().__init__(); skipping it made
        # the failure path itself raise AttributeError and mask the cause.
        try:
            cls = registry.get_connector_class(engine)
        except Exception:  # noqa: BLE001 - this machine may lack the driver
            pytest.skip(f"driver for {engine} is not installed here")
        connector = cls(_info(engine=engine, database="probe.db"))
        assert connector.last_error is None

    def test_postgres_connector_is_a_base_connector(self) -> None:
        assert isinstance(PostgreSQLConnector(_info()), BaseConnector)

    async def test_postgres_connector_without_driver_raises_typed_error(self) -> None:
        # A frozen build that shipped without asyncpg used to answer with a bare
        # ImportError (v0.8.0) or False (HEAD); it must name the missing extra.
        connector = PostgreSQLConnector(_info())
        with patch("open_navicat.drivers.postgresql_connector.asyncpg", None):
            with pytest.raises(DriverNotFoundError) as caught:
                await connector.connect()
        assert caught.value.code == ERR_DRIVER_MISSING
        assert "asyncpg" in caught.value.detail

    async def test_postgres_connect_failure_keeps_the_cause(self) -> None:
        connector = PostgreSQLConnector(_info())

        async def _boom(**_kwargs):
            raise OSError("connection refused")

        with patch("open_navicat.drivers.postgresql_connector.asyncpg") as fake:
            fake.create_pool = _boom
            assert await connector.connect() is False
        assert isinstance(connector.last_error, OSError)
        assert "connection refused" in str(connector.last_error)


class TestPoolDiagnostics:
    def test_missing_driver_reaches_the_pool_as_a_typed_error(self) -> None:
        pool = ConnectionPool()
        with patch(f"{POOL}.get_connector_class", return_value=PostgreSQLConnector), patch(
            "open_navicat.drivers.postgresql_connector.asyncpg", None
        ):
            assert pool.open(_info()) is False
        err = pool.last_error
        assert err is not None
        assert err.code == ERR_DRIVER_MISSING
        assert "asyncpg" in err.detail

    def test_broken_constructor_does_not_crash_the_pool(self) -> None:
        class Exploding:
            def __init__(self, info) -> None:
                raise RuntimeError("driver exploded during setup")

        pool = ConnectionPool()
        with patch(f"{POOL}.get_connector_class", return_value=Exploding):
            assert pool.open(_info()) is False
        assert pool.last_error is not None
        assert pool.last_error.stage == "connect"
        assert "driver exploded" in pool.last_error.detail

    def test_silent_failure_still_names_the_endpoint(self) -> None:
        class Silent:
            def __init__(self, info) -> None:
                self._last_error = None

            @property
            def last_error(self):
                return self._last_error

            async def connect(self) -> bool:
                return False

        pool = ConnectionPool()
        with patch(f"{POOL}.get_connector_class", return_value=Silent):
            assert pool.open(_info()) is False
        err = pool.last_error
        assert err is not None
        assert "127.0.0.1:5432" in err.detail
        assert "postgres" in err.detail
