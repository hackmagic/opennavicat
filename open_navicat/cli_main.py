"""Standalone CLI entry point for PyInstaller (no Qt imports)."""

from open_navicat.cli.app import cli_main


def main() -> None:
    cli_main()


if __name__ == "__main__":
    main()
