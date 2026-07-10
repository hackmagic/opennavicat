"""Community templates — generate and list starter templates."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

template_app = typer.Typer(help="List and generate community templates")
console = Console()

_TEMPLATES: dict[str, str] = {
    "daily_backup.sh": "Bash daily backup script with 7-day rotation",
    "daily_backup.ps1": "PowerShell daily backup script with 7-day rotation",
    "docker-compose.yml": "Docker Compose with MySQL 8 + PostgreSQL 16 + OpenNavicat",
}


@template_app.command("list")
def template_list() -> None:
    """List available community templates."""
    table = Table(title="Available Templates")
    table.add_column("Template", style="cyan")
    table.add_column("Description", style="white")
    for name, desc in _TEMPLATES.items():
        table.add_row(name, desc)
    console.print(table)


@template_app.command("generate")
def template_generate(
    name: str = typer.Argument(..., help="Template name (see 'template list')"),
    output: str = typer.Option(".", "--output", "-o", help="Output directory"),
) -> None:
    """Generate a community template file."""
    if name not in _TEMPLATES:
        console.print(f"[red]Unknown template '{name}'[/red]")
        console.print("Run [bold]opennavicat template list[/bold] to see available templates.")
        raise typer.Exit(1)

    src = Path(__file__).parent.parent / "templates" / name
    dst = Path(output) / name

    if not src.exists():
        console.print(f"[red]Template source not found: {src}[/red]")
        raise typer.Exit(1)

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    console.print(f"[green]✓[/green] Generated [bold]{name}[/bold] → {dst}")
