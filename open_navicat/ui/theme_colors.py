"""Dynamic theme color accessor — returns the current theme's Color class."""

from __future__ import annotations

from open_navicat.config import config


def get_colors():
    """Return the Color class for the currently active theme."""
    from open_navicat.ui.themes import _ensure_themes_loaded, theme_map
    _ensure_themes_loaded()
    name = config.get("theme", "pro-dark")
    cls = theme_map.get(name)
    if cls is None:
        cls = theme_map.get("pro-dark")
    if cls is None:
        # Fallback: minimal dark palette
        class _Fallback:
            BG_PRIMARY = "#1e1e2e"
            BG_SECONDARY = "#181825"
            SURFACE = "#313244"
            TEXT_PRIMARY = "#cdd6f4"
            TEXT_SECONDARY = "#a6adc8"
            TEXT_MUTED = "#6c7086"
            ACCENT = "#89b4fa"
            ACCENT_HOVER = "#b4d0fb"
            ACCENT_PRESSED = "#6a94e0"
            ACCENT_BG = "#1e2a4a"
            BORDER = "#45475a"
            BORDER_LIGHT = "#585b70"
            ERROR = "#f38ba8"
            SUCCESS = "#a6e3a1"
            WARNING = "#f9e2af"
        return _Fallback
    return cls.Color
