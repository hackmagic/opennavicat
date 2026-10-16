"""MCP server command — expose OpenNavicat as tools for an AI client."""

from __future__ import annotations

import typer
from rich.console import Console

from open_navicat.errors import NavicatError
from open_navicat.mcp import safety

mcp_app = typer.Typer(
    name="mcp",
    help="Run the MCP server that lets AI clients use these databases",
    no_args_is_help=True,
)
console = Console()

_ACCESS_HELP = (
    "Widest access a client may ask for: 'read' runs queries only, "
    "'safe-write' adds row-scoped writes it confirms, 'full' adds destructive "
    "ones.  A client cannot widen this."
)


@mcp_app.command("serve")
def serve(
    access: str = typer.Option(safety.TIER_READ, "--access", help=_ACCESS_HELP),
    transport: str = typer.Option("stdio", "--transport", help="stdio (the only one in v1)"),
) -> None:
    """Serve the MCP tools over stdio until the client disconnects.

    The server holds no connections of its own: a client opens sessions with the
    ``open_session`` tool, and those sessions live for this process.
    """
    from open_navicat.mcp import server as mcp_server

    try:
        ceiling = safety.normalize_tier(access)
    except NavicatError as err:
        console.print(f"[red]x {err.detail}[/red]")
        raise typer.Exit(2) from err

    try:
        mcp_server.serve(access=ceiling, transport=transport)
    except ImportError as err:
        console.print(f"[red]x {err}[/red]")
        raise typer.Exit(1) from err
    except KeyboardInterrupt:  # pragma: no cover - the client decides when to stop
        console.print("[yellow]! mcp server interrupted[/yellow]")
