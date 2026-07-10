"""Bundled plugin: export query results as pretty JSON lines."""

from __future__ import annotations

import json
from typing import Any

from open_navicat.plugin.base import BasePlugin


def _export_jsonl(rows: list[dict[str, Any]], title: str = "") -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows)


class JSONLExport(BasePlugin):
    @property
    def name(self) -> str:
        return "jsonl_export"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Export query results as JSON Lines (.jsonl)"

    def get_export_formats(self) -> dict[str, callable]:
        return {"jsonl": _export_jsonl}
