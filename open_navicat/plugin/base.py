"""Plugin base class and registration helpers."""

from __future__ import annotations

from abc import ABC


class BasePlugin(ABC):
    """Abstract base for OpenNavicat plugins.

    Override only the hooks your plugin needs — all have no-op defaults.
    """

    @property
    def name(self) -> str:
        return type(self).__module__.split(".")[-1]

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return ""

    # ---- Lifecycle ----

    def on_load(self) -> None:
        """Called when the plugin is loaded."""

    def on_unload(self) -> None:
        """Called when the plugin is unloaded."""

    def on_ready(self) -> None:
        """Called after all plugins are loaded."""

    # ---- Extension hooks (return dicts of name→callable) ----

    def get_export_formats(self) -> dict[str, callable]:
        """Return {format_name: renderer(rows, title) -> str}."""
        return {}

    def get_mask_rules(self) -> dict[str, callable]:
        """Return {column_pattern: mask_func(val) -> str}."""
        return {}

    def get_notification_backends(self) -> dict[str, callable]:
        """Return {backend_name: send_func(message, config) -> None}."""
        return {}
