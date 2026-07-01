"""Backup & restore CLI commands."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

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


@backup_app.command("create")
def backup_database(
    database: str = typer.Argument(..., help="Database name"),
    output: str = typer.Option("", "--output", "-o", help="Output file (default: {db}_{date}.sql)"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    compress: bool = typer.Option(False, "--compress", "-z", help="Gzip compress the backup"),
) -> None:
    """Backup a database to SQL file."""
    cid = _resolve_conn(conn)
    connections = connection_manager.list_saved()
    info = next((c for c in connections if c.id == cid), None)
    if not info:
        console.print("[red]Connection info not found.[/red]")
        raise typer.Exit(1)

    # Build mysqldump command
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not output:
        output = f"{database}_{ts}.sql"
    if compress and not output.endswith(".gz"):
        output += ".gz"

    console.print(f"[yellow]Backing up '{database}' → {output}...[/yellow]")

    import subprocess
    is_pg = info.engine == "postgresql"

    if is_pg:
        cmd = [
            "pg_dump",
            f"--host={info.host}",
            f"--port={info.port}",
            f"--username={info.user}",
            "--no-owner",
            "--no-privileges",
            "--clean",
            "--if-exists",
            database,
        ]
    else:
        cmd = [
            "mysqldump",
            f"--host={info.host}",
            f"--port={info.port}",
            f"--user={info.user}",
            f"--password={info.password}",
            "--routines",
            "--triggers",
            "--events",
            "--add-drop-table",
            "--single-transaction",
            "--quick",
            database,
        ]

    try:
        import os
        env = os.environ.copy()
        if is_pg and info.password:
            env["PGPASSWORD"] = info.password

        if compress:
            with open(output.replace(".gz", ""), "wb") as f:
                proc = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True, env=env)
                if proc.returncode != 0:
                    console.print(f"[red]Error: {proc.stderr}[/red]")
                    raise typer.Exit(1)

            import gzip
            with open(output.replace(".gz", ""), "rb") as f_in:
                with gzip.open(output, "wb") as f_out:
                    f_out.writelines(f_in)
            Path(output.replace(".gz", "")).unlink()
        else:
            with open(output, "w", encoding="utf-8") as f:
                proc = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True, env=env)
                if proc.returncode != 0:
                    console.print(f"[red]Error: {proc.stderr}[/red]")
                    raise typer.Exit(1)

        file_size = Path(output).stat().st_size
        console.print(f"[green]✓ Backup completed: {output} ({file_size / 1024:.1f} KB)[/green]")

    except FileNotFoundError:
        tool = "pg_dump" if is_pg else "mysqldump"
        console.print(f"[red]{tool} not found. Ensure {'PostgreSQL' if is_pg else 'MySQL'} client tools are installed.[/red]")
        raise typer.Exit(1)


@backup_app.command("restore")
def restore_database(
    database: str = typer.Argument(..., help="Database name"),
    input_file: str = typer.Argument(..., help="SQL backup file to restore"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    create_db: bool = typer.Option(False, "--create-db", help="Create database if not exists"),
) -> None:
    """Restore a database from a SQL backup file."""
    cid = _resolve_conn(conn)
    connections = connection_manager.list_saved()
    info = next((c for c in connections if c.id == cid), None)
    if not info:
        console.print("[red]Connection info not found.[/red]")
        raise typer.Exit(1)

    if not Path(input_file).exists():
        console.print(f"[red]File not found: {input_file}[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Restoring '{database}' from {input_file}...[/yellow]")

    if create_db:
        from open_navicat.services.query_engine import query_engine
        is_pg = info.engine == "postgresql"
        if is_pg:
            query_engine.execute(cid, f'CREATE DATABASE "{database}"')
        else:
            query_engine.execute(cid, f"CREATE DATABASE IF NOT EXISTS `{database}`")

    import subprocess
    is_pg = info.engine == "postgresql"

    if is_pg:
        cmd = [
            "psql",
            f"--host={info.host}",
            f"--port={info.port}",
            f"--username={info.user}",
            "--no-psqlrc",
            "--set", "ON_ERROR_STOP=1",
            "--dbname", database,
        ]
    else:
        cmd = [
            "mysql",
            f"--host={info.host}",
            f"--port={info.port}",
            f"--user={info.user}",
            f"--password={info.password}",
            database,
        ]

    try:
        import os
        env = os.environ.copy()
        if is_pg and info.password:
            env["PGPASSWORD"] = info.password

        with open(input_file, "r", encoding="utf-8") as f:
            proc = subprocess.run(cmd, stdin=f, capture_output=True, text=True, env=env)
            if proc.returncode != 0:
                console.print(f"[red]Error: {proc.stderr}[/red]")
                raise typer.Exit(1)

        console.print(f"[green]✓ Database '{database}' restored from {input_file}[/green]")

    except FileNotFoundError:
        tool = "psql" if is_pg else "mysql"
        console.print(f"[red]{tool} client not found. Ensure {'PostgreSQL' if is_pg else 'MySQL'} client tools are installed.[/red]")
        raise typer.Exit(1)


@backup_app.command("list")
def list_backups(
    path: str = typer.Option(".", "--path", "-p", help="Directory to scan for backup files"),
) -> None:
    """List backup files in a directory."""
    backup_dir = Path(path)
    if not backup_dir.exists():
        console.print(f"[red]Directory not found: {path}[/red]")
        raise typer.Exit(1)

    files = []
    for f in sorted(backup_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix in (".sql", ".gz") and f.stem:
            size_kb = f.stat().st_size / 1024
            from datetime import datetime
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            files.append({"name": f.name, "size": f"{size_kb:.1f} KB", "modified": mtime})

    if not files:
        console.print(f"[yellow]No backup files found in '{path}'.[/yellow]")
        raise typer.Exit()

    format_output(files[:30], "table", title=f"Backup Files in '{path}'")


@backup_app.command("schedule")
def schedule_backup(
    database: str = typer.Argument(..., help="Database name"),
    cron: str = typer.Option("0 2 * * *", "--cron", "-c", help="Cron expression (default: daily at 2am)"),
    conn: str = typer.Option("", "--conn", help="Connection name"),
    output_dir: str = typer.Option("./backups", "--output-dir", "-o", help="Backup output directory"),
    compress: bool = typer.Option(True, "--compress", "-z", help="Compress backup"),
) -> None:
    """Schedule periodic backups using cron expression."""
    # Store in local config
    from open_navicat.dal.local_config import local_db

    job = {
        "type": "backup",
        "database": database,
        "conn_name": conn,
        "cron": cron,
        "output_dir": output_dir,
        "compress": compress,
        "enabled": True,
    }

    jobs = local_db.get_setting("scheduled_jobs", [])
    jobs.append(job)
    local_db.set_setting("scheduled_jobs", jobs)

    console.print(f"[green]✓ Backup scheduled: {database} @ '{cron}' → {output_dir}[/green]")
    console.print("[yellow]Scheduled jobs run when the GUI is open or via 'opennavicat scheduler run'.[/yellow]")
