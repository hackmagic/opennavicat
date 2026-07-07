"""SQL utility commands — translate, optimize."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.syntax import Syntax

from open_navicat.utils.sql_dialect import optimize_sql, translate_sql

sql_app = typer.Typer(help="SQL utilities: dialect translation & optimization")
console = Console()


@sql_app.command("translate")
def sql_translate(
    sql: str = typer.Argument(..., help="SQL statement to translate"),
    source: str = typer.Option("mysql", "--from", "-f", help="Source dialect (mysql, postgresql)"),
    target: str = typer.Option("postgresql", "--to", "-t", help="Target dialect (mysql, postgresql)"),
) -> None:
    """Translate SQL between MySQL and PostgreSQL dialects."""
    result = translate_sql(sql, source, target)
    if result == sql:
        console.print("[yellow]Translation returned unchanged — dialect may already match or parsing failed.[/yellow]")
    console.print(Syntax(result, "sql", theme="monokai", word_wrap=True))


@sql_app.command("optimize")
def sql_optimize(
    sql: str = typer.Argument(..., help="SQL statement to optimize"),
    dialect: str = typer.Option("mysql", "--dialect", "-d", help="Database dialect"),
) -> None:
    """Optimize SQL using AST-level transformations."""
    result = optimize_sql(sql, dialect)
    if result == sql:
        console.print("[yellow]Optimization returned unchanged.[/yellow]")
    console.print(Syntax(result, "sql", theme="monokai", word_wrap=True))
