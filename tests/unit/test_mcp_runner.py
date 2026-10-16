"""Tests for the MCP service thread.

These never touch a database: the runner's whole job is threading, so the fakes
are plain callables and coroutines.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Iterator

import pytest

from open_navicat.errors import ERR_POLICY_DENIED, PolicyDeniedError, QueryTimeoutError
from open_navicat.mcp.runner import ServiceRunner


@pytest.fixture()
def runner() -> Iterator[ServiceRunner]:
    r = ServiceRunner(name="opennavicat-test-services")
    try:
        yield r
    finally:
        r.stop()


def _thread_name() -> str:
    return threading.current_thread().name


class TestDispatch:
    def test_work_runs_on_the_service_thread(self, runner: ServiceRunner) -> None:
        assert runner.submit(_thread_name) == "opennavicat-test-services"
        assert threading.current_thread().name != "opennavicat-test-services"

    def test_coroutine_functions_are_driven_not_scheduled(self, runner: ServiceRunner) -> None:
        async def work() -> int:
            await asyncio.sleep(0)
            return 41 + 1

        assert runner.submit(work) == 42

    def test_exceptions_reach_the_caller_unchanged(self, runner: ServiceRunner) -> None:
        def boom() -> None:
            raise PolicyDeniedError("denied for a reason")

        with pytest.raises(PolicyDeniedError) as excinfo:
            runner.submit(boom)
        # The error contract is the point: a tool caller still sees the code.
        assert excinfo.value.code == ERR_POLICY_DENIED
        assert excinfo.value.to_dict()["code"] == ERR_POLICY_DENIED

    def test_calls_run_one_at_a_time(self, runner: ServiceRunner) -> None:
        widths: list[int] = []
        active: list[int] = []

        def work(index: int):
            def run() -> int:
                active.append(index)
                widths.append(len(active))
                time.sleep(0.02)
                active.remove(index)
                return index

            return run

        threads = [threading.Thread(target=lambda i=i: runner.submit(work(i))) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max(widths) == 1

    def test_nested_submit_runs_inline(self, runner: ServiceRunner) -> None:
        """A job may call the runner again; queueing behind itself would hang."""

        def outer() -> str:
            assert runner.owns_current_thread
            return runner.submit(_thread_name)

        assert runner.submit(outer) == "opennavicat-test-services"

    def test_caller_timeout_reports_without_aborting(self, runner: ServiceRunner) -> None:
        release = threading.Event()
        finished = threading.Event()

        def slow() -> str:
            release.wait(5)
            finished.set()
            return "done"

        with pytest.raises(QueryTimeoutError):
            runner.submit(slow, timeout=0.1)
        assert not finished.is_set()

        release.set()
        for _ in range(100):
            if finished.is_set():
                break
            time.sleep(0.01)
        assert finished.is_set()


class TestLifecycle:
    def test_start_is_idempotent(self, runner: ServiceRunner) -> None:
        assert runner.start().submit(_thread_name) == runner.submit(_thread_name)
        assert runner.is_running

    def test_stop_is_idempotent_and_freezes_the_runner(self, runner: ServiceRunner) -> None:
        runner.start()
        runner.stop()
        runner.stop()
        assert not runner.is_running
        with pytest.raises(RuntimeError, match="stopped"):
            runner.submit(_thread_name)

    def test_startup_failure_surfaces_on_the_caller(self, monkeypatch, runner) -> None:
        def refuse() -> None:
            raise OSError("no loop for you")

        monkeypatch.setattr("open_navicat.mcp.runner._get_loop", refuse)
        with pytest.raises(OSError, match="no loop for you"):
            runner.start()

    def test_repr_names_the_state(self, runner: ServiceRunner) -> None:
        assert "idle" in repr(runner)
        runner.start()
        assert "running" in repr(runner)
