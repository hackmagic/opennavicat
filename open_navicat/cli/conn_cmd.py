"""Connection management CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console

from open_navicat.models.connection import ConnectionInfo
from open_navicat.services.connection_manager import connection_manager
from open_navicat.utils.output_formatter import format_output

conn_app = typer.Typer(name="conn", help="Manage database connections", no_args_is_help=True)
console = Console()


@conn_app.command("list")
def list_connections(
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
) -> None:
    """List all saved connections."""
    connections = connection_manager.list_saved()
    if not connections:
        console.print("[yellow]No saved connections found.[/yellow]")
        raise typer.Exit()

    rows = [
        {"id": c.id, "name": c.name or "-", "host": c.host, "port": c.port,
         "user": c.user, "database": c.database or "-", "ssh": "✓" if c.use_ssh else "",
         "active": "✓" if c.id in connection_manager.active_ids else ""}
        for c in connections
    ]
    format_output(rows, format, title="Saved Connections")


@conn_app.command("add")
def add_connection(
    name: str = typer.Option(..., "--name", "-n", help="Connection name"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Database host"),
    port: int = typer.Option(3306, "--port", "-p", help="Database port"),
    user: str = typer.Option("root", "--user", "-u", help="Database user"),
    password: str = typer.Option("", "--password", "-P", help="Database password", hide_input=True),
    database: str = typer.Option("", "--database", "-d", help="Default database"),
    charset: str = typer.Option("utf8mb4", "--charset", "-c", help="Connection charset"),
    ssh_host: str = typer.Option("", "--ssh-host", help="SSH tunnel host"),
    ssh_port: int = typer.Option(22, "--ssh-port", help="SSH tunnel port"),
    ssh_user: str = typer.Option("", "--ssh-user", help="SSH tunnel user"),
    ssh_password: str = typer.Option("", "--ssh-password", help="SSH tunnel password", hide_input=True),
    ssh_key: str = typer.Option("", "--ssh-key", help="SSH private key file path"),
    test: bool = typer.Option(False, "--test", "-t", help="Test connection before saving"),
) -> None:
    """Add and save a new database connection."""
    info = ConnectionInfo(
        name=name, host=host, port=port, user=user, password=password,
        database=database, charset=charset,
        use_ssh=bool(ssh_host), ssh_host=ssh_host, ssh_port=ssh_port,
        ssh_user=ssh_user, ssh_password=ssh_password, ssh_key_file=ssh_key,
    )

    if test:
        console.print("[yellow]Testing connection...[/yellow]")
        success = connection_manager.connect(info)
        if success:
            connection_manager.disconnect(info.id)
            console.print("[green]✓ Connection test successful![/green]")
        else:
            console.print("[red]✗ Connection failed![/red]")
            raise typer.Exit(1)

    from open_navicat.dal.local_config import local_db
    local_db.save_connection(info)
    console.print(f"[green]✓ Connection '{name}' saved.[/green]")


@conn_app.command("edit")
def edit_connection(
    name: str = typer.Argument(..., help="Connection name to edit"),
    new_name: str = typer.Option("", "--name", "-n", help="New connection name"),
    host: str = typer.Option("", "--host", "-h", help="New host"),
    port: int = typer.Option(0, "--port", "-p", help="New port"),
    user: str = typer.Option("", "--user", "-u", help="New user"),
    password: str = typer.Option("", "--password", "-P", help="New password", hide_input=True),
    database: str = typer.Option("", "--database", "-d", help="New default database"),
) -> None:
    """Edit an existing connection."""
    connections = connection_manager.list_saved()
    target = next((c for c in connections if c.name == name), None)
    if not target:
        console.print(f"[red]Connection '{name}' not found.[/red]")
        raise typer.Exit(1)

    if new_name:
        target.name = new_name
    if host:
        target.host = host
    if port:
        target.port = port
    if user:
        target.user = user
    if password:
        target.password = password
    if database:
        target.database = database

    from open_navicat.dal.local_config import local_db
    local_db.save_connection(target)
    console.print(f"[green]✓ Connection '{name}' updated.[/green]")


@conn_app.command("remove")
def remove_connection(
    name: str = typer.Argument(..., help="Connection name to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Force remove without confirmation"),
) -> None:
    """Remove a saved connection."""
    connections = connection_manager.list_saved()
    target = next((c for c in connections if c.name == name), None)
    if not target:
        console.print(f"[red]Connection '{name}' not found.[/red]")
        raise typer.Exit(1)

    if not force:
        confirm = typer.confirm(f"Delete connection '{name}'?")
        if not confirm:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit()

    connection_manager.delete_saved(target.id)
    console.print(f"[green]✓ Connection '{name}' removed.[/green]")


@conn_app.command("test")
def test_connection(
    name: str = typer.Argument(..., help="Connection name to test"),
) -> None:
    """Test a saved connection."""
    connections = connection_manager.list_saved()
    target = next((c for c in connections if c.name == name), None)
    if not target:
        console.print(f"[red]Connection '{name}' not found.[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Testing connection '{name}'...[/yellow]")
    success = connection_manager.connect(target)
    if success:
        connection_manager.disconnect(target.id)
        console.print(f"[green]✓ Connection to {target.host}:{target.port} successful![/green]")
    else:
        console.print(f"[red]✗ Connection to {target.host}:{target.port} failed![/red]")
        raise typer.Exit(1)


@conn_app.command("open")
def open_connection(
    name: str = typer.Argument(..., help="Connection name to open"),
) -> None:
    """Open (activate) a connection for use by other commands."""
    connections = connection_manager.list_saved()
    target = next((c for c in connections if c.name == name), None)
    if not target:
        console.print(f"[red]Connection '{name}' not found.[/red]")
        raise typer.Exit(1)

    success = connection_manager.connect(target)
    if success:
        console.print(f"[green]✓ Connected to {target.host}:{target.port} as {target.user}[/green]")
    else:
        console.print(f"[red]✗ Failed to connect to {target.host}:{target.port}[/red]")
        raise typer.Exit(1)


@conn_app.command("close")
def close_connection(
    name: str = typer.Argument("", help="Connection name to close (default: active connection)"),
) -> None:
    """Close an active connection."""
    if name:
        connections = connection_manager.list_saved()
        target = next((c for c in connections if c.name == name), None)
        if not target:
            console.print(f"[red]Connection '{name}' not found.[/red]")
            raise typer.Exit(1)
        cid = target.id
    else:
        active = connection_manager.active_ids
        if not active:
            console.print("[yellow]No active connections.[/yellow]")
            raise typer.Exit()
        cid = active[0]

    connection_manager.disconnect(cid)
    console.print("[green]✓ Connection closed.[/green]")
