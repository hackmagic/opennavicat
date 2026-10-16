"""MCP protocol adapter — the only module here that imports the ``mcp`` SDK.

The split matters: :mod:`open_navicat.mcp.tools` holds the behaviour and stays
plain Python, so a policy change never needs an MCP client in the loop, and this
file stays the single place that can break because the SDK changed its mind.

The SDK dispatches synchronous tools on *arbitrary* worker threads, which is why
:mod:`open_navicat.mcp.runner` exists: every call it forwards lands on the one
thread that owns the services' event loop.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from open_navicat import __version__
from open_navicat.mcp import safety, tools
from open_navicat.mcp.runner import service_runner

#: Shown when the optional dependency is absent.
INSTALL_HINT = "the MCP server needs the mcp package: pip install open-navicat[mcp]"

#: Sent to the client at handshake time.  This is the text a model reads before
#: it starts calling tools, so the rules it must follow are stated here as well
#: as in each tool's own description.
INSTRUCTIONS = """OpenNavicat exposes live databases through a policy the caller does not control.

- Call list_connections and then open_session first; every other tool needs an
  open session, one per database.
- execute_query runs under the 'read' tier unless told otherwise, so statements
  that change data are refused there. Request tier='safe-write' or 'full' only
  after the human agreed, and pass dry_run=true first to see what a write hits.
- dry_run never executes anything and works at every tier; confirm only matters
  together with a tier that allows the change.
- The server caps the tier a client may request. A refusal names the tier that
  is actually in force; re-read it instead of retrying.
- Every response carries the connection, engine and database it came from.
  Quote that provenance back before acting on the rows.
"""


def build_server(access: str = safety.TIER_READ) -> Any:
    """Create the MCP server exposing :data:`open_navicat.mcp.tools.TOOLS`.

    ``access`` is the operator's ceiling, not a suggestion: a client asking for
    a wider tier is capped by :func:`open_navicat.mcp.tools._gate`.  A tier
    spelled wrong raises rather than defaulting to something wider.
    """
    try:
        from mcp.server import MCPServer
    except ImportError as exc:  # pragma: no cover - depends on the extra
        raise ImportError(INSTALL_HINT) from exc

    tools.max_tier = safety.normalize_tier(access)

    server = MCPServer(
        name="opennavicat",
        version=__version__,
        instructions=INSTRUCTIONS,
    )
    for tool in tools.TOOLS:
        # Registered as-is on purpose: the SDK reads the signature to build the
        # input schema and copies the docstring into the description, so wrapping
        # a tool here would hide the arguments it actually takes.
        server.tool()(tool)
    return server


def _route_logs_to_stderr() -> None:
    """Keep stdout free for JSON-RPC.

    A single stray log line on stdout breaks the protocol for the whole session,
    and library defaults (or an already-configured root logger) like to write
    there.
    """
    for handler in logging.root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(sys.stderr)
            return
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)


def serve(access: str = safety.TIER_READ, transport: str = "stdio") -> None:
    """Run the server until the client disconnects."""
    _route_logs_to_stderr()
    server = build_server(access)
    service_runner.start()
    try:
        server.run(transport=transport)
    finally:
        service_runner.stop()


__all__ = ["INSTRUCTIONS", "INSTALL_HINT", "build_server", "serve"]
