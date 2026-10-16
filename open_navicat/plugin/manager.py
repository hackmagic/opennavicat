"""Plugin discovery, lifecycle management and host-side hook wiring."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from open_navicat.plugin import loader
from open_navicat.plugin.base import BasePlugin
from open_navicat.plugin.permissions import HOOK_PERMISSIONS, check_hook_permissions

logger = logging.getLogger("opennavicat.plugin")


class PluginManager:
    """Discovers and manages plugins from entry_points, bundled plugins and
    installed ``.onvpkg`` packages."""

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}
        self._export_formats: dict[str, callable] = {}
        self._mask_rules: dict[str, callable] = {}
        self._notification_backends: dict[str, callable] = {}
        #: plugin id -> permissions it was granted.  Entry-point and bundled
        #: plugins are trusted by construction and get every hook permission.
        self._granted: dict[str, list[str]] = {}
        self._errors: list[str] = []

    @property
    def plugins(self) -> dict[str, BasePlugin]:
        return dict(self._plugins)

    @property
    def load_errors(self) -> list[str]:
        """Failures from the most recent ``discover_and_load`` call."""
        return list(self._errors)

    def discover_and_load(self) -> None:
        """Discover plugins from every source and wire up their hooks."""
        self._errors = []
        self._load_entry_point_plugins()
        self._load_bundled_plugins()
        self._load_installed_plugins()
        for p in self._plugins.values():
            try:
                p.on_ready()
            except Exception as e:
                self._note(f"{getattr(p, 'name', '?')}: on_ready failed ({e})")

    def _note(self, message: str) -> None:
        logger.warning(message)
        self._errors.append(message)

    def _load_entry_point_plugins(self) -> None:
        """Load plugins registered via 'opennavicat.plugins' entry point."""
        try:
            import importlib.metadata as met

            for ep in met.entry_points(group="opennavicat.plugins"):
                try:
                    cls = ep.load()
                    self._register(cls(), _all_permissions=True)
                except Exception as e:
                    self._note(f"entry point {ep.name}: {e}")
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
                        if (
                            isinstance(obj, type)
                            and issubclass(obj, BasePlugin)
                            and obj is not BasePlugin
                        ):
                            self._register(obj(), _all_permissions=True)
                except Exception as e:
                    self._note(f"bundled plugin {mod_name}: {e}")
        except ImportError:
            pass

    def _load_installed_plugins(self) -> None:
        """Load installed ``.onvpkg`` plugins that are enabled.

        Each plugin is imported under its own mangled top-level package so
        two plugins cannot shadow each other (or the host).
        """
        try:
            installed = loader.read_installed()
        except Exception as e:
            self._note(f"cannot read installed plugins: {e}")
            return
        for plugin_id, entry in sorted(installed.items()):
            if not entry.enabled:
                logger.debug("Plugin %s is disabled, skipping", plugin_id)
                continue
            try:
                cls = loader.import_plugin_class(entry)
            except Exception as e:
                self._note(str(e))
                continue
            self._register(cls(), _all_permissions=False, manifest=entry.manifest)

    def _register(
        self,
        plugin: BasePlugin,
        *,
        _all_permissions: bool = False,
        manifest: Any = None,
    ) -> None:
        granted: list[str]
        if _all_permissions:
            granted = sorted({p for names in HOOK_PERMISSIONS.values() for p in names})
        else:
            granted = list(getattr(manifest, "permissions", []) or [])
        name = getattr(plugin, "name", None) or getattr(manifest, "id", type(plugin).__name__)
        if name in self._plugins:
            logger.debug("Plugin %s already loaded, skipping", name)
            return
        try:
            plugin.on_load()
            self._plugins[name] = plugin
            self._granted[name] = granted
            self._wire_hooks(plugin, granted, name)
            logger.info(
                "Loaded plugin: %s v%s%s",
                name,
                getattr(plugin, "version", "?"),
                f" (permissions: {', '.join(granted)})" if granted else "",
            )
        except Exception as e:
            self._note(f"{name}: {e}")

    def _wire_hooks(self, plugin: BasePlugin, granted: list[str], plugin_id: str) -> None:
        """Register hook results, refusing hooks whose permission is missing.

        A missing permission drops only that hook; the plugin still loads so
        a single over-broad plugin cannot take the whole host down.
        """
        for hook_name, target in (
            ("get_export_formats", self._export_formats),
            ("get_mask_rules", self._mask_rules),
            ("get_notification_backends", self._notification_backends),
        ):
            hook = getattr(plugin, hook_name, None)
            if not callable(hook):
                continue
            problems = check_hook_permissions(hook_name, granted, plugin_id)
            if problems:
                for problem in problems:
                    self._note(problem)
                continue
            try:
                produced = hook() or {}
            except Exception as e:
                self._note(f"{plugin_id}: {hook_name} raised {type(e).__name__}: {e}")
                continue
            for key, value in produced.items():
                if key in target and target[key] is not value:
                    self._note(
                        f"{plugin_id}: hook {hook_name} wants to override {key!r}, "
                        "which is already registered -- keeping the first plugin"
                    )
                    continue
                target[key] = value

    def granted_permissions(self, plugin_id: str) -> list[str]:
        return list(self._granted.get(plugin_id, []))

    def unload_all(self) -> None:
        for name, p in self._plugins.items():
            try:
                p.on_unload()
            except Exception as e:
                logger.warning("Error unloading plugin %s: %s", name, e)
        self._plugins.clear()
        self._granted.clear()
        self._export_formats.clear()
        self._mask_rules.clear()
        self._notification_backends.clear()

    def reload_installed(self) -> int:
        """Re-scan installed packages.  Returns the number of new plugins."""
        before = set(self._plugins)
        self._load_installed_plugins()
        return len(set(self._plugins) - before)

    # ---- Hook accessors ----

    def get_export_formats(self) -> dict[str, callable]:
        return dict(self._export_formats)

    def get_mask_rules(self) -> dict[str, callable]:
        return dict(self._mask_rules)

    def get_notification_backends(self) -> dict[str, callable]:
        return dict(self._notification_backends)


plugin_manager = PluginManager()
