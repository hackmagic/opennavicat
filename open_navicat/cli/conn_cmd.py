"""Connection management CLI commands."""

from __future__ import annotations

import typer
from rich.console import Console

from open_navicat.drivers.dsn import dsn_to_connection
from open_navicat.drivers.registry import (
    SUPPORTED_ENGINES,
    get_spec,
    is_available,
    is_file_engine,
    normalize_engine,
    supported_engines,
)
from open_navicat.errors import ConfigError, NavicatError
from open_navicat.models.connection import ConnectionInfo
from open_navicat.services.connection_manager import connection_manager
from open_navicat.utils.output_formatter import format_output

conn_app = typer.Typer(name="conn", help="Manage database connections", no_args_is_help=True)
console = Console()


#: Shown in ``--engine`` help so the list can never drift from the registry.
ENGINE_HELP = "Database engine: " + "|".join(SUPPORTED_ENGINES)


def _fail(context: str, err: NavicatError) -> None:
    """Print a structured error and exit with a usage-error status."""
    console.print(f"[red]x {context}[/red]")
    console.print(f"  [bold red]{err.code}[/bold red] {err.detail}")
    raise typer.Exit(2)


def _looks_like_dsn(text: str) -> bool:
    """True when ``text`` is a connection string rather than a saved name."""
    if "://" in text:
        return True
    scheme, sep, _rest = text.partition(":")
    if not sep:
        return False
    try:
        get_spec(scheme)
    except NavicatError:
        return False
    return True


def _resolve_target(target: str) -> ConnectionInfo | None:
    """Accept either a saved connection name or an ad-hoc connection string."""
    if _looks_like_dsn(target):
        return dsn_to_connection(target, name=target)
    saved = connection_manager.list_saved()
    return next((c for c in saved if c.name == target), None)


def _build_connection(
    *,
    name: str,
    dsn: str = "",
    engine: str = "",
    host: str = "",
    port: int = 0,
    user: str = "",
    password: str = "",
    database: str = "",
    charset: str = "",
) -> ConnectionInfo:
    """Build a ConnectionInfo from a DSN or from individual flags.

    The DSN wins as the base; any flag the user also supplied overrides it, so
    ``conn add --dsn <url> --password <pw>`` works for rotating a secret.
    """
    if dsn:
        info = dsn_to_connection(dsn, name=name)
        if user:
            info.user = user
        if password:
            info.password = password
        if database:
            info.database = database
        if host:
            info.host = host
        if port:
            info.port = port
        if charset:
            info.charset = charset
        return info

    requested = engine or "mysql"
    spec = get_spec(requested)  # raises EngineNotSupportedError
    resolved = normalize_engine(requested)

    if is_file_engine(resolved):
        path = database or host
        if not path:
            raise ConfigError(
                f"engine '{resolved}' is file-backed; pass the file path with "
                f"--database/-d (or use --dsn {resolved}:///path/to/file)"
            )
        return ConnectionInfo(
            name=name,
            engine=resolved,
            host="",
            port=0,
            database=path,
            user=user,
            password=password,
        )

    return ConnectionInfo(
        name=name,
        engine=resolved,
        host=host or "127.0.0.1",
        port=port or spec.default_port,
        # "root" only where it is actually the convention.
        user=user or ("root" if resolved == "mysql" else ""),
        password=password,
        database=database,
        charset=charset or "utf8mb4",
    )


def _report_connect_failure(context: str) -> None:
    """Print the structured error left by the last failed connection attempt.

    ``context`` is a short human label, e.g. "Connection test failed" - it is
    framing, not part of the error contract.
    """
    err = connection_manager.last_error
    if err is None:
        console.print(f"[red]Connection failed: {context}[/red]")
        return
    console.print(f"[red]Connection failed: {context}[/red]")
    console.print(f"  [bold red]{err.code}[/bold red] {err.detail}")
    console.print(
        f"  [dim]source={err.source}  stage={err.stage}  "
        f"recoverable={err.recoverable}  retryable={err.retryable}[/dim]"
    )


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
        {
            "id": c.id,
            "name": c.name or "-",
            "host": c.host,
            "port": c.port,
            "user": c.user,
            "database": c.database or "-",
            "ssh": "✓" if c.use_ssh else "",
            "active": "✓" if c.id in connection_manager.active_ids else "",
        }
        for c in connections
    ]
    format_output(rows, format, title="Saved Connections")


@conn_app.command("engines")
def list_engines(
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
) -> None:
    """List supported database engines and whether their driver is installed."""
    rows = []
    for key in supported_engines():
        spec = get_spec(key)
        ready = is_available(key)
        rows.append(
            {
                "engine": key,
                "name": spec.display_name,
                "status": "ready" if ready else "driver missing",
                "install": spec.install_hint or "-",
            }
        )
    format_output(rows, format, title="Supported Engines")


@conn_app.command("add")
def add_connection(
    name: str = typer.Option(..., "--name", "-n", help="Connection name"),
    dsn: str = typer.Option(
        "", "--dsn", help="Connection string, e.g. postgresql://user:pw@host:5432/db"
    ),
    engine: str = typer.Option("", "--engine", "-e", help=ENGINE_HELP),
    host: str = typer.Option("", "--host", "-h", help="Host (file path for sqlite/duckdb)"),
    port: int = typer.Option(0, "--port", "-p", help="Port (0 = engine default)"),
    user: str = typer.Option("", "--user", "-u", help="Database user"),
    password: str = typer.Option("", "--password", "-P", help="Database password", hide_input=True),
    database: str = typer.Option(
        "", "--database", "-d", help="Default database (file path for sqlite/duckdb)"
    ),
    charset: str = typer.Option("", "--charset", "-c", help="Connection charset"),
    ssh_host: str = typer.Option("", "--ssh-host", help="SSH tunnel host"),
    ssh_port: int = typer.Option(22, "--ssh-port", help="SSH tunnel port"),
    ssh_user: str = typer.Option("", "--ssh-user", help="SSH tunnel user"),
    ssh_password: str = typer.Option(
        "", "--ssh-password", help="SSH tunnel password", hide_input=True
    ),
    ssh_key: str = typer.Option("", "--ssh-key", help="SSH private key file path"),
    test: bool = typer.Option(False, "--test", "-t", help="Test connection before saving"),
) -> None:
    """Add and save a new connection, from a DSN or from individual flags."""
    try:
        info = _build_connection(
            name=name,
            dsn=dsn,
            engine=engine,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            charset=charset,
        )
    except NavicatError as err:
        _fail("Could not build the connection", err)
        return

    if ssh_host:
        info.use_ssh = True
        info.ssh_host = ssh_host
        info.ssh_port = ssh_port
        info.ssh_user = ssh_user
        info.ssh_password = ssh_password
        info.ssh_key_file = ssh_key

    if test:
        console.print("[yellow]Testing connection...[/yellow]")
        success = connection_manager.connect(info, persist=False)
        if success:
            connection_manager.disconnect(info.id)
            console.print("[green]Connection test successful![/green]")
        else:
            _report_connect_failure("Connection test failed")
            raise typer.Exit(1)

    from open_navicat.dal.local_config import local_db

    local_db.save_connection(info)
    console.print(f"[green]Connection '{info.name}' saved.[/green]")


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
    target: str = typer.Argument(..., help="Saved connection name, or a connection string"),
) -> None:
    """Test a saved connection, or an ad-hoc DSN without saving it."""
    info = _resolve_target(target)
    if info is None:
        console.print(f"[red]Connection '{target}' not found.[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Testing connection '{target}'...[/yellow]")
    # persist=False: a DSN typed on the command line is not something the user
    # asked to keep, and a saved name is already in the config.
    if connection_manager.connect(info, persist=False):
        connection_manager.disconnect(info.id)
        console.print(f"[green]Connection to {info.display_name} successful![/green]")
    else:
        _report_connect_failure(f"Connection to {info.display_name} failed")
        raise typer.Exit(1)


@conn_app.command("open")
def open_connection(
    target: str = typer.Argument(..., help="Saved connection name, or a connection string"),
) -> None:
    """Open (activate) a connection for use by other commands."""
    info = _resolve_target(target)
    if info is None:
        console.print(f"[red]Connection '{target}' not found.[/red]")
        raise typer.Exit(1)

    if connection_manager.connect(info):
        console.print(f"[green]Connected to {info.display_name} as {info.user}[/green]")
    else:
        _report_connect_failure(f"Could not connect to {info.display_name}")
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
    output: str = typer.Option(
        "", "--output", "-o", help="Output file path (default: {name}.json)"
    ),
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
