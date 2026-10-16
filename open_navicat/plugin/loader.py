"""Installing, extracting and importing plugin packages.

Install layout on disk::

    <plugins_root>/
        installed/<plugin-id>/plugin.json
        installed/<plugin-id>/plugin.json.sig
        installed/<plugin-id>/code/...          the importable package
        installed/<plugin-id>/state.json        {"enabled": true}

Each plugin's ``code/`` is imported under a **mangled top-level name** derived
from its id (``com.example.demo`` -> ``onvp_com_example_demo``).  Importing
every plugin under a bare name like ``code`` or ``plugin`` would let two
plugins shadow each other, or shadow an application module; the mangled
prefix makes collisions impossible without asking authors to namespace their
own code.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import re
import shutil
import sys
from pathlib import Path

from open_navicat.errors import PluginError, PluginPackageError
from open_navicat.plugin.base import BasePlugin
from open_navicat.plugin.manifest import PluginManifest, parse_manifest
from open_navicat.plugin.package import (
    CODE_DIR,
    MANIFEST_NAME,
    SIGNATURE_NAME,
    PackagedPlugin,
)

logger = logging.getLogger("opennavicat.plugin")

__all__ = [
    "INSTALLED_DIRNAME",
    "STATE_FILENAME",
    "mangle_plugin_id",
    "InstalledPlugin",
    "extract_package",
    "read_installed",
    "write_state",
    "remove_installed",
    "import_plugin_class",
    "unload_plugin_module",
]

INSTALLED_DIRNAME = "installed"
STATE_FILENAME = "state.json"
_TOP_PREFIX = "onvp_"
_MANGLE_RE = re.compile(r"[^a-z0-9]+")


def mangle_plugin_id(plugin_id: str) -> str:
    """``com.example.demo`` -> ``onvp_com_example_demo`` (a valid module name)."""
    mangled = _MANGLE_RE.sub("_", plugin_id.strip().lower()).strip("_")
    if not mangled or mangled[0].isdigit():
        mangled = f"p{mangled}"
    return f"{_TOP_PREFIX}{mangled}"


class InstalledPlugin:
    """One plugin directory under ``installed/``."""

    def __init__(self, root: Path, manifest: PluginManifest, enabled: bool) -> None:
        self.root = root
        self.manifest = manifest
        self.enabled = enabled

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def module_name(self) -> str:
        return mangle_plugin_id(self.manifest.id)

    def state_path(self) -> Path:
        return self.root / STATE_FILENAME


def _plugins_root() -> Path:
    """Root directory holding ``installed/``."""
    from open_navicat.config import CONFIG_DIR

    root = CONFIG_DIR / "plugins"
    root.mkdir(parents=True, exist_ok=True)
    return root


def installed_root() -> Path:
    return _plugins_root() / INSTALLED_DIRNAME


def _read_enabled_flag(path: Path) -> bool:
    if not path.is_file():
        return True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return bool(data.get("enabled", True))


def read_installed() -> dict[str, InstalledPlugin]:
    """Every plugin on disk, keyed by id.

    A directory whose manifest cannot be parsed is reported to the log and
    skipped rather than aborting the whole scan: one broken plugin must not
    stop the other plugins from loading.
    """
    out: dict[str, InstalledPlugin] = {}
    root = installed_root()
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / MANIFEST_NAME
        if not manifest_path.is_file():
            logger.warning("plugin directory %s has no %s", entry.name, MANIFEST_NAME)
            continue
        try:
            manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"))
        except PluginError as exc:
            logger.warning("skipping plugin directory %s: %s", entry.name, exc)
            continue
        out[manifest.id] = InstalledPlugin(
            entry, manifest, _read_enabled_flag(entry / STATE_FILENAME)
        )
    return out


def write_state(plugin_id: str, enabled: bool) -> None:
    """Persist the enabled/disabled flag for one plugin."""
    entry = installed_root() / plugin_id
    entry.mkdir(parents=True, exist_ok=True)
    payload = {"enabled": bool(enabled)}
    (entry / STATE_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def remove_installed(plugin_id: str) -> bool:
    """Delete an installed plugin directory.  Returns True when it existed."""
    entry = installed_root() / plugin_id
    if not entry.is_dir():
        return False
    shutil.rmtree(entry, ignore_errors=True)
    unload_plugin_module(plugin_id)
    return True


def extract_package(pkg: PackagedPlugin, plugins_root: Path) -> Path:
    """Write a verified package into ``installed/<id>/`` and return that path.

    The destination is removed first so an upgrade leaves no stale files from
    the previous version behind (a file deleted in v2 would otherwise survive
    and keep importing).
    """
    from open_navicat.plugin.manifest import dump_manifest

    dest = plugins_root / INSTALLED_DIRNAME / pkg.id
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / MANIFEST_NAME).write_text(dump_manifest(pkg.manifest), encoding="utf-8")
    if pkg.signature:
        (dest / SIGNATURE_NAME).write_text(pkg.signature, encoding="utf-8")
    for name, blob in pkg.files.items():
        if name == "README.md":
            target = dest / "README.md"
        elif name.startswith(f"{CODE_DIR}/"):
            # Keep the code/ level: import_plugin_class() imports
            # <mangled>.plugin, so the package root must be the directory
            # holding __init__.py, i.e. code/ itself.
            target = dest / name
        else:
            target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    return dest


def _ensure_package_importable(installed: InstalledPlugin, module_name: str) -> None:
    """Register the plugin's ``code/`` package under its mangled name."""
    if module_name in sys.modules:
        return
    code_dir = installed.root / CODE_DIR
    init_file = code_dir / "__init__.py"
    if not init_file.is_file():
        raise PluginPackageError(f"plugin {installed.id}: {CODE_DIR}/__init__.py is missing")
    spec = importlib.util.spec_from_file_location(
        module_name,
        init_file,
        submodule_search_locations=[str(code_dir)],
    )
    if spec is None or spec.loader is None:
        raise PluginError(f"plugin {installed.id}: cannot build import spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)


def import_plugin_class(installed: InstalledPlugin) -> type[BasePlugin]:
    """Import the ``BasePlugin`` subclass named by the manifest's entry point.

    Raises :class:`PluginError` with a message naming the plugin and the entry
    point, because "cannot import name" from a mangled package name tells the
    author nothing.
    """
    module_name = installed.module_name
    entry = installed.manifest.entry_point
    parts = entry.split(".")
    if len(parts) < 2:
        raise PluginError(
            f"plugin {installed.id}: entry_point {entry!r} must be 'module.ClassName'"
        )
    class_name = parts[-1]
    sub_path = ".".join(parts[:-1])
    full_module = f"{module_name}.{sub_path}"

    _ensure_package_importable(installed, module_name)
    try:
        module = importlib.import_module(full_module)
    except ImportError as exc:
        raise PluginError(f"plugin {installed.id}: cannot import {entry!r} ({exc})") from exc
    except BaseException as exc:
        # A plugin that raises at import time must not crash the host; the
        # original traceback is chained so the author still sees the real error.
        raise PluginError(
            f"plugin {installed.id}: cannot import {entry!r} ({type(exc).__name__}: {exc})"
        ) from exc
    obj = getattr(module, class_name, None)
    if obj is None:
        raise PluginError(f"plugin {installed.id}: {entry!r} not found in {full_module}")
    if not (isinstance(obj, type) and issubclass(obj, BasePlugin)):
        raise PluginError(f"plugin {installed.id}: {entry!r} is not a BasePlugin subclass")
    return obj


def unload_plugin_module(plugin_id: str) -> None:
    """Drop a plugin's mangled package from ``sys.modules``.

    Without this, re-installing a plugin in the same process would reuse the
    *old* module objects, and an upgrade would appear to have no effect until
    restart.
    """
    base = mangle_plugin_id(plugin_id)
    prefix = base + "."
    for name in [n for n in sys.modules if n == base or n.startswith(prefix)]:
        del sys.modules[name]
