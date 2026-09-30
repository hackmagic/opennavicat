"""Query engine — executes SQL, manages result sets, and provides pagination.

What this module owns on top of the raw connector contract:

* result caching for read-only queries, plus write-triggered invalidation,
* per-query time budgets (``timeout``),
* caller-side cancellation (``CancelToken`` / :meth:`QueryEngine.cancel`),
* converting driver exceptions into structured :class:`NavicatError`s.

``execute`` keeps returning :class:`QueryResult` — the historical contract —
and mirrors the failure in ``last_error`` for callers that need the code.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable

from open_navicat.dal.connection_pool import _get_loop as _pool_loop
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.errors import (
    SOURCE_QUERY,
    STAGE_EXECUTE,
    ConnectionClosedError,
    NavicatError,
    QueryCanceledError,
    QueryExecutionError,
    QueryTimeoutError,
)
from open_navicat.models.query_result import QueryResult
from open_navicat.utils.query_cache import query_cache

_log = logging.getLogger(__name__)

#: Poll interval used to notice that a :class:`CancelToken` was triggered.
CANCEL_POLL_S = 0.05

#: SQL verbs that can change data.  Any of these invalidates the cache for the
#: connection, otherwise a stale SELECT result would be served after a write.
_WRITE_VERBS: tuple[str, ...] = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "REPLACE",
    "TRUNCATE",
    "CREATE",
    "DROP",
    "ALTER",
    "RENAME",
    "CALL",
    "LOAD",
    "GRANT",
    "REVOKE",
    "MERGE",
    "COPY",
)


def is_write(sql: str) -> bool:
    """True when ``sql`` starts with a verb that mutates data."""
    head = sql.strip().upper()
    return any(head.startswith(verb) for verb in _WRITE_VERBS)


def _sql_hint(sql: str, limit: int = 80) -> str:
    return sql.strip()[:limit]


def _is_select(sql: str) -> bool:
    head = sql.strip().upper()
    return head.startswith("SELECT") or head.startswith("WITH")


class CancelToken:
    """Cooperative cancellation signal shared between a caller and the engine.

    Create one, hand it to :meth:`QueryEngine.execute`, then call
    :meth:`cancel` from another thread.  Thread-safe by construction.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_canceled(self) -> bool:
        return self._event.is_set()


async def _wait_for_cancel(token: CancelToken, poll: float = CANCEL_POLL_S) -> None:
    """Resolve as soon as ``token`` is canceled.

    Returns immediately when the token is already canceled, so a caller that
    cancels before the query starts still wins the race.
    """
    while not token.is_canceled():
        await asyncio.sleep(poll)


async def _execute_with_budget(
    connector: Any, sql: str, timeout: float | None, token: CancelToken | None
) -> QueryResult:
    """Run ``connector.execute(sql)`` under an optional time budget and token.

    The query and (optionally) the cancel trigger are raced with
    :func:`asyncio.wait` instead of nested ``ensure_future`` + ``await``.
    Nesting makes cancellation ambiguous — an outer ``Task.cancel`` can be
    parked behind an inner task and never delivered — whereas a race has one
    clear winner and every loser is canceled in ``finally``.
    """
    task = asyncio.ensure_future(connector.execute(sql))
    trigger = asyncio.ensure_future(_wait_for_cancel(token)) if token is not None else None

    try:
        groups = [task] + ([trigger] if trigger is not None else [])
        done, _pending = await asyncio.wait(
            groups, return_when=asyncio.FIRST_COMPLETED, timeout=timeout
        )

        if trigger is not None and trigger in done:
            raise QueryCanceledError(
                f"query canceled by the caller: {_sql_hint(sql)}",
                source=SOURCE_QUERY,
                stage=STAGE_EXECUTE,
            )
        if timeout is not None and task not in done:
            raise QueryTimeoutError(
                f"query exceeded {timeout}s: {_sql_hint(sql)}",
                source=SOURCE_QUERY,
                stage=STAGE_EXECUTE,
            )
        return task.result()

    except asyncio.TimeoutError:
        raise QueryTimeoutError(
            f"query exceeded {timeout}s: {_sql_hint(sql)}",
            source=SOURCE_QUERY,
            stage=STAGE_EXECUTE,
        ) from None
    finally:
        if trigger is not None and not trigger.done():
            trigger.cancel()
            with contextlib.suppress(BaseException):
                await trigger
        if not task.done():
            task.cancel()
            with contextlib.suppress(BaseException):
                await task


@dataclass
class _PendingQuery:
    task: asyncio.Task
    future: asyncio.Future
    connection_id: str
    token: CancelToken
    sql: str


class QueryEngine:
    """Service layer for SQL query execution and result management."""

    def __init__(self) -> None:
        #: Structured error from the most recent failed :meth:`execute`.
        self.last_error: NavicatError | None = None
        self._running: dict[str, _PendingQuery] = {}

    # ---- internals ----

    def _fail(self, err: NavicatError) -> QueryResult:
        self.last_error = err
        _log.warning("query failed: %s", err.render())
        return QueryResult(success=False, error_message=err.render())

    def _no_connection(self, connection_id: str) -> QueryResult:
        """Keep the historical 'No active connection' message in the payload."""
        err = ConnectionClosedError(
            f"no active connection for '{connection_id}'",
            source=SOURCE_QUERY,
            stage=STAGE_EXECUTE,
        )
        self.last_error = err
        _log.warning("query failed: %s", err.render())
        return QueryResult(success=False, error_message=f"No active connection: {err.render()}")

    # ---- synchronous API (historical contract) ----

    def execute(
        self,
        connection_id: str,
        sql: str,
        timeout: float | None = None,
        cancel_token: CancelToken | None = None,
    ) -> QueryResult:
        """Execute ``sql`` and return a :class:`QueryResult`.

        ``timeout`` is a hard time budget in seconds.  ``cancel_token`` lets an
        external caller (a UI button, a Ctrl-C handler) abort the query.  Both
        default to ``None``, which keeps the original behaviour: no budget, no
        cancellation.
        """
        self.last_error = None

        write = is_write(sql)
        if write:
            # A write must not be served from, or added to, the read cache.
            query_cache.invalidate(connection_id)
        else:
            if _is_select(sql):
                cached = query_cache.get(connection_id, "", sql)
                if cached is not None:
                    return cached

        connector = connection_pool.get(connection_id)
        if connector is None:
            return self._no_connection(connection_id)

        try:
            if timeout is None and cancel_token is None:
                # Fast path: unchanged from before, no extra tasks.
                result = _pool_loop().run_until_complete(connector.execute(sql))
            else:
                result = _pool_loop().run_until_complete(
                    _execute_with_budget(connector, sql, timeout, cancel_token)
                )
        except NavicatError as err:
            return self._fail(err)
        except Exception as exc:  # noqa: BLE001 - connector boundary
            return self._fail(
                NavicatError.from_exception(exc, source=SOURCE_QUERY, stage=STAGE_EXECUTE)
            )

        if result.success and not write and _is_select(sql):
            query_cache.set(connection_id, "", sql, result)
        return result

    # ---- background API: submit / cancel / result ----

    @property
    def running_queries(self) -> dict[str, bool]:
        """``query_id -> still pending``, useful for progress UIs."""
        return {qid: not entry.task.done() for qid, entry in self._running.items()}

    def submit(self, connection_id: str, sql: str, timeout: float | None = None) -> str:
        """Start ``sql`` in the background and return its query id.

        Use :meth:`cancel` to abort and :meth:`result` to await.  This is the
        entry point for the GUI, which must never block its event loop on a
        long query.
        """
        connector = connection_pool.get(connection_id)
        if connector is None:
            raise ConnectionClosedError(
                f"no active connection for '{connection_id}'",
                source=SOURCE_QUERY,
                stage=STAGE_EXECUTE,
            )

        # Bind to the pool loop explicitly: ``asyncio.ensure_future`` would pick
        # whatever loop is current, which is not this one when submit() is called
        # from outside a running loop.
        loop = _pool_loop()
        query_id = uuid.uuid4().hex[:12]
        future: asyncio.Future = loop.create_future()
        token = CancelToken()

        async def _supervise() -> None:
            try:
                future.set_result(await _execute_with_budget(connector, sql, timeout, token))
            except NavicatError as err:
                future.set_exception(err)
            except asyncio.CancelledError:
                future.set_exception(
                    QueryCanceledError(
                        f"query canceled by the caller: {_sql_hint(sql)}",
                        source=SOURCE_QUERY,
                        stage=STAGE_EXECUTE,
                    )
                )
            except BaseException as exc:  # noqa: BLE001 - connector boundary
                future.set_exception(
                    NavicatError.from_exception(exc, source=SOURCE_QUERY, stage=STAGE_EXECUTE)
                )

        task = loop.create_task(_supervise())
        self._running[query_id] = _PendingQuery(
            task=task, future=future, connection_id=connection_id, token=token, sql=sql
        )
        return query_id

    def cancel(self, query_id: str) -> bool:
        """Cancel a query started with :meth:`submit`.

        Returns ``True`` when there was a pending task to signal.  Cancellation
        is cooperative: it triggers the query task directly, so it takes effect
        promptly instead of waiting for the driver call to finish.  Whether the
        database server also stops scanning is a later refinement (per-engine
        ``KILL QUERY``).
        """
        entry = self._running.get(query_id)
        if entry is None or entry.task.done():
            return False
        entry.token.cancel()
        _log.info("cancel(%s) requested for connection %s", query_id, entry.connection_id)
        return True

    def result(self, query_id: str) -> QueryResult:
        """Block until the query started by :meth:`submit` finishes."""
        entry = self._running.pop(query_id, None)
        if entry is None:
            raise QueryExecutionError(
                f"unknown query id '{query_id}'", source=SOURCE_QUERY, stage=STAGE_EXECUTE
            )
        self.last_error = None
        try:
            return _pool_loop().run_until_complete(entry.future)
        except NavicatError as err:
            return self._fail(err)
        except BaseException as exc:  # noqa: BLE001 - connector boundary
            return self._fail(
                NavicatError.from_exception(exc, source=SOURCE_QUERY, stage=STAGE_EXECUTE)
            )

    def cancel_all(self) -> int:
        """Cancel every pending query; returns how many were pending."""
        count = 0
        for qid in list(self._running.keys()):
            if self.cancel(qid):
                count += 1
        return count

    # ---- caching ----

    def invalidate_cache(self, connection_id: str) -> None:
        """Drop every cached result for ``connection_id``."""
        query_cache.invalidate(connection_id)

    # ---- file / script execution ----

    def execute_file(self, connection_id: str, file_path: str, **kwargs: Any) -> list[QueryResult]:
        """Execute multiple statements from a .sql file, return results per statement."""
        from pathlib import Path

        content = Path(file_path).read_text(encoding="utf-8")
        return self.execute_script(connection_id, content, **kwargs)

    def execute_script(self, connection_id: str, script: str, **kwargs: Any) -> list[QueryResult]:
        """Split script by ';' and execute each statement."""
        import sqlparse

        results: list[QueryResult] = []
        for stmt in sqlparse.split(script):
            stmt = stmt.strip()
            if stmt:
                results.append(self.execute(connection_id, stmt, **kwargs))
        return results

    # ---- helpers ----

    def explain(self, connection_id: str, sql: str) -> QueryResult:
        """Run EXPLAIN on a query and return the execution plan."""
        return self.execute(connection_id, f"EXPLAIN {sql}")

    def explain_format_json(self, connection_id: str, sql: str) -> QueryResult:
        """Run EXPLAIN FORMAT=JSON for detailed plan."""
        return self.execute(connection_id, f"EXPLAIN FORMAT=JSON {sql}")

    def count_rows(self, connection_id: str, database: str, table: str) -> int:
        connector = connection_pool.get(connection_id)
        if connector is None:
            return 0
        info = getattr(connector, "_info", None)
        engine = getattr(info, "engine", "mysql") if info else "mysql"
        if engine == "postgresql":
            q = '"'
            sql = f"SELECT COUNT(*) FROM {q}{database}{q}.{q}{table}{q}"
        else:
            safe_db = database.replace("`", "``")
            safe_table = table.replace("`", "``")
            sql = f"SELECT COUNT(*) FROM `{safe_db}`.`{safe_table}`"
        result = _pool_loop().run_until_complete(connector.execute(sql))
        if result.success and result.rows:
            return result.rows[0][0]
        return 0

    def execute_stream(self, connection_id: str, sql: str, chunk_size: int = 1000):
        """Execute a query and yield rows in chunks (server-side cursor for large datasets)."""
        conn = connection_pool.get(connection_id)
        if conn is None:
            return
        try:
            result = _pool_loop().run_until_complete(conn.execute(sql))
            if result.success and result.rows:
                total = len(result.rows)
                for i in range(0, total, chunk_size):
                    yield result.rows[i : i + chunk_size]
        except Exception as e:
            _log.warning("Stream execute failed: %s", e)


# Module-level singleton
query_engine = QueryEngine()
