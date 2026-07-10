"""Auto Recovery service — periodically saves editor content for crash recovery."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

# Singleton
_instance: AutoRecoveryService | None = None


class AutoRecoveryService:
    """Periodically saves editor content to prevent data loss on crash."""

    def __init__(self) -> None:
        self._recovery_dir = Path.home() / ".opennavicat" / "recovery"
        self._recovery_dir.mkdir(parents=True, exist_ok=True)
        self._interval: int = 30  # seconds
        self._enabled: bool = True
        self._editors: dict[str, Any] = {}  # editor_id -> (widget, get_text_fn)
        self._last_save: dict[str, float] = {}

    @classmethod
    def instance(cls) -> AutoRecoveryService:
        global _instance
        if _instance is None:
            _instance = cls()
        return _instance

    def configure(self, interval: int = 30, enabled: bool = True) -> None:
        self._interval = interval
        self._enabled = enabled

    def register_editor(self, editor_id: str, widget: Any, get_text_fn: Any) -> None:
        """Register an editor for auto-recovery.

        Args:
            editor_id: Unique identifier (e.g., "query_123", "bi_dashboard_456")
            widget: The editor widget (for checking if modified)
            get_text_fn: Callable that returns the current text content
        """
        self._editors[editor_id] = (widget, get_text_fn)
        self._last_save[editor_id] = time.time()

    def unregister_editor(self, editor_id: str) -> None:
        self._editors.pop(editor_id, None)
        self._last_save.pop(editor_id, None)
        # Clean up recovery file
        recovery_file = self._recovery_dir / f"{editor_id}.json"
        if recovery_file.exists():
            recovery_file.unlink()

    def save_all(self) -> int:
        """Save all registered editors. Returns count of saved editors."""
        if not self._enabled:
            return 0

        saved = 0
        now = time.time()
        for editor_id, (widget, get_text_fn) in list(self._editors.items()):
            last = self._last_save.get(editor_id, 0)
            if now - last >= self._interval:
                try:
                    content = get_text_fn()
                    if content:
                        recovery_file = self._recovery_dir / f"{editor_id}.json"
                        data = {
                            "editor_id": editor_id,
                            "content": content,
                            "timestamp": now,
                        }
                        recovery_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                        self._last_save[editor_id] = now
                        saved += 1
                except Exception as e:
                    _log.warning("Auto-recovery save failed for %s: %s", editor_id, e)
        return saved

    def recover(self, editor_id: str) -> str | None:
        """Recover content for an editor. Returns content or None."""
        recovery_file = self._recovery_dir / f"{editor_id}.json"
        if not recovery_file.exists():
            return None
        try:
            data = json.loads(recovery_file.read_text(encoding="utf-8"))
            return data.get("content")
        except Exception as e:
            _log.warning("Auto-recovery load failed for %s: %s", editor_id, e)
            return None

    def list_recovery_files(self) -> list[dict[str, Any]]:
        """List all recovery files with metadata."""
        results = []
        for f in self._recovery_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                results.append({
                    "editor_id": data.get("editor_id"),
                    "timestamp": data.get("timestamp"),
                    "file": str(f),
                })
            except Exception:
                pass
        return sorted(results, key=lambda x: x.get("timestamp", 0), reverse=True)

    def cleanup_recovery(self, editor_id: str) -> None:
        """Remove recovery file after successful save."""
        recovery_file = self._recovery_dir / f"{editor_id}.json"
        if recovery_file.exists():
            recovery_file.unlink()
