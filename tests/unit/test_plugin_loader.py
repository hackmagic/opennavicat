import importlib
import json
import sys
from pathlib import Path

import pytest

from open_navicat.errors import PluginError, PluginPackageError
from open_navicat.plugin import loader
from open_navicat.plugin.base import BasePlugin
from open_navicat.plugin.loader import (
    InstalledPlugin,
    extract_package,
    import_plugin_class,
    installed_root,
    mangle_plugin_id,
    read_installed,
    remove_installed,
    unload_plugin_module,
    write_state,
)
from open_navicat.plugin.manifest import PluginManifest, parse_manifest
from open_navicat.plugin.package import CODE_DIR, MANIFEST_NAME, SIGNATURE_NAME
from open_navicat.plugin.signing import generate_keypair

GOOD_CODE = (
    "from open_navicat.plugin.base import BasePlugin\n\n\nclass Demo(BasePlugin):\n    pass\n"
)


@pytest.fixture(autouse=True)
def isolated_plugins_root(tmp_path, monkeypatch):
    # The loader reads CONFIG_DIR lazily inside _plugins_root(), so patching
    # the module attribute is enough.
    from open_navicat.plugin import loader

    monkeypatch.setattr(loader, "installed_root", lambda: tmp_path / "installed")
    yield
    for name in [n for n in sys.modules if n.startswith("onvp_")]:
        del sys.modules[name]


def _manifest(plugin_id="com.example.demo", version="1.0.0", entry_point="plugin.Demo"):
    return parse_manifest(
        {
            "id": plugin_id,
            "version": version,
            "entry_point": entry_point,
            "min_host_version": ">=0.0.1",
        }
    )


def _build_package(tmp_path, plugin_id="com.example.demo", code=GOOD_CODE):
    root = tmp_path / "src"
    (root / CODE_DIR).mkdir(parents=True, exist_ok=True)
    (root / CODE_DIR / "__init__.py").write_text("", encoding="utf-8")
    (root / CODE_DIR / "plugin.py").write_text(code, encoding="utf-8")
    (root / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0.0",
                "entry_point": "plugin.Demo",
                "min_host_version": ">=0.0.1",
            }
        ),
        encoding="utf-8",
    )
    pub, priv = generate_keypair()
    from open_navicat.plugin.package import pack_plugin_dir

    return pack_plugin_dir(str(root), priv), pub


def _install(tmp_path, monkeypatch, plugin_id="com.example.demo", code=GOOD_CODE):
    from open_navicat.plugin.package import verify_package

    pub, _ = generate_keypair()
    data, pub = _build_package(tmp_path, plugin_id, code)
    pkg = verify_package(data, [pub], "1.0.0")
    dest = extract_package(pkg, tmp_path)
    return dest, pkg


class TestMangle:
    def test_basic(self):
        assert mangle_plugin_id("com.example.demo") == "onvp_com_example_demo"

    def test_hyphens_and_slashes(self):
        assert mangle_plugin_id("io.github/t8y2-my-plugin") == "onvp_io_github_t8y2_my_plugin"

    def test_uppercase_folded(self):
        assert mangle_plugin_id("Com.Example.Demo") == "onvp_com_example_demo"

    def test_leading_digit_prefixed(self):
        assert mangle_plugin_id("9lives") == "onvp_p9lives"

    def test_all_separators_collapses_to_prefixed_empty(self):
        assert mangle_plugin_id("///") == "onvp_p"

    def test_deterministic(self):
        assert mangle_plugin_id("a.b.c") == mangle_plugin_id("a.b.c")


class TestExtract:
    def test_creates_layout(self, tmp_path, monkeypatch):
        dest, pkg = _install(tmp_path, monkeypatch)
        assert (dest / MANIFEST_NAME).is_file()
        assert (dest / SIGNATURE_NAME).is_file()
        assert (dest / CODE_DIR / "plugin.py").is_file()
        assert (dest / CODE_DIR / "__init__.py").is_file()

    def test_manifest_round_trips(self, tmp_path, monkeypatch):
        dest, pkg = _install(tmp_path, monkeypatch)
        again = parse_manifest((dest / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert again == pkg.manifest

    def test_signature_written_with_trailing_newline(self, tmp_path, monkeypatch):
        dest, pkg = _install(tmp_path, monkeypatch)
        raw = (dest / SIGNATURE_NAME).read_text(encoding="utf-8")
        assert raw == pkg.signature

    def test_upgrade_removes_stale_files(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch)
        stale = dest / CODE_DIR / "removed_in_v2.py"
        stale.write_text("X = 1\n", encoding="utf-8")
        dest2, _ = _install(tmp_path, monkeypatch)
        assert dest2 == dest
        assert not stale.exists()

    def test_readme_copied_to_top_level(self, tmp_path, monkeypatch):
        from open_navicat.plugin.package import pack_plugin_dir, verify_package

        root = tmp_path / "src"
        (root / CODE_DIR).mkdir(parents=True)
        (root / CODE_DIR / "__init__.py").write_text("", encoding="utf-8")
        (root / CODE_DIR / "plugin.py").write_text(GOOD_CODE, encoding="utf-8")
        (root / "README.md").write_text("# hi\n", encoding="utf-8")
        (root / MANIFEST_NAME).write_text(
            json.dumps(
                {"id": "com.example.demo", "version": "1.0.0", "entry_point": "plugin.Demo"}
            ),
            encoding="utf-8",
        )
        pub, priv = generate_keypair()
        data = pack_plugin_dir(str(root), priv)
        pkg = verify_package(data, [pub], "1.0.0")
        dest = extract_package(pkg, tmp_path)
        assert (dest / "README.md").read_text(encoding="utf-8") == "# hi\n"


class TestReadInstalled:
    def test_empty_when_no_dir(self, tmp_path, monkeypatch):
        assert read_installed() == {}

    def test_finds_installed_plugin(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch)
        found = read_installed()
        assert set(found) == {"com.example.demo"}
        assert found["com.example.demo"].root == dest
        assert found["com.example.demo"].version == "1.0.0"

    def test_enabled_by_default(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        assert read_installed()["com.example.demo"].enabled is True

    def test_disabled_flag_respected(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        write_state("com.example.demo", False)
        assert read_installed()["com.example.demo"].enabled is False

    def test_corrupt_state_falls_back_to_enabled(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch)
        (dest / "state.json").write_text("{not json", encoding="utf-8")
        assert read_installed()["com.example.demo"].enabled is True

    def test_missing_manifest_skipped(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch)
        (dest / MANIFEST_NAME).unlink()
        assert read_installed() == {}

    def test_invalid_manifest_skipped(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch)
        (dest / MANIFEST_NAME).write_text('{"id": "bad id!"}', encoding="utf-8")
        assert read_installed() == {}

    def test_non_directory_entries_ignored(self, tmp_path, monkeypatch):
        installed_root().parent.mkdir(parents=True, exist_ok=True)
        installed_root().mkdir(parents=True, exist_ok=True)
        (installed_root() / "stray.txt").write_text("x", encoding="utf-8")
        assert read_installed() == {}

    def test_module_name_matches_mangle(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        entry = read_installed()["com.example.demo"]
        assert entry.module_name == "onvp_com_example_demo"


class TestWriteState:
    def test_creates_dir_and_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(loader, "installed_root", lambda: tmp_path / "installed")
        write_state("com.example.new", True)
        state = tmp_path / "installed" / "com.example.new" / "state.json"
        assert json.loads(state.read_text(encoding="utf-8")) == {"enabled": True}

    def test_round_trip_false(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        write_state("com.example.demo", False)
        assert read_installed()["com.example.demo"].enabled is False


class TestRemove:
    def test_removes_directory(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch)
        assert remove_installed("com.example.demo") is True
        assert not dest.exists()

    def test_returns_false_when_absent(self, monkeypatch, tmp_path):
        assert remove_installed("com.example.nope") is False

    def test_unloads_module_too(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        import_plugin_class(read_installed()["com.example.demo"])
        assert "onvp_com_example_demo" in sys.modules
        remove_installed("com.example.demo")
        assert "onvp_com_example_demo" not in sys.modules


PLUGIN_SRC = "from open_navicat.plugin.base import BasePlugin\nfrom .helpers import ANSWER\n\n\nclass D(BasePlugin):\n    answer = ANSWER\n"
HELPERS_SRC = "ANSWER = 42\n"


class TestImport:
    def test_imports_entry_point_class(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        cls = import_plugin_class(read_installed()["com.example.demo"])
        assert isinstance(cls, type)
        assert issubclass(cls, BasePlugin)

    def test_module_registered(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        import_plugin_class(read_installed()["com.example.demo"])
        assert "onvp_com_example_demo" in sys.modules
        assert "onvp_com_example_demo.plugin" in sys.modules

    def test_submodule_relative_import(self, tmp_path, monkeypatch):
        from open_navicat.plugin.package import pack_plugin_dir, verify_package

        monkeypatch.setattr(loader, "installed_root", lambda: tmp_path / "installed")
        root = tmp_path / "src"
        (root / CODE_DIR).mkdir(parents=True)
        (root / CODE_DIR / "__init__.py").write_text("", encoding="utf-8")
        (root / CODE_DIR / "plugin.py").write_text(PLUGIN_SRC, encoding="utf-8")
        (root / CODE_DIR / "helpers.py").write_text(HELPERS_SRC, encoding="utf-8")
        (root / MANIFEST_NAME).write_text(
            json.dumps({"id": "com.example.demo", "version": "1.0.0", "entry_point": "plugin.D"}),
            encoding="utf-8",
        )
        pub, priv = generate_keypair()
        data = pack_plugin_dir(str(root), priv)
        pkg = verify_package(data, [pub], "1.0.0")
        extract_package(pkg, tmp_path)
        cls = import_plugin_class(read_installed()["com.example.demo"])
        assert cls.answer == 42

    def test_missing_symbol_named_in_error(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch, code="X = 1\n")
        with pytest.raises(PluginError, match="not found"):
            import_plugin_class(read_installed()["com.example.demo"])

    def test_not_a_plugin_class(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch, code="class Demo:\n    pass\n")

    def test_broken_entry_point_format(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch)
        m = _manifest(entry_point="NoModule")
        (dest / MANIFEST_NAME).write_text(json.dumps(m.to_dict()), encoding="utf-8")
        with pytest.raises(PluginError, match="module.ClassName"):
            import_plugin_class(read_installed()["com.example.demo"])

    def test_import_error_wrapped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(loader, "installed_root", lambda: tmp_path / "installed")
        _install(tmp_path, monkeypatch, code="raise RuntimeError('boom')\n")
        with pytest.raises(PluginError, match="cannot import"):
            import_plugin_class(read_installed()["com.example.demo"])

    def test_missing_init_rejected(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch)
        (dest / CODE_DIR / "__init__.py").unlink()
        unload_plugin_module("com.example.demo")
        with pytest.raises(PluginPackageError, match="__init__.py is missing"):
            import_plugin_class(read_installed()["com.example.demo"])


class TestUnload:
    def test_removes_package_and_submodules(self, tmp_path, monkeypatch):
        _install(tmp_path, monkeypatch)
        import_plugin_class(read_installed()["com.example.demo"])
        unload_plugin_module("com.example.demo")
        assert "onvp_com_example_demo" not in sys.modules
        assert "onvp_com_example_demo.plugin" not in sys.modules

    def test_idempotent(self):
        unload_plugin_module("com.example.demo")
        unload_plugin_module("com.example.demo")

    def test_unknown_id_is_safe(self):
        unload_plugin_module("com.example.never-installed")

    def test_reload_picks_up_new_code(self, tmp_path, monkeypatch):
        dest, _ = _install(tmp_path, monkeypatch, code="class Demo:\n    pass\n")
        unload_plugin_module("com.example.demo")
        (dest / CODE_DIR / "plugin.py").write_text(GOOD_CODE, encoding="utf-8")
        cls = import_plugin_class(read_installed()["com.example.demo"])
        assert issubclass(cls, BasePlugin)
