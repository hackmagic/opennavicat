"""AI assistant CLI commands — natural-language SQL, optimization, schema design, chat."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax

from open_navicat.services.ai_service import AIError, AITransientError
from open_navicat.services.connection_manager import connection_manager

ai_app = typer.Typer(name="ai", help="AI-powered database assistant", no_args_is_help=True)
console = Console()


def _handle_ai_error(e: Exception) -> None:
    if isinstance(e, AITransientError):
        console.print(f"[yellow]⚠️  AI service temporarily unavailable: {e}[/yellow]")
        console.print("[dim]Check your network connection and try again.[/dim]")
    elif isinstance(e, AIError):
        console.print(f"[red]✗ AI error: {e}[/red]")
    else:
        console.print(f"[red]✗ Unexpected error: {e}[/red]")
    raise typer.Exit(1)


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
    database = ""
    if conn or connection_manager.active_ids:
        cid = _resolve_conn(conn)
        info = connection_manager.get_saved(cid)
        if info:
            database = info.database or ""
        schema_context = ai_service.build_schema_context_for_query(cid, database, question)

    console.print("[dim]🤖 AI thinking...[/dim]")
    try:
        answer = ai_service.ask(question, schema_context)
    except (AIError, AITransientError) as e:
        _handle_ai_error(e)
    if not answer:
        console.print("[red]AI returned empty response.[/red]")
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
    try:
        advice = ai_service.optimize(sql, explain_data)
    except (AIError, AITransientError) as e:
        _handle_ai_error(e)
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
    try:
        explanation = ai_service.explain_query(sql)
    except (AIError, AITransientError) as e:
        _handle_ai_error(e)
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
    try:
        fixed = ai_service.fix_sql(sql, error)
    except (AIError, AITransientError) as e:
        _handle_ai_error(e)
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
        try:
            answer = ai_service.chat(prompt)
        except (AIError, AITransientError) as e:
            _handle_ai_error(e)
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
        try:
            answer = ai_service.chat(user_input)
        except (AIError, AITransientError) as e:
            console.print(f"[red]✗ {e}[/red]")
            continue
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
    try:
        ddl = ai_service.design_schema(description)
    except (AIError, AITransientError) as e:
        _handle_ai_error(e)
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


@ai_app.command("agent")
def ai_agent(
    request: str = typer.Argument(..., help="Natural language request for the agent to execute"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
    db: str = typer.Option("", "--db", "-d", help="Database name"),
    max_steps: int = typer.Option(5, "--steps", help="Max reasoning steps"),
) -> None:
    """ReAct agent — reasons, generates SQL, executes, and iterates."""
    from open_navicat.services.ai_service import ai_service

    cid = _resolve_conn(conn) if conn else ""
    database = db

    # If no db specified, try to get from active connection
    if cid and not database:
        connections = connection_manager.list_saved()
        info = next((c for c in connections if c.id == cid), None)
        if info:
            database = info.database

    def _confirm_sql(sql: str) -> bool:
        """Prompt user to confirm DDL/DML execution."""
        console.print("\n[bold red]⚠ DDL/DML requires confirmation:[/bold red]")
        console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True))
        return typer.confirm("Execute?", default=False)

    console.print(f"[yellow]🤖 Agent thinking (max {max_steps} steps)...[/yellow]")
    try:
        result = ai_service.agent(
            request, connection_id=cid, database=database,
            max_steps=max_steps, confirm_callback=_confirm_sql,
        )
    except (AIError, AITransientError) as e:
        _handle_ai_error(e)

    # Show steps
    for i, step in enumerate(result.steps):
        if step.thought:
            console.print(f"[dim]  Thought: {step.thought}[/dim]")
        if step.action and step.action != "answer":
            console.print(f"[dim]  Action: {step.action}({step.action_input})[/dim]")
        if step.observation:
            console.print(f"[dim]  → {step.observation[:200]}[/dim]")

    if result.sql:
        console.print("\n[bold]Generated SQL:[/bold]")
        console.print(Syntax(result.sql, "sql", theme="monokai", word_wrap=True))

    if result.answer:
        console.print(Panel(Markdown(result.answer), title="🤖 Agent Answer", border_style="green"))


@ai_app.command("chat-history")
def ai_chat_history(
    action: str = typer.Argument("show", help="Action: show, clear"),
    session: str = typer.Option("default", "--session", "-s", help="Session ID"),
) -> None:
    """View or clear persisted chat history."""
    from open_navicat.services.ai_service import ai_service

    if action == "clear":
        ai_service.clear_chat_history(session)
        console.print(f"[green]✓ Chat history cleared for session '{session}'[/green]")
    else:
        ai_service.load_chat_history(session)
        if not ai_service._chat_history:
            console.print(f"[yellow]No chat history for session '{session}'[/yellow]")
            return
        for msg in ai_service._chat_history[-20:]:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                console.print(f"\n[bold]You:[/bold] {content[:200]}")
            else:
                console.print(f"[bold blue]AI:[/bold blue] {content[:200]}")


@ai_app.command("config")
def ai_config(
    provider: str = typer.Option("", "--provider", "-p", help="AI provider: openai|deepseek|ollama|custom"),
    api_key: str = typer.Option("", "--api-key", "-k", help="API key"),
    api_base: str = typer.Option("", "--api-base", "-b", help="API base URL"),
    model: str = typer.Option("", "--model", "-m", help="Model name"),
    show: bool = typer.Option(False, "--show", "-s", help="Show current config"),
) -> None:
    """Configure AI provider settings."""
    from open_navicat.services.ai_service import ai_service

    if show:
        console.print(f"[bold]Provider:[/bold] {ai_service._provider}")
        console.print(f"[bold]Model:[/bold] {ai_service._model}")
        console.print(f"[bold]API Base:[/bold] {ai_service._api_base or '(default)'}")
        console.print(f"[bold]API Key:[/bold] {'***' + ai_service._api_key[-4:] if ai_service._api_key else '(not set)'}")
        return

    cfg = {}
    if provider:
        cfg["provider"] = provider
    if api_key:
        cfg["api_key"] = api_key
    if api_base:
        cfg["api_base"] = api_base
    if model:
        cfg["model"] = model

    if cfg:
        ai_service.update_config(cfg)
        console.print("[green]✓ AI config updated.[/green]")
    else:
        console.print("[yellow]No changes. Use --provider, --api-key, --api-base, --model to configure.[/yellow]")


@ai_app.command("schema")
def ai_schema(
    description: str = typer.Argument("", help="Initial description to design schema (or use --ddl)"),
    ddl: str = typer.Option("", "--ddl", help="Start from existing DDL"),
    deploy: bool = typer.Option(False, "--deploy", "-d", help="Deploy final DDL to database"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name for deploy"),
) -> None:
    """Interactive multi-round schema design — iteratively refine your database schema."""
    from open_navicat.services.ai_service import ai_service

    # Start with initial schema
    current_ddl = ddl
    if not current_ddl and description:
        console.print("[yellow]🤖 Designing initial schema...[/yellow]")
        try:
            current_ddl = ai_service.design_schema(description)
        except (AIError, AITransientError) as e:
            _handle_ai_error(e)
        if not current_ddl:
            console.print("[red]Failed to generate initial schema.[/red]")
            raise typer.Exit(1)
    elif not current_ddl:
        console.print("[red]Provide either --ddl or a description argument.[/red]")
        raise typer.Exit(1)

    console.print(Panel(Syntax(current_ddl, "sql", theme="monokai", word_wrap=True),
                        title="📐 Current Schema", border_style="magenta"))

    while True:
        try:
            user_input = typer.prompt("\n[bold]Modification[/bold] (or /done, /deploy, /show)").strip()
        except EOFError:
            break

        if not user_input:
            continue
        if user_input.lower() in ("/done", "/exit", "/quit"):
            break
        if user_input.lower() == "/show":
            console.print(Panel(Syntax(current_ddl, "sql", theme="monokai", word_wrap=True),
                                title="📐 Current Schema", border_style="magenta"))
            continue
        if user_input.lower() == "/deploy":
            if not conn and not connection_manager.active_ids:
                console.print("[red]No active connection. Use --conn to specify one.[/red]")
                continue
            cid = _resolve_conn(conn)
            from open_navicat.services.query_engine import query_engine
            result = query_engine.execute(cid, current_ddl)
            if result.success:
                console.print("[green]✓ Schema deployed![/green]")
            else:
                console.print(f"[red]✗ Error: {result.error_message}[/red]")
            break

        console.print("[yellow]🤖 Applying modification...[/yellow]")
        try:
            updated = ai_service.design_schema_iterative(current_ddl, user_input)
        except (AIError, AITransientError) as e:
            console.print(f"[red]✗ {e}[/red]")
            continue
        if not updated:
            console.print("[red]Failed to apply modification.[/red]")
            continue

        current_ddl = updated
        console.print(Panel(Syntax(current_ddl, "sql", theme="monokai", word_wrap=True),
                            title="📐 Updated Schema", border_style="green"))


@ai_app.command("build")
def ai_build(
    description: str = typer.Argument("", help="Describe the query you want to build"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name (for schema context)"),
    show_schema: bool = typer.Option(False, "--show-schema", "-s", help="Show loaded schema context"),
) -> None:
    """Conversational query builder — describe what you need, iteratively refine the SQL."""
    from open_navicat.services.ai_service import ai_service
    from open_navicat.services.query_engine import query_engine

    cid = ""
    schema_context = ""
    if conn or connection_manager.active_ids:
        cid = _resolve_conn(conn)
        schema_context = _get_schema_context(cid)

    ai_service.set_system_prompt(
        "You are a SQL query builder. Help the user build a SQL query step by step. "
        "When the user describes what they want, generate the SQL and explain it. "
        "When they ask for changes, update the SQL accordingly. "
        "Always show the complete SQL query in your response." +
        (f"\n\nDatabase schema context:\n{schema_context}" if schema_context else "")
    )

    if show_schema and schema_context:
        console.print(Panel(schema_context, title="Schema Context", border_style="yellow"))

    console.print(Panel(
        "[bold]🤖 AI Query Builder[/bold]\n"
        "Describe what you want to query, and I'll build the SQL for you.\n"
        "You can then refine: [italic]'add a filter on status', 'join with orders table'[/italic]\n"
        "Commands: [bold]/run[/bold] to execute the SQL, [bold]/show[/bold] to see current SQL, [bold]/exit[/bold] to quit.",
        title="AI Query Builder",
        border_style="cyan",
    ))

    if description:
        console.print("[yellow]🤖 Building query...[/yellow]")
        try:
            answer = ai_service.chat(description)
        except (AIError, AITransientError) as e:
            _handle_ai_error(e)
        console.print(Panel(Markdown(answer), title="🤖 SQL Query", border_style="green"))

    while True:
        try:
            user_input = typer.prompt("\n[bold]Refine[/bold] (or /run, /show, /exit)").strip()
        except EOFError:
            break

        if not user_input:
            continue
        if user_input.lower() in ("/exit", "/quit"):
            break
        if user_input.lower() == "/show":
            console.print(Panel(
                ai_service._chat_history[-1]["content"] if ai_service._chat_history else "(no SQL yet)",
                title="Current Query", border_style="yellow",
            ))
            continue
        if user_input.lower() == "/run":
            if not cid:
                console.print("[red]No active connection. Use --conn to specify one.[/red]")
                continue
            last_msg = ai_service._chat_history[-1]["content"] if ai_service._chat_history else ""
            console.print("[yellow]Executing...[/yellow]")
            result = query_engine.execute(cid, last_msg)
            if result.success:
                if result.is_select:
                    from open_navicat.utils.output_formatter import format_output
                    rows = [{c.name: str(v) if v is not None else None
                             for c, v in zip(result.columns, row)} for row in result.rows[:50]]
                    format_output(rows, "table", title=f"Result ({result.row_count} rows)")
                else:
                    console.print(f"[green]OK, {result.affected_rows} rows affected[/green]")
            else:
                console.print(f"[red]Error: {result.error_message}[/red]")
            continue

        console.print("[yellow]🤖 Refining...[/yellow]")
        try:
            answer = ai_service.chat(user_input)
        except (AIError, AITransientError) as e:
            console.print(f"[red]✗ {e}[/red]")
            continue
        console.print(Panel(Markdown(answer), title="🤖 SQL Query", border_style="green"))


@ai_app.command("data-quality")
def ai_data_quality(
    table: str = typer.Argument(..., help="Table name"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
) -> None:
    """Analyze data quality issues in a table."""
    from open_navicat.services.ai_service import ai_service

    cid = _resolve_conn(conn) if conn else _get_active_conn() if connection_manager.active_ids else ""
    schema_context = _get_schema_context(cid) if cid else ""
    console.print("[yellow]🤖 Analyzing data quality...[/yellow]")
    try:
        result = ai_service.data_quality(table, schema_context)
    except (AIError, AITransientError) as e:
        _handle_ai_error(e)
    console.print(Panel(Markdown(result), title="🔍 Data Quality", border_style="blue"))


@ai_app.command("anomaly")
def ai_anomaly(
    table: str = typer.Argument(..., help="Table name"),
    column: str = typer.Argument(..., help="Column name"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name"),
) -> None:
    """Detect anomalies in table data."""
    from open_navicat.services.ai_service import ai_service

    console.print("[yellow]🤖 Analyzing anomalies...[/yellow]")
    try:
        result = ai_service.anomaly_detection(table, column)
    except (AIError, AITransientError) as e:
        _handle_ai_error(e)
    console.print(Panel(Markdown(result), title="📊 Anomaly Detection", border_style="red"))


@ai_app.command("review")
def ai_review(
    sql: str = typer.Argument(..., help="SQL query to review"),
    conn: str = typer.Option("", "--conn", "-c", help="Connection name (for schema context)"),
) -> None:
    """Review SQL for security and performance issues."""
    from open_navicat.services.ai_service import ai_service

    cid = _resolve_conn(conn) if conn else _get_active_conn() if connection_manager.active_ids else ""
    schema_context = _get_schema_context(cid) if cid else ""
    console.print("[yellow]🤖 Reviewing SQL...[/yellow]")
    try:
        result = ai_service.sql_review(sql, schema_context)
    except (AIError, AITransientError) as e:
        _handle_ai_error(e)
    console.print(Syntax(sql, "sql", theme="monokai", word_wrap=True))
    console.print(Panel(Markdown(result), title="🛡️ SQL Review", border_style="yellow"))


@ai_app.command("test")
def ai_test(
    provider: str = typer.Option("", "--provider", "-p", help="Provider to test"),
    api_key: str = typer.Option("", "--api-key", "-k", help="API key"),
    api_base: str = typer.Option("", "--api-base", "-b", help="API base URL"),
    model: str = typer.Option("", "--model", "-m", help="Model name"),
) -> None:
    """Test AI connection with current or provided config."""
    from open_navicat.services.ai_service import ai_service

    cfg = {}
    if provider:
        cfg["provider"] = provider
    if api_key:
        cfg["api_key"] = api_key
    if api_base:
        cfg["api_base"] = api_base
    if model:
        cfg["model"] = model

    console.print("[yellow]🤖 Testing AI connection...[/yellow]")
    ok, msg = ai_service.test_config(cfg or None)
    if ok:
        console.print(f"[green]✓ AI connection OK: {msg}[/green]")
    else:
        console.print(f"[red]✗ AI connection failed: {msg}[/red]")
        raise typer.Exit(1)


# ---- helper ----

def _get_schema_context(conn_id: str, max_tables: int = 10) -> str:
    """Build a compact schema description for AI prompt context."""
    from open_navicat.services.metadata_service import metadata_service
    dbs = metadata_service.list_databases(conn_id)
    lines = []
    remaining = max_tables
    for db in dbs[:3]:
        tables = metadata_service.list_tables(conn_id, db.name)
        for table in tables[:remaining]:
            info = metadata_service.get_table_info(conn_id, db.name, table)
            if info:
                cols = ", ".join(f"{c.name} ({c.data_type})" for c in info.columns[:10])
                lines.append(f"{db.name}.{table}: {cols}")
                remaining -= 1
                if remaining <= 0:
                    break
        if remaining <= 0:
            break
    return "\n".join(lines)
