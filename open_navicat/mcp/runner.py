"""One thread that owns the asyncio loop every service call runs on.

Why this exists: :class:`ConnectionPool` and the service singletons drive their
async connectors with ``loop.run_until_complete(...)`` against a module-global
loop.  An asyncio loop may be driven by exactly one thread at a time, while the
MCP SDK dispatches synchronous tool callables on *arbitrary* anyio worker
threads.  Handing those calls straight to the services would mean two threads
driving one loop — which fails as ``RuntimeError: This event loop is already
running`` or, worse, as a half-read connection.

So the tool layer routes everything through here.  The queue also makes the
server easy to reason about: one statement at a time, in call order, exactly
like a human at a console.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import queue
import threading
from typing import Any, Callable

from open_navicat.dal.connection_pool import _get_loop
from open_navicat.errors import QueryTimeoutError

_log = logging.getLogger(__name__)

#: How long :meth:`ServiceRunner.start` waits for the worker before giving up.
STARTUP_TIMEOUT_S = 5.0

_STOP = object()


class _Job:
    """A unit of work handed from a caller to the service thread."""

    __slots__ = ("call", "done", "value", "error")

    def __init__(self, call: Callable[[], Any]) -> None:
        self.call = call
        self.done = threading.Event()
        self.value: Any = None
        self.error: BaseException | None = None


class ServiceRunner:
    """Serialises service calls onto a single thread that owns the event loop.

    Not reusable after :meth:`stop`: the loop it bound dies with the thread.
    Build a new instance instead.
    """

    def __init__(self, name: str = "opennavicat-services") -> None:
        self._name = name
        self._jobs: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._stopped = False
        self._lock = threading.Lock()

    # ---- lifecycle ----

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stopped

    @property
    def owns_current_thread(self) -> bool:
        """True when the caller *is* the service thread, so calls run inline."""
        return self._thread is not None and threading.current_thread() is self._thread

    def start(self) -> "ServiceRunner":
        """Bring the worker up, or return immediately if it is already running.

        The loop is fetched *inside* the worker so that, in a fresh process, the
        pool's lazily-created loop is bound to this thread from the start.
        """
        with self._lock:
            if self._stopped:
                raise RuntimeError(f"{self._name} was stopped; build a new ServiceRunner")
            if self.is_running:
                return self
            self._ready.clear()
            self._startup_error = None
            self._thread = threading.Thread(target=self._bootstrap, name=self._name, daemon=True)
            self._thread.start()
            if not self._ready.wait(STARTUP_TIMEOUT_S):
                raise RuntimeError(f"{self._name} did not start within {STARTUP_TIMEOUT_S}s")
            if self._startup_error is not None:
                raise self._startup_error
        return self

    def stop(self, timeout: float = 5.0) -> None:
        """End the worker thread.  Idempotent.

        Open connections are left alone — closing them is the pool's job
        (``connection_pool.close_all()``), not this thread's.
        """
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            thread = self._thread
        if thread is not None and thread.is_alive():
            self._jobs.put(_STOP)
            thread.join(timeout)
            if thread.is_alive():  # pragma: no cover - wedged on a live query
                _log.warning("%s did not stop within %.1fs", self._name, timeout)
        self._thread = None
        self._ready.clear()

    # ---- dispatch ----

    def submit(self, call: Callable[[], Any], timeout: float | None = None) -> Any:
        """Run ``call`` on the service thread and return its result.

        ``call`` may be a plain callable or a coroutine function; anything
        asynchronous is driven with :meth:`run_until_complete` here, so callers
        never manage a loop of their own.  Exceptions raised by ``call`` are
        re-raised here unchanged, so structured error codes survive the hand-off.

        ``timeout`` bounds how long the *caller* waits; it does not abort the
        work — the statement keeps running on the service thread.  A query that
        must be cut short needs the engine's own ``timeout`` argument instead.
        """
        if self.owns_current_thread:
            return self._invoke(call)
        if not self.is_running:
            self.start()
        job = _Job(call)
        self._jobs.put(job)
        if not job.done.wait(timeout):
            raise QueryTimeoutError(
                f"the service thread did not answer within {timeout}s; the statement is "
                "still running behind it",
                retryable=True,
            )
        if job.error is not None:
            raise job.error
        return job.value

    def _invoke(self, call: Callable[[], Any]) -> Any:
        if self._loop is None:  # pragma: no cover - only reachable if bootstrap failed
            raise RuntimeError(f"{self._name} has no event loop")
        outcome = call()
        if inspect.isawaitable(outcome):
            return self._loop.run_until_complete(outcome)
        return outcome

    # ---- worker ----

    def _bootstrap(self) -> None:
        try:
            self._loop = _get_loop()
            asyncio.set_event_loop(self._loop)
        except BaseException as exc:  # noqa: BLE001 - handed back to start()
            self._startup_error = exc
            self._ready.set()
            return
        self._ready.set()
        while True:
            job = self._jobs.get()
            if job is _STOP:
                break
            try:
                job.value = self._invoke(job.call)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
                job.error = exc
            finally:
                job.done.set()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "running" if self.is_running else ("stopped" if self._stopped else "idle")
        return f"<ServiceRunner {self._name} {state}>"


#: Process-wide runner used by the MCP tool layer.
service_runner = ServiceRunner()

__all__ = ["STARTUP_TIMEOUT_S", "ServiceRunner", "service_runner"]
