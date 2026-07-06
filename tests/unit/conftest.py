"""Global conftest — mock PySide6 and problematic sub-packages for all UI import tests."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# ── PySide6 ────────────────────────────────────────────────────────────────
_pyside6 = MagicMock()
_pyside6.__version__ = "6.11.0"  # pytest-qt needs this for report header
sys.modules.setdefault("PySide6", _pyside6)
sys.modules.setdefault("PySide6.QtCore", MagicMock())
sys.modules.setdefault("PySide6.QtWidgets", MagicMock())
sys.modules.setdefault("PySide6.QtGui", MagicMock())
sys.modules.setdefault("PySide6.QtNetwork", MagicMock())
sys.modules.setdefault("PySide6.QtSvg", MagicMock())
sys.modules.setdefault("PySide6.QtSvgWidgets", MagicMock())
sys.modules.setdefault("PySide6.QtPrintSupport", MagicMock())
sys.modules.setdefault("PySide6.QtConcurrent", MagicMock())
sys.modules.setdefault("PySide6.QtDBus", MagicMock())
sys.modules.setdefault("PySide6.QtXml", MagicMock())

# ── Sub-packages that fail to import with mocked PySide6 ──────────────────
# model_designer & object_designer subclass PySide6 classes at module level,
# which returns a MagicMock instead of a real class, losing class attributes.
sys.modules.setdefault("open_navicat.ui.widgets.model_designer", MagicMock())
sys.modules.setdefault("open_navicat.ui.widgets.object_designer", MagicMock())
