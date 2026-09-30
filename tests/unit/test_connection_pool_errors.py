"""Tests for structured errors out of the connection pool."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from open_navicat.dal.connection_pool import ConnectionPool
from open_navicat.dal.ssh_tunnel import SSHTunnel
from open_navicat.errors import (
    ERR_CONNECTION_CLOSED,
    ERR_DRIVER_MISSING,
    ERR_ENGINE_UNSUPPORTED,
    ERR_SSH_TUNNEL_FAILED,
    EngineNotSupportedError,
    SSHTunnelError,
)
from open_navicat.models.connection import ConnectionInfo

POOL = "open_navicat.dal.connection_pool"


class _LastErrorMixin:
    """Mimics :attr:`BaseConnector.last_error` so stubs honor the contract."""

    @property
    def last_error(self):
        return self._last_error


class StubConnector(_LastErrorMixin):
    """Minimal connector that succeeds and records nothing."""

    def __init__(self, info) -> None:
        self._info = info
        self._last_error: BaseException | None = None
        self.disconnected = False

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        self.disconnected = True

    async def is_connected(self) -> bool:
        return True


class FailingConnector(_LastErrorMixin):
    """Connector that swallowed its cause into ``_last_error``."""

    def __init__(self, info, exc: BaseException) -> None:
        self._info = info
        self._last_error = exc
        self.disconnected = False

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        self.disconnected = True


class SilentFailingConnector(_LastErrorMixin):
    """Connector that reports failure without keeping a cause."""

    def __init__(self, info) -> None:
        self._info = info
        self._last_error = None
        self.disconnected = False

    async def connect(self) -> bool:
        return False

    async def disconnect(self) -> None:
        self.disconnected = True


class HangingConnector(_LastErrorMixin):
    def __init__(self, info) -> None:
        self._info = info
        self._last_error = None

    async def connect(self) -> bool:
        await asyncio.sleep(30.0)
        return True

    async def disconnect(self) -> None:
        pass


class RaisingConnector(_LastErrorMixin):
    def __init__(self, info) -> None:
        self._info = info
        self._last_error = None

    async def connect(self) -> bool:
        raise RuntimeError("boom from driver")

    async def disconnect(self) -> None:
        pass


def _info(**overrides) -> ConnectionInfo:
    base = dict(
        id="c1",
        name="test",
        engine="mysql",
        host="127.0.0.1",
        port=3306,
        user="root",
        password="",
        connect_timeout=5,
    )
    base.update(overrides)
    return ConnectionInfo(**base)


@pytest.fixture
def pool() -> ConnectionPool:
    return ConnectionPool()


@pytest.fixture
def stubbed(pool):
    """Replace connector resolution with a stub class; keeps the real registry."""
    with patch(f"{POOL}.get_connector_class", return_value=StubConnector):
        yield pool


class TestEngineResolution:
    def test_unknown_engine_is_a_structured_failure(self, pool) -> None:
        with patch(
            f"{POOL}.get_connector_class",
            side_effect=EngineNotSupportedError("engine 'oracle' is not supported"),
        ):
            assert pool.open(_info(engine="oracle")) is False
            assert pool.last_error is not None
            assert pool.last_error.code == ERR_ENGINE_UNSUPPORTED

    def test_alias_resolves_to_the_real_engine(self, stubbed) -> None:
        assert stubbed.open(_info(engine="pg")) is True
        assert "c1" in stubbed.active_connections

    def test_last_error_is_cleared_on_each_attempt(self, stubbed) -> None:
        with patch(f"{POOL}.get_connector_class", side_effect=EngineNotSupportedError("nope")):
            stubbed.open(_info(engine="oracle"))
        assert stubbed.last_error is not None
        assert stubbed.open(_info(engine="mysql")) is True
        assert stubbed.last_error is None


class TestFailurePaths:
    def test_captured_cause_is_propagated(self, pool) -> None:
        cause = OSError("connection refused")

        class CauseKeepingConnector(_LastErrorMixin):
            def __init__(self, info) -> None:
                self._info = info
                self._last_error = cause
                self.disconnected = False

            async def connect(self) -> bool:
                return False

            async def disconnect(self) -> None:
                self.disconnected = True

        with patch(f"{POOL}.get_connector_class", return_value=CauseKeepingConnector):
            assert pool.open(_info()) is False

        err = pool.last_error
        assert err.code.startswith("ONV-CNN-")
        assert err.stage == "connect"
        assert err.raw is cause
        assert "connection refused" in err.detail

    def test_swallowed_failure_describes_the_attempt(self, pool) -> None:
        with patch(f"{POOL}.get_connector_class", return_value=SilentFailingConnector):
            assert pool.open(_info(host="10.0.0.5", port=5555, user="appuser")) is False
        err = pool.last_error
        assert err.code.startswith("ONV-CNN-")
        assert err.raw is None
        assert "10.0.0.5:5555" in err.detail
        assert "appuser" in err.detail

    def test_password_never_leaks(self, pool) -> None:
        with patch(f"{POOL}.get_connector_class", return_value=SilentFailingConnector):
            pool.open(_info(password="hunter2", ssh_password="hunter2"))
        payload = pool.last_error.to_dict()
        flat = str(payload)
        assert "hunter2" not in flat

    def test_connect_timeout_enforced(self, pool) -> None:
        with patch(f"{POOL}.get_connector_class", return_value=HangingConnector):
            assert pool.open(_info(connect_timeout=1)) is False
        err = pool.last_error
        assert err.code.startswith("ONV-CNN-")
        assert "timed out after 1s" in err.detail

    def test_driver_exception_becomes_connection_failure(self, pool) -> None:
        with patch(f"{POOL}.get_connector_class", return_value=RaisingConnector):
            assert pool.open(_info()) is False
        err = pool.last_error
        assert err.code.startswith("ONV-CNN-")
        assert err.stage == "connect"
        assert err.raw is not None

    def test_port_defaults_from_the_engine_spec(self, stubbed) -> None:
        stubbed.open(_info(engine="redis", port=0))
        assert stubbed.get("c1")._info.port == 6379


class TestSSHTunnel:
    def test_tunnel_failure_is_typed(self, pool) -> None:
        with (
            patch(f"{POOL}.get_connector_class", return_value=StubConnector),
            patch(f"{POOL}.SSHTunnel", SSHTunnel) as _ssht,
            patch.object(SSHTunnel, "connect", return_value=False),
        ):
            assert (
                pool.open(_info(use_ssh=True, ssh_host="bastion", ssh_port=22, ssh_user="ops"))
                is False
            )
        assert pool.last_error.code == ERR_SSH_TUNNEL_FAILED
        assert "bastion" in pool.last_error.detail


class TestLifecycle:
    def test_successful_open_caches_the_connector(self, stubbed) -> None:
        assert stubbed.open(_info()) is True
        assert stubbed.active_connections == ["c1"]
        assert isinstance(stubbed.get("c1"), StubConnector)

    def test_open_does_not_cache_on_failure(self, stubbed) -> None:
        with patch(f"{POOL}.get_connector_class", return_value=SilentFailingConnector):
            assert stubbed.open(_info()) is False
        assert stubbed.active_connections == []
        assert stubbed.get("c1") is None

    def test_close_disconnects_and_clears(self, stubbed) -> None:
        stubbed.open(_info())
        connector = stubbed.get("c1")
        stubbed.close("c1")
        assert connector.disconnected is True
        assert stubbed.active_connections == []

    def test_close_unknown_id_is_a_noop(self, stubbed) -> None:
        stubbed.close("missing")  # must not raise

    def test_close_all(self, stubbed) -> None:
        stubbed.open(_info())
        stubbed.open(_info(id="c2", name="second"))
        stubbed.close_all()
        assert stubbed.active_connections == []

    def test_get_missing_returns_none(self, stubbed) -> None:
        assert stubbed.get("missing") is None
