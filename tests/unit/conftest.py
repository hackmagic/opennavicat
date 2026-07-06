"""Global conftest — mock PySide6 and problematic sub-packages for all UI import tests."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock


def _mock_module(name: str) -> MagicMock:
    m = MagicMock()
    m.__version__ = "6.11.0"  # pytest-qt needs __version__ on all Qt modules
    sys.modules.setdefault(name, m)
    return m


# ── PySide6 ────────────────────────────────────────────────────────────────
_pyside6 = MagicMock()
_pyside6.__version__ = "6.11.0"
sys.modules.setdefault("PySide6", _pyside6)

# All Qt submodules need __version__ for pytest-qt
for _sub in ("QtCore", "QtWidgets", "QtGui", "QtNetwork", "QtSvg",
             "QtSvgWidgets", "QtPrintSupport", "QtConcurrent", "QtDBus", "QtXml"):
    _mock_module(f"PySide6.{_sub}")

# ── Sub-packages that fail to import with mocked PySide6 ──────────────────
# model_designer & object_designer subclass PySide6 classes at module level,
# which returns a MagicMock instead of a real class, losing class attributes.
sys.modules.setdefault("open_navicat.ui.widgets.model_designer", MagicMock())
sys.modules.setdefault("open_navicat.ui.widgets.object_designer", MagicMock())
