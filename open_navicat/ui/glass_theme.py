"""
Backward-compatible re-exports from the pywinstyles theme.

All symbols that were previously defined here are now in
open_navicat/ui/themes/acrylic.py.  This module exists so that
existing imports (e.g. from ai_copilot) keep working without
changes.
"""

from __future__ import annotations

from open_navicat.ui.themes.acrylic import (  # noqa: F401
    # Constants
    GLASS_LIGHT, GLASS_MEDIUM, GLASS_DARK, GLASS_ACTIVE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_ACCENT, TEXT_MUTED,
    BORDER_LIGHT, BORDER_MEDIUM,
    # Snippets
    BUTTON_PRIMARY_QSS, BUTTON_GHOST_QSS,
    # Engine
    DwmEngine as AcrylicEngine,
)

# Backward-compatible aliases
setup_acrylic_window = AcrylicEngine.apply_to
