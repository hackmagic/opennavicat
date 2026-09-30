"""Tests for query budgets, cancellation and cache invalidation.

These cover the Phase 2 gap: the old ``QueryEngine.execute`` had no time
budget, no way to cancel a running query, and never invalidated the cache after
a write.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import patch

import pytest

from open_navicat.errors import (
    ERR_QUERY_CANCELED,
    ERR_QUERY_FAILED,
    ERR_QUERY_TIMEOUT,
    ConnectionClosedError,
    QueryExecutionError,
)
from open_navicat.models.query_result import QueryResult
from open_navicat.services.query_engine import (
    CancelToken,
    QueryEngine,
    is_write,
    query_engine,
)

QE = "open_navicat.services.query_engine"


class SlowConnector:
    """Connector whose ``execute`` sleeps for ``delay`` seconds."""

    def __init__(self, delay: float = 5.0) -> None:
        self._delay = delay
        self.calls: list[str] = []

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        self.calls.append(sql)
        await asyncio.sleep(self._delay)
        return QueryResult(success=True, columns=[], rows=[[1]])


class RaisingConnector:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def execute(self, sql: str, params: tuple | None = None) -> QueryResult:
        raise self._exc


def fake_pool(connector):
    """A stub pool whose ``get`` always returns ``connector``."""
    return type("FakePool", (), {"get": staticmethod(lambda cid: connector)})()


def fake_pool_none():
    return type("FakePool", (), {"get": staticmethod(lambda cid: None)})()


@pytest.fixture
def engine() -> QueryEngine:
    return QueryEngine()


@pytest.fixture
def loop():
    lp = asyncio.new_event_loop()
    yield lp
    lp.close()


@pytest.fixture
def stubbed(engine, loop):
    """Patch pool + loop + cache the way the rest of the suite does."""
    with (
        patch(f"{QE}.connection_pool") as pool,
        patch(f"{QE}._pool_loop", lambda: loop),
        patch(f"{QE}.query_cache") as cache,
    ):
        pool.get.return_value = SlowConnector(0.01)
        cache.get.return_value = None
        yield cache


class TestIsWrite:
    def test_select_is_not_a_write(self) -> None:
        assert is_write("select 1") is False
        assert is_write("WITH t AS (SELECT 1) SELECT * FROM t") is False

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO t VALUES (1)",
            "update t set a = 1",
            "DELETE FROM t",
            "DROP TABLE t",
            "ALTER TABLE t ADD COLUMN x int",
            "CALL proc()",
        ],
    )
    def test_mutation_verbs_are_writes(self, sql: str) -> None:
        assert is_write(sql) is True


class TestTimeout:
    def test_timeout_returns_structured_failure(self, engine, loop) -> None:
        with (
            patch(f"{QE}.connection_pool", fake_pool(SlowConnector(5.0))),
            patch(f"{QE}._pool_loop", lambda: loop),
            patch(f"{QE}.query_cache") as cache,
        ):
            cache.get.return_value = None
            result = engine.execute("c1", "SELECT SLEEP(5)", timeout=0.05)

        assert result.success is False
        assert "ONV-QRY-002" in result.error_message
        assert engine.last_error is not None
        assert engine.last_error.code == ERR_QUERY_TIMEOUT
        assert engine.last_error.retryable is True

    def test_no_budget_completes_normally(self, engine, loop) -> None:
        with (
            patch(f"{QE}.connection_pool", fake_pool(SlowConnector(0.01))),
            patch(f"{QE}._pool_loop", lambda: loop),
            patch(f"{QE}.query_cache") as cache,
        ):
            cache.get.return_value = None
            result = engine.execute("c1", "SELECT 1")

        assert result.success is True
        assert engine.last_error is None


class TestCancellation:
    def test_cancel_token_stops_the_query(self, engine, loop) -> None:
        token = CancelToken()
        threading.Timer(0.1, token.cancel).start()

        with (
            patch(f"{QE}.connection_pool", fake_pool(SlowConnector(5.0))),
            patch(f"{QE}._pool_loop", lambda: loop),
            patch(f"{QE}.query_cache") as cache,
        ):
            cache.get.return_value = None
            result = engine.execute("c1", "SELECT SLEEP(5)", cancel_token=token, timeout=5.0)

        assert result.success is False
        assert "ONV-QRY-003" in result.error_message
        assert engine.last_error.code == ERR_QUERY_CANCELED
        assert engine.last_error.recoverable is True
        assert engine.last_error.retryable is True

    def test_uncancelled_token_does_not_interrupt(self, stubbed, engine) -> None:
        token = CancelToken()
        result = engine.execute("c1", "SELECT 1", cancel_token=token)
        assert result.success is True
        assert token.is_canceled() is False

    def test_background_submit_and_result(self, stubbed, engine) -> None:
        engine.execute("c1", "SELECT 1")  # warm the loop
        qid = engine.submit("c1", "SELECT 42")
        assert engine.running_queries[qid] is True
        result = engine.result(qid)
        assert result.success is True
        assert engine.running_queries == {}

    def test_cancel_pending_query(self, stubbed, engine) -> None:
        engine.execute("c1", "SELECT 1")  # warm the loop
        qid = engine.submit("c1", "SELECT SLEEP(5)")
        assert engine.cancel(qid) is True
        result = engine.result(qid)
        assert result.success is False
        assert "ONV-QRY-003" in result.error_message

    def test_cancel_unknown_id_is_a_noop(self, engine) -> None:
        assert engine.cancel("nope") is False

    def test_cancel_all_counts_pending(self, stubbed, engine) -> None:
        engine.execute("c1", "SELECT 1")
        engine.submit("c1", "SELECT SLEEP(5)")
        engine.submit("c1", "SELECT SLEEP(5)")
        assert engine.cancel_all() == 2

    def test_submit_without_connection_raises(self, engine, loop) -> None:
        with (
            patch(f"{QE}.connection_pool", fake_pool_none()),
            patch(f"{QE}._pool_loop", lambda: loop),
        ):
            with pytest.raises(ConnectionClosedError):
                engine.submit("c1", "SELECT 1")

    def test_result_unknown_id_raises_query_failed(self, engine) -> None:
        with pytest.raises(QueryExecutionError) as exc:
            engine.result("missing")
        assert exc.value.code == ERR_QUERY_FAILED


class TestCacheInvalidation:
    def test_write_invalidates_the_connection_cache(self, engine, loop) -> None:
        with (
            patch(f"{QE}.connection_pool", fake_pool(SlowConnector(0.01))),
            patch(f"{QE}._pool_loop", lambda: loop),
            patch(f"{QE}.query_cache") as cache,
        ):
            engine.execute("c1", "INSERT INTO t VALUES (1)")
            cache.invalidate.assert_called_once_with("c1")
            cache.set.assert_not_called()

    def test_select_is_cached(self, engine, loop) -> None:
        with (
            patch(f"{QE}.connection_pool", fake_pool(SlowConnector(0.01))),
            patch(f"{QE}._pool_loop", lambda: loop),
            patch(f"{QE}.query_cache") as cache,
        ):
            cache.get.return_value = None
            result = engine.execute("c1", "SELECT 1")
            cache.set.assert_called_once()
            assert result.success is True

    def test_no_connection_keeps_the_stable_message(self, engine, loop) -> None:
        with (
            patch(f"{QE}.connection_pool", fake_pool_none()),
            patch(f"{QE}._pool_loop", lambda: loop),
            patch(f"{QE}.query_cache") as cache,
        ):
            cache.get.return_value = None
            result = engine.execute("c1", "SELECT 1")

        assert result.success is False
        assert "No active connection" in result.error_message
        assert engine.last_error.code == "ONV-CNN-002"

    def test_driver_exception_becomes_a_structured_failure(self, engine, loop) -> None:
        with (
            patch(f"{QE}.connection_pool", fake_pool(RaisingConnector(RuntimeError("boom")))),
            patch(f"{QE}._pool_loop", lambda: loop),
            patch(f"{QE}.query_cache") as cache,
        ):
            cache.get.return_value = None
            result = engine.execute("c1", "SELECT 1")

        assert result.success is False
        assert engine.last_error.code == ERR_QUERY_FAILED
        assert engine.last_error.raw is not None

    def test_invalidate_cache_helper(self, engine) -> None:
        with patch(f"{QE}.query_cache") as cache:
            engine.invalidate_cache("c1")
            cache.invalidate.assert_called_once_with("c1")


class TestSingleton:
    def test_module_singleton_exists(self) -> None:
        assert isinstance(query_engine, QueryEngine)
