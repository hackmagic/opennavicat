"""Unified structured error model for OpenNavicat.

Every user-facing failure in the codebase is expressed as a :class:`NavicatError`
(or one of its subclasses).  A single error carries both a stable machine
identity and the context needed to decide what to do with it:

``code``        stable machine key, e.g. ``ONV-QRY-002``.  Codes are never
                reused and never renamed; add new ones instead.
``message_key`` localizable key for UI text (future error i18n).
``detail``      human description, always passed through the redactor so
                passwords, tokens and DSN credentials cannot leak into logs.
``source``      origin domain: ``connection`` / ``query`` / ``driver`` /
                ``ai`` / ``plugin`` / ``config`` / ``sql``.
``stage``       the step that failed: ``resolve`` / ``import`` / ``connect`` /
                ``execute`` / ``parse`` / ``request`` ...
``recoverable`` the caller may retry the *operation*; the surrounding
                connection still looks alive.
``retryable``   the operation may be retried automatically (no side effects).

``NavicatError.to_dict()`` produces a stable JSON-friendly payload so the CLI,
the GUI and a future MCP server all render the *same* error identity instead of
each inventing their own string.

Design is original: DBX's public error contract was only consulted for *shape*
(which fields a caller needs), not copied.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

#: Error contract version.  Bump only when a field type/meaning changes.
ERROR_CONTRACT_VERSION = 1

# ---- domains -------------------------------------------------------------
SOURCE_CONNECTION = "connection"
SOURCE_QUERY = "query"
SOURCE_DRIVER = "driver"
SOURCE_SQL = "sql"
SOURCE_AI = "ai"
SOURCE_PLUGIN = "plugin"
SOURCE_CONFIG = "config"

# ---- stages --------------------------------------------------------------
STAGE_RESOLVE = "resolve"
STAGE_IMPORT = "import"
STAGE_CONNECT = "connect"
STAGE_EXECUTE = "execute"
STAGE_PARSE = "parse"
STAGE_REQUEST = "request"
STAGE_LOAD = "load"

# ---- stable error codes --------------------------------------------------
ERR_CONNECTION_FAILED = "ONV-CNN-001"
ERR_CONNECTION_CLOSED = "ONV-CNN-002"
ERR_SSH_TUNNEL_FAILED = "ONV-CNN-003"
ERR_ENGINE_UNSUPPORTED = "ONV-DRV-001"
ERR_DRIVER_MISSING = "ONV-DRV-002"
ERR_QUERY_FAILED = "ONV-QRY-001"
ERR_QUERY_TIMEOUT = "ONV-QRY-002"
ERR_QUERY_CANCELED = "ONV-QRY-003"
ERR_SQL_SYNTAX = "ONV-SQL-001"
ERR_AI_FAILED = "ONV-AI-001"
ERR_AI_TRANSIENT = "ONV-AI-002"
ERR_PLUGIN_FAILED = "ONV-PLG-001"
ERR_CONFIG_INVALID = "ONV-CFG-001"

#: Human labels for the code catalog; used by ``opennavicat doctor``-style tooling.
ERROR_CATALOG: dict[str, str] = {
    ERR_CONNECTION_FAILED: "database connection could not be established",
    ERR_CONNECTION_CLOSED: "the connection is not open",
    ERR_SSH_TUNNEL_FAILED: "ssh tunnel could not be established",
    ERR_ENGINE_UNSUPPORTED: "engine is not supported by this build",
    ERR_DRIVER_MISSING: "driver package for this engine is not installed",
    ERR_QUERY_FAILED: "the query did not complete",
    ERR_QUERY_TIMEOUT: "the query exceeded its time budget",
    ERR_QUERY_CANCELED: "the query was canceled by the caller",
    ERR_SQL_SYNTAX: "the sql could not be parsed",
    ERR_AI_FAILED: "the ai provider rejected the request",
    ERR_AI_TRANSIENT: "the ai provider failed transiently",
    ERR_PLUGIN_FAILED: "a plugin raised an error",
    ERR_CONFIG_INVALID: "configuration value is invalid",
}

# ---- redaction -----------------------------------------------------------

_REDACT_TOKEN = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|api[_-]?key)\b(\s*[:=]\s*)(['\"]?)(\S+?)\3(?=\s|$|,)"
)
_REDACT_DSN = re.compile(r"(?i)(://[^@\s/]+):([^@\s]+)@")
_REDACT_BEARER = re.compile(r"(?i)\b(bearer)\s+\S+")


def redact(text: str) -> str:
    """Strip credentials out of ``text`` so it is safe to log or display.

    Handles ``password=x`` / ``password: x`` pairs, ``scheme://user:pass@host``
    credentials and ``Bearer <token>`` headers.  Returns the input unchanged
    for non-strings.
    """
    if not text:
        return ""
    out = str(text)
    out = _REDACT_TOKEN.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}***{m.group(3)}", out)
    out = _REDACT_DSN.sub(r"\1:***@", out)
    out = _REDACT_BEARER.sub(r"\1 ***", out)
    return out


class NavicatError(Exception):
    """Base class for every structured OpenNavicat error.

    Subclasses only need to set the class-level defaults below; they inherit
    ``to_dict`` / ``render`` / ``from_exception`` for free.
    """

    CODE: str = ERR_CONNECTION_FAILED
    MESSAGE_KEY: str = ""
    SOURCE: str = SOURCE_CONNECTION
    STAGE: str = STAGE_EXECUTE
    RECOVERABLE: bool = False
    RETRYABLE: bool = False

    def __init__(
        self,
        detail: str | None = None,
        code: str | None = None,
        *,
        message_key: str | None = None,
        source: str | None = None,
        stage: str | None = None,
        recoverable: bool | None = None,
        retryable: bool | None = None,
        from_exc: BaseException | None = None,
    ) -> None:
        self.code = code or self.CODE
        self.message_key = message_key or self.MESSAGE_KEY
        self.source = source or self.SOURCE
        self.stage = stage or self.STAGE
        self.recoverable = self.RECOVERABLE if recoverable is None else recoverable
        self.retryable = self.RETRYABLE if retryable is None else retryable
        self.detail = redact(detail or ERROR_CATALOG.get(self.code, ""))
        self.raw: BaseException | None = from_exc
        super().__init__(self.detail)

    # ---- rendering ----

    def __str__(self) -> str:  # noqa: D105 - keep plain text for log callers
        return self.detail

    def render(self) -> str:
        """Single-line, code-prefixed form for CLI output."""
        return f"[{self.code}] {self.detail}"

    def to_dict(self) -> dict[str, Any]:
        """Stable JSON payload shared by CLI / GUI / MCP."""
        payload: dict[str, Any] = {
            "version": ERROR_CONTRACT_VERSION,
            "code": self.code,
            "messageKey": self.message_key,
            "detail": self.detail,
            "source": self.source,
            "stage": self.stage,
            "recoverable": self.recoverable,
            "retryable": self.retryable,
        }
        if self.raw is not None:
            payload["rawType"] = type(self.raw).__name__
            raw = redact(str(self.raw))
            if raw and raw != self.detail:
                payload["raw"] = raw[:300]
        return payload

    def user_message(self) -> str:
        """Text safe to show verbatim in a UI."""
        return self.detail

    # ---- construction helpers ----

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        *,
        source: str = SOURCE_QUERY,
        stage: str = STAGE_EXECUTE,
    ) -> NavicatError:
        """Best-effort conversion of an arbitrary exception into a typed error.

        Never raises: if ``exc`` is already a :class:`NavicatError` it is
        returned unchanged, otherwise it is wrapped in the narrowest matching
        subclass so callers can branch on ``code``.
        """
        if isinstance(exc, NavicatError):
            return exc
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
            return QueryTimeoutError(redact(str(exc)), source=source, stage=stage, from_exc=exc)
        if isinstance(exc, asyncio.CancelledError):
            return QueryCanceledError(redact(str(exc)), source=source, stage=stage, from_exc=exc)
        if isinstance(exc, ImportError):
            if isinstance(exc, ModuleNotFoundError):
                return DriverNotFoundError(
                    f"driver package missing: {redact(str(exc))}",
                    source=SOURCE_DRIVER,
                    stage=STAGE_IMPORT,
                    from_exc=exc,
                )
            return DriverNotFoundError(
                redact(str(exc)), source=SOURCE_DRIVER, stage=STAGE_IMPORT, from_exc=exc
            )
        if isinstance(exc, ConnectionError):
            return DatabaseConnectionError(
                redact(str(exc)), source=source, stage=STAGE_CONNECT, from_exc=exc
            )
        if isinstance(exc, OSError):
            return DatabaseConnectionError(
                redact(str(exc)), source=source, stage=STAGE_CONNECT, from_exc=exc
            )
        if isinstance(exc, SyntaxError):
            return SQLError(redact(str(exc)), source=SOURCE_SQL, stage=STAGE_PARSE, from_exc=exc)
        if stage == STAGE_CONNECT:
            return DatabaseConnectionError(
                redact(str(exc)), source=source, stage=STAGE_CONNECT, from_exc=exc
            )
        return QueryExecutionError(redact(str(exc)), source=source, stage=stage, from_exc=exc)


class DatabaseConnectionError(NavicatError):
    """The database connection could not be established."""

    CODE = ERR_CONNECTION_FAILED
    SOURCE = SOURCE_CONNECTION
    STAGE = STAGE_CONNECT


class ConnectionClosedError(NavicatError):
    """An operation asked for a connection that is not open."""

    CODE = ERR_CONNECTION_CLOSED
    MESSAGE_KEY = "connection.closed"
    SOURCE = SOURCE_CONNECTION
    STAGE = STAGE_CONNECT
    RECOVERABLE = True
    RETRYABLE = True


class SSHTunnelError(NavicatError):
    """The ssh tunnel in front of the database could not be opened."""

    CODE = ERR_SSH_TUNNEL_FAILED
    SOURCE = SOURCE_CONNECTION
    STAGE = STAGE_CONNECT


class EngineNotSupportedError(NavicatError):
    """The requested engine is not part of this build's registry."""

    CODE = ERR_ENGINE_UNSUPPORTED
    SOURCE = SOURCE_DRIVER
    STAGE = STAGE_RESOLVE


class DriverNotFoundError(NavicatError):
    """The optional driver package for a supported engine is not installed."""

    CODE = ERR_DRIVER_MISSING
    SOURCE = SOURCE_DRIVER
    STAGE = STAGE_IMPORT


class QueryExecutionError(NavicatError):
    """The query ran but did not complete successfully."""

    CODE = ERR_QUERY_FAILED
    SOURCE = SOURCE_QUERY
    STAGE = STAGE_EXECUTE


class QueryTimeoutError(NavicatError):
    """The query exceeded its time budget."""

    CODE = ERR_QUERY_TIMEOUT
    SOURCE = SOURCE_QUERY
    STAGE = STAGE_EXECUTE
    RETRYABLE = True


class QueryCanceledError(NavicatError):
    """The caller canceled the query before it finished."""

    CODE = ERR_QUERY_CANCELED
    SOURCE = SOURCE_QUERY
    STAGE = STAGE_EXECUTE
    RECOVERABLE = True
    RETRYABLE = True


class SQLError(NavicatError):
    """The SQL could not be parsed or is not valid for the target dialect."""

    CODE = ERR_SQL_SYNTAX
    SOURCE = SOURCE_SQL
    STAGE = STAGE_PARSE


class PluginError(NavicatError):
    """A plugin raised an error during load or execution."""

    CODE = ERR_PLUGIN_FAILED
    SOURCE = SOURCE_PLUGIN
    STAGE = STAGE_LOAD


class ConfigError(NavicatError):
    """A configuration value is missing or invalid."""

    CODE = ERR_CONFIG_INVALID
    SOURCE = SOURCE_CONFIG


class AIError(NavicatError):
    """The AI provider rejected the request (auth, unknown model, bad input)."""

    CODE = ERR_AI_FAILED
    SOURCE = SOURCE_AI
    STAGE = STAGE_REQUEST


class AITransientError(AIError):
    """Transient AI failure that may succeed on retry (timeout, rate limit)."""

    CODE = ERR_AI_TRANSIENT
    STAGE = STAGE_REQUEST
    RETRYABLE = True


__all__ = [
    "ERROR_CONTRACT_VERSION",
    "ERROR_CATALOG",
    "STAGE_CONNECT",
    "STAGE_EXECUTE",
    "STAGE_IMPORT",
    "STAGE_LOAD",
    "STAGE_PARSE",
    "STAGE_REQUEST",
    "STAGE_RESOLVE",
    "SOURCE_AI",
    "SOURCE_CONFIG",
    "SOURCE_CONNECTION",
    "SOURCE_DRIVER",
    "SOURCE_PLUGIN",
    "SOURCE_QUERY",
    "SOURCE_SQL",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_FAILED",
    "ERR_CONFIG_INVALID",
    "ERR_DRIVER_MISSING",
    "ERR_ENGINE_UNSUPPORTED",
    "ERR_PLUGIN_FAILED",
    "ERR_QUERY_CANCELED",
    "ERR_QUERY_FAILED",
    "ERR_QUERY_TIMEOUT",
    "ERR_SSH_TUNNEL_FAILED",
    "ERR_SQL_SYNTAX",
    "ERR_AI_FAILED",
    "ERR_AI_TRANSIENT",
    "NavicatError",
    "AIError",
    "AITransientError",
    "ConfigError",
    "ConnectionClosedError",
    "DatabaseConnectionError",
    "DriverNotFoundError",
    "EngineNotSupportedError",
    "PluginError",
    "QueryCanceledError",
    "QueryExecutionError",
    "QueryTimeoutError",
    "SQLError",
    "SSHTunnelError",
    "redact",
]
