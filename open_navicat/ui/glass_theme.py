"""
Backward-compatible re-exports from the pywinstyles theme.

All symbols that were previously defined here are now in
open_navicat/ui/themes/acrylic.py.  This module exists so that
existing imports (e.g. from ai_copilot) keep working without
changes.
"""

from __future__ import annotations

from open_navicat.ui.themes.acrylic import (  # noqa: F401
    BORDER_LIGHT,
    BORDER_MEDIUM,
    BUTTON_GHOST_QSS,
    # Snippets
    BUTTON_PRIMARY_QSS,
    GLASS_ACTIVE,
    GLASS_DARK,
    # Constants
    GLASS_LIGHT,
    GLASS_MEDIUM,
    TEXT_ACCENT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from open_navicat.ui.themes.acrylic import (
    # Engine
    DwmEngine as AcrylicEngine,
)

# Backward-compatible aliases
setup_acrylic_window = AcrylicEngine.apply_to
