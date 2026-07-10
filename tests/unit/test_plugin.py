"""Tests for the plugin system."""

from __future__ import annotations

from open_navicat.plugin.base import BasePlugin
from open_navicat.plugin.manager import PluginManager


class _TestPlugin(BasePlugin):
    @property
    def name(self) -> str:
        return "test_plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_export_formats(self) -> dict[str, callable]:
        return {"test_fmt": lambda rows, title: "test output"}

    def get_mask_rules(self) -> dict[str, callable]:
        return {"custom_key": lambda val: "MASKED"}


class TestBasePlugin:
    def test_default_properties(self) -> None:
        p = _TestPlugin()
        assert p.name == "test_plugin"
        assert p.version == "1.0.0"

    def test_lifecycle_hooks(self) -> None:
        p = _TestPlugin()
        p.on_load()
        p.on_ready()
        p.on_unload()


class TestPluginManager:
    def test_register_plugin(self) -> None:
        mgr = PluginManager()
        p = _TestPlugin()
        mgr._register(p)
        assert "test_plugin" in mgr.plugins

    def test_register_skips_duplicates(self) -> None:
        mgr = PluginManager()
        mgr._register(_TestPlugin())
        assert len(mgr.plugins) == 1
        mgr._register(_TestPlugin())
        assert len(mgr.plugins) == 1

    def test_get_export_formats(self) -> None:
        mgr = PluginManager()
        mgr._register(_TestPlugin())
        fmts = mgr.get_export_formats()
        assert "test_fmt" in fmts
        assert fmts["test_fmt"]([], "") == "test output"

    def test_get_mask_rules(self) -> None:
        mgr = PluginManager()
        mgr._register(_TestPlugin())
        rules = mgr.get_mask_rules()
        assert "custom_key" in rules
        assert rules["custom_key"]("anything") == "MASKED"

    def test_get_notification_backends_empty(self) -> None:
        mgr = PluginManager()
        assert mgr.get_notification_backends() == {}

    def test_unload_all(self) -> None:
        mgr = PluginManager()
        mgr._register(_TestPlugin())
        mgr.unload_all()
        assert len(mgr.plugins) == 0

    def test_discover_and_load_no_crash(self) -> None:
        mgr = PluginManager()
        mgr.discover_and_load()
        assert isinstance(mgr.plugins, dict)


class TestBundledPlugins:
    def test_webhook_notifier(self) -> None:
        from open_navicat.plugins.webhook_notifier import WebhookNotifier
        p = WebhookNotifier()
        assert p.name == "webhook_notifier"
        backends = p.get_notification_backends()
        assert "webhook" in backends
        assert callable(backends["webhook"])

    def test_jsonl_export(self) -> None:
        from open_navicat.plugins.json_export import JSONLExport
        p = JSONLExport()
        assert p.name == "jsonl_export"
        fmts = p.get_export_formats()
        assert "jsonl" in fmts
        result = fmts["jsonl"]([{"id": 1, "name": "test"}], "")
        assert '{"id": 1' in result
        assert '"test"' in result
