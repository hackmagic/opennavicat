"""Main CLI application — typer entry point with all subcommand groups."""

from __future__ import annotations

import typer

from open_navicat.cli.ai_cmd import ai_app
from open_navicat.cli.backup_cmd import backup_app
from open_navicat.cli.conn_cmd import conn_app
from open_navicat.cli.data_cmd import data_app
from open_navicat.cli.query_cmd import query_app
from open_navicat.cli.schema_cmd import schema_app

app = typer.Typer(
    name="opennavicat",
    help="Open-source database administration tool — CLI-First, AI-Native",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register subcommand groups
app.add_typer(conn_app, name="conn", help="Connection management")
app.add_typer(query_app, name="query", help="SQL query execution & natural-language query")
app.add_typer(schema_app, name="schema", help="Database schema management & design")
app.add_typer(data_app, name="data", help="Data browse, export, import & sync")
app.add_typer(backup_app, name="backup", help="Backup, restore & scheduling")
app.add_typer(ai_app, name="ai", help="AI-powered database assistant")

# Also register as top-level aliases for common operations
app.add_typer(ai_app, name="ask", help="Shortcut: AI ask (see 'ai' subcommand for full features)")

@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit"),
) -> None:
    """OpenNavicat — CLI-native database administration tool."""
    if version:
        from open_navicat import __version__
        typer.echo(f"OpenNavicat v{__version__}")
        raise typer.Exit()


def cli_main() -> None:
    """Entry point for CLI mode."""
    app()
