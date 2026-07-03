"""Standalone CLI entry point for PyInstaller (no Qt imports).

Routes 'gui' argument to launch GUI instead of CLI.
"""

import sys


def main() -> None:
    """CLI entry point. If first arg is 'gui', launch the PySide6 GUI."""
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        sys.argv.pop(1)  # Remove "gui" from args
        from open_navicat.gui_main import main as gui_main
        gui_main()
        return

    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-v"):
        from open_navicat import __version__
        print(f"OpenNavicat v{__version__}")
        return

    from open_navicat.cli.app import cli_main
    cli_main()


if __name__ == "__main__":
    main()
