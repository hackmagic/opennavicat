"""Manifest parsing, validation and version-range semantics.

The manifest is the unit of trust: if a malformed or ambiguous manifest can
be accepted, every check downstream of it (signature, digests, permissions)
is checking a lie.  So these tests assert rejection, not just acceptance.
"""

import pytest

from open_navicat.errors import PluginManifestError
from open_navicat.plugin.manifest import (
    PLUGIN_ID_RE,
    SEMVER_RE,
    PluginManifest,
    canonical_manifest_bytes,
    dump_manifest,
    parse_manifest,
    satisfies,
)


def _manifest(**over):
    base = {
        "id": "com.example.demo",
        "version": "1.2.3",
        "entry_point": "plugin.DemoPlugin",
    }
    base.update(over)
    return base


class TestPluginId:
    @pytest.mark.parametrize(
        "plugin_id,ok",
        [
            ("com.example.demo", True),
            ("a.b", True),
            ("com.example.d3m0", True),
            ("x.y-z", False),
            ("COM.Example", False),
            ("com..demo", False),
            (".com.demo", False),
            ("com.example.", False),
            ("com", False),
            ("com.example.demo.extra", True),
        ],
    )
    def test_id_shape(self, plugin_id, ok):
        assert bool(PLUGIN_ID_RE.match(plugin_id)) is ok

    def test_id_must_be_a_safe_directory_name(self):
        # An id that could escape installed/<id>/ would let a plugin write
        # outside its own directory.
        for evil in ["../evil", "com/../../etc", r"com\evil"]:
            assert not PLUGIN_ID_RE.match(evil)


class TestVersion:
    @pytest.mark.parametrize(
        "version,ok",
        [
            ("1.2.3", True),
            ("0.0.0", True),
            ("10.20.30", True),
            ("1.2", False),
            ("1.2.3.4", False),
            ("v1.2.3", False),
            ("1.2.3-beta", False),
            ("01.2.3", False),
        ],
    )
    def test_semver_shape(self, version, ok):
        assert bool(SEMVER_RE.match(version)) is ok

    def test_leading_zero_rejected(self):
        # "01.2.3" parses in int() but sorts unpredictably against "1.2.3".
        with pytest.raises(PluginManifestError):
            PluginManifest(id="a.b", version="01.2.3", entry_point="m.C")


class TestParse:
    def test_minimal_manifest(self):
        m = parse_manifest(_manifest())
        assert m.id == "com.example.demo"
        assert m.version == "1.2.3"
        assert m.entry_point == "plugin.DemoPlugin"
        assert m.dependencies == {}
        assert m.permissions == ()
        assert m.files == {}

    def test_entry_alias(self):
        m = parse_manifest(_manifest(entry="plugin.DemoPlugin"))
        assert m.entry_point == "plugin.DemoPlugin"

    def test_requires_alias_for_min_host_version(self):
        m = parse_manifest(_manifest(requires="1.0.0"))
        assert m.min_host_version == "1.0.0"

    def test_unknown_field_rejected(self):
        with pytest.raises(PluginManifestError, match="unknown manifest field"):
            parse_manifest(_manifest(entrypoint="plugin.DemoPlugin"))

    def test_missing_entry_point_rejected(self):
        with pytest.raises(PluginManifestError, match="no entry_point"):
            parse_manifest({"id": "a.b", "version": "1.0.0"})

    def test_bad_json_rejected(self):
        with pytest.raises(PluginManifestError, match="not valid JSON"):
            parse_manifest("{not json")

    def test_non_object_rejected(self):
        with pytest.raises(PluginManifestError, match="must be a JSON object"):
            parse_manifest("[1, 2, 3]")

    def test_self_dependency_rejected(self):
        with pytest.raises(PluginManifestError, match="depends on itself"):
            parse_manifest(_manifest(dependencies={"com.example.demo": ">=1.0.0"}))

    def test_dependencies_must_be_strings(self):
        with pytest.raises(PluginManifestError, match="id -> constraint"):
            parse_manifest(_manifest(dependencies={"com.x": 5}))

    def test_permissions_must_be_a_list(self):
        with pytest.raises(PluginManifestError, match="must be a list"):
            parse_manifest(_manifest(permissions="network.http"))

    def test_permission_must_be_non_empty(self):
        with pytest.raises(PluginManifestError, match="non-empty"):
            parse_manifest(_manifest(permissions=["network.http", "  "]))

    def test_duplicate_permissions_rejected(self):
        with pytest.raises(PluginManifestError, match="duplicate"):
            parse_manifest(_manifest(permissions=["network.http", "network.http"]))

    def test_files_map_must_be_digests(self):
        with pytest.raises(PluginManifestError, match="sha256"):
            parse_manifest(_manifest(files={"code/a.py": "deadbeef"}))

    def test_files_map_rejects_absolute_and_traversal(self):
        for bad in ["/etc/passwd", "../escape.py", "code/../../x"]:
            with pytest.raises(PluginManifestError, match="unsafe path"):
                parse_manifest(_manifest(files={bad: "a" * 64}))

    def test_permissions_normalized_to_tuple(self):
        m = parse_manifest(_manifest(permissions=["network.http", "filesystem.write"]))
        assert m.permissions == ("network.http", "filesystem.write")


class TestCanonical:
    def test_canonical_is_order_independent(self):
        # Two manifests that differ only in key order must produce identical
        # signed bytes, otherwise a signature would depend on dict ordering.
        a = parse_manifest(_manifest(name="Demo", author="A"))
        b = parse_manifest(_manifest(author="A", name="Demo"))
        assert canonical_manifest_bytes(a) == canonical_manifest_bytes(b)

    def test_dump_is_stable(self):
        text = dump_manifest(parse_manifest(_manifest(name="Demo")))
        assert text == dump_manifest(parse_manifest(_manifest(name="Demo")))
        assert text.endswith("\n")

    def test_to_dict_omits_empty_optionals(self):
        d = parse_manifest(_manifest()).to_dict()
        assert "description" not in d
        assert "dependencies" not in d
        assert "permissions" not in d
        assert "files" not in d

    def test_roundtrip(self):
        m = parse_manifest(
            _manifest(name="Demo", permissions=["network.http"], files={"a.py": "b" * 64})
        )
        assert parse_manifest(dump_manifest(m)) == m


class TestSatisfies:
    @pytest.mark.parametrize(
        "version,constraint,expected",
        [
            ("1.2.3", ">=1.0.0", True),
            ("1.2.3", ">=1.2.3", True),
            ("1.2.2", ">=1.2.3", False),
            ("1.0.0", "<=2.0.0", True),
            ("2.0.1", "<=2.0.0", False),
            ("1.5.0", ">1.4.0", True),
            ("1.4.0", ">1.4.0", False),
            ("0.9.0", "<1.0.0", True),
            ("1.0.0", "<1.0.0", False),
            ("1.0.0", "==1.0.0", True),
            ("1.0.1", "==1.0.0", False),
            ("1.0.0", "1.0.0", True),
            ("1.0.1", "1.0.0", False),
            ("1.0.0", "!=1.0.0", False),
            ("1.0.1", "!=1.0.0", True),
            ("1.2.9", "^1.2.0", True),
            ("1.9.0", "^1.2.0", True),
            ("2.0.0", "^1.2.0", False),
            ("0.2.9", "^0.2.0", True),
            ("0.3.0", "^0.2.0", False),
            ("0.0.1", "^0.0.0", False),
            ("1.4.2", "~1.4.2", True),
            ("1.4.9", "~1.4.2", True),
            ("1.5.0", "~1.4.2", False),
            ("1.4.1", "~1.4.2", False),
            ("1.4.9", "~=1.4.2", True),
            ("1.5.0", "~=1.4.2", False),
            ("0.0.1", "*", True),
            ("99.99.99", "*", True),
            ("1.0.0", "", True),
            ("1.0.0", None, True),
            ("1.5.0", ">=1.0.0 <2.0.0", True),
            ("2.5.0", ">=1.0.0 <2.0.0", False),
            ("0.5.0", ">=1.0.0 <2.0.0", False),
        ],
    )
    def test_matrix(self, version, constraint, expected):
        assert satisfies(version, constraint) is expected

    @pytest.mark.parametrize(
        "constraint", ["~>1.0", "1.0", "latest", ">=1.0.0 || <0.5", "^1", ">= 1.0.0"]
    )
    def test_unsupported_syntax_raises(self, constraint):
        # A silently-matching-everything constraint is how a plugin pins
        # nothing and still installs; refusing is the safe default.
        with pytest.raises(ValueError):
            satisfies("1.0.0", constraint)

    @pytest.mark.parametrize("version", ["1.0", "v1.0.0", "1.0.0-beta"])
    def test_bad_version_raises(self, version):
        with pytest.raises(ValueError):
            satisfies(version, ">=1.0.0")

    def test_whitespace_tolerated(self):
        assert satisfies("1.2.3", "  >=1.0.0  ") is True


class TestRequiresHost:
    def test_no_minimum_always_ok(self):
        m = parse_manifest(_manifest())
        assert m.requires_host("0.0.1") is True

    def test_minimum_enforced(self):
        m = parse_manifest(_manifest(min_host_version="^1.2.0"))
        assert m.requires_host("1.2.5") is True
        assert m.requires_host("1.1.9") is False
        assert m.requires_host("2.0.0") is False
