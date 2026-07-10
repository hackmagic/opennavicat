"""Unit tests for auto_recovery_service."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

from open_navicat.services.auto_recovery_service import AutoRecoveryService


class TestAutoRecoveryService:
    def test_singleton(self) -> None:
        a = AutoRecoveryService.instance()
        b = AutoRecoveryService.instance()
        assert a is b

    def test_register_and_unregister(self) -> None:
        svc = AutoRecoveryService()
        svc._editors.clear()
        svc._last_save.clear()

        widget = MagicMock()
        svc.register_editor("test_1", widget, lambda: "hello")
        assert "test_1" in svc._editors

        svc.unregister_editor("test_1")
        assert "test_1" not in svc._editors

    def test_save_and_recover(self) -> None:
        svc = AutoRecoveryService()
        svc._editors.clear()
        svc._last_save.clear()

        svc.register_editor("save_test", MagicMock(), lambda: "SELECT 1")
        svc._interval = 0  # immediate

        saved = svc.save_all()
        assert saved == 1

        content = svc.recover("save_test")
        assert content == "SELECT 1"

        svc.cleanup_recovery("save_test")
        assert svc.recover("save_test") is None

    def test_disabled_skips_save(self) -> None:
        svc = AutoRecoveryService()
        svc._enabled = False
        svc.register_editor("x", MagicMock(), lambda: "data")
        assert svc.save_all() == 0
        svc._enabled = True

    def test_list_recovery_files(self) -> None:
        svc = AutoRecoveryService()
        svc._editors.clear()
        svc._last_save.clear()

        svc.register_editor("list_test", MagicMock(), lambda: "content")
        svc._interval = 0
        svc.save_all()

        files = svc.list_recovery_files()
        assert any(f["editor_id"] == "list_test" for f in files)

        svc.cleanup_recovery("list_test")
