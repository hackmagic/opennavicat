"""Plugin package format (``.onvpkg``).

A package is a plain ZIP with a fixed layout::

    plugin.json          the manifest (signed)
    plugin.json.sig      detached Ed25519 signature over the canonical manifest
    code/                the importable package directory
    README.md            optional, shown in the install dialog

ZIP, not a novel container: every language can produce one, users can inspect
one with a text editor, and the signature covers the manifest which in turn
covers a sha256 of every file in ``code/`` -- so tampering with any byte
inside the archive invalidates the signature.

Two rules make verification deterministic even when the author re-zips:
* only the four entries above are considered, in sorted name order;
* the ``files`` map in the manifest is authoritative -- an extra file that is
  not listed is rejected, and a listed file that is absent is rejected.
"""

from __future__ import annotations

import io
import zipfile

from open_navicat.errors import PluginPackageError, PluginSignatureError
from open_navicat.plugin.manifest import (
    MANIFEST_NAME,
    PluginManifest,
    canonical_manifest_bytes,
    parse_manifest,
)
from open_navicat.plugin.signing import (
    sign_bytes,
    verify_bytes,
)

__all__ = [
    "PACKAGE_SUFFIX",
    "SIGNATURE_NAME",
    "CODE_DIR",
    "PACKAGED_FILENAMES",
    "PackagedPlugin",
    "pack_plugin_dir",
    "open_package",
    "verify_package",
]

PACKAGE_SUFFIX = ".onvpkg"
SIGNATURE_NAME = MANIFEST_NAME + ".sig"
CODE_DIR = "code"
README_NAME = "README.md"

#: The only entries a package may contain.  Anything else (``__MACOSX/``,
#: stray ``.DS_Store``, a ``setup.py`` the author left behind) is refused so a
#: package cannot carry a payload outside the declared layout.
PACKAGED_FILENAMES = (MANIFEST_NAME, SIGNATURE_NAME, README_NAME)


class PackagedPlugin:
    """A verified, ready-to-install plugin plus its signed manifest."""

    def __init__(
        self,
        manifest: PluginManifest,
        files: dict[str, bytes],
        signature: str,
        archive: bytes,
    ) -> None:
        self.manifest = manifest
        #: ``{"code/<relpath>": bytes}`` plus an optional ``README.md``.
        self.files = files
        self.signature = signature
        #: The original archive bytes, kept so an install can hash them.
        self.archive = archive

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def version(self) -> str:
        return self.manifest.version

    def readme_text(self) -> str:
        """The package README, or ``""`` when it ships without one."""
        raw = self.files.get(README_NAME)
        if raw is None:
            return ""
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")

    def total_size(self) -> int:
        return sum(len(v) for v in self.files.values())

    def requested_permissions(self) -> tuple[str, ...]:
        return self.manifest.permissions


def _read_zip(data: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return {name: zf.read(name) for name in zf.namelist() if name}
    except zipfile.BadZipFile as exc:
        raise PluginPackageError(f"not a valid ZIP archive: {exc}") from exc


def _check_layout(entries: dict[str, bytes]) -> None:
    """Refuse anything that is not part of the declared four-entry layout."""
    for name in entries:
        parts = name.replace("\\", "/").split("/")
        top = parts[0]
        if top not in PACKAGED_FILENAMES and top != CODE_DIR:
            raise PluginPackageError(
                f"unexpected entry {name!r}: a plugin package may only contain "
                f"{', '.join(PACKAGED_FILENAMES)} and {CODE_DIR}/"
            )
        if ".." in parts:
            raise PluginPackageError(f"unsafe path in package: {name!r}")


def verify_package(
    data: bytes,
    trusted_public_keys: list[str],
    host_version: str,
) -> PackagedPlugin:
    """Verify an archive's layout, manifest, digests, signature and host.

    Order matters and is deliberate: layout, then manifest, then digests, then
    signature, then host version.  A malformed archive produces a *structural*
    error, a tampered file a *signature* error, and an incompatible plugin a
    *version* error, so the install dialog can say which of the three it is
    instead of reporting one generic failure.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise PluginPackageError("package is empty")
    data = bytes(data)
    entries = _read_zip(data)
    _check_layout(entries)

    if MANIFEST_NAME not in entries:
        raise PluginPackageError(f"package is missing {MANIFEST_NAME}")
    manifest = parse_manifest(entries[MANIFEST_NAME])

    if SIGNATURE_NAME not in entries:
        raise PluginSignatureError(
            f"package is unsigned ({SIGNATURE_NAME} missing); unsigned plugins cannot be installed"
        )
    signature = entries[SIGNATURE_NAME].decode("utf-8", errors="replace").strip()
    if not signature:
        raise PluginSignatureError("signature file is empty")

    code_files = {
        name: blob
        for name, blob in entries.items()
        if name.startswith(f"{CODE_DIR}/") and not name.endswith("/")
    }
    declared = {f"{CODE_DIR}/{rel}" for rel in manifest.files}
    present = set(code_files)
    missing = sorted(declared - present)
    extra = sorted(present - declared)
    if missing:
        raise PluginPackageError(
            f"manifest declares {len(missing)} file(s) absent from the package: "
            + ", ".join(missing[:5])
        )
    if extra:
        raise PluginPackageError(
            f"package contains {len(extra)} file(s) absent from the manifest: "
            + ", ".join(extra[:5])
        )

    payload = canonical_manifest_bytes(manifest)
    if not any(verify_bytes(payload, signature, key) for key in trusted_public_keys):
        raise PluginSignatureError(
            "signature verification failed: none of the configured trusted keys signed this package"
        )

    from open_navicat.plugin.signing import sha256_hex

    for rel, expected in sorted(manifest.files.items()):
        actual = sha256_hex(code_files[f"{CODE_DIR}/{rel}"])
        if actual != expected:
            raise PluginSignatureError(
                f"digest mismatch for {rel}: manifest says {expected[:12]}, "
                f"file hashes to {actual[:12]}"
            )

    if not manifest.requires_host(host_version):
        raise PluginPackageError(
            f"plugin {manifest.id} requires host >= {manifest.min_host_version}, "
            f"this is {host_version}"
        )

    kept = {name: blob for name, blob in entries.items() if not name.startswith(f"{CODE_DIR}/")}
    kept.update(code_files)
    return PackagedPlugin(manifest, kept, signature, data)


def open_package(data: bytes) -> PackagedPlugin:
    """Read a package *without* verifying it (for ``plugin inspect``).

    Used to show a manifest and permission list before the user decides to
    trust it, so a bad signature must not prevent inspection.
    """
    data = bytes(data)
    entries = _read_zip(data)
    _check_layout(entries)
    if MANIFEST_NAME not in entries:
        raise PluginPackageError(f"package is missing {MANIFEST_NAME}")
    manifest = parse_manifest(entries[MANIFEST_NAME])
    signature = ""
    if SIGNATURE_NAME in entries:
        signature = entries[SIGNATURE_NAME].decode("utf-8", errors="replace").strip()
    files = {
        name: blob
        for name, blob in entries.items()
        if name.startswith(f"{CODE_DIR}/") or name == README_NAME
    }
    return PackagedPlugin(manifest, files, signature, data)


def pack_plugin_dir(source_dir: str, private_key_b64: str) -> bytes:
    """Build a signed ``.onvpkg`` from a plugin source directory.

    ``source_dir`` must contain ``plugin.json`` and a ``code/`` directory.
    Every file under ``code/`` is hashed into the manifest *before* signing, so
    a file added after the first build is picked up on the next one
    automatically -- the digests cannot drift out of sync with the archive.
    """
    import pathlib

    from open_navicat.plugin.manifest import dump_manifest
    from open_navicat.plugin.signing import sha256_hex

    root = pathlib.Path(source_dir)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise PluginPackageError(f"{source_dir} has no {MANIFEST_NAME}")
    manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"))

    code_dir = root / CODE_DIR
    if not code_dir.is_dir():
        raise PluginPackageError(f"{source_dir} has no {CODE_DIR}/ directory")

    digests: dict[str, str] = {}
    for path in sorted(code_dir.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(code_dir).as_posix()
        digests[rel] = sha256_hex(path.read_bytes())
    if not digests:
        raise PluginPackageError(f"{code_dir} contains no files")

    signed = PluginManifest(
        id=manifest.id,
        version=manifest.version,
        name=manifest.name,
        description=manifest.description,
        author=manifest.author,
        homepage=manifest.homepage,
        entry_point=manifest.entry_point,
        dependencies=manifest.dependencies,
        permissions=manifest.permissions,
        min_host_version=manifest.min_host_version,
        files=digests,
    )

    payload = canonical_manifest_bytes(signed)
    signature = sign_bytes(payload, private_key_b64)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, dump_manifest(signed))
        zf.writestr(SIGNATURE_NAME, signature)
        readme = root / README_NAME
        if readme.is_file():
            zf.writestr(README_NAME, readme.read_bytes())
        for rel in sorted(digests):
            zf.writestr(f"{CODE_DIR}/{rel}", (code_dir / rel).read_bytes())
    return buf.getvalue()
