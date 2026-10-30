"""Installed-plugin registry: install, uninstall, enable/disable, resolve dependencies.

This module owns *state*, not *execution*.  It writes directories under
``CONFIG_DIR/plugins/installed/`` and records which trusted public key
signed each package; loading the code into the interpreter is
``loader.import_plugin_class``'s job, and wiring its hooks is the
manager's.  Keeping them apart means a corrupt plugin can be uninstalled
even when it can no longer be imported.

Trust model, restated because it is easy to get wrong: a package is only
installed if one of the public keys in ``plugin.trusted_keys`` (settings)
signed its canonical manifest.  The manifest lists a sha256 for every file
under ``code/``, so editing any file after signing breaks the signature.
There is no second signature and no "allow unsigned" flag: the absence of
an unsigned escape hatch is the whole point.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from open_navicat.errors import (
    PluginConflictError,
    PluginError,
    PluginPackageError,
    PluginPermissionError,
    PluginVersionError,
)
from open_navicat.plugin import loader
from open_navicat.plugin.loader import InstalledPlugin, installed_root, read_installed
from open_navicat.plugin.manifest import PluginManifest, satisfies
from open_navicat.plugin.package import PACKAGE_SUFFIX, open_package, verify_package

logger = logging.getLogger("opennavicat.plugin.registry")

#: Settings key holding the list of base64 public keys that may sign
#: packages for this install.  Empty by default: nothing installs.
TRUSTED_KEYS_SETTING = "plugin.trusted_keys"

#: Recorded per install so a later audit can say *which* key signed what
#: without re-reading the package.
TRUST_FILENAME = "trust.json"

#: ``xxxxxxxx:xxxx`` shape produced by :func:`public_key_fingerprint`.
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{8}:[0-9a-f]{4}$")


@dataclass(frozen=True)
class InstallResult:
    """What :func:`install_package` did, for the caller to report."""

    plugin_id: str
    version: str
    action: str  # "installed" | "upgraded" | "downgraded" | "reinstalled"
    permissions: tuple[str, ...] = ()
    fingerprint: str = ""


def trusted_public_keys(settings: Any) -> list[str]:
    """The base64 public keys this install accepts, from application settings."""
    raw = settings.get(TRUSTED_KEYS_SETTING, []) if settings is not None else []
    if isinstance(raw, str):
        # A single key written by hand in settings.json must still work.
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise PluginPermissionError(f"{TRUSTED_KEYS_SETTING} must be a list of base64 keys")
    return [str(k).strip() for k in raw if str(k).strip()]


def trust_public_key(settings: Any, public_key_b64: str) -> str:
    """Add a public key to the trust list.  Returns its fingerprint."""
    key = str(public_key_b64).strip()
    if not key:
        raise PluginPermissionError("empty public key")
    from open_navicat.plugin.signing import public_key_fingerprint

    fingerprint = public_key_fingerprint(key)
    keys = trusted_public_keys(settings)
    if key not in keys:
        settings.set(TRUSTED_KEYS_SETTING, keys + [key])
    return fingerprint


def untrust_public_key(settings: Any, fingerprint: str) -> bool:
    """Drop every trusted key with ``fingerprint``.  True if any was removed.

    A fingerprint that is not even shaped like ``xxxxxxxx:xxxx`` raises
    ValueError: silently returning False there would tell the caller "no
    such key", which is wrong -- the input was invalid.
    """
    want = str(fingerprint).strip().lower()
    if not _FINGERPRINT_RE.fullmatch(want):
        raise ValueError(f"not a fingerprint: {fingerprint!r}")
    kept: list[str] = []
    removed = False
    for key in trusted_public_keys(settings):
        try:
            from open_navicat.plugin.signing import public_key_fingerprint

            if public_key_fingerprint(key).lower() == want:
                removed = True
                continue
        except Exception:  # noqa: BLE001 - a malformed key must not block removal
            logger.warning("ignoring malformed trusted key")
            removed = True
            continue
        kept.append(key)
    if removed:
        settings.set(TRUSTED_KEYS_SETTING, kept)
    return removed


def _write_trust_record(plugin_id: str, public_key_b64: str, fingerprint: str) -> None:
    entry = loader.installed_root() / plugin_id
    entry.mkdir(parents=True, exist_ok=True)
    payload = {
        "public_key": public_key_b64,
        "fingerprint": fingerprint,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    (entry / TRUST_FILENAME).write_text(text, encoding="utf-8")


def read_trust_record(plugin_id: str) -> dict[str, str] | None:
    """The key that signed an installed plugin, or None if unknown."""
    path = loader.installed_root() / plugin_id / TRUST_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {str(k): str(v) for k, v in data.items()}


def _host_version() -> str:
    from open_navicat import __version__

    return __version__


def _version_tuple(text: str) -> tuple[int, int, int]:
    from open_navicat.plugin.manifest import SEMVER_RE

    m = SEMVER_RE.match(str(text).strip())
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def check_dependencies(
    manifest: PluginManifest,
    installed: dict[str, InstalledPlugin],
    *,
    include_self: bool = False,
) -> list[str]:
    """Human-readable problems with ``manifest``'s dependencies.

    An empty list means every declared dependency is installed and its
    version satisfies the constraint.  ``include_self`` lets an upgrade of a
    plugin that others depend on be checked against the post-install state.
    """
    problems: list[str] = []
    for dep_id, constraint in sorted(manifest.dependencies.items()):
        if dep_id == manifest.id and not include_self:
            continue
        dep = installed.get(dep_id)
        if dep is None:
            problems.append(f"missing dependency {dep_id} {constraint}")
            continue
        if not satisfies(dep.version, constraint):
            problems.append(f"dependency {dep_id} is {dep.version}, need {constraint}")
    return problems


def _dependents(plugin_id: str, installed: dict[str, InstalledPlugin]) -> list[str]:
    """Ids of installed plugins that declare a dependency on ``plugin_id``."""
    out = []
    for dep_id, entry in sorted(installed.items()):
        if dep_id == plugin_id:
            continue
        if plugin_id in entry.manifest.dependencies:
            out.append(dep_id)
    return out


def install_package(data: bytes, settings: Any) -> InstallResult:
    """Verify and install a ``.onvpkg`` archive.

    Order is deliberate and each failure mode is distinct:

    1. signature against the trusted key list -- an untrusted package is
       refused before anything is written to disk;
    2. host version;
    3. dependency resolution against what is already installed;
    4. reverse-dependency check when this would overwrite an existing
       install (an upgrade must not silently break the plugins that
       depend on the old version).

    The package is extracted only after every check passes, so a rejected
    install never leaves a half-written directory behind.
    """
    keys = trusted_public_keys(settings)
    if not keys:
        raise PluginPermissionError(
            "no trusted plugin keys configured: add a public key with "
            "'plugin key add <key>' before installing"
        )

    pkg = verify_package(data, keys, _host_version())
    manifest = pkg.manifest

    installed = read_installed()
    problems = check_dependencies(manifest, installed, include_self=True)
    if problems:
        raise PluginConflictError(
            f"plugin {manifest.id} {manifest.version}: " + "; ".join(problems)
        )

    previous = installed.get(manifest.id)
    if previous is not None:
        if _version_tuple(manifest.version) < _version_tuple(previous.version):
            raise PluginPackageError(
                f"refusing to downgrade {manifest.id} from {previous.version} "
                f"to {manifest.version}: uninstall it first"
            )
        # Plugins depending on this one must still be satisfied afterwards.
        broken = []
        for dependent in _dependents(manifest.id, installed):
            dep_manifest = installed[dependent].manifest
            constraint = dep_manifest.dependencies.get(manifest.id, "")
            if constraint and not satisfies(manifest.version, constraint):
                broken.append(f"{dependent} needs {manifest.id} {constraint}")
        if broken:
            raise PluginConflictError(
                f"upgrading {manifest.id} to {manifest.version} would break: " + "; ".join(broken),
            )

    from open_navicat.plugin.package import PACKAGE_SUFFIX
    from open_navicat.plugin.signing import public_key_fingerprint

    root = loader.installed_root() / manifest.id
    if root.exists():
        # Unload first: a stale module would otherwise shadow the new code
        # even though the files on disk were replaced.
        loader.unload_plugin_module(manifest.id)
    loader.extract_package(pkg, loader.installed_root().parent)
    loader.write_state(manifest.id, previous.enabled if previous is not None else True)
    signing_key = _signing_key(pkg, keys)
    _write_trust_record(manifest.id, signing_key, public_key_fingerprint(signing_key))

    if previous is None:
        action = "installed"
    elif _version_tuple(manifest.version) > _version_tuple(previous.version):
        action = "upgraded"
    elif _version_tuple(manifest.version) < _version_tuple(previous.version):
        action = "downgraded"
    else:
        action = "reinstalled"

    return InstallResult(
        plugin_id=manifest.id,
        version=manifest.version,
        action=action,
        permissions=manifest.permissions,
        fingerprint=public_key_fingerprint(signing_key),
    )


def _signing_key(pkg: Any, keys: list[str]) -> str:
    """Which trusted key signed ``pkg`` (needed for the trust record)."""
    from open_navicat.plugin.manifest import canonical_manifest_bytes
    from open_navicat.plugin.signing import verify_bytes

    payload = canonical_manifest_bytes(pkg.manifest)
    for key in keys:
        if verify_bytes(payload, pkg.signature, key):
            return key
    return ""


def uninstall_plugin(plugin_id: str) -> bool:
    """Remove an installed plugin.  Returns True when it existed.

    Refuses to remove a plugin others still depend on, because deleting it
    would leave those plugins unloadable with no way to express why.
    """
    installed = read_installed()
    entry = installed.get(plugin_id)
    if entry is None:
        return False
    dependents = _dependents(plugin_id, installed)
    if dependents:
        raise PluginConflictError(f"plugin {plugin_id} is required by: " + ", ".join(dependents))
    return loader.remove_installed(plugin_id)


def set_enabled(plugin_id: str, enabled: bool) -> bool:
    """Enable or disable an installed plugin.  False when not installed."""
    installed = read_installed()
    if plugin_id not in installed:
        return False
    loader.write_state(plugin_id, enabled)
    if not enabled:
        loader.unload_plugin_module(plugin_id)
    return True


def describe_installed(plugin_id: str) -> dict[str, Any]:
    """Everything ``plugin info`` shows for one installed plugin."""
    installed = read_installed()
    entry = installed.get(plugin_id)
    if entry is None:
        raise PluginPackageError(f"plugin {plugin_id} is not installed")
    manifest = entry.manifest
    trust = read_trust_record(plugin_id) or {}
    problems = check_dependencies(manifest, installed)
    return {
        "id": manifest.id,
        "version": manifest.version,
        "name": manifest.label,
        "description": manifest.description,
        "author": manifest.author,
        "homepage": manifest.homepage,
        "enabled": entry.enabled,
        "entry_point": manifest.entry_point,
        "permissions": list(manifest.permissions),
        "dependencies": dict(sorted(manifest.dependencies.items())),
        "min_host_version": manifest.min_host_version,
        "files": len(manifest.files),
        "fingerprint": trust.get("fingerprint", ""),
        "signed_by": trust.get("public_key", ""),
        "problems": problems,
        "path": str(entry.root),
    }


def inspect_package(data: bytes) -> dict[str, Any]:
    """Manifest + permission disclosure for a package not yet installed.

    Deliberately does *not* verify the signature: the user has to be able
    to see what an untrusted package asks for before deciding whether to
    trust its key.
    """
    pkg = open_package(data)
    manifest = pkg.manifest
    return {
        "id": manifest.id,
        "version": manifest.version,
        "name": manifest.label,
        "description": manifest.description,
        "author": manifest.author,
        "homepage": manifest.homepage,
        "permissions": list(manifest.permissions),
        "dependencies": dict(sorted(manifest.dependencies.items())),
        "min_host_version": manifest.min_host_version,
        "files": sorted(manifest.files),
        "signed": bool(pkg.signature),
        "requires_host": manifest.requires_host(_host_version()),
        "host_version": _host_version(),
        "suffix": PACKAGE_SUFFIX,
    }


def installed_summary() -> list[dict[str, Any]]:
    """One row per installed plugin, sorted by id, for ``plugin list``."""
    rows = []
    for plugin_id in sorted(read_installed()):
        info = describe_installed(plugin_id)
        rows.append(
            {
                "id": info["id"],
                "version": info["version"],
                "name": info["name"],
                "enabled": info["enabled"],
                "permissions": ",".join(info["permissions"]) or "-",
                "fingerprint": info["fingerprint"] or "-",
                "problems": "; ".join(info["problems"]) or "",
            }
        )
    return rows


def verify_installed(plugin_id: str) -> list[str]:
    """Re-check an installed plugin against its own recorded digests.

    Catches the case the signature cannot: files edited *after* install
    (a user poking at the extracted directory, or a bad restore).  Returns
    a list of problems; empty means the install still matches its manifest.
    """
    from open_navicat.plugin.signing import sha256_hex

    installed = read_installed()
    entry = installed.get(plugin_id)
    if entry is None:
        return [f"plugin {plugin_id} is not installed"]
    problems: list[str] = []
    for rel, expected in sorted(entry.manifest.files.items()):
        # manifest.files keys are relative to code/, matching pack_plugin_dir.
        path = entry.root / "code" / rel
        if not path.is_file():
            problems.append(f"missing file {rel}")
            continue
        actual = sha256_hex(path.read_bytes())
        if actual != expected:
            problems.append(f"modified file {rel} (manifest says {expected[:12]})")
    return problems


__all__ = [
    "TRUSTED_KEYS_SETTING",
    "TRUST_FILENAME",
    "InstallResult",
    "check_dependencies",
    "describe_installed",
    "inspect_package",
    "install_package",
    "installed_summary",
    "read_trust_record",
    "set_enabled",
    "trust_public_key",
    "trusted_public_keys",
    "uninstall_plugin",
    "untrust_public_key",
    "verify_installed",
]
