"""Global configuration management for OpenNavicat."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _get_config_dir() -> Path:
    """Return the platform-specific config directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif os.uname().sysname == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "OpenNavicat"


CONFIG_DIR = _get_config_dir()
DATA_DIR = CONFIG_DIR / "data"
CONFIG_FILE = CONFIG_DIR / "settings.json"
CONNECTION_DB = DATA_DIR / "connections.sqlite"


class AppConfig:
    """Application-level configuration, persisted as JSON."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            raw = CONFIG_FILE.read_text(encoding="utf-8")
            self._data = json.loads(raw)
        else:
            self._data = self._defaults()
            self._save()

    def _save(self) -> None:
        CONFIG_FILE.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _defaults() -> dict[str, Any]:
        return {
            "language": "en_US",
            "theme": "light",
            "editor": {
                "font_size": 13,
                "font_family": "Consolas",
                "tab_size": 4,
                "auto_complete": True,
            },
            "data_viewer": {
                "page_size": 500,
                "max_text_preview": 1024,
                "null_string": "(NULL)",
            },
            "ai": {
                "provider": "openai",
                "api_key": "",
                "api_base": "https://api.openai.com/v1",
                "model": "gpt-4o-mini",
            },
            "pool": {
                "min_size": 1,
                "max_size": 10,
            },
            "recent_connections": [],
            "window": {
                "x": 100,
                "y": 100,
                "width": 1280,
                "height": 800,
                "maximized": False,
            },
        }

    # ---- accessors ----

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        val: Any = self._data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
        return val if val is not None else default

    def set(self, key: str, value: Any) -> None:
        keys = key.split(".")
        target = self._data
        for k in keys[:-1]:
            target = target.setdefault(k, {})
        target[keys[-1]] = value
        self._save()

    @property
    def language(self) -> str:
        return self.get("language", "en_US")

    @language.setter
    def language(self, lang: str) -> None:
        self.set("language", lang)

    @property
    def theme(self) -> str:
        return self.get("theme", "light")

    @theme.setter
    def theme(self, t: str) -> None:
        self.set("theme", t)


# Module-level singleton
config = AppConfig()
