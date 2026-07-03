"""Standalone GUI entry point for PyInstaller.

Top-level PySide6 imports ensure PyInstaller hooks fire correctly.
"""

import sys

# Top-level imports for PyInstaller hook detection
from PySide6.QtCore import Qt  # noqa: F401
from PySide6.QtWidgets import QApplication  # noqa: F401

from open_navicat.app import Application


def main() -> int:
    app = Application(sys.argv)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
