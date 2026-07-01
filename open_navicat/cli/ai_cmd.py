"""AI assistant CLI commands — natural-language SQL, optimization, schema design, chat."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax

from open_navicat.services.connection_manager import connection_manager

ai_app = typer.Typer(name="ai", help="AI-powered database assistant", no_args_is_help=True)
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


@ai_app.command("ask")
def ai_ask(
    question: str = typer.Argument(..., help="Ask anything about your database"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name (for context)"),
) -> None:
    """Ask AI questions about your database schema and data."""
    from open_navicat.services.ai_service import ai_service

    cid = ""
    schema_context = ""
    if conn or connection_manager.active_ids:
        cid = _resolve_conn(conn)
        schema_context = _get_schema_context(cid)

    console.print("[dim]🤖 AI thinking...[/dim]")
    answer = ai_service.ask(question, schema_context)
    if not answer:
        console.print("[red]No response from AI.[/red]")
        raise typer.Exit(1)

    console.print(Panel(Markdown(answer), title="🤖 AI Answer", border_style="blue"))


@ai_app.command("optimize")
def ai_optimize(
    sql: str = typer.Argument(..., help="SQL query to optimize"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name (for schema context)"),
    explain: bool = typer.Option(True, "--explain/--no-explain", help="Include EXPLAIN data"),
) -> None:
    """Analyze a SQL query and suggest optimizations."""
    from open_navicat.services.ai_service import ai_service
    from open_navicat.services.query_engine import query_engine

    cid = ""
    explain_data = ""
    if conn or connection_manager.active_ids:
        cid = _resolve_conn(conn)
        if explain:
            result = query_engine.explain_format_json(cid, sql)
            if result.success and result.rows:
                import json
                explain_data = json.dumps(result.rows[:5], indent=2)

    console.print("[yellow]🤖 Analyzing query performance...[/yellow]")
    advice = ai_service.optimize(sql, explain_data)
    if not advice:
        console.print("[red]No optimization advice returned.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]Original SQL:[/bold]")
    console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True))
    console.print("\n[bold]💡 Optimization Advice:[/bold]")
    console.print(Panel(Markdown(advice), border_style="green"))


@ai_app.command("explain")
def ai_explain(
    sql: str = typer.Argument(..., help="SQL query to explain"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
) -> None:
    """Explain what a SQL query does in plain language."""
    from open_navicat.services.ai_service import ai_service

    console.print("[yellow]🤖 Analyzing query...[/yellow]")
    explanation = ai_service.explain_query(sql)
    if not explanation:
        console.print("[red]Failed to explain query.[/red]")
        raise typer.Exit(1)

    console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True))
    console.print()
    console.print(Panel(Markdown(explanation), title="📖 Explanation", border_style="cyan"))


@ai_app.command("fix")
def ai_fix(
    sql: str = typer.Argument(..., help="SQL query with error"),
    error: str = typer.Option("", "--error", "-e", help="Error message from the database"),
) -> None:
    """Fix a broken SQL query — provide the query and optional error message."""
    from open_navicat.services.ai_service import ai_service

    console.print("[yellow]🤖 Diagnosing and fixing...[/yellow]")
    fixed = ai_service.fix_sql(sql, error)
    if not fixed:
        console.print("[red]Failed to fix the query.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]Original:[/bold]")
    console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True))
    console.print("\n[bold]✅ Fixed:[/bold]")
    console.print(Syntax(fixed, "sql", theme="monokai", word_wrap=True))


@ai_app.command("chat")
def ai_chat(
    conn: str = typer.Option("", "--conn", "-c", help="Connection name for live context"),
    prompt: str = typer.Option("", "--prompt", "-p", help="Optional initial prompt"),
    interactive: bool = typer.Option(True, "--interactive/--once", help="Start interactive session"),
) -> None:
    """Interactive AI chat — have a conversation about your database."""
    from open_navicat.services.ai_service import ai_service
    from open_navicat.services.query_engine import query_engine

    cid = ""
    if conn or connection_manager.active_ids:
        cid = _resolve_conn(conn)
        schema_context = _get_schema_context(cid)
        ai_service.set_system_prompt(f"You are a database expert. Here is the database schema context:\n{schema_context}")

    # Handle one-shot prompt
    if prompt:
        console.print("[dim]🤖 Thinking...[/dim]")
        answer = ai_service.chat(prompt)
        console.print(Panel(Markdown(answer), title="🤖 AI", border_style="blue"))
        if not interactive:
            raise typer.Exit()

    # Interactive mode
    console.print(Panel(
        "[bold]🤖 OpenNavicat AI Assistant[/bold]\n"
        "Ask questions about your database, request SQL queries, or get advice.\n"
        "Type [bold]!sql <query>[/bold] to execute raw SQL.\n"
        "Type [bold]/exit[/bold] or [bold]/quit[/bold] to exit.\n"
        "Type [bold]/schema[/bold] to see loaded schema context.",
        title="AI Chat",
        border_style="cyan",
    ))

    while True:
        try:
            user_input = typer.prompt("\n[bold]You[/bold]").strip()
        except EOFError:
            break

        if not user_input:
            continue
        if user_input.lower() in ("/exit", "/quit", ":q"):
            break
        if user_input.lower() == "/schema":
            console.print(Panel(schema_context if schema_context else "(no schema loaded)",
                                title="Schema Context", border_style="yellow"))
            continue
        if user_input.startswith("!sql "):
            sql = user_input[5:].strip()
            if cid:
                result = query_engine.execute(cid, sql)
                if result.success:
                    from open_navicat.utils.output_formatter import format_output
                    if result.is_select:
                        rows = [{c.name: str(v) if v is not None else None
                                 for c, v in zip(result.columns, row)} for row in result.rows[:20]]
                        format_output(rows, "table", title=f"Result ({result.row_count} rows)")
                    else:
                        console.print(f"[green]OK, {result.affected_rows} rows affected[/green]")
                else:
                    console.print(f"[red]Error: {result.error_message}[/red]")
            else:
                console.print("[red]No active connection.[/red]")
            continue

        console.print("[dim]🤖 Thinking...[/dim]")
        answer = ai_service.chat(user_input)
        console.print(Panel(Markdown(answer), title="🤖 AI", border_style="blue"))


@ai_app.command("tables")
def ai_tables(
    description: str = typer.Argument(..., help="Describe what tables you need"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name (optional for deploy)"),
    deploy: bool = typer.Option(False, "--deploy", "-d", help="Deploy DDL to database"),
) -> None:
    """AI schema design — describe your data model in plain language, get DDL."""
    from open_navicat.services.ai_service import ai_service

    console.print("[yellow]🤖 Designing database schema...[/yellow]")
    ddl = ai_service.design_schema(description)
    if not ddl:
        console.print("[red]Failed to generate schema.[/red]")
        raise typer.Exit(1)

    console.print(Panel(Syntax(ddl, "sql", theme="monokai", word_wrap=True),
                        title="📐 AI-Generated Schema", border_style="magenta"))

    if deploy:
        cid = _resolve_conn(conn)
        from open_navicat.services.query_engine import query_engine
        result = query_engine.execute(cid, ddl)
        if result.success:
            console.print("[green]✓ Schema deployed![/green]")
        else:
            console.print(f"[red]✗ Error: {result.error_message}[/red]")
            raise typer.Exit(1)


# ---- helper ----

def _get_schema_context(conn_id: str) -> str:
    """Build a compact schema description for AI prompt context."""
    from open_navicat.services.metadata_service import metadata_service
    dbs = metadata_service.list_databases(conn_id)
    lines = []
    for db in dbs[:5]:
        tables = metadata_service.list_tables(conn_id, db.name)
        for table in tables[:20]:
            info = metadata_service.get_table_info(conn_id, db.name, table)
            if info:
                cols = ", ".join(f"{c.name} ({c.data_type})" for c in info.columns[:10])
                lines.append(f"{db.name}.{table}: {cols}")
    return "\n".join(lines)
