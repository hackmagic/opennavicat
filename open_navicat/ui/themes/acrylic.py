"""
DWM engine — acrylic/blur window effect via pywinstyles.

This module provides the DwmEngine used by pro-dark and pro-light
to apply Windows DWM composition effects to the main window.
All DWM theme variants (acrylic, aero, mica, ...) have been removed.
Use pro-dark or pro-light instead.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QMainWindow

logger = logging.getLogger("opennavicat.theme.dwm")

# ── Colour palette (kept for backward compat via glass_theme.py) ──────
GLASS_LIGHT    = "rgba(255, 255, 255, 0.06)"
GLASS_MEDIUM   = "rgba(255, 255, 255, 0.10)"
GLASS_DARK     = "rgba(0, 0, 0, 0.20)"
GLASS_ACTIVE   = "rgba(255, 255, 255, 0.15)"

TEXT_PRIMARY   = "#f0f0f0"
TEXT_SECONDARY = "#b0b0b0"
TEXT_ACCENT    = "#64b5f6"
TEXT_MUTED     = "#888888"

BORDER_LIGHT   = "rgba(255, 255, 255, 0.12)"
BORDER_MEDIUM  = "rgba(255, 255, 255, 0.06)"

BUTTON_PRIMARY_QSS = """
    QPushButton {
        padding: 6px 16px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 rgba(233,69,96,0.7),
                                    stop:1 rgba(83,52,131,0.7));
        color: #f0f0f0;
        border: none;
        border-radius: 6px;
        font-size: 11px;
        font-weight: bold;
    }
    QPushButton:hover {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 rgba(255,90,119,0.85),
                                    stop:1 rgba(107,68,160,0.85));
    }
    QPushButton:pressed {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 rgba(201,56,79,0.85),
                                    stop:1 rgba(69,43,112,0.85));
    }
"""

BUTTON_GHOST_QSS = """
    QPushButton {
        padding: 4px 12px;
        background: rgba(255, 255, 255, 0.06);
        color: #b0b0b0;
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 6px;
        font-size: 11px;
    }
    QPushButton:hover {
        background: rgba(255, 255, 255, 0.15);
        color: #f0f0f0;
        border-color: rgba(255, 255, 255, 0.25);
    }
    QPushButton:pressed {
        background: rgba(255, 255, 255, 0.20);
        color: #f0f0f0;
    }
"""


class DwmEngine:
    """Applies DWM acrylic/blur via pywinstyles.

    Used by pro-dark and pro-light for window background effects.
    Must be called after the window handle (winId) is valid.
    """

    _applied = False
    _style: str = "acrylic"

    @classmethod
    def apply_to(cls, window: QMainWindow) -> None:
        """Apply DWM effect to *window*."""
        try:
            import pywinstyles
            from pywinstyles.py_win_style import ChangeDWMAttrib, detect
            if window.winId():
                pywinstyles.apply_style(window, cls._style)
                ChangeDWMAttrib(detect(window), 20, __import__("ctypes").c_int(1))
                cls._applied = True
                logger.info("DWM style '%s' applied (winId=%d)", cls._style, int(window.winId()))
            else:
                logger.warning("winId() not ready — call DwmEngine.apply_to after show()")
        except ImportError:
            logger.warning("pywinstyles not installed — DWM styles unavailable")
