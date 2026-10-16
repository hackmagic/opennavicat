"""Tests for the plugin manager's permission gating and installed-plugin loading."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from open_navicat.plugin import loader
from open_navicat.plugin.manager import PluginManager
from open_navicat.plugin.registry import install_package, set_enabled

_NL = chr(10)


class _Settings:
    def __init__(self, keys: list[str] | None = None) -> None:
        self._data: dict[str, Any] = {"plugin.trusted_keys": keys or []}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value


PLUGIN_SRC = _NL.join(
    [
        "from open_navicat.plugin.base import BasePlugin",
        "",
        "",
        "class Probe(BasePlugin):",
        "    name = 'probe'",
        "",
        "    def get_export_formats(self):",
        "        return {'probe_fmt': self.render}",
        "",
        "    def render(self, *a, **k):",
        "        return ''",
        "",
    ]
)


def _pack(tmp_path: Path, plugin_id: str, permissions: list[str]) -> tuple[bytes, str]:
    from open_navicat.plugin.package import pack_plugin_dir
    from open_navicat.plugin.signing import generate_keypair

    pub, priv = generate_keypair()
    root = tmp_path / plugin_id
    code = root / "code"
    code.mkdir(parents=True)
    (code / "__init__.py").write_text("", encoding="utf-8")
    (code / "plugin.py").write_text(PLUGIN_SRC, encoding="utf-8")
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0.0",
                "name": plugin_id,
                "entry_point": "plugin.Probe",
                "permissions": permissions,
                "min_host_version": ">=0.0.1",
            }
        ),
        encoding="utf-8",
    )
    return pack_plugin_dir(str(root), priv), pub


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "installed_root", lambda: tmp_path / "installed")
    yield tmp_path
    for name in [n for n in sys.modules if n.startswith("onvp_")]:
        del sys.modules[name]


def test_installed_plugin_hook_requires_permission(isolated):
    data, pub = _pack(isolated, "com.example.noperm", [])
    install_package(data, _Settings([pub]))
    mgr = PluginManager()
    mgr.discover_and_load()
    assert mgr.granted_permissions("probe") == []
    assert "probe_fmt" not in mgr.get_export_formats()
    assert any("filesystem.write" in e for e in mgr.load_errors)
    mgr.unload_all()


def test_installed_plugin_hook_wired_with_permission(isolated):
    data, pub = _pack(isolated, "com.example.withperm", ["filesystem.write"])
    install_package(data, _Settings([pub]))
    mgr = PluginManager()
    mgr.discover_and_load()
    assert mgr.granted_permissions("probe") == ["filesystem.write"]
    assert "probe_fmt" in mgr.get_export_formats()
    # The probe only overrides get_export_formats, so the notification
    # hook it inherits is still gated and reported.
    assert mgr.load_errors == [
        "probe: plugin probe may not register get_notification_backends:"
        " missing permission(s) notification.send"
    ]
    assert "probe" in mgr.plugins
    mgr.unload_all()


def test_disabled_plugin_not_loaded(isolated):
    data, pub = _pack(isolated, "com.example.off", ["filesystem.write"])
    install_package(data, _Settings([pub]))
    set_enabled("com.example.off", False)
    mgr = PluginManager()
    mgr.discover_and_load()
    assert "plugin" not in mgr.plugins
    assert "probe" not in mgr.plugins
    mgr.unload_all()


def test_enabled_again_after_disable(isolated):
    data, pub = _pack(isolated, "com.example.toggle", ["filesystem.write"])
    install_package(data, _Settings([pub]))
    set_enabled("com.example.toggle", False)
    set_enabled("com.example.toggle", True)
    mgr = PluginManager()
    mgr.discover_and_load()
    assert "probe" in mgr.plugins
    mgr.unload_all()


def test_unload_all_clears_hooks(isolated):
    data, pub = _pack(isolated, "com.example.clear", ["filesystem.write"])
    install_package(data, _Settings([pub]))
    mgr = PluginManager()
    mgr.discover_and_load()
    mgr.unload_all()
    assert mgr.plugins == {}
    assert mgr.get_export_formats() == {}


def test_duplicate_plugin_class_is_not_registered_twice(isolated):
    # Two packages whose plugin class reports the same name='probe'.  The
    # manager must register exactly one of them.
    for pid in ("com.example.one", "com.example.two"):
        data, pub = _pack(isolated, pid, ["filesystem.write"])
        install_package(data, _Settings([pub]))
    mgr = PluginManager()
    mgr.discover_and_load()
    assert [k for k in mgr.plugins if k.startswith("probe")] == ["probe"]
    mgr.unload_all()
