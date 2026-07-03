"""Standalone GUI entry point for PyInstaller.

Top-level PySide6 imports ensure PyInstaller hooks fire correctly.
When run with CLI arguments (e.g. from terminal), routes to CLI mode.
"""

import sys

# Top-level imports for PyInstaller hook detection
from PySide6.QtCore import Qt  # noqa: F401
from PySide6.QtWidgets import QApplication  # noqa: F401


def main() -> int:
    args = sys.argv[1:]

    # --version is handled by both GUI and CLI
    if args and args[0] in ("--version", "-v"):
        from open_navicat import __version__
        print(f"OpenNavicat v{__version__}")
        return 0

    # With CLI commands (conn, query, ai, ...), route to CLI mode
    if args:
        from open_navicat.cli_main import main as cli_entry
        cli_entry()
        return 0

    # No args → launch GUI
    from open_navicat.app import Application
    app = Application(sys.argv)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
