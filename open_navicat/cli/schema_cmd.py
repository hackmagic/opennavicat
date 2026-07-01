"""Schema management CLI commands — list, show, create, diff, sync, AI design."""

from __future__ import annotations

import typer
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.syntax import Syntax
from rich import print as rprint

from open_navicat.services.connection_manager import connection_manager
from open_navicat.services.metadata_service import metadata_service
from open_navicat.services.sync_engine import sync_engine
from open_navicat.utils.output_formatter import format_output
from open_navicat.utils.sql_formatter import beautify

schema_app = typer.Typer(name="schema", help="Manage database schema", no_args_is_help=True)
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


@schema_app.command("list")
def list_objects(
    database: str = typer.Argument(..., help="Database name"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
) -> None:
    """List all tables, views and routines in a database."""
    cid = _resolve_conn(conn)

    tables = metadata_service.list_tables(cid, database)
    views = metadata_service.list_views(cid, database)
    routines = metadata_service.list_routines(cid, database)

    rows = []
    for t in tables:
        rows.append({"name": t, "type": "TABLE"})
    for v in views:
        rows.append({"name": v, "type": "VIEW"})
    for name, rtype in routines:
        rows.append({"name": name, "type": rtype})

    if not rows:
        console.print(f"[yellow]No objects found in '{database}'.[/yellow]")
        raise typer.Exit()

    format_output(rows, format, title=f"Objects in '{database}'")


@schema_app.command("show")
def show_schema(
    table: str = typer.Argument(..., help="Table name (format: db.table)"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    ddl: bool = typer.Option(False, "--ddl", "-d", help="Show CREATE TABLE statement"),
) -> None:
    """Show table/view schema details."""
    cid = _resolve_conn(conn)

    if "." in table:
        database, table_name = table.split(".", 1)
    else:
        console.print("[red]Use format: db.table (e.g. mydb.users)[/red]")
        raise typer.Exit(1)

    info = metadata_service.get_table_info(cid, database, table_name)
    if not info:
        console.print(f"[red]Table '{table}' not found.[/red]")
        raise typer.Exit(1)

    # Columns
    col_rows = [
        {"name": c.name, "type": c.data_type, "nullable": "YES" if c.nullable else "NO",
         "default": str(c.default) if c.default is not None else "",
         "key": "PRI" if c.is_primary_key else ("UNI" if c.is_unique else ""),
         "extra": "AUTO_INC" if c.is_auto_increment else "",
         "comment": c.comment}
        for c in info.columns
    ]
    format_output(col_rows, "table", title=f"Columns: {database}.{table_name}")

    # Indexes
    if info.indexes:
        idx_rows = [
            {"name": i.name, "columns": ", ".join(i.columns), "unique": str(i.is_unique),
             "type": i.index_type}
            for i in info.indexes
        ]
        format_output(idx_rows, "table", title="Indexes")

    # FK
    if info.foreign_keys:
        fk_rows = [
            {"name": fk.name, "column": fk.column, "references": f"{fk.ref_table}({fk.ref_column})",
             "on_delete": fk.on_delete, "on_update": fk.on_update}
            for fk in info.foreign_keys
        ]
        format_output(fk_rows, "table", title="Foreign Keys")

    # DDL
    if ddl:
        ddl_sql = metadata_service.get_create_table_sql(cid, database, table_name)
        if ddl_sql:
            console.print("\n[bold]DDL:[/bold]")
            console.print(Syntax(beautify(ddl_sql), "sql", theme="monokai", word_wrap=True))


@schema_app.command("create")
def create_table(
    name: str = typer.Argument(..., help="Table name (format: db.table)"),
    ddl: str = typer.Option("", "--ddl", "-d", help="CREATE TABLE DDL statement (or use --file)"),
    file: str = typer.Option("", "--file", "-f", help="SQL file containing DDL"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    preview: bool = typer.Option(False, "--preview", "-p", help="Only preview, don't execute"),
) -> None:
    """Create a new table from DDL."""
    cid = _resolve_conn(conn)

    if file:
        try:
            with open(file, "r", encoding="utf-8") as fh:
                ddl = fh.read()
        except FileNotFoundError:
            console.print(f"[red]File not found: {file}[/red]")
            raise typer.Exit(1)

    if not ddl:
        console.print("[red]Provide DDL via --ddl or --file[/red]")
        raise typer.Exit(1)

    console.print(Syntax(beautify(ddl), "sql", theme="monokai", word_wrap=True))

    if preview:
        console.print("[yellow]Preview mode — not executed.[/yellow]")
        raise typer.Exit()

    from open_navicat.services.query_engine import query_engine
    result = query_engine.execute(cid, ddl)
    if result.success:
        console.print(f"[green]✓ Table '{name}' created.[/green]")
    else:
        console.print(f"[red]✗ Error: {result.error_message}[/red]")
        raise typer.Exit(1)


@schema_app.command("diff")
def schema_diff(
    source: str = typer.Argument(..., help="Source database (format: db.table or db)"),
    target: str = typer.Argument(..., help="Target database"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name (for both source and target)"),
    target_conn: str = typer.Option("", "--target-conn", help="Connection name for target (default: same as source)"),
    detail: bool = typer.Option(False, "--detail", "-d", help="Show column/index/FK level details"),
) -> None:
    """Compare schema between two databases (full structural diff)."""
    cid = _resolve_conn(conn)
    tcid = _resolve_conn(target_conn) if target_conn else cid

    console.print("[yellow]Comparing schemas (deep analysis)...[/yellow]")

    diff = sync_engine.compare_databases(cid, source, target, tcid)

    if not diff.has_changes:
        console.print("[green]✓ Schemas are identical![/green]")
        raise typer.Exit()

    rows = []

    # Added tables
    for t in diff.added_tables:
        rows.append({"object": f"[green]+ {t.name}[/green]", "type": "TABLE",
                      "change": "Only in source"})
        if detail:
            for col in t.columns:
                rows.append({"object": f"  · {col.name} {col.data_type}", "type": "",
                              "change": "New column"})

    # Removed tables
    for t in diff.removed_tables:
        rows.append({"object": f"[red]- {t}[/red]", "type": "TABLE",
                      "change": "Only in target"})

    # Modified tables
    for td in diff.modified_tables:
        rows.append({"object": f"[yellow]~ {td.table_name}[/yellow]", "type": "TABLE",
                      "change": "Modified"})
        if detail:
            for col in td.added_columns:
                rows.append({"object": f"  [green]+ {col.name} {col.data_type}[/green]",
                              "type": "", "change": "ADD COLUMN"})
            for col_name in td.removed_columns:
                rows.append({"object": f"  [red]- {col_name}[/red]",
                              "type": "", "change": "DROP COLUMN"})
            for cd in td.modified_columns:
                rows.append({"object": f"  [yellow]~ {cd.column_name}: {cd.old_type} → {cd.new_type}[/yellow]",
                              "type": "", "change": "MODIFY COLUMN"})

    format_output(rows, "table", title=f"Schema Diff: {source} ↔ {target}")
    console.print(f"\nTotal: {diff.total_changes} differences "
                  f"(+{len(diff.added_tables)} tables, "
                  f"-{len(diff.removed_tables)} tables, "
                  f"~{len(diff.modified_tables)} tables)")


@schema_app.command("sync")
def schema_sync(
    source: str = typer.Argument(..., help="Source database (format: db.table or db)"),
    target: str = typer.Argument(..., help="Target database"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    target_conn: str = typer.Option("", "--target-conn", help="Connection name for target (default: same as source)"),
    apply: bool = typer.Option(False, "--apply", "-a", help="Apply changes to target"),
    preview: bool = typer.Option(True, "--preview/--no-preview", help="Preview changes before applying"),
) -> None:
    """Synchronize schema from source to target (full structural diff)."""
    cid = _resolve_conn(conn)
    tcid = _resolve_conn(target_conn) if target_conn else cid
    from open_navicat.services.query_engine import query_engine

    console.print("[yellow]Analyzing schema differences (deep comparison)...[/yellow]")

    diff = sync_engine.compare_databases(cid, source, target, tcid)

    if not diff.has_changes:
        console.print("[green]✓ Target is up-to-date with source.[/green]")
        raise typer.Exit()

    statements = sync_engine.generate_sync_script(diff, target_db=target)

    console.print(f"[yellow]{diff.total_changes} change(s) · {len(statements)} DDL statement(s):[/yellow]\n")
    for stmt in statements:
        console.print(Syntax(beautify(stmt), "sql", theme="monokai", word_wrap=True))
        console.print("---")

    if apply:
        if preview:
            confirm = typer.confirm("Apply these changes?")
            if not confirm:
                console.print("[yellow]Cancelled.[/yellow]")
                raise typer.Exit()

        for stmt in statements:
            result = query_engine.execute(tcid, stmt)
            if result.success:
                console.print(f"[green]✓ {stmt[:60]}...[/green]")
            else:
                console.print(f"[red]✗ {result.error_message}[/red]")
                raise typer.Exit(1)

        console.print("[green]✓ Schema synchronized![/green]")
    else:
        console.print("[yellow]Preview mode only. Use --apply to execute.[/yellow]")


@schema_app.command("design")
def ai_design(
    description: str = typer.Argument(..., help="Describe your database requirements in plain language"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name (optional, for deploy)"),
    deploy: bool = typer.Option(False, "--deploy", "-d", help="Deploy to database after design"),
    preview: bool = typer.Option(True, "--preview/--no-preview", help="Preview before deploy"),
) -> None:
    """AI-powered database schema design — describe requirements, get DDL."""
    from open_navicat.services.ai_service import ai_service

    console.print("[yellow]🤖 AI is designing your schema...[/yellow]")
    ddl = ai_service.design_schema(description)
    if not ddl:
        console.print("[red]Failed to generate schema design.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]📐 AI-Generated Schema:[/bold]")
    console.print(Syntax(beautify(ddl), "sql", theme="monokai", word_wrap=True))

    if deploy:
        cid = _resolve_conn(conn)
        if preview:
            confirm = typer.confirm("Deploy this schema to database?")
            if not confirm:
                console.print("[yellow]Cancelled.[/yellow]")
                raise typer.Exit()

        from open_navicat.services.query_engine import query_engine
        result = query_engine.execute(cid, ddl)
        if result.success:
            console.print("[green]✓ Schema deployed successfully![/green]")
        else:
            console.print(f"[red]✗ Error: {result.error_message}[/red]")
            raise typer.Exit(1)
    else:
        console.print("[yellow]Preview only. Use --deploy to push to database.[/yellow]")
