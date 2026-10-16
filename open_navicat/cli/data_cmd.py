"""Data operations CLI commands — browse, export, import, sync, generate."""

from __future__ import annotations

import itertools

import typer
from rich.console import Console

from open_navicat.services.connection_manager import connection_manager
from open_navicat.services.query_engine import query_engine
from open_navicat.utils.output_formatter import format_output

data_app = typer.Typer(name="data", help="Browse, export, import & sync data", no_args_is_help=True)
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


@data_app.command("browse")
def browse_table(
    table: str = typer.Argument(..., help="Table name (format: db.table)"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum rows"),
    offset: int = typer.Option(0, "--offset", "-o", help="Row offset"),
    where: str = typer.Option("", "--where", "-w", help="WHERE clause (SQL)"),
    order: str = typer.Option("", "--order", help="ORDER BY clause"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
) -> None:
    """Browse table data with pagination and filtering."""
    cid = _resolve_conn(conn)

    if "." not in table:
        console.print("[red]Use format: db.table (e.g. mydb.users)[/red]")
        raise typer.Exit(1)
    database, table_name = table.split(".", 1)

    # Detect engine for quoting (per-engine quoting, not MySQL-or-nothing)
    from open_navicat.dal.connection_pool import connection_pool as _pool
    from open_navicat.sql.quoting import limit_clause, quote_qualified

    _conn = _pool.get(cid)
    _info = getattr(_conn, "_info", None) if _conn else None
    _engine = getattr(_info, "engine", "mysql") if _info else "mysql"

    # Build query
    parts = [f"SELECT * FROM {quote_qualified(table_name, _engine, database)}"]
    if where:
        parts.append(f"WHERE {where}")
    if order:
        parts.append(f"ORDER BY {order}")
    sql = " ".join(parts) + " " + limit_clause(limit, offset, _engine)
    result = query_engine.execute(cid, sql)

    if not result.success:
        console.print(f"[red]Error: {result.error_message}[/red]")
        raise typer.Exit(1)

    if result.is_select:
        rows = [
            {c.name: str(v) if v is not None else None for c, v in zip(result.columns, row)}
            for row in result.rows
        ]
        format_output(rows, format, title=f"{table} ({result.row_count} rows)")
    else:
        console.print(f"[green]{result.affected_rows} rows affected[/green]")


@data_app.command("export")
def export_data(
    table: str = typer.Argument(..., help="Table name (format: db.table)"),
    output: str = typer.Option("", "--output", "-o", help="Output file path"),
    format: str = typer.Option(
        "csv", "--format", "-f",
        help="Export format: csv|tsv|json|markdown|xlsx|sql",
    ),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    where: str = typer.Option("", "--where", "-w", help="WHERE clause (raw SQL)"),
    limit: int = typer.Option(0, "--limit", "-l", help="Maximum rows (0 = all)"),
    batch_size: int = typer.Option(1000, "--batch-size", "-b", help="Rows per page"),
) -> None:
    """Export table data to a file, one page at a time."""
    from open_navicat.dal.connection_pool import connection_pool
    from open_navicat.formats.exporters import ExportFormat, export_rows
    from open_navicat.sql.quoting import limit_clause, quote_qualified

    cid = _resolve_conn(conn)
    if "." not in table:
        console.print("[red]Use format: db.table (e.g. mydb.users)[/red]")
        raise typer.Exit(1)
    database, table_name = table.split(".", 1)

    fmt = format.strip().lower()
    if fmt in ("excel", "xlsx"):
        fmt = "xlsx"
    try:
        kind = ExportFormat(fmt)
    except ValueError:
        console.print(f"[red]Unknown format {format!r}[/red]")
        raise typer.Exit(1)

    connector = connection_pool.get(cid)
    info = getattr(connector, "_info", None) if connector else None
    engine = getattr(info, "engine", "mysql") if info else "mysql"
    ref = quote_qualified(table_name, engine, database)
    page = max(1, batch_size)

    def _pages():
        """Yield one page of rows at a time; never holds the whole table."""
        offset = 0
        while True:
            parts = [f"SELECT * FROM {ref}"]
            if where:
                parts.append(f"WHERE {where}")
            parts.append(limit_clause(page, offset, engine))
            result = query_engine.execute(cid, " ".join(parts))
            if not result.success:
                console.print(f"[red]Error: {result.error_message}[/red]")
                raise typer.Exit(1)
            if not result.is_select:
                break
            rows = [list(row) for row in result.rows]
            if not rows:
                break
            if not offset:
                header[:] = [c.name for c in result.columns]
            yield rows
            offset += len(rows)
            if limit and offset >= limit:
                break

    header: list[str] = []

    if not output:
        output = f"{table_name}.{kind.value}"

    # The header is only known once the first page comes back, so pull one
    # batch eagerly instead of handing an empty header to the writer.
    pages = _pages()
    first = next(pages, None)
    if first is None:
        console.print("[yellow]No data to export.[/yellow]")
        raise typer.Exit()

    written = export_rows(output, header, itertools.chain([first], pages), kind, table=table_name)
    if not written:
        console.print("[yellow]No data to export.[/yellow]")
        raise typer.Exit()
    console.print(f"[green]✓ Exported {written} rows to {output}[/green]")


@data_app.command("import")
def import_data(
    table: str = typer.Argument(..., help="Target table (format: db.table)"),
    file: str = typer.Argument(..., help="Input file path"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    batch_size: int = typer.Option(1000, "--batch-size", "-b", help="Rows per batch insert"),
    no_header: bool = typer.Option(False, "--no-header", help="The file has no header row"),
    columns: str = typer.Option("", "--columns", help="Comma-separated names (implies --no-header)"),
    delimiter: str = typer.Option("", "--delimiter", help="Force the CSV delimiter"),
    sheet: str = typer.Option("", "--sheet", help="Worksheet for workbooks"),
    encoding: str = typer.Option("", "--encoding", help="File encoding (default utf-8-sig)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the mapping without writing"),
) -> None:
    """Import a file into a table: streamed, type-coerced, transactional."""
    from open_navicat.formats.importers import (
        ImportFileError,
        ReadOptions,
        count_rows,
        detect_format,
        iter_batches,
    )
    from open_navicat.sql.migration import MigrationOptions, plan_migration, run_migration

    cid = _resolve_conn(conn)
    if "." not in table:
        console.print("[red]Use format: db.table (e.g. mydb.users)[/red]")
        raise typer.Exit(1)
    database, table_name = table.split(".", 1)

    try:
        detect_format(file)
    except ImportFileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    declared = tuple(c.strip() for c in columns.split(",") if c.strip()) if columns else None
    opts = MigrationOptions(
        batch_size=batch_size,
        has_header=False if (no_header or declared) else True,
        columns=declared,
        delimiter=delimiter or None,
        sheet=sheet or None,
        encoding=encoding or "utf-8-sig",
    )

    from open_navicat.dal.connection_pool import _get_loop, connection_pool

    connector = connection_pool.get(cid)
    if not connector:
        console.print("[red]Connection lost.[/red]")
        raise typer.Exit(1)
    loop = _get_loop()

    def _read_options() -> ReadOptions:
        return ReadOptions(
            encoding=opts.encoding,
            delimiter=opts.delimiter,
            sheet=opts.sheet,
            columns=opts.columns,
            has_header=opts.has_header,
            batch_size=opts.batch_size,
        )

    if dry_run:
        async def _plan():
            info = await connector.get_table_info(database, table_name)
            target = list(getattr(info, "columns", []) or [])
            first = next(iter_batches(file, _read_options()), None)
            source = first.columns if first else []
            return plan_migration(
                source, target,
                table=table_name, database=database,
                batch_size=opts.batch_size,
                row_count=count_rows(file, _read_options()),
            )

        plan = loop.run_until_complete(_plan())
        console.print(plan.render())
        raise typer.Exit()

    last_shown = 0

    def _progress(p) -> None:
        nonlocal last_shown
        if p.rows_read - last_shown >= 10_000:
            last_shown = p.rows_read
            console.print(
                f"  [dim]{p.rows_read} read / {p.rows_written} written "
                f"/ {p.rows_failed} failed[/dim]"
            )

    try:
        result = loop.run_until_complete(
            run_migration(
                connector, database, table_name, file,
                options=opts, on_progress=_progress,
            )
        )
    except ImportFileError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if result.aborted:
        console.print(f"[red]Import aborted: {result.render()}[/red]")
        for err in result.errors[:10]:
            console.print(f"  [red]{err}[/red]")
        raise typer.Exit(1)

    if result.errors:
        console.print(f"[yellow]{result.render()}[/yellow]")
        console.print(f"[yellow]{len(result.errors)} row error(s), first 10:[/yellow]")
        for err in result.errors[:10]:
            console.print(f"  {err}")
        raise typer.Exit(1)

    console.print(f"[green]{result.render()}[/green]")


@data_app.command("generate")
def generate_data(
    table: str = typer.Argument(..., help="Target table (format: db.table)"),
    count: int = typer.Option(100, "--count", "-n", help="Number of rows to generate"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    prompt: str = typer.Option(
        "", "--prompt", "-p", help="AI prompt: describe realistic data rules (AI mode only)"
    ),
    method: str = typer.Option("auto", "--method", "-m", help="Generation method: auto|ai|pattern"),
    preview: bool = typer.Option(True, "--preview/--yes", help="Preview before inserting"),
) -> None:
    """Generate test data — pattern-based (no AI) or AI-powered."""
    cid = _resolve_conn(conn)
    if "." not in table:
        console.print("[red]Use format: db.table (e.g. mydb.users)[/red]")
        raise typer.Exit(1)
    database, table_name = table.split(".", 1)

    from open_navicat.services.metadata_service import metadata_service

    info = metadata_service.get_table_info(cid, database, table_name)
    if not info:
        console.print(f"[red]Table '{table}' not found.[/red]")
        raise typer.Exit(1)

    # Decide method
    use_ai = method == "ai" or (method == "auto" and prompt)

    if use_ai:
        from open_navicat.services.ai_service import ai_service

        console.print(f"[yellow]🤖 AI generating {count} rows for {table}...[/yellow]")
        rows = ai_service.generate_data(info, count, prompt)
    else:
        from open_navicat.services.data_generator import data_generator

        console.print(f"[yellow]⚡ Pattern-generating {count} rows for {table}...[/yellow]")
        rows = data_generator.generate(info, count)

    if not rows:
        console.print("[red]Failed to generate data.[/red]")
        raise typer.Exit(1)

    if preview:
        format_output(rows[:5], "table", title=f"Preview: {len(rows)} rows to insert")
        confirm = typer.confirm(f"Insert {len(rows)} rows?")
        if not confirm:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit()

    from open_navicat.dal.connection_pool import _get_loop as _pool_loop_getter

    pool_loop = _pool_loop_getter()
    from open_navicat.dal.connection_pool import connection_pool

    connector = connection_pool.get(cid)
    inserted = pool_loop.run_until_complete(connector.batch_insert(database, table_name, rows))
    console.print(f"[green]✓ Inserted {inserted} rows into {table}[/green]")


@data_app.command("compare")
def data_compare(
    source: str = typer.Argument(..., help="Source table (format: conn:db.table)"),
    target: str = typer.Argument(..., help="Target table (format: conn:db.table)"),
    output: str = typer.Option("", "--output", "-o", help="Save sync SQL to file"),
) -> None:
    """Compare row-level data between two tables (same or different connections)."""
    from open_navicat.services.data_sync_engine import data_sync_engine

    def parse_table(spec: str) -> tuple[str, str, str]:
        parts = spec.split(":", 1)
        if len(parts) == 1:
            conn_id = _get_active_conn()
            db, tbl = parts[0].split(".", 1)
        else:
            conn_id = _resolve_conn(parts[0])
            db, tbl = parts[1].split(".", 1)
        return conn_id, db, tbl

    src_conn, src_db, src_tbl = parse_table(source)
    tgt_conn, tgt_db, tgt_tbl = parse_table(target)

    console.print(f"[yellow]Comparing {src_db}.{src_tbl} → {tgt_db}.{tgt_tbl}...[/yellow]")
    result = data_sync_engine.compare_tables(src_conn, src_db, src_tbl, tgt_conn, tgt_db, tgt_tbl)
    console.print(
        f"[bold]Source:[/bold] {result.source_rows} rows, [bold]Target:[/bold] {result.target_rows} rows"
    )
    console.print(f"[bold]Differences:[/bold] {result.total_diffs} total")
    console.print(
        f"  [green]+{len(result.inserts)}[/green] inserts  "
        f"[yellow]~{len(result.updates)}[/yellow] updates  "
        f"[red]-{len(result.deletes)}[/red] deletes"
    )
    if result.total_diffs == 0:
        console.print("[green]✓ Tables are in sync![/green]")
        return

    script = data_sync_engine.generate_sync_script(result)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(script)
        console.print(f"[green]Sync script saved to {output}[/green]")
    else:
        from rich.syntax import Syntax

        console.print(Syntax(script, "sql", theme="monokai"))


@data_app.command("sync")
def data_sync(
    source: str = typer.Argument(..., help="Source table (format: conn:db.table)"),
    target: str = typer.Argument(..., help="Target table (format: conn:db.table)"),
    dry_run: bool = typer.Option(
        True, "--dry-run/--execute", help="Preview only (default: dry-run)"
    ),
) -> None:
    """Execute data sync: apply INSERT/UPDATE/DELETE to make target match source."""
    from open_navicat.services.data_sync_engine import data_sync_engine

    def parse_table(spec: str) -> tuple[str, str, str]:
        parts = spec.split(":", 1)
        if len(parts) == 1:
            conn_id = _get_active_conn()
            db, tbl = parts[0].split(".", 1)
        else:
            conn_id = _resolve_conn(parts[0])
            db, tbl = parts[1].split(".", 1)
        return conn_id, db, tbl

    src_conn, src_db, src_tbl = parse_table(source)
    tgt_conn, tgt_db, tgt_tbl = parse_table(target)

    console.print(f"[yellow]Comparing {src_db}.{src_tbl} → {tgt_db}.{tgt_tbl}...[/yellow]")
    result = data_sync_engine.compare_tables(src_conn, src_db, src_tbl, tgt_conn, tgt_db, tgt_tbl)

    if result.total_diffs == 0:
        console.print("[green]✓ Tables are already in sync![/green]")
        return

    console.print(
        f"Changes to apply: [green]+{len(result.inserts)}[/green] "
        f"[yellow]~{len(result.updates)}[/yellow] "
        f"[red]-{len(result.deletes)}[/red]"
    )

    if dry_run:
        script = data_sync_engine.generate_sync_script(result)
        from rich.syntax import Syntax

        console.print(Syntax(script, "sql", theme="monokai"))
        console.print("[yellow]Dry-run mode. Use --execute to apply changes.[/yellow]")
        return

    if not typer.confirm("Apply these changes to target?"):
        console.print("[yellow]Cancelled.[/yellow]")
        return

    from open_navicat.dal.connection_pool import _get_loop as _pool_loop_getter

    pool_loop = _pool_loop_getter()
    from open_navicat.dal.connection_pool import connection_pool

    tgt_connector = connection_pool.get(tgt_conn)
    if not tgt_connector:
        console.print("[red]Target connection not found.[/red]")
        raise typer.Exit(1)

    script = data_sync_engine.generate_sync_script(result)
    for stmt in script.split("\n"):
        stmt = stmt.strip()
        if stmt:
            pool_loop.run_until_complete(tgt_connector.execute(stmt))
    console.print(f"[green]✓ Synced {result.total_diffs} changes to target.[/green]")
