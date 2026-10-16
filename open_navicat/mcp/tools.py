"""MCP tools — the operations an AI client can call.

Split from the SDK on purpose: these functions take JSON-friendly arguments and
return JSON-friendly dicts, so they are unit-testable (and reusable by the CLI)
without an MCP client in the loop.  :mod:`open_navicat.mcp.server` is the only
place that knows the protocol exists.

Three rules every tool follows:

* the work happens on :data:`open_navicat.mcp.runner.service_runner`, because
  the services underneath drive one asyncio loop;
* anything that changes state goes through :mod:`open_navicat.mcp.safety` first,
  so no caller — human, CLI or LLM — reaches a write the tier did not allow;
* every response says which connection, engine and database it came from.  A
  model that cannot see where its rows came from cannot be audited afterwards.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

from open_navicat.errors import (
    STAGE_RESOLVE,
    ConfigError,
    ConnectionClosedError,
    NavicatError,
    PolicyDeniedError,
    SQLError,
    redact,
)
from open_navicat.mcp import safety
from open_navicat.mcp.runner import service_runner
from open_navicat.models.query_result import QueryResult

_log = logging.getLogger(__name__)

#: Rows handed back in one call.  The limiting factor is the model's context
#: window, not the database.
DEFAULT_ROW_LIMIT = 100
MAX_ROW_LIMIT = 1000

#: Wall-clock budget for one statement, seconds.
DEFAULT_TIMEOUT_S = 30.0

#: Engines whose "query" is a command line rather than SQL.
COMMAND_ENGINES = frozenset({"redis"})

#: Widest tier a client may use, set by whoever started the process (the CLI
#: takes it from ``--access``).  A model passing ``tier="full"`` does not earn
#: full access; it gets whatever the human running the server allowed.
max_tier: str = safety.TIER_FULL


def _submit(call: Callable[[], dict[str, Any]], timeout: float | None = None) -> dict[str, Any]:
    """Run ``call`` on the service thread and turn its outcome into a response.

    A tool call that raises is a protocol error the model cannot read, so every
    failure - including the structured ones the services raise - is converted
    back into the same envelope the tools return on success.
    """
    try:
        return service_runner.submit(call, timeout=timeout)
    except NavicatError as err:
        return failure(err)
    except Exception as exc:  # noqa: BLE001 - tool boundary
        _log.exception("MCP tool call failed")
        return failure(NavicatError.from_exception(exc))


# ---- envelopes -------------------------------------------------------------


def ok(**payload: Any) -> dict[str, Any]:
    """Success envelope every tool returns."""
    return {"ok": True, **payload}


def failure(error: BaseException, **payload: Any) -> dict[str, Any]:
    """Failure envelope carrying the stable error contract."""
    if not isinstance(error, NavicatError):
        error = NavicatError.from_exception(error)
    return {"ok": False, "error": error.to_dict(), **payload}


def _refused(decision: safety.Decision) -> dict[str, Any]:
    """A policy refusal, shaped so a model can re-ask instead of retrying blind."""
    return failure(
        decision.error or PolicyDeniedError("refused by the access policy"),
        policy=decision.to_dict(),
    )


# ---- JSON coercion ---------------------------------------------------------


def _cell(value: Any) -> Any:
    """Coerce one database value into something JSON can carry.

    ``Decimal`` becomes a string rather than a float: a lossy amount column is
    worse than an inconvenient one.  Anything unrecognised goes through
    :func:`redact`, so an unexpected driver type cannot leak credentials in a
    ``repr``.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(value).hex()
    if isinstance(value, dict):
        return {str(k): _cell(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_cell(v) for v in value]
    return redact(str(value))


def _table_of(rows: list[list[Any]], limit: int, mask: bool, columns: list[str]) -> dict[str, Any]:
    """Trim and optionally mask a result set.

    Masking is on by default because these rows leave the machine for a
    third-party model — the same reason :mod:`open_navicat.services.ai_service`
    masks before showing a model a result.
    """
    kept = rows[:limit]
    if mask and columns:
        from open_navicat.utils.data_masker import mask_row

        body = [[_cell(v) for v in mask_row(list(row), columns)] for row in kept]
    else:
        body = [[_cell(v) for v in row] for row in kept]
    payload: dict[str, Any] = {"rows": body}
    if len(rows) > limit:
        payload["truncated"] = True
        payload["note"] = f"{len(rows)} rows came back; only {limit} are shown"
    return payload


def _result_payload(result: QueryResult, limit: int, mask: bool = True) -> dict[str, Any]:
    """Turn a :class:`QueryResult` into a tool response.

    ``QueryResult`` reports failure as data rather than as an exception, so the
    failure branch is part of this function's normal path.
    """
    if not result.success:
        return failure(SQLError(redact(result.error_message or "the statement did not complete")))
    columns = [c.name for c in result.columns]
    payload = ok(
        columns=[
            {
                "name": c.name,
                "type": c.data_type,
                "nullable": c.nullable,
                "table": c.table_name,
            }
            for c in result.columns
        ],
        rowCount=result.row_count,
        affectedRows=result.affected_rows,
        executionTimeMs=round(result.execution_time_ms, 2),
        **_table_of(result.rows, limit, mask, columns),
    )
    if result.warnings:
        payload["warnings"] = [redact(w) for w in result.warnings]
    return payload


# ---- session resolution ----------------------------------------------------


def _manager() -> Any:
    from open_navicat.services.connection_manager import connection_manager

    return connection_manager


def _resolve_connection_id(connection_id: str = "") -> str:
    """Pick the session to work on.

    An empty ``connection_id`` means "the obvious one": if exactly one session
    is open, that is it.  With several open it is an error, because guessing
    which host an agent meant is how the wrong database gets queried.
    """
    manager = _manager()
    if connection_id:
        if manager.get_connector(connection_id) is not None:
            return connection_id
        open_ids = ", ".join(manager.active_ids) or "none"
        raise ConnectionClosedError(
            f"connection '{connection_id}' is not open; open sessions: {open_ids}",
            recoverable=True,
        )
    active = manager.active_ids
    if len(active) == 1:
        return active[0]
    if not active:
        raise ConnectionClosedError("no connection is open; call open_session first")
    raise ConnectionClosedError(
        f"{len(active)} connections are open ({', '.join(active)}); pass connection_id",
        recoverable=True,
    )


def _connector_of(connection_id: str) -> Any:
    return _manager().get_connector(connection_id)


def _engine_of(connection_id: str) -> str:
    connector = _connector_of(connection_id)
    if connector is None:
        return ""
    info = getattr(connector, "info", None)
    return getattr(connector, "engine", "") or getattr(info, "engine", "") or ""


def _default_database(connection_id: str) -> str:
    """The database a session is pointed at.

    The live connector answers this rather than the saved profile: a session
    opened from a DSN is deliberately not saved, and the caller still needs to
    know which database the rows came from.
    """
    connector = _connector_of(connection_id)
    info = getattr(connector, "info", None) if connector is not None else None
    if info is None:
        info = _manager().get_saved(connection_id)
    return getattr(info, "database", "") or ""


def _require_database(database: str, connection_id: str) -> str:
    resolved = (database or "").strip() or _default_database(connection_id)
    if not resolved:
        raise SQLError(
            f"no database selected for connection '{connection_id}'; pass database explicitly",
            stage=STAGE_RESOLVE,
            recoverable=True,
        )
    return resolved


def _context(connection_id: str, database: str, decision: safety.Decision) -> dict[str, Any]:
    """Where these rows came from, and under which policy they were fetched."""
    return {
        "connectionId": connection_id,
        "engine": _engine_of(connection_id),
        "database": database,
        "accessTier": decision.tier,
        "risk": decision.risk,
    }


#: Metadata reads never hit the gate, but their context block still names the
#: tier they ran under.
_READ_ONLY = safety.Decision(allowed=True, tier=safety.TIER_READ, risk=safety.RISK_READ)


# ---- session tools ----


def list_connections() -> dict[str, Any]:
    """List saved connection profiles and say which are currently open.

    Returns id, name, engine, host, port, database and user per profile, plus
    ``activeIds``.  Credentials are never included — a client that needs one
    calls :func:`open_session` with the id instead.
    """

    def call() -> dict[str, Any]:
        manager = _manager()
        active = list(manager.active_ids)
        profiles = [
            {
                "id": info.id,
                "name": info.name,
                "engine": info.engine,
                "host": info.host,
                "port": info.port,
                "database": info.database,
                "user": info.user,
                "active": info.id in active,
            }
            for info in manager.list_saved()
        ]
        return ok(connections=profiles, activeIds=active, defaultTier=safety.TIER_READ)

    return _submit(call)


def open_session(connection_id: str = "", dsn: str = "", name: str = "") -> dict[str, Any]:
    """Open a database session and return its id.

    Pass either ``connection_id`` (a saved profile from
    :func:`list_connections`) or ``dsn`` such as ``mysql://user:pass@host/db``.
    A DSN session is not saved, so a throwaway target cannot end up in the
    user's connection list.
    """
    if not connection_id and not dsn:
        return failure(ConfigError("open_session needs connection_id or dsn", recoverable=True))

    def call() -> dict[str, Any]:
        manager = _manager()
        if connection_id:
            info = manager.get_saved(connection_id)
            if info is None:
                raise ConnectionClosedError(f"no saved connection '{connection_id}'")
        else:
            from open_navicat.drivers.dsn import dsn_to_connection

            info = dsn_to_connection(dsn, name=name)

        if manager.get_connector(info.id) is not None:
            return ok(connectionId=info.id, engine=info.engine, alreadyOpen=True)
        if not manager.connect(info, persist=False):
            raise manager.last_error or ConnectionClosedError(
                f"could not open '{info.name or info.id}'"
            )
        return ok(
            connectionId=info.id,
            engine=info.engine,
            database=info.database,
            persisted=False,
        )

    return _submit(call)


def close_session(connection_id: str) -> dict[str, Any]:
    """Close a session previously opened."""

    def call() -> dict[str, Any]:
        _manager().disconnect(connection_id)
        return ok(connectionId=connection_id, closed=True)

    return _submit(call)


def session_status() -> dict[str, Any]:
    """Report open sessions, supported engines and policy defaults.

    Cheap, and worth calling first: it tells a client which database it is
    actually looking at before it runs anything.
    """

    def call() -> dict[str, Any]:
        from open_navicat.drivers.registry import DRIVER_REGISTRY, is_installed

        manager = _manager()
        sessions = [
            {
                "connectionId": cid,
                "engine": _engine_of(cid),
                "database": _default_database(cid),
            }
            for cid in manager.active_ids
        ]
        engines = [
            {
                "engine": key,
                "displayName": spec.display_name,
                "defaultPort": spec.default_port,
                "driverInstalled": is_installed(key),
                "optional": bool(spec.optional),
            }
            for key, spec in DRIVER_REGISTRY.items()
        ]
        return ok(
            sessions=sessions,
            engines=engines,
            accessTiers=list(safety.TIERS),
            defaultTier=safety.TIER_READ,
            # Asking for a wider tier than this is capped, not granted.
            maxTier=max_tier,
            rowLimit=DEFAULT_ROW_LIMIT,
        )

    return _submit(call)


# ---- metadata tools ----


def list_databases(connection_id: str = "") -> dict[str, Any]:
    """List databases (or schemas) available on a session."""

    def call() -> dict[str, Any]:
        from open_navicat.services.metadata_service import metadata_service

        cid = _resolve_connection_id(connection_id)
        databases = [
            {
                "name": db.name,
                "charset": db.charset,
                "collation": db.collation,
                "sizeBytes": db.size_bytes,
                "tableCount": db.table_count,
            }
            for db in metadata_service.list_databases(cid)
        ]
        return ok(
            databases=databases,
            context=_context(cid, "", _READ_ONLY),
        )

    return _submit(call)


def list_tables(database: str = "", connection_id: str = "") -> dict[str, Any]:
    """List tables and views in a database."""

    def call() -> dict[str, Any]:
        from open_navicat.services.metadata_service import metadata_service

        cid = _resolve_connection_id(connection_id)
        db = _require_database(database, cid)
        return ok(
            tables=list(metadata_service.list_tables(cid, db)),
            views=list(metadata_service.list_views(cid, db)),
            routines=[
                {"name": name, "type": kind}
                for name, kind in metadata_service.list_routines(cid, db)
            ],
            context=_context(cid, db, _READ_ONLY),
        )

    return _submit(call)


def describe_table(table: str, database: str = "", connection_id: str = "") -> dict[str, Any]:
    """Describe one table: columns, keys, indexes and the DDL that created it.

    This is the metadata a model needs to write SQL against a schema it has not
    seen, so it comes back as text it can quote back to the user.
    """

    def call() -> dict[str, Any]:
        from open_navicat.services.metadata_service import metadata_service

        cid = _resolve_connection_id(connection_id)
        db = _require_database(database, cid)
        info = metadata_service.get_table_info(cid, db, table)
        if info is None:
            raise SQLError(
                f"table '{db}.{table}' does not exist", stage=STAGE_RESOLVE, recoverable=True
            )
        read = _READ_ONLY
        return ok(
            table=info.name,
            comment=info.comment,
            engine=info.engine,
            rowCount=info.row_count,
            columns=[
                {
                    "name": c.name,
                    "type": c.data_type,
                    "nullable": c.nullable,
                    "primaryKey": c.is_primary_key,
                    "unique": c.is_unique,
                    "autoIncrement": c.is_auto_increment,
                    "default": _cell(c.default),
                    "comment": c.comment,
                }
                for c in info.columns
            ],
            indexes=[
                {
                    "name": i.name,
                    "columns": list(i.columns),
                    "unique": i.is_unique,
                    "primary": i.is_primary,
                    "type": i.index_type,
                }
                for i in info.indexes
            ],
            foreignKeys=[
                {
                    "name": fk.name,
                    "column": fk.column,
                    "refTable": fk.ref_table,
                    "refColumn": fk.ref_column,
                    "onDelete": fk.on_delete,
                    "onUpdate": fk.on_update,
                }
                for fk in info.foreign_keys
            ],
            createSql=metadata_service.get_create_table_sql(cid, db, table),
            context=_context(cid, db, read),
        )

    return _submit(call)


# ---- execution tools ----


def _gate(
    text: str,
    engine: str,
    tier: str,
    dry_run: bool,
    confirm: bool,
    as_command: bool,
) -> safety.Decision:
    """Classify and gate one request under the tier the operator allows.

    Redis speaks commands, not SQL, and routing ``GET key`` through the SQL
    splitter would fail closed on every read — so the classifier follows the
    engine, and ``execute_command`` forces it.
    """
    analysis = (
        safety.analyze_command(text)
        if as_command or engine in COMMAND_ENGINES
        else safety.analyze(text)
    )
    requested = safety.normalize_tier(tier)
    effective = safety.clamp_tier(requested, max_tier)
    decision = safety.decide(analysis, tier=effective, dry_run=dry_run, confirm=confirm)
    if effective != requested:
        decision = dataclasses.replace(
            decision,
            reasons=decision.reasons
            + (
                f"the requested '{requested}' tier was capped at '{effective}' by the server "
                "operator",
            ),
        )
    return decision


def _execute(
    cid: str,
    text: str,
    decision: safety.Decision,
    limit: int,
    mask: bool,
    timeout: float,
) -> dict[str, Any]:
    from open_navicat.services.query_engine import query_engine

    result = query_engine.execute(cid, text, timeout=timeout or None)
    payload = _result_payload(result, limit, mask)
    payload["context"] = _context(cid, _default_database(cid), decision)
    if decision.reasons:
        payload["policyReasons"] = list(decision.reasons)
    return payload


def _dry_run(cid: str, text: str, decision: safety.Decision, limit: int) -> dict[str, Any]:
    """Report what a write would change, without changing it.

    A row-scoped UPDATE/DELETE gets a real ``COUNT(*)`` under its own predicate,
    which is the same row set the write targets.  Anything else only gets the
    static analysis — returning an empty preview would read as "checked, no rows
    affected".
    """
    payload = ok(
        executed=False,
        dryRun=True,
        statement=redact(text)[:300],
        policyReasons=list(decision.reasons),
        context=_context(cid, _default_database(cid), decision),
    )
    if decision.preview_sql:
        from open_navicat.services.query_engine import query_engine

        result = query_engine.execute(cid, decision.preview_sql)
        preview = _result_payload(result, limit, mask=False)
        payload["preview"] = preview
        payload["note"] = (
            "rows matched by the write's own predicate; nothing was changed"
            if preview.get("ok")
            else "the preview query itself failed; the write was not attempted"
        )
    else:
        payload["note"] = (
            "this statement has no static preview; re-run with confirm=true to execute it"
        )
    return payload


def _run_gated(
    text: str,
    connection_id: str,
    tier: str,
    limit: int,
    timeout: float,
    dry_run: bool,
    confirm: bool,
    mask: bool,
    as_command: bool,
) -> dict[str, Any]:
    """Shared body of :func:`execute_query` and :func:`execute_command`."""
    capped = max(1, min(int(limit or DEFAULT_ROW_LIMIT), MAX_ROW_LIMIT))

    def call() -> dict[str, Any]:
        cid = _resolve_connection_id(connection_id)
        engine = _engine_of(cid)
        decision = _gate(text, engine, tier, dry_run, confirm, as_command)
        if not decision.allowed:
            return _refused(decision)
        if decision.dry_run:
            return _dry_run(cid, text, decision, capped)
        return _execute(cid, text, decision, capped, mask, timeout)

    return _submit(call)


def execute_query(
    sql: str,
    connection_id: str = "",
    tier: str = safety.TIER_READ,
    limit: int = DEFAULT_ROW_LIMIT,
    timeout: float = DEFAULT_TIMEOUT_S,
    dry_run: bool = False,
    confirm: bool = False,
    mask: bool = True,
) -> dict[str, Any]:
    """Run one SQL statement against a session and return its rows.

    Args:
        sql: the statement — one per call, so the policy can rate it.
        connection_id: session from :func:`open_session`; omit when exactly one
            session is open.
        tier: ``read`` (default), ``safe-write`` or ``full``.
        dry_run: change nothing; report or preview the effect instead.
        confirm: the caller — or the human behind it — agreed to a real write.
        limit: maximum rows returned, capped at 1000.
        mask: blank columns that look like personal data.

    There is no database argument: a statement runs in the database its session
    was opened against, so qualifying object names is how you reach another one.

    A dry run changes nothing and is allowed at every tier, so it is how to find
    out what a write would do before asking for permission.  A real write needs
    the tier to allow it *and* ``confirm`` — and the tier is capped by whoever
    started this server, so asking for ``full`` does not grant it.

    Refusals come back as data rather than exceptions, with the reason spelled
    out in ``error.detail`` so the model can re-ask instead of retrying the same
    call.
    """
    return _run_gated(
        sql, connection_id, tier, limit, timeout, dry_run, confirm, mask, as_command=False
    )


def execute_command(
    command: str,
    connection_id: str = "",
    tier: str = safety.TIER_READ,
    limit: int = DEFAULT_ROW_LIMIT,
    timeout: float = DEFAULT_TIMEOUT_S,
    dry_run: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Run a key-value command such as ``GET user:1`` or ``INFO memory``.

    Same policy as :func:`execute_query`, but always rated as a command: only a
    known read command passes tier ``read``, so anything else costs a
    confirmation rather than running silently.
    """
    return _run_gated(
        command, connection_id, tier, limit, timeout, dry_run, confirm, True, as_command=True
    )


#: Tools the MCP server exposes, in documentation order.
TOOLS: tuple[Callable[..., dict[str, Any]], ...] = (
    list_connections,
    open_session,
    close_session,
    session_status,
    list_databases,
    list_tables,
    describe_table,
    execute_query,
    execute_command,
)

__all__ = [
    "COMMAND_ENGINES",
    "DEFAULT_ROW_LIMIT",
    "DEFAULT_TIMEOUT_S",
    "MAX_ROW_LIMIT",
    "TOOLS",
    "close_session",
    "describe_table",
    "execute_command",
    "execute_query",
    "failure",
    "list_connections",
    "list_databases",
    "list_tables",
    "ok",
    "open_session",
    "session_status",
]
