"""Entry point for OpenNavicat — supports both CLI and GUI modes.

Usage:
    opennavicat <command>    # CLI mode (default)
    opennavicat gui          # Launch GUI
    opennavicat --version    # Show version
"""

from __future__ import annotations

import sys
import os


def cli_main() -> None:
    """Entry point for CLI mode (default)."""
    # If user passes "gui" as the first arg, launch GUI instead
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        sys.argv.pop(1)  # Remove "gui" from args
        main()
        return

    # Support: --version
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v"):
        from open_navicat import __version__
        print(f"OpenNavicat v{__version__}")
        sys.exit(0)

    from open_navicat.cli.app import cli_main as _cli
    # Re-export for the pyproject.toml entry point
    _cli()


def main() -> int:
    """Launch the OpenNavicat GUI application."""
    from open_navicat.app import Application
    app = Application(sys.argv)
    return app.run()


if __name__ == "__main__":
    if "--gui" in sys.argv or os.environ.get("OPENNAVICAT_MODE") == "gui":
        sys.exit(main())
    else:
        cli_main()
