"""Standalone GUI entry point for PyInstaller."""

import sys

from open_navicat.app import Application


def main() -> int:
    app = Application(sys.argv)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
