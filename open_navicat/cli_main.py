"""Standalone CLI entry point for PyInstaller (no Qt imports).

Routes 'gui' argument to launch GUI instead of CLI.
"""

import sys


def _make_streams_resilient() -> None:
    """Never let a cosmetic glyph crash a run on a GBK console.

    zh-CN Windows defaults to the GBK code page.  Messages like ``✓ Exported``
    raise ``UnicodeEncodeError`` the moment stdout is a pipe (CI, subprocess
    capture, ``> file``), which would turn a successful export into a
    traceback.  Reconfigure both streams to replace unencodable characters.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass  # not a TextIOWrapper, or already closed


def _close_open_connections() -> None:
    """Shut every pooled connection down before the interpreter exits.

    Engine connectors run their I/O on background threads (aiosqlite starts a
    non-daemon worker per connection, ClickHouse/SQL Server/Oracle use
    ThreadPoolExecutors).  A one-shot CLI process that leaves a connection open
    hangs forever in interpreter shutdown: CPython joins non-daemon threads
    *before* running atexit handlers, so a plain ``atexit`` hook never gets a
    chance to close them — this must run from a ``finally`` in ``main``.
    """
    try:
        from open_navicat.dal.connection_pool import connection_pool

        if connection_pool.active_connections:
            connection_pool.close_all()
    except Exception:  # noqa: BLE001 - teardown must never mask the real exit code
        pass


def main() -> None:
    """CLI entry point. If first arg is 'gui', launch the PySide6 GUI."""
    _make_streams_resilient()

    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        sys.argv.pop(1)
        try:
            from open_navicat.gui_main import main as gui_main
        except ImportError:
            print("GUI mode requires PySide6. Use 'pip install open-navicat' or download the GUI package.")
            return
        try:
            gui_main()
        finally:
            _close_open_connections()
        return

    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v"):
        from open_navicat import __version__
        print(f"OpenNavicat v{__version__}")
        return

    from open_navicat.cli.app import cli_main

    try:
        cli_main()
    finally:
        # Typer raises SystemExit on its own; run cleanup while the main
        # thread is still alive, before CPython's thread-join phase.
        _close_open_connections()


if __name__ == "__main__":
    main()
