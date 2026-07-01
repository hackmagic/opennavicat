"""Internationalization (i18n) — lightweight translation support.

Usage:
    from open_navicat.i18n.translator import t, set_language

    set_language("zh_CN")
    print(t("connection.new"))          # "新建连接"
    print(t("status.connected", host="localhost"))  # "已连接到 localhost"
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from open_navicat.config import config

_TRANSLATIONS: dict[str, str] = {}
_CURRENT_LANG: str = ""


def _load_lang(lang: str) -> dict[str, str]:
    """Load translation JSON file for the given language code."""
    path = Path(__file__).parent / f"{lang}.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def set_language(lang: str | None = None) -> None:
    """Set active language. Defaults to config language."""
    global _TRANSLATIONS, _CURRENT_LANG
    lang = lang or config.get("language", "zh_CN")
    _TRANSLATIONS = _load_lang(lang)
    _CURRENT_LANG = lang


def t(key: str, **kwargs: Any) -> str:
    """Translate a key into the current language, with optional format vars."""
    if not _TRANSLATIONS:
        set_language()
    text = _TRANSLATIONS.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text


def current_language() -> str:
    """Return the currently active language code."""
    if not _CURRENT_LANG:
        set_language()
    return _CURRENT_LANG


# Initialize on import
set_language()
