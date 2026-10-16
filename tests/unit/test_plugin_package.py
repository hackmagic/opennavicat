""".onvpkg layout, digest binding and signature enforcement."""

import io
import json
import zipfile

import pytest

from open_navicat.errors import PluginPackageError, PluginSignatureError
from open_navicat.plugin.manifest import PluginManifest
from open_navicat.plugin.package import (
    CODE_DIR,
    MANIFEST_NAME,
    SIGNATURE_NAME,
    open_package,
    pack_plugin_dir,
    verify_package,
)
from open_navicat.plugin.signing import generate_keypair

HOST = "1.0.0"
MUTATED = b"VALUE = 2\n"


def _make_source(tmp_path, plugin_id="com.example.demo", version="0.1.0", **manifest_extra):
    root = tmp_path / "src"
    (root / CODE_DIR).mkdir(parents=True)
    (root / CODE_DIR / "__init__.py").write_text("", encoding="utf-8")
    (root / CODE_DIR / "plugin.py").write_text(
        "from open_navicat.plugin.base import BasePlugin\n\n\nclass P(BasePlugin):\n    pass\n",
        encoding="utf-8",
    )
    (root / CODE_DIR / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n\nHello\n", encoding="utf-8")
    manifest = {
        "id": plugin_id,
        "version": version,
        "entry_point": "plugin.P",
        "min_host_version": ">=0.0.1",
    }
    manifest.update(manifest_extra)
    (root / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _repack(data, mutate):
    """Rebuild a zip, applying ``mutate(name, blob) -> blob | None`` per entry."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        entries = [(n, zf.read(n)) for n in zf.namelist()]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, blob in entries:
            new = mutate(name, blob)
            if new is not None:
                zf.writestr(name, new)
    return out.getvalue()


def _append(data, name, blob):
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as new:
            for n in zf.namelist():
                new.writestr(n, zf.read(n))
            new.writestr(name, blob)
    return out.getvalue()


@pytest.fixture(scope="module")
def keys():
    return generate_keypair()


@pytest.fixture
def package(tmp_path, keys):
    _, priv = keys
    return pack_plugin_dir(str(_make_source(tmp_path)), priv)


class TestPack:
    def test_layout(self, package):
        with zipfile.ZipFile(io.BytesIO(package)) as zf:
            names = set(zf.namelist())
        assert MANIFEST_NAME in names
        assert SIGNATURE_NAME in names
        assert "README.md" in names
        assert CODE_DIR + "/__init__.py" in names
        assert CODE_DIR + "/plugin.py" in names

    def test_manifest_lists_every_code_file(self, package, keys):
        pub, _ = keys
        pkg = verify_package(package, [pub], HOST)
        assert set(pkg.manifest.files) == {"__init__.py", "plugin.py", "helper.py"}

    def test_digest_recomputed_each_build(self, tmp_path, keys):
        # Digests come from disk at pack time; a file added after a first build
        # must still show up (no stale cache in the source manifest).
        _, priv = keys
        root = _make_source(tmp_path)
        pack_plugin_dir(str(root), priv)
        (root / CODE_DIR / "extra.py").write_text("X = 1\n", encoding="utf-8")
        data = pack_plugin_dir(str(root), priv)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            manifest = json.loads(zf.read(MANIFEST_NAME))
        assert "extra.py" in manifest["files"]

    def test_missing_code_dir_rejected(self, tmp_path, keys):
        import shutil

        _, priv = keys
        root = _make_source(tmp_path)
        shutil.rmtree(root / CODE_DIR)
        with pytest.raises(PluginPackageError, match="no code/"):
            pack_plugin_dir(str(root), priv)

    def test_empty_code_dir_rejected(self, tmp_path, keys):
        import shutil

        _, priv = keys
        root = _make_source(tmp_path)
        shutil.rmtree(root / CODE_DIR)
        (root / CODE_DIR).mkdir()
        with pytest.raises(PluginPackageError, match="no files"):
            pack_plugin_dir(str(root), priv)

    def test_no_manifest_rejected(self, tmp_path, keys):
        _, priv = keys
        root = _make_source(tmp_path)
        (root / MANIFEST_NAME).unlink()
        with pytest.raises(PluginPackageError, match="no plugin.json"):
            pack_plugin_dir(str(root), priv)

    def test_pycache_excluded(self, tmp_path, keys):
        _, priv = keys
        root = _make_source(tmp_path)
        cache = root / CODE_DIR / "__pycache__"
        cache.mkdir()
        (cache / "junk.cpython-312.pyc").write_bytes(b"\x00")
        data = pack_plugin_dir(str(root), priv)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert not any("__pycache__" in n for n in zf.namelist())


class TestVerify:
    def test_good_package(self, package, keys):
        pub, _ = keys
        pkg = verify_package(package, [pub], HOST)
        assert pkg.id == "com.example.demo"
        assert pkg.version == "0.1.0"
        assert pkg.readme_text().startswith("# Demo")

    def test_empty_package_rejected(self, keys):
        pub, _ = keys
        with pytest.raises(PluginPackageError, match="empty"):
            verify_package(b"", [pub], HOST)

    def test_not_a_zip_rejected(self, keys):
        pub, _ = keys
        with pytest.raises(PluginPackageError, match="not a valid ZIP"):
            verify_package(b"definitely not a zip file", [pub], HOST)

    def test_unsigned_package_rejected(self, package, keys):
        pub, _ = keys
        stripped = _repack(package, lambda n, b: None if n == SIGNATURE_NAME else b)
        with pytest.raises(PluginSignatureError, match="unsigned"):
            verify_package(stripped, [pub], HOST)

    def test_no_trusted_keys_rejected(self, package, keys):
        with pytest.raises(PluginSignatureError, match="none of the configured"):
            verify_package(package, [], HOST)

    def test_wrong_key_rejected(self, package, keys):
        other_pub, _ = generate_keypair()
        with pytest.raises(PluginSignatureError, match="signature verification failed"):
            verify_package(package, [other_pub], HOST)

    def test_tampered_code_rejected(self, package, keys):
        pub, _ = keys
        tampered = _repack(package, lambda n, b: MUTATED if n == CODE_DIR + "/helper.py" else b)
        with pytest.raises(PluginSignatureError, match="digest mismatch"):
            verify_package(tampered, [pub], HOST)

    def test_tampered_manifest_rejected(self, package, keys):
        pub, _ = keys

        def bump(name, blob):
            if name != MANIFEST_NAME:
                return blob
            data = json.loads(blob)
            data["version"] = "9.9.9"
            return json.dumps(data).encode()

        with pytest.raises(PluginSignatureError, match="signature verification failed"):
            verify_package(_repack(package, bump), [pub], HOST)

    def test_undeclared_extra_file_rejected(self, package, keys):
        pub, _ = keys
        with pytest.raises(PluginPackageError, match="absent from the manifest"):
            verify_package(_append(package, CODE_DIR + "/evil.py", b"import os\n"), [pub], HOST)

    def test_undeclared_top_level_entry_rejected(self, package, keys):
        pub, _ = keys
        with pytest.raises(PluginPackageError, match="unexpected entry"):
            verify_package(_append(package, "payload.sh", b"echo hi\n"), [pub], HOST)

    def test_declared_but_missing_file_rejected(self, package, keys):
        pub, _ = keys
        stripped = _repack(package, lambda n, b: None if n == CODE_DIR + "/helper.py" else b)
        with pytest.raises(PluginPackageError, match="absent from the package"):
            verify_package(stripped, [pub], HOST)

    def test_traversal_entry_rejected(self, package, keys):
        pub, _ = keys
        with pytest.raises(PluginPackageError, match="unexpected entry"):
            verify_package(_append(package, "../escape.txt", b"x"), [pub], HOST)
