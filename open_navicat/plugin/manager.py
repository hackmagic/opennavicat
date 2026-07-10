"""Plugin discovery and lifecycle management."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from open_navicat.plugin.base import BasePlugin

logger = logging.getLogger("opennavicat.plugin")


class PluginManager:
    """Discovers and manages plugins from entry_points and bundled plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}
        self._export_formats: dict[str, callable] = {}
        self._mask_rules: dict[str, callable] = {}
        self._notification_backends: dict[str, callable] = {}

    @property
    def plugins(self) -> dict[str, BasePlugin]:
        return dict(self._plugins)

    def discover_and_load(self) -> None:
        """Discover plugins from entry_points and bundled packages."""
        self._load_entry_point_plugins()
        self._load_bundled_plugins()
        for p in self._plugins.values():
            p.on_ready()

    def _load_entry_point_plugins(self) -> None:
        """Load plugins registered via 'opennavicat.plugins' entry point."""
        try:
            import importlib.metadata as met
            for ep in met.entry_points(group="opennavicat.plugins"):
                try:
                    cls = ep.load()
                    self._register(cls())
                except Exception as e:
                    logger.warning("Failed to load plugin %s: %s", ep.name, e)
        except Exception as e:
            logger.debug("Entry-point discovery skipped: %s", e)

    def _load_bundled_plugins(self) -> None:
        """Auto-discover plugin modules under open_navicat.plugins."""
        try:
            import open_navicat.plugins as pkg
            for _, mod_name, _ in pkgutil.iter_modules(pkg.__path__):
                if mod_name.startswith("_"):
                    continue
                try:
                    mod = importlib.import_module(f"open_navicat.plugins.{mod_name}")
                    for attr in dir(mod):
                        obj = getattr(mod, attr)
                        if isinstance(obj, type) and issubclass(obj, BasePlugin) and obj is not BasePlugin:
                            self._register(obj())
                except Exception as e:
                    logger.warning("Failed to load bundled plugin %s: %s", mod_name, e)
        except ImportError:
            pass

    def _register(self, plugin: BasePlugin) -> None:
        if plugin.name in self._plugins:
            logger.debug("Plugin %s already loaded, skipping", plugin.name)
            return
        try:
            plugin.on_load()
            self._plugins[plugin.name] = plugin
            self._export_formats.update(plugin.get_export_formats())
            self._mask_rules.update(plugin.get_mask_rules())
            self._notification_backends.update(plugin.get_notification_backends())
            logger.info("Loaded plugin: %s v%s", plugin.name, plugin.version)
        except Exception as e:
            logger.warning("Error loading plugin %s: %s", plugin.name, e)

    def unload_all(self) -> None:
        for p in self._plugins.values():
            try:
                p.on_unload()
            except Exception as e:
                logger.warning("Error unloading plugin %s: %s", p.name, e)
        self._plugins.clear()
        self._export_formats.clear()
        self._mask_rules.clear()
        self._notification_backends.clear()

    # ---- Hook accessors ----

    def get_export_formats(self) -> dict[str, callable]:
        return dict(self._export_formats)

    def get_mask_rules(self) -> dict[str, callable]:
        return dict(self._mask_rules)

    def get_notification_backends(self) -> dict[str, callable]:
        return dict(self._notification_backends)


plugin_manager = PluginManager()
