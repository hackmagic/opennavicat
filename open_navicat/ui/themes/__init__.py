"""
Theme system for OpenNavicat.

Provides a pluggable theme architecture:
  - Theme (ABC):  base class every theme must implement
  - theme_map:    name → Theme class registry
  - apply_theme:  apply a named theme to the QApplication + QMainWindow

Adding a new theme:
    1. Subclass Theme in a file under open_navicat/ui/themes/
    2. Decorate with @register_theme("theme_name")
    3. The theme is automatically discoverable via theme_map
"""

from __future__ import annotations

import importlib
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication, QMainWindow

logger = logging.getLogger("opennavicat.theme")

# ── Registry ────────────────────────────────────────────────────────────────

theme_map: dict[str, type["Theme"]] = {}

# Known theme modules — imported lazily so their @register_theme decorators fire
_THEME_MODULES: dict[str, str] = {
    "pro-dark": "open_navicat.ui.themes.pro_dark",
    "pro-light": "open_navicat.ui.themes.pro_light",
}


def _ensure_themes_loaded() -> None:
    """Import all known theme modules so their decorators populate theme_map."""
    for name, mod_path in _THEME_MODULES.items():
        if name not in theme_map:
            try:
                importlib.import_module(mod_path)
            except Exception as exc:
                logger.warning("Failed to load theme '%s' from %s: %s", name, mod_path, exc)


def register_theme(name: str):
    """Decorator that registers a Theme subclass under *name*."""
    def wrapper(cls: type[Theme]) -> type[Theme]:
        theme_map[name] = cls
        cls.name = name
        logger.info("Registered theme: %s (%s)", name, cls.__name__)
        return cls
    return wrapper


# ── Base class ──────────────────────────────────────────────────────────────

class Theme(ABC):
    """Abstract base for all visual themes.

    Subclasses must override:
      - name             (class attribute set by @register_theme)
      - apply_stylesheet (set QApplication stylesheet)
      - setup_window     (configure QMainWindow flags, title bar, acrylic, etc.)
    """

    name: str = ""

    @abstractmethod
    def apply_stylesheet(self, app: QApplication) -> None:
        """Apply the global stylesheet to *app*."""

    @abstractmethod
    def setup_window(self, window: QMainWindow) -> None:
        """Configure *window* — window flags, custom chrome, acrylic/blur, etc.

        This is called from MainWindow.__init__ before any child widgets are
        created, so the central widget (if any) is available for _setup_ui().
        """

    def apply(self, app: QApplication, window: QMainWindow) -> None:
        """Convenience: apply stylesheet then configure the window."""
        self.apply_stylesheet(app)
        self.setup_window(window)


# ── Public API ──────────────────────────────────────────────────────────────

def apply_theme(name: str, app: QApplication, window: QMainWindow) -> None:
    """Look up *name* in the registry and apply it (QSS + window setup)."""
    _ensure_themes_loaded()
    cls = theme_map.get(name)
    if cls is None:
        available = ", ".join(theme_map)
        logger.warning("Unknown theme '%s'. Available: %s. Falling back to 'acrylic'.", name, available)
        cls = theme_map.get("acrylic")
    if cls is None:
        raise RuntimeError(f"No theme found (name={name!r}, registry={list(theme_map)})")
    theme = cls()
    # 1. Clear old stylesheet first so Qt doesn't merge old+new
    app.setStyleSheet("")
    app.processEvents()
    # 2. Apply the new theme (QSS + window setup)
    theme.apply(app, window)
    # 3. Force all widgets to re-read the new stylesheet
    app.processEvents()
    refresh_all_widgets(app)
    logger.info("Applied theme: %s", cls.name)


def apply_theme_window(name: str, window: QMainWindow) -> None:
    """Re-apply only the window-level effects (acrylic/blur/title-bar) for *name*.

    This is called from MainWindow.showEvent when the window handle is
    guaranteed to be valid — pywinstyles calls require a valid HWND.
    """
    _ensure_themes_loaded()
    cls = theme_map.get(name)
    if cls is None:
        cls = theme_map.get("acrylic")
    if cls is None:
        return
    theme = cls()
    theme.setup_window(window)
    logger.info("Re-applied window effects for theme: %s", cls.name)


def refresh_all_widgets(app: QApplication) -> None:
    """Force-polish all top-level widgets so the new QSS takes effect immediately.

    Qt caches style information per-widget; after changing the application
    stylesheet at runtime, every widget must be unpolished then re-polished
    so it picks up the new rules.
    """
    app_style = app.style()
    for widget in app.topLevelWidgets():
        _deep_polish(widget, app_style)
    # Extra pass: update the entire app palette
    app.setPalette(app.style().standardPalette())


def _deep_polish(widget, app_style) -> None:
    """Recursively unpolish/re-polish *widget* and all QWidget descendants.

    Uses QApplication.style() (not widget.style()) for reliable cross-theme
    style refresh.
    """
    from PySide6.QtWidgets import QWidget as _QWidget

    if not isinstance(widget, _QWidget):
        return
    # Unpolish → re-polish via the application-level style engine
    app_style.unpolish(widget)
    app_style.polish(widget)
    # Recursively process every QWidget child
    for child in widget.children():
        if isinstance(child, _QWidget):
            _deep_polish(child, app_style)


def list_themes() -> list[str]:
    """Return sorted list of registered theme names."""
    _ensure_themes_loaded()
    return sorted(theme_map)
