"""Tests for the installed-plugin registry (install/uninstall/trust)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from open_navicat.errors import (
    PluginConflictError,
    PluginPackageError,
    PluginPermissionError,
    PluginSignatureError,
)
from open_navicat.plugin import loader, registry
from open_navicat.plugin.loader import InstalledPlugin, import_plugin_class, read_installed
from open_navicat.plugin.manifest import PluginManifest
from open_navicat.plugin.package import MANIFEST_NAME, pack_plugin_dir
from open_navicat.plugin.registry import (
    TRUSTED_KEYS_SETTING,
    check_dependencies,
    describe_installed,
    inspect_package,
    install_package,
    installed_summary,
    read_trust_record,
    set_enabled,
    trust_public_key,
    trusted_public_keys,
    uninstall_plugin,
    untrust_public_key,
    verify_installed,
)
from open_navicat.plugin.signing import generate_keypair, public_key_fingerprint

PLUGIN_CODE = (
    "from open_navicat.plugin.base import BasePlugin\n\n\nclass Demo(BasePlugin):\n    pass\n"
)


class FakeSettings:
    """Just enough AppConfig for the registry's two setting calls."""

    def __init__(self, keys: list[str] | None = None) -> None:
        self._data: dict = {}
        self.set(TRUSTED_KEYS_SETTING, list(keys or []))

    def get(self, key: str, default=None):
        val = self._data.get(key, default)
        return default if val is None else val

    def set(self, key: str, value) -> None:
        self._data[key] = value


@pytest.fixture(autouse=True)
def isolated_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "installed_root", lambda: tmp_path / "installed")
    yield
    for name in [n for n in list(sys.modules) if n.startswith("onvp_")]:
        del sys.modules[name]


def make_package(
    tmp_path,
    plugin_id="com.example.demo",
    code=None,
    version="1.0.0",
    deps=None,
    permissions=None,
):
    root = tmp_path / ("src-" + plugin_id + "-" + version.replace(".", "_"))
    (root / "code").mkdir(parents=True, exist_ok=True)
    (root / "code" / "__init__.py").write_text("", encoding="utf-8")
    (root / "code" / "plugin.py").write_text(
        PLUGIN_CODE if code is None else code, encoding="utf-8"
    )
    manifest = {
        "id": plugin_id,
        "version": version,
        "entry_point": "plugin.Demo",
        "min_host_version": ">=0.0.0",
    }
    if deps:
        manifest["dependencies"] = deps
    if permissions:
        manifest["permissions"] = permissions
    (root / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    pub, priv = generate_keypair()
    return pack_plugin_dir(str(root), priv), pub, priv


def _pack(tmp_path, plugin_id, version, priv, deps=None, permissions=None):
    """Build a package signed by a caller-supplied private key.

    Tests that install several plugins together must share one key, so
    the private key is passed in rather than generated per package.
    """
    root = tmp_path / ("pack-" + plugin_id + "-" + version.replace(".", "_"))
    (root / "code").mkdir(parents=True, exist_ok=True)
    (root / "code" / "__init__.py").write_text("", encoding="utf-8")
    (root / "code" / "plugin.py").write_text(PLUGIN_CODE, encoding="utf-8")
    manifest = {
        "id": plugin_id,
        "version": version,
        "entry_point": "plugin.Demo",
        "min_host_version": ">=0.0.0",
    }
    if deps:
        manifest["dependencies"] = deps
    if permissions:
        manifest["permissions"] = permissions
    (root / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return pack_plugin_dir(str(root), priv)


# ------------------------- trust store -------------------------


def test_trusted_public_keys_defaults_to_empty():
    assert trusted_public_keys(None) == []


def test_trusted_public_keys_reads_settings():
    pub, _priv = generate_keypair()
    assert trusted_public_keys(FakeSettings([pub])) == [pub]


def test_trust_and_untrust_roundtrip():
    pub, _priv = generate_keypair()
    cfg = FakeSettings()
    fingerprint = trust_public_key(cfg, pub)
    assert pub in trusted_public_keys(cfg)
    assert fingerprint == public_key_fingerprint(pub)
    assert untrust_public_key(cfg, fingerprint) is True
    assert trusted_public_keys(cfg) == []
    assert untrust_public_key(cfg, fingerprint) is False


def test_untrust_by_unknown_fingerprint_is_false():
    pub, _priv = generate_keypair()
    cfg = FakeSettings([pub])
    assert untrust_public_key(cfg, "00000000:0000") is False


def test_untrust_rejects_malformed_fingerprint():
    cfg = FakeSettings()
    # A malformed fingerprint must not silently "match nothing".
    with pytest.raises(ValueError):
        untrust_public_key(cfg, "not-a-fingerprint")


def test_trust_rejects_non_ed25519_base64():
    # public_key_fingerprint() rejects short keys before anything is stored.
    with pytest.raises(PluginSignatureError):
        trust_public_key(FakeSettings(), "AAAA")


# ------------------------- install -------------------------


def test_install_happy_path(tmp_path):
    data, pub, _priv = make_package(tmp_path)
    result = install_package(data, FakeSettings([pub]))
    assert result.plugin_id == "com.example.demo"
    assert result.version == "1.0.0"
    assert set(read_installed()) == {"com.example.demo"}


def test_install_writes_trust_record(tmp_path):
    data, pub, _priv = make_package(tmp_path)
    install_package(data, FakeSettings([pub]))
    record = read_trust_record("com.example.demo")
    assert record is not None
    assert record["fingerprint"] == public_key_fingerprint(pub)


def test_install_refuses_untrusted_package(tmp_path):
    data, _pub, _priv = make_package(tmp_path)
    # "no keys configured" is a distinct failure from "wrong key", so it
    # raises PluginPermissionError and nothing is written to disk.
    with pytest.raises(PluginPermissionError):
        install_package(data, FakeSettings())
    assert read_installed() == {}


def test_install_refuses_wrong_key(tmp_path):
    data, _pub, _priv = make_package(tmp_path)
    other, _opriv = generate_keypair()
    with pytest.raises(PluginSignatureError):
        install_package(data, FakeSettings([other]))
    assert read_installed() == {}


def test_install_records_permissions_in_result(tmp_path):
    data, pub, _priv = make_package(tmp_path, permissions=["filesystem.write", "notification.send"])
    result = install_package(data, FakeSettings([pub]))
    assert set(result.permissions) == {"filesystem.write", "notification.send"}


def test_install_refuses_downgrade(tmp_path):
    pub, priv = generate_keypair()
    cfg = FakeSettings([pub])
    install_package(_pack(tmp_path, "com.example.demo", "2.0.0", priv), cfg)
    old = _pack(tmp_path, "com.example.demo", "1.0.0", priv)
    with pytest.raises(PluginPackageError):
        install_package(old, cfg)
    assert read_installed()["com.example.demo"].manifest.version == "2.0.0"


def test_install_upgrade_removes_stale_files(tmp_path):
    # A file present in v1 but not v2 must not survive the upgrade, or it
    # keeps being imported from the stale copy.
    root = tmp_path / "up"
    (root / "code").mkdir(parents=True)
    (root / "code" / "__init__.py").write_text("", encoding="utf-8")
    (root / "code" / "stale.py").write_text("MARKER = 1", encoding="utf-8")
    (root / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "id": "com.example.demo",
                "version": "1.0.0",
                "entry_point": "plugin.Demo",
                "min_host_version": ">=0.0.0",
            }
        ),
        encoding="utf-8",
    )
    pub, priv = generate_keypair()
    install_package(pack_plugin_dir(str(root), priv), FakeSettings([pub]))
    installed_dir = loader.installed_root() / "com.example.demo"
    assert (installed_dir / "code" / "stale.py").exists()
    (root / "code" / "stale.py").unlink()
    (root / "code" / "fresh.py").write_text("MARKER = 2", encoding="utf-8")
    (root / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "id": "com.example.demo",
                "version": "1.1.0",
                "entry_point": "plugin.Demo",
                "min_host_version": ">=0.0.0",
            }
        ),
        encoding="utf-8",
    )
    install_package(pack_plugin_dir(str(root), priv), FakeSettings([pub]))
    assert not (installed_dir / "code" / "stale.py").exists()
    assert (installed_dir / "code" / "fresh.py").exists()
    assert read_installed()["com.example.demo"].manifest.version == "1.1.0"


def test_install_upgrade_keeps_enabled_state(tmp_path):
    pub, priv = generate_keypair()
    cfg = FakeSettings([pub])
    install_package(_pack(tmp_path, "com.example.demo", "1.0.0", priv), cfg)
    assert set_enabled("com.example.demo", False) is True
    install_package(_pack(tmp_path, "com.example.demo", "1.1.0", priv), cfg)
    assert read_installed()["com.example.demo"].enabled is False


def test_install_upgrade_blocked_by_dependent(tmp_path):
    pub, priv = generate_keypair()
    cfg = FakeSettings([pub])
    install_package(_pack(tmp_path, "com.example.lib", "1.0.0", priv), cfg)
    app = _pack(
        tmp_path,
        "com.example.app",
        "1.0.0",
        priv,
        deps={"com.example.lib": "<2.0.0"},
    )
    install_package(app, cfg)
    with pytest.raises(PluginConflictError):
        install_package(_pack(tmp_path, "com.example.lib", "2.0.0", priv), cfg)
    assert read_installed()["com.example.lib"].manifest.version == "1.0.0"


def test_install_missing_dependency_is_refused(tmp_path):
    data, pub, _priv = make_package(tmp_path, deps={"com.example.absent": ">=1.0.0"})
    with pytest.raises(PluginConflictError):
        install_package(data, FakeSettings([pub]))
    assert read_installed() == {}


def test_install_satisfied_dependency_installs(tmp_path):
    pub, priv = generate_keypair()
    cfg = FakeSettings([pub])
    install_package(_pack(tmp_path, "com.example.lib", "1.0.0", priv), cfg)
    app = _pack(tmp_path, "com.example.app", "1.0.0", priv, deps={"com.example.lib": "^1.0.0"})
    install_package(app, cfg)
    assert set(read_installed()) == {"com.example.lib", "com.example.app"}


def test_uninstall_removes_directory_and_modules(tmp_path):
    data, pub, _priv = make_package(tmp_path)
    install_package(data, FakeSettings([pub]))
    import_plugin_class(read_installed()["com.example.demo"])
    assert any(n.startswith("onvp_") for n in sys.modules)
    assert uninstall_plugin("com.example.demo") is True
    assert not (loader.installed_root() / "com.example.demo").exists()
    assert not any(n.startswith("onvp_") for n in sys.modules)
    assert read_trust_record("com.example.demo") is None
    assert uninstall_plugin("com.example.demo") is False


def test_uninstall_refuses_when_dependents_exist(tmp_path):
    pub, priv = generate_keypair()
    cfg = FakeSettings([pub])
    install_package(_pack(tmp_path, "com.example.lib", "1.0.0", priv), cfg)
    app = _pack(tmp_path, "com.example.app", "1.0.0", priv, deps={"com.example.lib": ">=1.0.0"})
    install_package(app, cfg)
    with pytest.raises(PluginConflictError):
        uninstall_plugin("com.example.lib")
    assert (loader.installed_root() / "com.example.lib").exists()


def test_set_enabled_persists_and_rejects_unknown(tmp_path):
    assert set_enabled("com.example.absent", True) is False
    data, pub, _priv = make_package(tmp_path)
    install_package(data, FakeSettings([pub]))
    assert set_enabled("com.example.demo", False) is True
    assert read_installed()["com.example.demo"].enabled is False
    assert set_enabled("com.example.demo", True) is True
    assert read_installed()["com.example.demo"].enabled is True


# ------------------------- query surface -------------------------


def test_installed_summary_reports_every_plugin(tmp_path):
    pub, priv = generate_keypair()
    cfg = FakeSettings([pub])
    install_package(_pack(tmp_path, "com.example.a", "1.0.0", priv), cfg)
    install_package(_pack(tmp_path, "com.example.b", "1.0.0", priv), cfg)
    summary = {row["id"]: row for row in installed_summary()}
    assert set(summary) == {"com.example.a", "com.example.b"}
    assert summary["com.example.a"]["enabled"] is True
    assert summary["com.example.a"]["version"] == "1.0.0"


def test_describe_installed_reports_version_and_permissions(tmp_path):
    data, pub, _priv = make_package(tmp_path, permissions=["ui.menu"])
    install_package(data, FakeSettings([pub]))
    info = describe_installed("com.example.demo")
    assert info is not None
    assert info["id"] == "com.example.demo"
    assert info["version"] == "1.0.0"
    assert info["enabled"] is True
    assert info["permissions"] == ["ui.menu"]
    with pytest.raises(PluginPackageError):
        describe_installed("com.example.absent")


def test_verify_installed_clean(tmp_path):
    data, pub, _priv = make_package(tmp_path)
    install_package(data, FakeSettings([pub]))
    assert verify_installed("com.example.demo") == []


def test_verify_installed_detects_tampering(tmp_path):
    data, pub, _priv = make_package(tmp_path)
    install_package(data, FakeSettings([pub]))
    target = loader.installed_root() / "com.example.demo" / "code" / "plugin.py"
    target.write_text("MARKER = 1", encoding="utf-8")
    problems = verify_installed("com.example.demo")
    assert any("modified file" in p for p in problems)


def test_verify_installed_reports_missing_files(tmp_path):
    data, pub, _priv = make_package(tmp_path)
    install_package(data, FakeSettings([pub]))
    (loader.installed_root() / "com.example.demo" / "code" / "plugin.py").unlink()
    problems = verify_installed("com.example.demo")
    assert any("missing" in p for p in problems)
    assert verify_installed("com.example.absent") == ["plugin com.example.absent is not installed"]


def test_inspect_package_without_trust(tmp_path):
    # inspect must not need a trusted key: the user decides afterwards.
    data, pub, _priv = make_package(tmp_path)
    info = inspect_package(data)
    assert info["id"] == "com.example.demo"
    assert info["signed"] is True
    assert info["requires_host"] is True
    assert info["files"]


def test_inspect_package_does_not_verify_signature(tmp_path):
    # inspect is read-only and takes no key list: it never calls verify.
    data, pub, _priv = make_package(tmp_path)
    with pytest.raises(TypeError):
        inspect_package(data, [pub])
    info = inspect_package(data)
    assert info["signed"] is True


def test_check_dependencies_reports_missing():
    installed = {"com.example.lib": _inst("com.example.lib", "1.2.0")}
    manifest = PluginManifest(
        id="com.example.app",
        version="1.0.0",
        entry_point="plugin.Demo",
        dependencies={"com.example.lib": ">=2.0.0"},
    )
    assert check_dependencies(manifest, installed)
    ok = PluginManifest(
        id="com.example.app",
        version="1.0.0",
        entry_point="plugin.Demo",
        dependencies={"com.example.lib": "^1.2.0"},
    )
    assert check_dependencies(ok, installed) == []


def test_check_dependencies_ignores_wildcard():
    installed = {"com.example.demo": _inst("com.example.demo", "1.0.0")}
    own = PluginManifest(
        id="com.example.demo",
        version="1.0.0",
        entry_point="plugin.Demo",
        dependencies={"com.example.demo": "*"},
    )
    assert check_dependencies(own, installed) == []


def test_installed_summary_empty_when_nothing_installed():
    assert installed_summary() == []


# ------------------------- helpers -------------------------


def _inst(plugin_id, version):
    """Build the minimal duck-typed object check_dependencies consumes."""
    manifest = PluginManifest(id=plugin_id, version=version, entry_point="plugin.Demo")
    return InstalledPlugin(root=Path("/nonexistent") / plugin_id, manifest=manifest, enabled=True)
