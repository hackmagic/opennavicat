"""Application bootstrap — QApplication setup, i18n, theme, main window."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QLocale
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QPixmap, QIcon

from open_navicat import __app_name__, __version__
from open_navicat.config import config
from open_navicat.ui.main_window import MainWindow

logger = logging.getLogger("opennavicat.app")

# Paths to resource assets
_RESOURCES = Path(__file__).resolve().parent / "ui" / "resources"


def _load_icon(name: str) -> QIcon:
    """Load an SVG icon from the resources directory, falling back silently."""
    path = _RESOURCES / name
    if path.exists():
        return QIcon(str(path))
    return QIcon()


def _load_pixmap(name: str) -> QPixmap:
    """Load an SVG pixmap from the resources directory."""
    path = _RESOURCES / name
    if path.exists():
        return QPixmap(str(path))
    return QPixmap()


def _setup_logging() -> None:
    """Configure logging for debug diagnostics."""
    level = logging.DEBUG
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, force=True)
    logging.getLogger("opennavicat").setLevel(level)


class Application:
    """Wraps QApplication lifecycle and global initialisation."""

    def __init__(self, argv: list[str]) -> None:
        _setup_logging()
        self._qt_app = QApplication(argv)
        self._qt_app.setApplicationName(__app_name__)
        self._qt_app.setApplicationVersion(__version__)
        self._qt_app.setOrganizationName(__app_name__)

        # Set application icon
        app_icon = _load_icon("icon.svg")
        if not app_icon.isNull():
            self._qt_app.setWindowIcon(app_icon)
            logger.info("App icon loaded from resources/icon.svg")

        self._apply_settings()
        self._main_window: MainWindow | None = None

    # ---- public API ----

    def run(self) -> int:
        """Show the main window and enter the event loop."""
        self._show_splash()
        self._main_window = MainWindow()
        self._main_window.show()
        self._hide_splash()
        return self._qt_app.exec()

    # ---- internal helpers ----

    def _apply_settings(self) -> None:
        """Apply persisted preferences to QApplication."""
        locale_str = config.language.replace("_", "-")
        self._qt_app.setProperty("appLanguage", config.language)

        # Theme is applied in MainWindow.__init__ via apply_theme()
        # Nothing to do here — MainWindow handles it
        pass

    def _show_splash(self) -> None:
        """Display a branded splash screen while the app loads."""
        pix = _load_pixmap("splash.svg")
        splash = QSplashScreen(pix if not pix.isNull() else QPixmap())
        splash.showMessage(
            f"{__app_name__} v{__version__} — Loading…",
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignCenter,
        )
        splash.show()
        self._qt_app.processEvents()
        # Store so we can close it later
        self._splash = splash

    def _hide_splash(self) -> None:
        if hasattr(self, "_splash") and self._splash is not None:
            self._splash.close()
            self._splash = None
