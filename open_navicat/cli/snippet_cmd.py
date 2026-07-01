"""Snippet management CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from open_navicat.dal.local_config import local_db
from open_navicat.utils.output_formatter import format_output

snippet_app = typer.Typer(name="snippet", help="Manage reusable SQL snippets", no_args_is_help=True)
console = Console()


@snippet_app.command("list")
def list_snippets(
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
) -> None:
    """List all saved SQL snippets."""
    snippets = local_db.list_snippets()
    if not snippets:
        console.print("[yellow]No snippets saved.[/yellow]")
        raise typer.Exit()

    rows = []
    for s in snippets:
        sql_preview = s["sql_text"][:60] + "..." if len(s["sql_text"]) > 60 else s["sql_text"]
        rows.append({
            "id": s["id"],
            "name": s["name"],
            "sql": sql_preview,
            "description": s.get("description", "") or "-",
        })
    format_output(rows, format, title="SQL Snippets")


@snippet_app.command("add")
def add_snippet(
    name: str = typer.Argument(..., help="Snippet name"),
    sql: str = typer.Argument(..., help="SQL text"),
    description: str = typer.Option("", "--desc", "-d", help="Optional description"),
) -> None:
    """Add a new SQL snippet."""
    local_db.save_snippet(name, sql, description)
    console.print(f"[green]✓ Snippet '{name}' saved.[/green]")


@snippet_app.command("remove")
def remove_snippet(
    snippet_id: int = typer.Argument(..., help="Snippet ID to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Remove without confirmation"),
) -> None:
    """Remove a SQL snippet by ID."""
    if not force:
        confirm = typer.confirm(f"Delete snippet #{snippet_id}?")
        if not confirm:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit()
    local_db.delete_snippet(snippet_id)
    console.print(f"[green]✓ Snippet #{snippet_id} removed.[/green]")


@snippet_app.command("show")
def show_snippet(
    snippet_id: int = typer.Argument(..., help="Snippet ID"),
) -> None:
    """Show full content of a snippet by ID."""
    snippets = local_db.list_snippets()
    target = next((s for s in snippets if s["id"] == snippet_id), None)
    if not target:
        console.print(f"[red]Snippet #{snippet_id} not found.[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]Name:[/bold] {target['name']}")
    if target.get("description"):
        console.print(f"[bold]Description:[/bold] {target['description']}")
    console.print(f"[bold]SQL:[/bold]\n{target['sql_text']}")
