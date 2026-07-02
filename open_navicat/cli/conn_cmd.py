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


# ── Import / Export ─────────────────────────────────────────────────────────

@conn_app.command("export")
def export_connection(
    name: str = typer.Argument(..., help="Connection name to export"),
    output: str = typer.Option("", "--output", "-o", help="Output file path (default: {name}.json)"),
) -> None:
    """Export a connection to JSON."""
    import json

    from open_navicat.dal.local_config import local_db
    connections = connection_manager.list_saved()
    target = next((c for c in connections if c.name == name), None)
    if not target:
        console.print(f"[red]Connection '{name}' not found.[/red]")
        raise typer.Exit(1)

    path = output or f"{name}.json"
    cfg = {
        "name": target.name,
        "host": target.host,
        "port": target.port,
        "user": target.user,
        "password": target.password,
        "database": target.database,
        "charset": target.charset,
        "use_ssh": target.use_ssh,
        "ssh_host": target.ssh_host,
        "ssh_port": target.ssh_port,
        "ssh_user": target.ssh_user,
        "ssh_password": target.ssh_password,
        "ssh_key_file": target.ssh_key_file,
        "use_ssl": target.use_ssl,
        "ssl_ca": target.ssl_ca,
        "ssl_cert": target.ssl_cert,
        "ssl_key": target.ssl_key,
        "color": target.color,
        "group": target.group,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    console.print(f"[green]✓ Connection '{name}' exported to {path}.[/green]")


@conn_app.command("import")
def import_connection(
    file: str = typer.Argument(..., help="JSON file path to import"),
    test: bool = typer.Option(False, "--test", "-t", help="Test connection before saving"),
) -> None:
    """Import a connection from JSON."""
    import json

    from open_navicat.dal.local_config import local_db
    from open_navicat.models.connection import ConnectionInfo

    with open(file, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    info = ConnectionInfo(
        name=cfg.get("name", "Imported"),
        host=cfg.get("host", "localhost"),
        port=int(cfg.get("port", 3306)),
        user=cfg.get("user", "root"),
        password=cfg.get("password", ""),
        database=cfg.get("database", ""),
        charset=cfg.get("charset", "utf8mb4"),
        use_ssh=cfg.get("use_ssh", False),
        ssh_host=cfg.get("ssh_host", ""),
        ssh_port=int(cfg.get("ssh_port", 22)),
        ssh_user=cfg.get("ssh_user", ""),
        ssh_password=cfg.get("ssh_password", ""),
        ssh_key_file=cfg.get("ssh_key_file", ""),
        use_ssl=cfg.get("use_ssl", False),
        ssl_ca=cfg.get("ssl_ca", ""),
        ssl_cert=cfg.get("ssl_cert", ""),
        ssl_key=cfg.get("ssl_key", ""),
        color=cfg.get("color", "#4A90D9"),
        group=cfg.get("group", ""),
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

    local_db.save_connection(info)
    console.print(f"[green]✓ Connection '{info.name}' imported from {file}.[/green]")


# ── Connection groups ──────────────────────────────────────────────────────

group_app = typer.Typer(name="group", help="Manage connection groups", no_args_is_help=True)
conn_app.add_typer(group_app)


@group_app.command("list")
def list_groups(
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
) -> None:
    """List all connection groups."""
    from open_navicat.dal.local_config import local_db
    groups = local_db.list_groups()
    if not groups:
        console.print("[yellow]No connection groups found.[/yellow]")
        raise typer.Exit()

    rows = []
    for g in groups:
        count = len(local_db.list_connections(group=g))
        rows.append({"name": g, "connections": count})
    format_output(rows, format, title="Connection Groups")


@group_app.command("rename")
def rename_group(
    name: str = typer.Argument(..., help="Current group name"),
    new_name: str = typer.Argument(..., help="New group name"),
) -> None:
    """Rename a connection group."""
    from open_navicat.dal.local_config import local_db
    local_db.rename_group(name, new_name)
    console.print(f"[green]✓ Group '{name}' renamed to '{new_name}'.[/green]")


@group_app.command("delete")
def delete_group(
    name: str = typer.Argument(..., help="Group name to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Delete without confirmation"),
) -> None:
    """Delete a connection group (connections become ungrouped)."""
    from open_navicat.dal.local_config import local_db
    if not force:
        confirm = typer.confirm(f"Delete group '{name}'? Connections will be ungrouped.")
        if not confirm:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit()
    local_db.delete_group(name)
    console.print(f"[green]✓ Group '{name}' deleted.[/green]")
