"""Plugin manifest: identity, dependencies and declared permissions.

Every installable plugin ships a ``plugin.json`` at the root of its package
(:mod:`open_navicat.plugin.package` unwraps it).  The manifest is the unit of
trust: it decides *which* plugin is being installed, what it needs, and what
it is allowed to ask for.  Code is free to lie in ``plugin.json``'s face, so
the manifest is signed too -- see :mod:`open_navicat.plugin.signing`.

The schema is our own; third-party plugin descriptors were consulted only for
*which fields* an installer must know (id, version, entry point, dependencies).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from open_navicat.errors import PluginManifestError

__all__ = [
    "MANIFEST_NAME",
    "PLUGIN_ID_RE",
    "SEMVER_RE",
    "PluginManifest",
    "parse_manifest",
    "dump_manifest",
    "canonical_manifest_bytes",
    "satisfies",
]

MANIFEST_NAME = "plugin.json"

#: ``reverse-dns`` style id: lowercase dot-separated segments.  Restricting to
#: this alphabet means an id is always a safe directory name on Windows, macOS
#: and Linux, so installs never need a sanitising round trip.
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9]+)+$")

#: ``major.minor.patch``, no pre-release.  A plugin whose version is not semver
#: cannot be compared against a dependency range, so it is rejected up front
#: rather than silently treated as "0.0.0".
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

#: Fields accepted in ``plugin.json``.  Unknown fields are a manifest error:
#: a typo like ``entrypoint`` must fail loudly, not silently disable the
#: entry point.
_KNOWN_FIELDS = frozenset(
    {
        "id",
        "version",
        "name",
        "description",
        "author",
        "homepage",
        "entry_point",
        "entry",
        "dependencies",
        "permissions",
        "min_host_version",
        "requires",
        "files",
    }
)


@dataclass(frozen=True)
class PluginManifest:
    """Parsed ``plugin.json`` -- immutable once installed."""

    id: str
    version: str
    name: str = ""
    description: str = ""
    author: str = ""
    homepage: str = ""
    #: Dotted module path holding the ``BasePlugin`` subclass, imported after
    #: the package is extracted (e.g. ``"my_plugin.plugin"``).
    entry_point: str = ""
    #: ``{plugin_id: version_constraint}``; see :func:`satisfies`.
    dependencies: dict[str, str] = field(default_factory=dict)
    #: Permissions the plugin declares.  Unknown names are a manifest error so
    #: an installer cannot silently drop one and let the plugin escalate later.
    permissions: tuple[str, ...] = ()
    #: Minimum OpenNavicat version, same constraint syntax as dependencies.
    min_host_version: str = ""
    #: ``{relative path: sha256 hex}`` for every file shipped in the package.
    #: The manifest is signed, so a tampered file changes a digest, changes the
    #: manifest, and invalidates the signature -- one chain, no second signature.
    files: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not PLUGIN_ID_RE.match(self.id):
            raise PluginManifestError(f"invalid plugin id {self.id!r}")
        if not SEMVER_RE.match(self.version):
            raise PluginManifestError(
                f"invalid version {self.version!r} (expected major.minor.patch)"
            )
        if not self.entry_point:
            raise PluginManifestError(f"plugin {self.id} has no entry_point")

    # ---- convenience ----

    @property
    def label(self) -> str:
        """Display name, falling back to the id."""
        return self.name or self.id

    def requires_host(self, host_version: str) -> bool:
        """True when ``host_version`` satisfies :attr:`min_host_version`."""
        if not self.min_host_version:
            return True
        return satisfies(host_version, self.min_host_version)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "version": self.version,
            "entry_point": self.entry_point,
        }
        for key, value in (
            ("name", self.name),
            ("description", self.description),
            ("author", self.author),
            ("homepage", self.homepage),
            ("min_host_version", self.min_host_version),
        ):
            if value:
                out[key] = value
        if self.dependencies:
            out["dependencies"] = dict(sorted(self.dependencies.items()))
        if self.permissions:
            out["permissions"] = list(self.permissions)
        if self.files:
            out["files"] = dict(sorted(self.files.items()))
        return out


def parse_manifest(raw: str | bytes | dict) -> PluginManifest:
    """Parse and validate a ``plugin.json`` document.

    Accepts JSON text/bytes, or an already-decoded mapping (which is what
    callers that build a manifest in memory hand over).
    """
    if isinstance(raw, dict):
        data: Any = dict(raw)
    else:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PluginManifestError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PluginManifestError("manifest must be a JSON object")

    unknown = set(data) - _KNOWN_FIELDS
    if unknown:
        raise PluginManifestError(f"unknown manifest field(s): {', '.join(sorted(unknown))}")

    deps_raw = data.get("dependencies") or {}
    if not isinstance(deps_raw, dict):
        raise PluginManifestError("dependencies must be an object")
    dependencies: dict[str, str] = {}
    for dep_id, constraint in deps_raw.items():
        if not isinstance(dep_id, str) or not isinstance(constraint, str):
            raise PluginManifestError("dependencies must be id -> constraint strings")
        if dep_id == data.get("id"):
            raise PluginManifestError(f"plugin {dep_id} depends on itself")
        dependencies[dep_id] = constraint

    perms_raw = data.get("permissions") or ()
    if isinstance(perms_raw, str) or not isinstance(perms_raw, (list, tuple)):
        raise PluginManifestError("permissions must be a list of strings")
    permissions: list[str] = []
    for item in perms_raw:
        if not isinstance(item, str) or not item.strip():
            raise PluginManifestError("permissions must be non-empty strings")
        permissions.append(item.strip())
    if len(set(permissions)) != len(permissions):
        raise PluginManifestError("duplicate permissions in manifest")

    files_raw = data.get("files") or {}
    if not isinstance(files_raw, dict):
        raise PluginManifestError("files must be an object of path -> sha256")
    files: dict[str, str] = {}
    for rel, digest in files_raw.items():
        if not isinstance(rel, str) or not isinstance(digest, str):
            raise PluginManifestError("files must map path -> sha256 string")
        if "\\" in rel or rel.startswith("/") or ".." in rel.split("/"):
            raise PluginManifestError(f"unsafe path in files map: {rel!r}")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise PluginManifestError(f"files[{rel!r}] is not a sha256 hex digest")
        files[rel] = digest.lower()

    return PluginManifest(
        id=data.get("id", ""),
        version=str(data.get("version", "")),
        name=str(data.get("name") or ""),
        description=str(data.get("description") or ""),
        author=str(data.get("author") or ""),
        homepage=str(data.get("homepage") or ""),
        entry_point=str(data.get("entry_point") or data.get("entry") or ""),
        dependencies=dependencies,
        permissions=tuple(permissions),
        min_host_version=str(data.get("min_host_version") or data.get("requires") or ""),
        files=files,
    )


def dump_manifest(manifest: PluginManifest) -> str:
    """Stable JSON text for a manifest (sorted keys, trailing newline)."""
    return json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n"


def canonical_manifest_bytes(manifest: PluginManifest) -> bytes:
    """The exact bytes that get signed and verified.

    Any pretty-printing difference between packager and installer changes the
    signature, so both sides hash *this* form, never a re-serialised copy.
    """
    return json.dumps(
        manifest.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# version ranges
# ---------------------------------------------------------------------------

_CONSTRAINT_RE = re.compile(r"^(>=|<=|==|!=|>|<|~=|~|\^|\*)?\s*(\d+\.\d+\.\d+)$")


def _version_tuple(text: str) -> tuple[int, int, int]:
    match = SEMVER_RE.match(text.strip())
    if not match:
        raise ValueError(f"not a version: {text!r}")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def satisfies(version: str, constraint: str) -> bool:
    """Does ``version`` satisfy ``constraint``?

    Supports the subset a plugin installer needs: ``>=1.2.0``, ``<=2.0.0``,
    ``==1.4.2``, ``!=1.0.0``, ``^1.2.0`` (compatible release: ``<2.0.0``, or
    ``<0.3.0`` for a ``0.x`` base), ``~1.4.2`` (``>=1.4.2,<1.5.0``), ``*``
    (anything) and a bare ``1.2.0`` (exact).  Space-separated terms are ANDed.
    Unsupported syntax raises ``ValueError`` rather than quietly matching
    everything.
    """
    constraint = (constraint or "*").strip()
    if constraint == "*":
        return True
    parts = constraint.split()
    if not parts:
        raise ValueError(f"empty constraint: {constraint!r}")
    for part in parts:
        if not _CONSTRAINT_RE.match(part):
            raise ValueError(f"unsupported constraint {part!r}")
    have = _version_tuple(version)
    for part in parts:
        match = _CONSTRAINT_RE.match(part)
        op, want_text = match.group(1) or "==", match.group(2)
        want = _version_tuple(want_text)
        if op == ">=" and not have >= want:
            return False
        if op == "<=" and not have <= want:
            return False
        if op == ">" and not have > want:
            return False
        if op == "<" and not have < want:
            return False
        if op == "==" and have != want:
            return False
        if op == "!=" and have == want:
            return False
        if op == "~=" and not want <= have < (want[0], want[1] + 1, 0):
            return False
        if op == "~":
            if not want <= have < (want[0], want[1] + 1, 0):
                return False
        if op == "^":
            # npm semantics: ^0.0.z pins the patch too (a 0.0.x release is
            # treated as unstable), ^0.y.z pins the minor, ^x.y.z the major.
            if want[0]:
                upper = (want[0] + 1, 0, 0)
            elif want[1]:
                upper = (0, want[1] + 1, 0)
            else:
                upper = (0, 0, want[2] + 1)
            if not want <= have < upper:
                return False
    return True
