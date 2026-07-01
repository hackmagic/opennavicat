"""Output formatter — renders data as table, JSON, CSV, or markdown for CLI display."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from rich.console import Console
from rich.table import Table as RichTable

_console = Console()


def format_output(
    rows: list[dict[str, Any]],
    format: str = "table",
    title: str = "",
) -> None:
    """Render a list of dicts in the specified output format."""
    if not rows:
        _console.print("[yellow](empty)[/yellow]")
        return

    if format == "json":
        _print_json(rows, title)
    elif format == "csv":
        _print_csv(rows)
    elif format == "table":
        _print_table(rows, title)
    elif format == "markdown":
        _print_markdown(rows)
    else:
        _print_table(rows, title)


def _print_table(rows: list[dict], title: str = "") -> None:
    """Render as a Rich table."""
    if not rows:
        return

    table = RichTable(title=title or None, title_justify="left",
                      show_header=True, header_style="bold cyan",
                      border_style="dim")
    columns = list(rows[0].keys())
    for col in columns:
        table.add_column(col)

    for row in rows:
        values = []
        for col in columns:
            val = row.get(col, "")
            if val is None or val == "":
                values.append("[dim]-[/dim]")
            elif isinstance(val, str) and val.startswith("[") and val.endswith("]"):
                # Rich markup passthrough
                values.append(val)
            else:
                values.append(str(val))
        table.add_row(*values)

    _console.print(table)


def _print_json(rows: list[dict], title: str = "") -> None:
    """Render as pretty-printed JSON."""
    data = rows if not title else {"title": title, "data": rows}
    text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    _console.print(text)


def _print_csv(rows: list[dict]) -> None:
    """Render as CSV."""
    if not rows:
        return
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    _console.print(output.getvalue())


def _print_markdown(rows: list[dict]) -> None:
    """Render as Markdown table."""
    if not rows:
        return
    columns = list(rows[0].keys())
    # Header
    _console.print("| " + " | ".join(columns) + " |")
    _console.print("| " + " | ".join("---" for _ in columns) + " |")
    # Rows
    for row in rows:
        vals = [str(row.get(c, "")) for c in columns]
        _console.print("| " + " | ".join(vals) + " |")
