"""SQL query CLI commands — execute, explain, natural-language query."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.syntax import Syntax

from open_navicat.services.connection_manager import connection_manager
from open_navicat.services.query_engine import query_engine
from open_navicat.utils.output_formatter import format_output

query_app = typer.Typer(name="query", help="Execute SQL queries", no_args_is_help=True)
console = Console()


def _get_active_conn() -> str:
    active = connection_manager.active_ids
    if not active:
        console.print("[red]No active connection. Use 'opennavicat conn open <name>' first.[/red]")
        raise typer.Exit(1)
    return active[0]


@query_app.command("run")
def run_sql(
    sql: str = typer.Argument(..., help="SQL statement to execute"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name (omit for active)"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
    limit: int = typer.Option(0, "--limit", "-l", help="Limit result rows (0 = no limit)"),
    show_sql: bool = typer.Option(False, "--show-sql", "-s", help="Show executed SQL"),
) -> None:
    """Execute a SQL statement and display results."""
    cid = _resolve_conn(conn)
    if show_sql:
        console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True))
        console.print()

    result = query_engine.execute(cid, sql)

    if not result.success:
        console.print(f"[red]SQL Error: {result.error_message}[/red]")
        raise typer.Exit(1)

    if result.is_select:
        rows = []
        for row in result.rows[:limit] if limit else result.rows:
            rows.append({c.name: str(v) if v is not None else None for c, v in zip(result.columns, row)})
        format_output(rows, format, title=f"Query Result ({result.row_count} rows, {result.execution_time_ms:.1f}ms)")
        if limit and result.row_count > limit:
            console.print(f"[dim]Showing {limit} of {result.row_count} rows[/dim]")
    else:
        msg = f"Query OK, {result.affected_rows} rows affected"
        if result.insert_id:
            msg += f", last insert ID: {result.insert_id}"
        msg += f" ({result.execution_time_ms:.1f}ms)"
        console.print(f"[green]{msg}[/green]")


@query_app.command("stream")
def stream_results(
    sql: str = typer.Argument(..., help="SQL statement to execute"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name (omit for active)"),
    chunk_size: int = typer.Option(1000, "--chunk-size", "-n", help="Rows per chunk"),
) -> None:
    """Execute a query and display results page by page (streaming for large datasets)."""
    cid = _resolve_conn(conn)
    from rich.table import Table
    page = 0
    for chunk in query_engine.execute_stream(cid, sql, chunk_size):
        page += 1
        table = Table(title=f"Page {page} ({len(chunk)} rows)", show_header=True, header_style="bold cyan")
        if chunk:
            keys = list(chunk[0].keys()) if isinstance(chunk[0], dict) else [f"col{i}" for i in range(len(chunk[0]))]
            for k in keys:
                table.add_column(str(k))
            for row in chunk:
                vals = [str(v) if v is not None else "" for v in (row.values() if isinstance(row, dict) else row)]
                table.add_row(*vals)
        console.print(table)
        if page > 0:
            input("Press Enter for next page...")


@query_app.command("file")
def run_sql_file(
    path: str = typer.Argument(..., help="Path to SQL file"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
) -> None:
    """Execute a .sql file."""
    import sqlparse
    cid = _resolve_conn(conn)

    try:
        with open(path, "r", encoding="utf-8") as f:
            script = f.read()
    except FileNotFoundError:
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(1)

    statements = sqlparse.split(script)
    total = len(statements)
    for i, stmt in enumerate(statements, 1):
        stmt = stmt.strip()
        if not stmt:
            continue
        console.print(f"[dim][{i}/{total}] Executing...[/dim]")
        result = query_engine.execute(cid, stmt)
        if not result.success:
            console.print(f"[red]Error on statement {i}: {result.error_message}[/red]")
            raise typer.Exit(1)
        console.print(f"[green]  ✓ {result.affected_rows} rows affected ({result.execution_time_ms:.1f}ms)[/green]")

    console.print(f"[green]✓ File '{path}' executed successfully ({total} statements).[/green]")


@query_app.command("explain")
def explain_query(
    sql: str = typer.Argument(..., help="SQL to explain"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    format: str = typer.Option("json", "--format", "-f", help="Explain format: text|json"),
) -> None:
    """Show EXPLAIN plan for a SQL query."""
    cid = _resolve_conn(conn)

    if format == "json":
        result = query_engine.explain_format_json(cid, sql)
    else:
        result = query_engine.explain(cid, sql)

    if not result.success:
        console.print(f"[red]Error: {result.error_message}[/red]")
        raise typer.Exit(1)

    if result.is_select:
        rows = [{c.name: str(v) if v is not None else "" for c, v in zip(result.columns, row)} for row in result.rows]
        format_output(rows, "table", title="EXPLAIN Plan")
    else:
        console.print(result.plan or "[yellow]No plan returned[/yellow]")


@query_app.command("nl")
def natural_language_query(
    description: str = typer.Argument(..., help="Describe what data you want in natural language"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
    show_sql: bool = typer.Option(True, "--show-sql/--hide-sql", "-s/-S", help="Show generated SQL"),
) -> None:
    """Natural language → SQL → Execute — describe what you want in plain language."""
    cid = _resolve_conn(conn)

    from open_navicat.services.ai_service import ai_service

    # Get schema context for the LLM
    schema_context = _get_schema_context(cid)

    # Generate SQL via AI
    sql = ai_service.nl2sql(description, schema_context)
    if not sql:
        console.print("[red]Failed to generate SQL from your description.[/red]")
        raise typer.Exit(1)

    if show_sql:
        console.print("[bold]Generated SQL:[/bold]")
        console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True))
        console.print()

    # Execute
    result = query_engine.execute(cid, sql)
    if not result.success:
        console.print(f"[red]SQL Error: {result.error_message}[/red]")
        raise typer.Exit(1)

    if result.is_select:
        rows = [{c.name: str(v) if v is not None else None for c, v in zip(result.columns, row)} for row in result.rows]
        format_output(rows, format, title=f"Query Result ({result.row_count} rows)")
    else:
        console.print(f"[green]Query OK, {result.affected_rows} rows affected[/green]")


@query_app.command("history")
def query_history(
    limit: int = typer.Option(20, "--limit", "-l", help="Number of recent queries"),
) -> None:
    """Show recent query history."""
    from open_navicat.dal.local_config import local_db
    history = local_db.get_setting("query_history", [])
    if not history:
        console.print("[yellow]No query history.[/yellow]")
        raise typer.Exit()

    rows = [
        {"#": i+1, "time": h.get("time", ""), "sql": h.get("sql", "")[:80] + "..." if len(h.get("sql", "")) > 80 else h.get("sql", ""),
         "status": "✓" if h.get("success") else "✗"}
        for i, h in enumerate(history[-limit:])
    ]
    format_output(rows, "table", title="Recent Queries")


# ---- helper ----

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


def _get_schema_context(conn_id: str) -> str:
    """Build a compact schema description for AI prompt context."""
    from open_navicat.services.metadata_service import metadata_service
    dbs = metadata_service.list_databases(conn_id)
    lines = []
    for db in dbs[:5]:  # Limit to 5 databases
        tables = metadata_service.list_tables(conn_id, db.name)
        for table in tables[:20]:  # Limit to 20 tables per DB
            info = metadata_service.get_table_info(conn_id, db.name, table)
            if info:
                cols = ", ".join(f"{c.name} ({c.data_type})" for c in info.columns[:10])
                lines.append(f"{db.name}.{table}: {cols}")
    return "\n".join(lines)
