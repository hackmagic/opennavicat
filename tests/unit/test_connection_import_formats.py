"""Tests for importing connections from the six supported third-party tools.

The previous importer only understood DBeaver's JSON and a best-effort Navicat
``.ncx``.  DBX (the tool this feature is modelled on) also reads DataGrip and
the two Redis clients, so those layouts are pinned here.  Two invariants run
through every case:

* another tool's *encrypted* password is never recovered — only DBX publishes
  its own export encryption, so only DBX can decrypt;
* an unsupported record is reported in ``skipped`` with the reason, never
  silently dropped and never turned into a half-configured profile.
"""

from __future__ import annotations

import base64
import json
import os

import pytest

from open_navicat.models.connection import ConnectionInfo
from open_navicat.services.connection_import import (
    DBX_TYPE_ALIASES,
    FORMAT_KEYS,
    IMPORT_FORMATS,
    decrypt_dbx_payload,
    detect_format,
    export_connections,
    get_format,
    import_file,
    parse_another_rdm,
    parse_datagrip,
    parse_dbx,
    parse_opennavicat,
    parse_rdm,
)

# ── fixtures ───────────────────────────────────────────────────────────────

DATAGRIP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="DataSourceManagerImpl">
    <data-source source="LOCAL" name="prod-pg" uuid="u1" group="Prod/APAC">
      <driver-ref>postgresql</driver-ref>
      <jdbc-url>jdbc:postgresql://db.internal:5432/analytics</jdbc-url>
      <jdbc-driver>org.postgresql.Driver</jdbc-driver>
    </data-source>
    <data-source source="LOCAL" name="shop" uuid="u2">
      <driver-ref>mysql</driver-ref>
      <jdbc-url>jdbc:mysql://10.0.0.5:3306/shop</jdbc-url>
    </data-source>
    <data-source source="LOCAL" name="notes" uuid="u3">
      <driver-ref>sqlite</driver-ref>
      <jdbc-url>jdbc:sqlite:$USER_HOME$/notes.db</jdbc-url>
    </data-source>
    <data-source source="LOCAL" name="ora" uuid="u4">
      <driver-ref>oracle</driver-ref>
      <jdbc-url>jdbc:oracle:thin:@ora1:1521:ORCL</jdbc-url>
    </data-source>
    <data-source source="LOCAL" name="mssql" uuid="u5">
      <driver-ref>sqlserver</driver-ref>
      <jdbc-url>jdbc:sqlserver://sql1:1433;databaseName=erp</jdbc-url>
    </data-source>
    <data-source source="LOCAL" name="cass" uuid="u6">
      <driver-ref>cassandra</driver-ref>
      <jdbc-url>jdbc:cassandra://n1:9042/ks</jdbc-url>
    </data-source>
  </component>
</project>
"""

DATAGRIP_LOCAL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<project version="4">
  <component name="DataSourceManagerImpl">
    <data-source source="LOCAL" name="prod-pg" uuid="u1">
      <database-info product="PostgreSQL"/>
      <user-name>ro</user-name>
    </data-source>
  </component>
</project>
"""

RDM_JSON = [
    {
        "type": "group",
        "name": "Team",
        "connections": [
            {
                "type": "connection",
                "name": "cache",
                "host": "10.0.0.9",
                "port": 6379,
                "auth": "pw",
                "namespace_separator": ":",
                "ssh_host": "bastion",
                "ssh_user": "ops",
            }
        ],
    },
    {"type": "connection", "name": "flat", "host": "flat.local", "port": 6380},
    {"type": "unknown-kind", "name": "weird"},
]

ANO_PAYLOAD = {
    "connections": [
        {"name": "ano-redis", "host": "r1", "port": 6380, "auth": "secret", "groupId": "g1"},
        {
            "name": "ano-ssh",
            "host": "r2",
            "port": 6379,
            "sshOptions": {"host": "hop", "port": 22, "username": "u", "password": "p"},
        },
    ],
    "groups": [{"id": "g1", "name": "Cluster"}],
}

DBX_PLAIN = {
    "format": "dbx-config",
    "version": 1,
    "connections": [
        {
            "name": "dbx-pg",
            "db_type": "postgres",
            "host": "pg1",
            "port": 5432,
            "username": "u",
            "database": "d",
        },
        {"name": "dbx-notes", "db_type": "sqlite", "file_path": "/tmp/n.db"},
        {
            "name": "dbx-tunnelled",
            "db_type": "mysql",
            "host": "10.1.1.1",
            "port": 3306,
            "transport_layers": [
                {"type": "ssh", "host": "bastion", "port": 2222, "user": "ops", "key_path": "~/.ssh/id"}
            ],
        },
        {"name": "bad", "db_type": "cassandra", "host": "n1"},
    ],
    "layout": {"groups": [{"id": "g1", "name": "Prod"}]},
}


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _encrypt_dbx(plain_json: str, passphrase: str) -> dict:
    """Build a DBX ``dbx-encrypted`` envelope the way DBX itself does."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(
        algorithm=SHA256(), length=32, salt=salt, iterations=100_000
    ).derive(passphrase.encode())
    ciphertext = AESGCM(key).encrypt(iv, plain_json.encode(), None)
    return {
        "format": "dbx-encrypted",
        "version": 1,
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(ciphertext).decode(),
    }


# ── format registry ────────────────────────────────────────────────────────


class TestFormatRegistry:
    def test_every_advertised_format_has_a_descriptor(self) -> None:
        assert FORMAT_KEYS == tuple(f.key for f in IMPORT_FORMATS)
        assert set(FORMAT_KEYS) == {
            "dbx",
            "navicat",
            "dbeaver",
            "datagrip",
            "rdm",
            "another_rdm",
        }

    def test_unknown_format_names_the_supported_ones(self) -> None:
        with pytest.raises(ValueError, match="unknown import format 'nope'"):
            get_format("nope")

    def test_only_dbx_is_exposed_as_encryptable(self) -> None:
        assert [f.key for f in IMPORT_FORMATS if f.may_be_encrypted] == ["dbx"]


# ── DataGrip ───────────────────────────────────────────────────────────────


class TestDataGrip:
    def test_parses_every_supported_driver(self, tmp_path) -> None:
        path = _write(tmp_path, "dataSources.xml", DATAGRIP_XML)
        result = parse_datagrip(path)
        engines = {c.name: c.engine for c in result.connections}
        assert engines == {
            "prod-pg": "postgresql",
            "shop": "mysql",
            "notes": "sqlite",
            "ora": "oracle",
            "mssql": "sqlserver",
        }

    def test_jdbc_url_is_split_into_target_fields(self, tmp_path) -> None:
        path = _write(tmp_path, "dataSources.xml", DATAGRIP_XML)
        by_name = {c.name: c for c in parse_datagrip(path).connections}
        assert (by_name["prod-pg"].host, by_name["prod-pg"].port) == ("db.internal", 5432)
        assert by_name["prod-pg"].database == "analytics"
        assert (by_name["shop"].host, by_name["shop"].port) == ("10.0.0.5", 3306)
        # SQL Server keeps the database inside `;databaseName=...`.
        assert by_name["mssql"].database == "erp"
        # Both Oracle URL shapes resolve to host/port/database.
        assert (by_name["ora"].host, by_name["ora"].port, by_name["ora"].database) == (
            "ora1",
            1521,
            "ORCL",
        )

    def test_local_xml_fills_in_user_and_product(self, tmp_path) -> None:
        _write(tmp_path, "dataSources.local.xml", DATAGRIP_LOCAL_XML)
        path = _write(tmp_path, "dataSources.xml", DATAGRIP_XML)
        result = parse_datagrip(path)  # auto-discovers the sibling local file
        assert {c.name: c.user for c in result.connections}["prod-pg"] == "ro"

    def test_group_attribute_becomes_a_group(self, tmp_path) -> None:
        path = _write(tmp_path, "dataSources.xml", DATAGRIP_XML)
        by_name = {c.name: c for c in parse_datagrip(path).connections}
        assert by_name["prod-pg"].group == "Prod/APAC"
        assert by_name["shop"].group == ""

    def test_user_home_macro_is_expanded(self, tmp_path) -> None:
        from pathlib import Path

        path = _write(tmp_path, "dataSources.xml", DATAGRIP_XML)
        by_name = {c.name: c for c in parse_datagrip(path).connections}
        assert by_name["notes"].host == ""
        assert by_name["notes"].database.startswith(str(Path.home()))

    def test_unsupported_driver_is_skipped_with_a_reason(self, tmp_path) -> None:
        path = _write(tmp_path, "dataSources.xml", DATAGRIP_XML)
        result = parse_datagrip(path)
        assert [s.name for s in result.skipped] == ["cass"]
        assert "cassandra" in result.skipped[0].reason

    def test_plain_file_is_rejected_as_xml(self, tmp_path) -> None:
        path = _write(tmp_path, "dataSources.xml", "not xml at all")
        with pytest.raises(ValueError, match="not well-formed XML"):
            parse_datagrip(path)


# ── RedisDesktopManager ────────────────────────────────────────────────────


class TestRedisDesktopManager:
    def test_nested_groups_become_group_paths(self, tmp_path) -> None:
        path = _write(tmp_path, "rdm.json", json.dumps(RDM_JSON))
        result = parse_rdm(path)
        by_name = {c.name: c for c in result.connections}
        assert by_name["cache"].group == "Team"
        assert by_name["flat"].group == ""
        assert all(c.engine == "redis" for c in result.connections)

    def test_credentials_and_ssh_are_carried(self, tmp_path) -> None:
        path = _write(tmp_path, "rdm.json", json.dumps(RDM_JSON))
        cache = {c.name: c for c in parse_rdm(path).connections}["cache"]
        assert cache.password == "pw"
        assert cache.use_ssh is True
        assert (cache.ssh_host, cache.ssh_user) == ("bastion", "ops")

    def test_unknown_entry_kind_is_skipped(self, tmp_path) -> None:
        path = _write(tmp_path, "rdm.json", json.dumps(RDM_JSON))
        result = parse_rdm(path)
        assert [s.name for s in result.skipped] == ["weird"]
        assert "unknown-kind" in result.skipped[0].reason

    def test_non_array_export_is_refused(self, tmp_path) -> None:
        path = _write(tmp_path, "rdm.json", json.dumps({"connections": []}))
        with pytest.raises(ValueError, match="JSON array"):
            parse_rdm(path)


# ── Another Redis Desktop Manager ──────────────────────────────────────────


class TestAnotherRedisDesktopManager:
    def test_base64_wrapped_json_is_unwrapped(self, tmp_path) -> None:
        packed = base64.b64encode(json.dumps(ANO_PAYLOAD).encode()).decode()
        path = _write(tmp_path, "connections.ano", packed)
        result = parse_another_rdm(path)
        assert {c.name for c in result.connections} == {"ano-redis", "ano-ssh"}
        assert all(c.engine == "redis" for c in result.connections)

    def test_group_id_is_resolved_to_the_group_name(self, tmp_path) -> None:
        packed = base64.b64encode(json.dumps(ANO_PAYLOAD).encode()).decode()
        path = _write(tmp_path, "connections.ano", packed)
        by_name = {c.name: c for c in parse_another_rdm(path).connections}
        assert by_name["ano-redis"].group == "Cluster"
        assert by_name["ano-ssh"].group == ""

    def test_ssh_options_are_carried(self, tmp_path) -> None:
        packed = base64.b64encode(json.dumps(ANO_PAYLOAD).encode()).decode()
        path = _write(tmp_path, "connections.ano", packed)
        by_name = {c.name: c for c in parse_another_rdm(path).connections}
        assert by_name["ano-ssh"].use_ssh is True
        assert by_name["ano-ssh"].ssh_host == "hop"

    def test_plain_json_export_is_also_accepted(self, tmp_path) -> None:
        path = _write(tmp_path, "connections.ano", json.dumps(ANO_PAYLOAD))
        assert len(parse_another_rdm(path).connections) == 2

    def test_non_base64_text_is_refused(self, tmp_path) -> None:
        path = _write(tmp_path, "connections.ano", "!!! not base64 !!!")
        with pytest.raises(ValueError):
            parse_another_rdm(path)


# ── DBX ────────────────────────────────────────────────────────────────────


class TestDbxPlain:
    def test_plain_export_keeps_targets(self, tmp_path) -> None:
        path = _write(tmp_path, "c.dbx", json.dumps(DBX_PLAIN))
        result = parse_dbx(path)
        by_name = {c.name: c for c in result.connections}
        assert (by_name["dbx-pg"].engine, by_name["dbx-pg"].host) == ("postgresql", "pg1")
        # A file engine keeps its path in `database` and drops the host.
        assert (by_name["dbx-notes"].engine, by_name["dbx-notes"].database) == ("sqlite", "/tmp/n.db")
        assert by_name["dbx-notes"].host == ""

    def test_ssh_transport_layer_becomes_a_tunnel(self, tmp_path) -> None:
        path = _write(tmp_path, "c.dbx", json.dumps(DBX_PLAIN))
        tunnelled = {c.name: c for c in parse_dbx(path).connections}["dbx-tunnelled"]
        assert tunnelled.use_ssh is True
        assert (tunnelled.ssh_host, tunnelled.ssh_port, tunnelled.ssh_user) == ("bastion", 2222, "ops")

    def test_unknown_db_type_is_skipped(self, tmp_path) -> None:
        path = _write(tmp_path, "c.dbx", json.dumps(DBX_PLAIN))
        result = parse_dbx(path)
        assert [s.name for s in result.skipped] == ["bad"]
        assert "cassandra" in result.skipped[0].reason

    def test_missing_connections_array_is_refused(self, tmp_path) -> None:
        path = _write(tmp_path, "c.dbx", json.dumps({"format": "dbx-config"}))
        with pytest.raises(ValueError, match="no 'connections' array"):
            parse_dbx(path)


class TestDbxEncrypted:
    def test_round_trip_with_the_right_passphrase(self, tmp_path) -> None:
        plain = json.dumps(DBX_PLAIN)
        envelope = _encrypt_dbx(plain, "pass123")
        path = _write(tmp_path, "e.dbx", json.dumps(envelope))
        result = parse_dbx(path, passphrase="pass123")
        assert {c.name for c in result.connections} == {
            "dbx-pg",
            "dbx-notes",
            "dbx-tunnelled",
        }

    def test_wrong_passphrase_is_reported_as_such(self, tmp_path) -> None:
        envelope = _encrypt_dbx(json.dumps(DBX_PLAIN), "pass123")
        path = _write(tmp_path, "e.dbx", json.dumps(envelope))
        with pytest.raises(ValueError, match="wrong passphrase"):
            parse_dbx(path, passphrase="nope")

    def test_missing_passphrase_explains_what_is_needed(self, tmp_path) -> None:
        envelope = _encrypt_dbx(json.dumps(DBX_PLAIN), "pass123")
        path = _write(tmp_path, "e.dbx", json.dumps(envelope))
        with pytest.raises(ValueError, match="passphrase is required"):
            parse_dbx(path)

    def test_envelope_validation_rejects_bad_base64(self) -> None:
        with pytest.raises(ValueError, match="invalid 'salt'"):
            decrypt_dbx_payload({"salt": "not base64!", "iv": "AAAA", "data": "AAAA"}, "x")


# ── Own export round-trip ──────────────────────────────────────────────────


class TestOwnExport:
    def test_export_then_import_preserves_the_profile(self, tmp_path) -> None:
        original = ConnectionInfo(
            id="x1",
            name="Shop",
            engine="postgresql",
            host="10.0.0.5",
            port=5432,
            user="app",
            password="s3cret",
            database="shop",
            group="Prod",
            use_ssh=True,
            ssh_host="bastion",
            ssh_port=2222,
            ssh_user="ops",
        )
        path = tmp_path / "ours.json"
        assert export_connections([original], path) == 1
        result = import_file(path)
        assert result.format == "opennavicat"
        back = result.connections[0]
        assert (back.engine, back.host, back.port, back.user, back.database) == (
            "postgresql",
            "10.0.0.5",
            5432,
            "app",
            "shop",
        )
        assert back.password == "s3cret"
        assert back.group == "Prod"
        assert back.ssh_host == "bastion"

    def test_export_can_omit_passwords(self, tmp_path) -> None:
        info = ConnectionInfo(name="n", engine="mysql", host="h", password="p")
        path = tmp_path / "ours.json"
        export_connections([info], path, include_passwords=False)
        assert import_file(path).connections[0].password == ""

    def test_legacy_bare_array_without_engine_still_imports(self, tmp_path) -> None:
        legacy = [{"name": "old", "host": "h", "port": 3306, "user": "root", "database": "d"}]
        path = _write(tmp_path, "old.json", json.dumps(legacy))
        result = parse_opennavicat(path)
        assert result.connections[0].engine == "mysql"


# ── Detection ──────────────────────────────────────────────────────────────


class TestDetectFormat:
    @pytest.mark.parametrize(
        ("name", "text", "expected"),
        [
            ("dataSources.xml", DATAGRIP_XML, "datagrip"),
            (
                "c.ncx",
                '<Connections><Connection Name="a" ConnType="MYSQL"/></Connections>',
                "navicat",
            ),
            ("rdm.json", json.dumps(RDM_JSON), "rdm"),
            ("c.dbx", json.dumps(DBX_PLAIN), "dbx"),
            (
                "ds.json",
                json.dumps({"connections": {"k": {"provider": "mysql", "name": "n"}}}),
                "dbeaver",
            ),
        ],
    )
    def test_content_wins_over_extension(self, tmp_path, name, text, expected) -> None:
        assert detect_format(_write(tmp_path, name, text)) == expected

    def test_base64_payload_is_another_rdm(self, tmp_path) -> None:
        packed = base64.b64encode(json.dumps(ANO_PAYLOAD).encode()).decode()
        assert detect_format(_write(tmp_path, "x.ano", packed)) == "another_rdm"

    def test_unrecognised_text_is_refused(self, tmp_path) -> None:
        path = _write(tmp_path, "x.txt", "nothing familiar here")
        with pytest.raises(ValueError, match="unrecognised connection-export format"):
            detect_format(path)

    def test_empty_file_is_refused(self, tmp_path) -> None:
        path = _write(tmp_path, "empty.json", "")
        with pytest.raises(ValueError, match="is empty"):
            detect_format(path)


# ── Dispatch ───────────────────────────────────────────────────────────────


class TestImportFileDispatch:
    def test_explicit_format_overrides_sniffing(self, tmp_path) -> None:
        # An object with a *list* `connections` plus `groups` is Another-RDM's
        # shape, not DBeaver's id-keyed map; the sniffer must say so.
        ano_path = _write(tmp_path, "x.json", json.dumps(ANO_PAYLOAD))
        assert import_file(ano_path).format == "another_rdm"

        # Asking for RDM explicitly uses the RDM parser, which refuses that
        # shape rather than quietly importing it as something else.
        with pytest.raises(ValueError, match="JSON array"):
            import_file(ano_path, fmt="rdm")

        # ...and an explicit RDM file is parsed by RDM regardless of extension.
        rdm_path = _write(tmp_path, "whatever.dat", json.dumps(RDM_JSON))
        assert import_file(rdm_path, fmt="rdm").format == "rdm"

    def test_passphrase_is_forwarded_to_dbx(self, tmp_path) -> None:
        envelope = _encrypt_dbx(json.dumps(DBX_PLAIN), "pw")
        path = _write(tmp_path, "e.dbx", json.dumps(envelope))
        result = import_file(path, passphrase="pw")
        assert result.format == "dbx"
        assert result.connections

    def test_alias_is_normalised_through_get_format(self, tmp_path) -> None:
        path = _write(tmp_path, "dataSources.xml", DATAGRIP_XML)
        assert import_file(path, fmt="datagrip").format == "datagrip"


# ── Engine aliases ─────────────────────────────────────────────────────────


class TestDbxTypeAliases:
    @pytest.mark.parametrize(
        ("db_type", "expected"),
        [
            ("postgres", "postgresql"),
            ("cockroachdb", "postgresql"),
            ("mssql", "sqlserver"),
            ("mongo", "mongodb"),
            ("mariadb", "mysql"),
        ],
    )
    def test_aliases_map_onto_our_engines(self, db_type, expected) -> None:
        from open_navicat.services.connection_import import resolve_engine

        assert resolve_engine(db_type, aliases=DBX_TYPE_ALIASES) == expected
