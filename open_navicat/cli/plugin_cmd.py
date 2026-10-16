"""Plugin management CLI: list, install, uninstall, enable, disable, verify."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from open_navicat.config import config
from open_navicat.errors import (
    PluginConflictError,
    PluginError,
    PluginManifestError,
    PluginPackageError,
    PluginPermissionError,
    PluginSignatureError,
    PluginVersionError,
)
from open_navicat.plugin.registry import (
    InstallResult,
    describe_installed,
    inspect_package,
    install_package,
    installed_summary,
    set_enabled,
    trust_public_key,
    trusted_public_keys,
    uninstall_plugin,
    untrust_public_key,
    verify_installed,
)
from open_navicat.plugin.signing import generate_keypair, public_key_fingerprint
from open_navicat.utils.output_formatter import format_output

plugin_app = typer.Typer(
    name="plugin",
    help="Manage OpenNavicat plugins (install, enable, verify, keygen)",
    no_args_is_help=True,
)
console = Console()


def _fail(message: str, hint: str = "") -> None:
    console.print(f"[red]{message}[/red]")
    if hint:
        console.print(f"[dim]{hint}[/dim]")
    raise typer.Exit(code=1)


def _handle_plugin_error(exc: PluginError) -> None:
    """Translate a plugin error into an actionable CLI message."""
    message = f"{exc.code}: {exc.message}"
    if isinstance(exc, PluginPermissionError):
        _fail(message, "add the author's public key with: opennavicat plugin key add <key>")
    if isinstance(exc, PluginSignatureError):
        _fail(message, "the package is not signed by any key you trust")
    if isinstance(exc, PluginVersionError):
        _fail(message, "upgrade OpenNavicat, or install an older plugin build")
    if isinstance(exc, PluginConflictError):
        _fail(message, "install/upgrade the dependency first, or uninstall the dependent")
    if isinstance(exc, PluginPackageError):
        _fail(message, "the file may be corrupt or not a .onvpkg archive")
    if isinstance(exc, PluginManifestError):
        _fail(message, "the plugin.json inside the package is invalid")
    _fail(message)


def _print_result(result: InstallResult) -> None:
    console.print(
        f"[green]{result.action}[/green] {result.plugin_id} {result.version} "
        f"(signed by {result.fingerprint})"
    )
    if result.permissions:
        console.print(f"[yellow]granted permissions:[/yellow] {', '.join(result.permissions)}")


def _read_package(path: str) -> bytes:
    p = Path(path)
    if not p.exists():
        _fail(f"no such file: {path}")
    try:
        return p.read_bytes()
    except OSError as exc:
        _fail(f"cannot read {path}: {exc}")
        raise  # pragma: no cover - _fail always exits


@plugin_app.command("list")
def list_plugins(
    format: str = typer.Option("table", "--format", "-f", help="Output format: table|json|csv"),
) -> None:
    """List installed plugins."""
    rows = installed_summary()
    if not rows:
        console.print("[yellow]No plugins installed.[/yellow]")
        console.print("[dim]Install one with: opennavicat plugin install <file.onvpkg>[/dim]")
        if format != "table":
            format_output([], format, title="Installed Plugins")
        return
    format_output(rows, format, title="Installed Plugins")


@plugin_app.command("info")
def info(plugin_id: str = typer.Argument(..., help="Plugin id, e.g. com.example.demo")) -> None:
    """Show manifest, permissions and trust record of an installed plugin."""
    data = describe_installed(plugin_id)
    if data is None:
        _fail(f"plugin {plugin_id!r} is not installed")
    console.print_json(json.dumps(data, indent=2, ensure_ascii=False))


@plugin_app.command("verify")
def verify(plugin_id: str = typer.Argument(..., help="Plugin id to verify")) -> None:
    """Re-check installed files against the signed manifest digests."""
    problems = verify_installed(plugin_id)
    if problems:
        for problem in problems:
            console.print(f"[red]{problem}[/red]")
        _fail(f"plugin {plugin_id!r} has been modified after installation")
    console.print(f"[green]ok[/green] {plugin_id}: every file matches its manifest digest")


@plugin_app.command("inspect")
def inspect(package: str = typer.Argument(..., help="Path to a .onvpkg file")) -> None:
    """Show a package's manifest and permissions WITHOUT trusting it."""
    data = _read_package(package)
    try:
        summary = inspect_package(data)
    except PluginError as exc:
        _handle_plugin_error(exc)
        return
    console.print_json(json.dumps(summary, indent=2, ensure_ascii=False))


@plugin_app.command("install")
def install(
    package: str = typer.Argument(..., help="Path to a .onvpkg file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Verify only, write nothing"),
) -> None:
    """Verify and install a signed plugin package."""
    data = _read_package(package)
    if dry_run:
        try:
            summary = inspect_package(data)
        except PluginError as exc:
            _handle_plugin_error(exc)
            return
        console.print(
            f"[green]would install[/green] {summary['id']} {summary['version']} "
            f"permissions={summary.get('permissions') or 'none'}"
        )
        return
    try:
        result = install_package(data, config)
    except PluginError as exc:
        _handle_plugin_error(exc)
        return
    _print_result(result)


@plugin_app.command("uninstall")
def uninstall(
    plugin_id: str = typer.Argument(..., help="Plugin id to remove"),
    force: bool = typer.Option(False, "--force", help="Also remove dependents"),
) -> None:
    """Uninstall a plugin (refuses while other plugins depend on it)."""
    try:
        if force:
            from open_navicat.plugin import loader
            from open_navicat.plugin.registry import _dependents

            installed = loader.read_installed()
            for dep in _dependents(plugin_id, installed):
                uninstall_plugin(dep)
                console.print(f"[dim]also removed dependent {dep}[/dim]")
        if not uninstall_plugin(plugin_id):
            _fail(f"plugin {plugin_id!r} is not installed")
    except PluginError as exc:
        _handle_plugin_error(exc)
        return
    console.print(f"[green]uninstalled[/green] {plugin_id}")


@plugin_app.command("enable")
def enable(plugin_id: str = typer.Argument(..., help="Plugin id")) -> None:
    """Enable a disabled plugin."""
    if not set_enabled(plugin_id, True):
        _fail(f"plugin {plugin_id!r} is not installed")
    console.print(f"[green]enabled[/green] {plugin_id}")


@plugin_app.command("disable")
def disable(plugin_id: str = typer.Argument(..., help="Plugin id")) -> None:
    """Disable a plugin without uninstalling it."""
    if not set_enabled(plugin_id, False):
        _fail(f"plugin {plugin_id!r} is not installed")
    console.print(f"[green]disabled[/green] {plugin_id}")


# ---- key management ----


@plugin_app.command("keygen")
def keygen(
    output: str = typer.Option(None, "--output", "-o", help="Write the keypair here"),
) -> None:
    """Generate a new Ed25519 keypair for signing plugins."""
    pub, priv = generate_keypair()
    if output:
        p = Path(output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"public_key": pub, "private_key": priv}, indent=2) + chr(10),
            encoding="utf-8",
        )
        console.print(f"[green]wrote keypair to[/green] {p}")
    console.print(f"public key:  {pub}")
    console.print(f"private key: {priv}")
    console.print("[yellow]keep the private key secret; it signs every release you ship[/yellow]")


@plugin_app.command("key-list")
def key_list() -> None:
    """List trusted plugin-signing public keys."""
    keys = trusted_public_keys(config)
    if not keys:
        console.print("[yellow]No trusted keys.[/yellow]")
        console.print("[dim]Add one with: opennavicat plugin key add <key>[/dim]")
        return
    table = Table(title="Trusted Keys")
    table.add_column("fingerprint")
    table.add_column("public key", overflow="fold")
    for key in keys:
        table.add_row(public_key_fingerprint(key), key)
    console.print(table)


@plugin_app.command("key-add")
def key_add(public_key: str = typer.Argument(..., help="Base64 Ed25519 public key")) -> None:
    """Trust a plugin-signing public key."""
    try:
        fingerprint = trust_public_key(config, public_key)
    except PluginError as exc:
        _handle_plugin_error(exc)
        return
    console.print(f"[green]trusted[/green] {fingerprint}")


@plugin_app.command("key-remove")
def key_remove(fingerprint: str = typer.Argument(..., help="Fingerprint to forget")) -> None:
    """Stop trusting a public key (installed plugins stay installed)."""
    if not untrust_public_key(config, fingerprint):
        _fail(f"no trusted key with fingerprint {fingerprint!r}")
    console.print(f"[green]removed[/green] {fingerprint}")
