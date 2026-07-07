"""Main CLI application — typer entry point with all subcommand groups."""

from __future__ import annotations

import random

import typer
from rich.console import Console

from open_navicat.cli.ai_cmd import ai_app
from open_navicat.cli.backup_cmd import backup_app
from open_navicat.cli.cloud_cmd import cloud_app
from open_navicat.cli.conn_cmd import conn_app
from open_navicat.cli.data_cmd import data_app
from open_navicat.cli.init_cmd import init_app
from open_navicat.cli.query_cmd import query_app
from open_navicat.cli.schema_cmd import schema_app
from open_navicat.cli.snippet_cmd import snippet_app
from open_navicat.cli.sql_cmd import sql_app

app = typer.Typer(
    name="opennavicat",
    help="Open-source database administration tool — CLI-First, AI-Native",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register subcommand groups
app.add_typer(init_app, name="init", help="Interactive setup wizard")
app.add_typer(conn_app, name="conn", help="Connection management")
app.add_typer(query_app, name="query", help="SQL query execution & natural-language query")
app.add_typer(schema_app, name="schema", help="Database schema management & design")
app.add_typer(data_app, name="data", help="Data browse, export, import & sync")
app.add_typer(backup_app, name="backup", help="Backup, restore & scheduling")
app.add_typer(ai_app, name="ai", help="AI-powered database assistant")
app.add_typer(snippet_app, name="snippet", help="Manage reusable SQL snippets")
app.add_typer(cloud_app, name="cloud", help="Cloud database discovery")
app.add_typer(sql_app, name="sql", help="SQL dialect translation & optimization")

# Also register as top-level aliases for common operations
app.add_typer(ai_app, name="ask", help="Shortcut: AI ask (see 'ai' subcommand for full features)")

_FUN_FACTS = [
    "The first database management system, IMS, was created by IBM in 1966.",
    "MySQL was named after co-founder Monty Widenius's daughter, My.",
    "PostgreSQL was originally called Postgres at UC Berkeley in 1986.",
    "SQLite is the most widely deployed database engine — it's in every smartphone.",
    "The average DBA types 'SELECT *' 47 times per hour. Probably.",
    "DuckDB, the 'Duck of databases', is built for analytical queries on local data.",
    "There are over 350 database engines in the DB-Engines ranking.",
    "The 'SQL' in MySQL and NoSQL stands for the same thing: Structured Query Language.",
    "Redis means REmote DIctionary Server. It's not just a cache.",
    "MongoDB got its name from 'humongous' — because it handles huge data.",
]

console = Console()


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit"),
    fun: bool = typer.Option(False, "--fun", help="Show a random database fact"),
) -> None:
    """OpenNavicat — CLI-native database administration tool."""
    if version:
        from open_navicat import __version__
        typer.echo(f"OpenNavicat v{__version__}")
        raise typer.Exit()
    if fun:
        fact = random.choice(_FUN_FACTS)
        console.print(f"[bold cyan]🦆 Fun Fact:[/bold cyan] {fact}")
        raise typer.Exit()


def cli_main() -> None:
    """Entry point for CLI mode."""
    app()
