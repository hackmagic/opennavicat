"""Backup & restore CLI commands — delegates to BackupService and AutomationService."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel

from open_navicat.services.connection_manager import connection_manager
from open_navicat.utils.output_formatter import format_output

backup_app = typer.Typer(name="backup", help="Backup, restore & schedule", no_args_is_help=True)
console = Console()


def _get_active_conn() -> str:
    active = connection_manager.active_ids
    if not active:
        console.print("[red]No active connection. Use 'opennavicat conn open <name>' first.[/red]")
        raise typer.Exit(1)
    return active[0]


def _resolve_conn(conn_name: str) -> str:
    if conn_name:
        connections = connection_manager.list_saved()
        target = next((c for c in connections if c.name == conn_name), None)
        if not target:
            console.print(f"[red]Connection '{conn_name}' not found.[/red]")
            raise typer.Exit(1)
        connection_manager.connect(target)
        return target.id
    return _get_active_conn()


def _get_conn_info(cid: str):
    connections = connection_manager.list_saved()
    info = next((c for c in connections if c.id == cid), None)
    if not info:
        console.print("[red]Connection info not found.[/red]")
        raise typer.Exit(1)
    return info


@backup_app.command("create")
def backup_database(
    database: str = typer.Argument(..., help="Database name"),
    output: str = typer.Option("", "--output", "-o", help="Output file (default: {db}_{date}.sql)"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    compress: bool = typer.Option(True, "--compress/--no-compress", "-z/-Z", help="Gzip compress"),
) -> None:
    """Backup a database to SQL file."""
    from open_navicat.services.backup_service import backup_service

    cid = _resolve_conn(conn)
    info = _get_conn_info(cid)

    console.print(f"[yellow]Backing up '{database}'...[/yellow]")
    try:
        record = backup_service.create_backup(info, database, output or None, compress)
        console.print(f"[green]✓ Backup completed: {record.file_name} ({record.size_human})[/green]")
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@backup_app.command("restore")
def restore_database(
    database: str = typer.Argument(..., help="Database name"),
    input_file: str = typer.Argument(..., help="Backup file to restore"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    create_db: bool = typer.Option(True, "--create-db/--no-create-db", help="Create database if not exists"),
) -> None:
    """Restore a database from a backup file."""
    from open_navicat.services.backup_service import backup_service

    cid = _resolve_conn(conn)
    info = _get_conn_info(cid)

    console.print(f"[yellow]Restoring '{database}' from {input_file}...[/yellow]")
    try:
        backup_service.restore_backup(info, database, input_file, create_db)
        console.print(f"[green]✓ Database '{database}' restored from {input_file}[/green]")
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@backup_app.command("list")
def list_backups(
    path: str = typer.Option("", "--path", "-p", help="Directory to scan (default: ./backups)"),
) -> None:
    """List backup files."""
    from open_navicat.services.backup_service import backup_service

    records = backup_service.list_backups(path or None)
    if not records:
        console.print("[yellow]No backup files found.[/yellow]")
        raise typer.Exit()

    rows = [r.to_dict() for r in records[:30]]
    format_output(rows, "table", title="Backup Files")


@backup_app.command("delete")
def delete_backup(
    file_path: str = typer.Argument(..., help="Backup file path to delete"),
) -> None:
    """Delete a backup file."""
    from open_navicat.services.backup_service import backup_service

    if backup_service.delete_backup(file_path):
        console.print(f"[green]✓ Deleted: {file_path}[/green]")
    else:
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)


@backup_app.command("history")
def backup_history(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of records"),
) -> None:
    """Show backup history."""
    from open_navicat.services.backup_service import backup_service

    history = backup_service.get_history(limit)
    if not history:
        console.print("[yellow]No backup history.[/yellow]")
        raise typer.Exit()

    format_output(history, "table", title="Backup History")


@backup_app.command("schedule")
def schedule_backup(
    database: str = typer.Argument(..., help="Database name"),
    cron: str = typer.Option("0 2 * * *", "--cron", help="Cron expression (default: daily at 2am)"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    output_dir: str = typer.Option("./backups", "--output-dir", "-o", help="Backup output directory"),
    compress: bool = typer.Option(True, "--compress/--no-compress", "-z/-Z", help="Compress backup"),
) -> None:
    """Schedule periodic backups using cron expression."""
    from open_navicat.services.automation_service import automation_service

    cid = _resolve_conn(conn)
    job = automation_service.add_backup_job(
        name=f"backup-{database}",
        connection_id=cid,
        database=database,
        cron_expr=cron,
        compress=compress,
        output_dir=output_dir,
    )
    console.print(f"[green]✓ Backup scheduled: {database} @ '{cron}' (job: {job['id']})[/green]")


@backup_app.command("jobs")
def list_jobs() -> None:
    """List all scheduled backup jobs."""
    from open_navicat.services.automation_service import automation_service

    jobs = automation_service.list_jobs()
    if not jobs:
        console.print("[yellow]No scheduled jobs.[/yellow]")
        raise typer.Exit()

    rows = []
    for j in jobs:
        cfg = j.get("config", {})
        rows.append({
            "id": j.get("id", ""),
            "name": j.get("name", ""),
            "database": cfg.get("database", ""),
            "cron": j.get("cron_expr", ""),
            "enabled": "✓" if j.get("enabled") else "✗",
            "status": j.get("status", ""),
        })
    format_output(rows, "table", title="Scheduled Jobs")


@backup_app.command("job-remove")
def remove_job(
    job_id: str = typer.Argument(..., help="Job ID to remove"),
) -> None:
    """Remove a scheduled job."""
    from open_navicat.services.automation_service import automation_service

    automation_service.remove_job(job_id)
    console.print(f"[green]✓ Job {job_id} removed[/green]")


@backup_app.command("job-toggle")
def toggle_job(
    job_id: str = typer.Argument(..., help="Job ID to enable/disable"),
    enable: bool = typer.Option(True, "--enable/--disable", help="Enable or disable"),
) -> None:
    """Enable or disable a scheduled job."""
    from open_navicat.services.automation_service import automation_service

    automation_service.enable_job(job_id, enable)
    state = "enabled" if enable else "disabled"
    console.print(f"[green]✓ Job {job_id} {state}[/green]")
