"""Global conftest — mock PySide6 only when not installed (for CI without Qt)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock


# ── Only mock PySide6 when it's not actually installed ──────────────────
try:
    import PySide6  # noqa: F401
except ImportError:
    def _mock_module(name: str) -> MagicMock:
        m = MagicMock()
        m.__version__ = "6.11.0"  # pytest-qt needs __version__ on all Qt modules
        sys.modules[name] = m
        return m

    _pyside6 = MagicMock()
    _pyside6.__version__ = "6.11.0"
    sys.modules["PySide6"] = _pyside6

    # pytest-qt does `from PySide6 import QtCore` which goes through
    # attribute access, NOT sys.modules. Set as attrs on the parent mock.
    for _sub in ("QtCore", "QtWidgets", "QtGui", "QtNetwork", "QtSvg",
                 "QtSvgWidgets", "QtPrintSupport", "QtConcurrent", "QtDBus", "QtXml"):
        m = _mock_module(f"PySide6.{_sub}")
        setattr(_pyside6, _sub, m)

    # Sub-packages that fail to import with mocked PySide6
    sys.modules.setdefault("open_navicat.ui.widgets.model_designer", MagicMock())
    sys.modules.setdefault("open_navicat.ui.widgets.object_designer", MagicMock())
else:
    # PySide6 is installed — skip all mocking, use real modules
    pass
