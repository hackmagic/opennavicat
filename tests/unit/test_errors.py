"""Tests for the unified error model (open_navicat.errors)."""

from __future__ import annotations

import asyncio

import pytest

from open_navicat.errors import (
    ERR_AI_TRANSIENT,
    ERR_DRIVER_MISSING,
    ERR_ENGINE_UNSUPPORTED,
    ERR_QUERY_CANCELED,
    ERR_QUERY_FAILED,
    ERR_QUERY_TIMEOUT,
    ERR_SQL_SYNTAX,
    ERROR_CATALOG,
    ERROR_CONTRACT_VERSION,
    AIError,
    AITransientError,
    DriverNotFoundError,
    EngineNotSupportedError,
    NavicatError,
    QueryCanceledError,
    QueryExecutionError,
    QueryTimeoutError,
    SQLError,
    redact,
)


class TestRedaction:
    def test_masks_kv_pairs(self) -> None:
        assert "password=***" in redact("connecting password=secret123 done")

    def test_masks_dsn_credentials(self) -> None:
        assert redact("mysql://root:hunter2@db:3306/x") == "mysql://root:***@db:3306/x"

    def test_masks_bearer_token(self) -> None:
        assert "bearer ***" in redact("Authorization: bearer abc.def.ghi")

    def test_masks_scheme_less_userinfo(self) -> None:
        assert redact("okpw:SECRET@h:1/db") == "okpw:***@h:1/db"

    def test_masks_jdbc_url(self) -> None:
        assert redact("jdbc:postgresql://user:pw@h:5432/db") == (
            "jdbc:postgresql://user:***@h:5432/db"
        )

    def test_leaves_bare_user_without_password(self) -> None:
        assert redact("user@h:1/db") == "user@h:1/db"

    def test_leaves_ordinary_sql(self) -> None:
        sql = "SELECT id, password FROM users WHERE password IS NOT NULL"
        assert redact(sql) == sql

    def test_empty_and_none(self) -> None:
        assert redact("") == ""
        assert redact(None) == ""

    def test_preserves_non_secret_sql(self) -> None:
        sql = "SELECT password FROM users WHERE id=1"
        # `password` here is a column reference with no assignment, so it stays.
        assert "SELECT password FROM users" in redact(sql)


class TestContract:
    def test_defaults_from_subclass(self) -> None:
        err = QueryTimeoutError("boom")
        assert err.code == ERR_QUERY_TIMEOUT
        assert err.source == "query"
        assert err.stage == "execute"
        assert err.retryable is True
        assert err.recoverable is False

    def test_recoverable_flag_for_cancellation(self) -> None:
        err = QueryCanceledError("stopped")
        assert err.recoverable is True
        assert err.retryable is True

    def test_override_wins(self) -> None:
        err = QueryTimeoutError("boom", retryable=False)
        assert err.retryable is False

    def test_detail_falls_back_to_catalog(self) -> None:
        err = NavicatError(code=ERR_ENGINE_UNSUPPORTED, source="driver", stage="resolve")
        assert err.detail == ERROR_CATALOG[ERR_ENGINE_UNSUPPORTED]

    def test_to_dict_payload(self) -> None:
        payload = QueryTimeoutError("slow").to_dict()
        assert payload["version"] == ERROR_CONTRACT_VERSION
        assert payload["code"] == ERR_QUERY_TIMEOUT
        assert payload["detail"] == "slow"
        assert payload["source"] == "query"
        assert payload["stage"] == "execute"
        assert set(payload) == {
            "version",
            "code",
            "messageKey",
            "detail",
            "source",
            "stage",
            "recoverable",
            "retryable",
        }

    def test_to_dict_includes_raw_type(self) -> None:
        err = QueryTimeoutError("slow", from_exc=asyncio.TimeoutError("inner"))
        payload = err.to_dict()
        assert payload["rawType"] == "TimeoutError"
        assert payload["raw"] == "inner"

    def test_str_is_detail_only(self) -> None:
        # Existing log/CLI callers use str(e); keep that plain.
        assert str(QueryExecutionError("bad sql")) == "bad sql"
        assert QueryExecutionError("bad sql").render() == "[ONV-QRY-001] bad sql"

    def test_user_message_equals_detail(self) -> None:
        err = QueryExecutionError("bad sql")
        assert err.user_message() == err.detail == "bad sql"

    def test_render_prefixes_code(self) -> None:
        err = SQLError("syntax")
        assert err.render() == "[ONV-SQL-001] syntax"
        assert err.code == ERR_SQL_SYNTAX

    def test_detail_is_redacted_on_construction(self) -> None:
        err = QueryExecutionError("mysql://root:hunter2@db password=xyz")
        assert "hunter2" not in err.detail
        assert "xyz" not in err.detail
        assert "mysql://root:***@db" in err.detail

    def test_ai_errors_are_ai_domain(self) -> None:
        assert AIError("nope").source == "ai"
        assert AIError("nope").stage == "request"
        assert AITransientError("429").code == ERR_AI_TRANSIENT
        assert AITransientError("429").retryable is True
        # Transient is still an AIError for existing `except AIError` blocks.
        assert isinstance(AITransientError("429"), AIError)


class TestFromException:
    def test_native_errors_return_unchanged(self) -> None:
        err = QueryTimeoutError("slow")
        assert NavicatError.from_exception(err) is err

    def test_timeout(self) -> None:
        assert NavicatError.from_exception(asyncio.TimeoutError("t")).code == ERR_QUERY_TIMEOUT

    def test_timeouterror_aliased(self) -> None:
        assert NavicatError.from_exception(TimeoutError("t")).code == ERR_QUERY_TIMEOUT

    def test_cancelled(self) -> None:
        assert NavicatError.from_exception(asyncio.CancelledError()).code == ERR_QUERY_CANCELED

    def test_import_error(self) -> None:
        err = NavicatError.from_exception(ImportError("no module"))
        assert err.code == ERR_DRIVER_MISSING
        assert err.source == "driver"
        assert err.stage == "import"

    def test_connection_error(self) -> None:
        err = NavicatError.from_exception(ConnectionRefusedError("refused"))
        assert err.code.startswith("ONV-CNN-")
        assert err.stage == "connect"

    def test_os_error(self) -> None:
        assert NavicatError.from_exception(OSError("net")).stage == "connect"

    def test_syntax_error(self) -> None:
        err = NavicatError.from_exception(SyntaxError("bad"))
        assert err.code == ERR_SQL_SYNTAX
        assert err.stage == "parse"

    def test_generic_exception_becomes_query_failed(self) -> None:
        err = NavicatError.from_exception(RuntimeError("wat"))
        assert err.code == ERR_QUERY_FAILED
        assert err.stage == "execute"

    def test_raw_is_kept(self) -> None:
        original = ConnectionRefusedError("refused")
        err = NavicatError.from_exception(original)
        assert err.raw is original

    def test_never_raises(self) -> None:
        for exc in (KeyError("k"), ValueError("v"), SystemExit, asyncio.CancelledError()):
            assert isinstance(NavicatError.from_exception(exc), NavicatError)

    def test_engine_and_driver_are_not_query_errors(self) -> None:
        with pytest.raises(EngineNotSupportedError):
            raise EngineNotSupportedError("x")
        with pytest.raises(DriverNotFoundError):
            raise DriverNotFoundError("y")
