"""Protocol-level tests: the same tools behind an MCP server object.

``call_tool`` is the entry point the SDK reaches for when a client asks for a
tool, so these tests cover the hand-off the unit tests cannot: worker thread in,
service thread out, JSON on the wire.
"""

# ruff: noqa: F811

from __future__ import annotations

import json
import logging
import sys
import threading
from typing import Any, Iterator

import pytest

# Importing the fakes' fixtures is what makes them available to this module.
# F811 is suppressed file-wide: those same names are test parameters, which
# is how a test asks for a fixture.
from mcp_fakes import engine, manager, metadata  # noqa: F401

from open_navicat.errors import PolicyDeniedError
from open_navicat.mcp import safety, tools
from open_navicat.mcp import server as mcp_server
from open_navicat.mcp.runner import service_runner

# ``open_navicat.mcp.server`` imports the SDK lazily, so this module still
# collects in a bare install and skips only when a test needs the SDK.
pytest.importorskip("mcp", reason="the MCP server needs the [mcp] extra")


@pytest.fixture(autouse=True)
def _restore_policy() -> Iterator[None]:
    ceiling = tools.max_tier
    try:
        yield
    finally:
        tools.max_tier = ceiling


@pytest.fixture()
def server(manager, metadata, engine) -> Any:
    """A server wired to the fakes, but on the real service thread."""
    return mcp_server.build_server(safety.TIER_SAFE_WRITE)


def _payload(result: Any) -> dict[str, Any]:
    """Read one tool result the way an MCP client does."""
    assert not result.is_error
    return json.loads(result.content[0].text)


async def _call(server: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _payload(await server.call_tool(name, arguments))


class TestSurface:
    async def test_every_tool_is_exposed_with_a_schema(self, server: Any) -> None:
        listed = await server.list_tools()
        assert [t.name for t in listed] == [t.__name__ for t in tools.TOOLS]
        for tool in listed:
            assert tool.description
            assert tool.input_schema["type"] == "object"

    async def test_execute_query_publishes_its_arguments(self, server: Any) -> None:
        listed = {t.name: t for t in await server.list_tools()}
        properties = listed["execute_query"].input_schema["properties"]
        assert set(properties) == {
            "sql",
            "connection_id",
            "tier",
            "limit",
            "timeout",
            "dry_run",
            "confirm",
            "mask",
        }
        assert listed["execute_query"].input_schema["required"] == ["sql"]

    def test_instructions_state_the_rules(self) -> None:
        assert "dry_run" in mcp_server.INSTRUCTIONS
        assert "tier" in mcp_server.INSTRUCTIONS

    def test_an_unknown_ceiling_is_refused_not_widened(self) -> None:
        with pytest.raises(PolicyDeniedError):
            mcp_server.build_server("everything")


class TestCalls:
    async def test_read_runs_on_the_service_thread(self, server: Any, engine) -> None:
        seen: list[str] = []
        original = engine.execute

        def spy(cid: str, sql: str, timeout: Any = None, **kwargs: Any) -> Any:
            seen.append(threading.current_thread().name)
            return original(cid, sql, timeout, **kwargs)

        engine.execute = spy  # type: ignore[method-assign]
        payload = await _call(server, "execute_query", {"sql": "SELECT id, total FROM orders"})
        assert payload["ok"] is True
        assert payload["rows"] == [[1, "10.50"]]
        # Not the caller's thread and not an SDK worker: the loop has one owner.
        assert seen == [service_runner.submit(lambda: threading.current_thread().name)]

    async def test_session_tools_answer_over_the_wire(self, server: Any) -> None:
        payload = await _call(server, "list_connections", {})
        assert payload["connections"][0]["id"] == "c1"
        assert "hunter2" not in json.dumps(payload)

    async def test_policy_refusal_is_a_result_not_a_protocol_error(self, server: Any) -> None:
        payload = await _call(server, "execute_query", {"sql": "DROP TABLE users"})
        assert payload["ok"] is False
        assert payload["error"]["code"] == "ONV-SEC-001"

    async def test_dry_run_needs_no_permission_beyond_reading(self, server: Any, engine) -> None:
        payload = await _call(
            server,
            "execute_query",
            {"sql": "DELETE FROM users WHERE id = 5", "tier": "read", "dry_run": True},
        )
        assert payload["ok"] is True
        assert payload["executed"] is False
        assert engine.calls and "DELETE" not in engine.calls[0][1]

    async def test_a_missing_session_comes_back_as_data(self, server: Any) -> None:
        payload = await _call(server, "list_tables", {"connection_id": "nope"})
        assert payload["ok"] is False
        assert payload["error"]["code"] == "ONV-CNN-002"

    async def test_the_operator_ceiling_beats_the_client_request(self, server: Any) -> None:
        tools.max_tier = safety.TIER_READ
        payload = await _call(
            server, "execute_query", {"sql": "UPDATE t SET a = 1 WHERE id = 2", "tier": "full"}
        )
        assert payload["ok"] is False
        assert payload["policy"]["tier"] == "read"
        assert "capped" in " ".join(payload["policy"]["reasons"])


class TestStdout:
    """One stray log line on stdout breaks the protocol for the whole session."""

    def test_a_fresh_logger_writes_to_stderr(self, monkeypatch) -> None:
        monkeypatch.setattr(logging.root, "handlers", [])
        mcp_server._route_logs_to_stderr()
        assert logging.root.handlers[0].stream is sys.stderr

    def test_an_existing_handler_is_repointed(self, monkeypatch) -> None:
        stdout_handler = logging.StreamHandler(sys.stdout)
        monkeypatch.setattr(logging.root, "handlers", [stdout_handler])
        mcp_server._route_logs_to_stderr()
        assert stdout_handler.stream is sys.stderr
        assert logging.root.handlers == [stdout_handler]
