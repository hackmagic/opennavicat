"""Cloud database discovery CLI commands."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

cloud_app = typer.Typer(name="cloud", help="Cloud database discovery", no_args_is_help=True)
console = Console()


@cloud_app.command("discover")
def cloud_discover(
    provider: str = typer.Option("aws", "--provider", "-p", help="Cloud provider"),
    region: str = typer.Option("", "--region", "-r", help="AWS region"),
) -> None:
    """Discover database instances from cloud providers."""
    from open_navicat.services.cloud_discovery import cloud_discovery

    console.print(f"[yellow]Scanning {provider} for database instances...[/yellow]")
    kwargs = {"aws": {"regions": [region] if region else None}}
    instances = cloud_discovery.discover_all(**kwargs)
    if not instances:
        console.print("[yellow]No instances found (cloud SDK not installed/configured).[/yellow]")
        return
    table = Table(title="Cloud Databases")
    table.add_column("Provider", style="cyan")
    table.add_column("Engine", style="green")
    table.add_column("Host", style="blue")
    table.add_column("Port")
    table.add_column("Status")
    for inst in instances:
        table.add_row(inst.provider, inst.engine, inst.host, str(inst.port), inst.status)
    console.print(table)
