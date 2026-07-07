"""Interactive setup wizard — guides through first-time configuration."""

from __future__ import annotations

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from open_navicat.config import config as app_config

init_app = typer.Typer(name="init", help="Interactive setup wizard", hidden=False)
console = Console()

PROVIDERS = {
    "1": {"name": "openai",     "label": "OpenAI",       "base": "https://api.openai.com/v1",           "model": "gpt-4o-mini"},
    "2": {"name": "deepseek",   "label": "DeepSeek",     "base": "https://api.deepseek.com",             "model": "deepseek-chat"},
    "3": {"name": "ollama",     "label": "Ollama (local)","base": "http://localhost:11434/v1",           "model": "llama3"},
    "4": {"name": "custom",     "label": "Custom API",    "base": "",                                     "model": ""},
}


@init_app.callback(invoke_without_command=True)
def _init_callback() -> None:
    """Interactive setup wizard for OpenNavicat."""
    _run_wizard()


def _run_wizard() -> None:
    console.print(Panel.fit(
        "[bold cyan]OpenNavicat Setup Wizard[/bold cyan]\n\n"
        "This will guide you through the initial configuration.",
        border_style="cyan",
    ))

    _configure_ai()
    _configure_connection()
    _show_summary()


def _configure_ai() -> None:
    console.print("\n[bold]🤖 AI Provider Configuration[/bold]")
    console.print("OpenNavicat uses AI for NL2SQL, query optimization, and more.\n")

    table = Table(box=box.SIMPLE)
    table.add_column("#", style="dim")
    table.add_column("Provider")
    table.add_column("Default Model")
    for key, p in PROVIDERS.items():
        table.add_row(key, p["label"], p["model"])
    console.print(table)

    choice = Prompt.ask(
        "\nSelect AI provider", choices=list(PROVIDERS.keys()), default="1"
    )
    provider = PROVIDERS[choice]

    api_key = ""
    api_base = provider["base"]
    model = provider["model"]

    if provider["name"] != "ollama":
        if provider["name"] == "custom":
            api_base = Prompt.ask("API base URL", default="https://api.openai.com/v1")
            model = Prompt.ask("Model name", default="gpt-4o-mini")
        elif provider["name"] == "openai":
            model = Prompt.ask("Model", default="gpt-4o-mini")
        elif provider["name"] == "deepseek":
            model = Prompt.ask("Model", default="deepseek-chat")

        api_key = Prompt.ask("API key", password=True)

    app_config.set("ai.provider", provider["name"])
    app_config.set("ai.api_key", api_key)
    app_config.set("ai.api_base", api_base)
    app_config.set("ai.model", model)
    console.print("[green]✓ AI configuration saved[/green]")

    if api_key and Confirm.ask("Test AI connection now?", default=True):
        _test_ai(provider["name"], api_key, api_base, model)


def _test_ai(provider: str, api_key: str, api_base: str, model: str) -> None:
    from open_navicat.services.ai_service import ai_service

    console.print("[dim]Testing AI connection...[/dim]")
    ok, msg = ai_service.test_config({
        "provider": provider,
        "api_key": api_key,
        "api_base": api_base,
        "model": model,
    })
    if ok:
        console.print(f"[green]✓ Connection OK — {msg}[/green]")
    else:
        console.print(f"[red]✗ Connection failed: {msg}[/red]")
        if Confirm.ask("Retry with different settings?", default=True):
            _configure_ai()


def _configure_connection() -> None:
    if not Confirm.ask("\nAdd a database connection now?", default=True):
        return

    from open_navicat.models.connection import ConnectionInfo
    from open_navicat.services.connection_manager import connection_manager

    console.print("\n[bold]🗄️  Database Connection[/bold]")

    name = Prompt.ask("Connection name", default="local")
    db_type = Prompt.ask("Database type", choices=["mysql", "postgresql", "sqlite"], default="mysql")
    host = "127.0.0.1"
    port = 3306
    user = "root"
    password = ""
    database = ""

    if db_type == "sqlite":
        database = Prompt.ask("Database file path")
    else:
        host = Prompt.ask("Host", default="127.0.0.1")
        port = int(Prompt.ask("Port", default="3306" if db_type == "mysql" else "5432"))
        user = Prompt.ask("User", default="root")
        password = Prompt.ask("Password", password=True)
        database = Prompt.ask("Database name (optional)", default="")

    info = ConnectionInfo(
        name=name, host=host, port=port, user=user, password=password,
        database=database, engine=db_type,
    )
    if Confirm.ask("Test connection before saving?", default=True):
        console.print("[dim]Testing connection...[/dim]")
        try:
            connection_manager.connect(info)
            connection_manager.disconnect(info.id)
            console.print("[green]✓ Connection successful[/green]")
        except Exception as e:
            console.print(f"[red]✗ Connection failed: {e}[/red]")
            if not Confirm.ask("Save anyway?", default=False):
                return

    connection_manager.connect(info)
    console.print("[green]✓ Connection saved[/green]")


def _show_summary() -> None:
    ai_provider = app_config.get("ai.provider", "not set")
    connections = len([c for c in _saved_connections()])

    table = Table(title="Setup Summary", box=box.ROUNDED)
    table.add_column("Item", style="cyan")
    table.add_column("Status")
    table.add_row("AI Provider", ai_provider)
    table.add_row("Saved Connections", str(connections))
    console.print("\n")
    console.print(table)

    console.print("\n[bold cyan]🎉 Setup complete![/bold cyan]")
    console.print("Next steps:")
    console.print("  • Run [bold]opennavicat conn open <name>[/bold] to activate a connection")
    console.print("  • Run [bold]opennavicat query nl \"your question\"[/bold] for natural language queries")
    console.print("  • Run [bold]opennavicat gui[/bold] to launch the graphical interface")
    console.print("  • Run [bold]opennavicat --help[/bold] to see all commands\n")


def _saved_connections() -> list:
    try:
        from open_navicat.services.connection_manager import connection_manager
        return connection_manager.list_saved()
    except Exception:
        return []
