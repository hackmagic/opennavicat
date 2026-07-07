"""Import test for CommandPanel widget."""

from __future__ import annotations


def test_import() -> None:
    """Verify the CommandPanel module imports without PySide6 errors."""
    from open_navicat.ui.widgets.command_panel import CommandPanel
    assert CommandPanel is not None
