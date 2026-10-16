"""Tests for importing connection profiles from DBeaver / Navicat exports.

The old ``conn import`` command read a single hand-written JSON profile and
silently defaulted everything it did not find.  These tests pin the
DBeaver JSON layouts, the best-effort Navicat paths and the duplicate
detection so an import never overwrites an existing profile by accident.
"""

from __future__ import annotations

import json

import pytest

from open_navicat.models.connection import ConnectionInfo
from open_navicat.services.connection_import import (
    NAVICAT_TYPE_ALIASES,
    PROVIDER_ALIASES,
    find_duplicates,
    import_file,
    parse_dbeaver,
    parse_navicat_ncx,
    read_navicat_registry,
    resolve_engine,
    save_imported,
)


def make(engine, name, *, host="", port=0, database="", user=""):
    from open_navicat.services.connection_import import ImportedConnection

    return ImportedConnection(
        engine=engine, name=name, host=host, port=port, database=database, user=user
    )

WORKSPACE = {
    "folders": {},
    "connections": {
        "mysql-abc": {
            "provider": "mysql",
            "driver": "mysql8",
            "name": "Shop MySQL",
            "configuration": {
                "host": "10.0.0.5", "port": "3306", "database": "shop",
                "user": "app", "password": "s3cret",
            },
        },
        "pg-1": {
            "provider": "postgresql",
            "name": "Analytics",
            "configuration": {
                "host": "db.internal", "port": "5432", "database": "analytics",
                "user": "ro", "tunnel": "tun-1",
            },
        },
        "sqlite-1": {
            "provider": "sqlite",
            "name": "Local notes",
            "configuration": {"database": "/home/me/notes.db"},
        },
        "redis-1": {
            "provider": "redis",
            "name": "Cache",
            "configuration": {"host": "127.0.0.1", "port": "6379", "database": "3"},
        },
        "weird-1": {
            "provider": "cassandra",
            "name": "Old cluster",
            "configuration": {"host": "node1"},
        },
    },
    "tunnels": {"tun-1": {"host": "bastion", "port": "22"}},
}

PROJECT = {
    "version": 3,
    "dataSources": {
        "pg-2": {
            "provider": "postgres",
            "name": "Proj PG",
            "configuration": {"host": "pg.proj", "port": "5432", "database": "d", "user": "u"},
        }
    },
}

NCX = """<?xml version="1.0" encoding="UTF-8"?>
<Connections Version="1.0">
  <Connection Name="Prod MySQL" ConnType="MYSQL">
    <Host>prod.db</Host><Port>3306</Port><UserName>root</UserName>
    <Database>erp</Database><Password>!!enc!!abc</Password>
  </Connection>
  <Connection Name="Legacy" ConnType="DB2"><Host>mainframe</Host></Connection>
</Connections>
"""


class TestResolveEngine:
    @pytest.mark.parametrize(
        ("provider", "expected"),
        [
            ("mysql", "mysql"),
            ("mariadb", "mysql"),
            ("postgres", "postgresql"),
            ("mssql", "sqlserver"),
            ("MySQL8", "mysql"),
            ("PostgreSQL", "postgresql"),
            ("clickhouse", "clickhouse"),
            ("oracle", "oracle"),
        ],
    )
    def test_known_aliases(self, provider, expected):
        assert resolve_engine(provider, aliases=PROVIDER_ALIASES) == expected
        assert resolve_engine(provider, aliases=NAVICAT_TYPE_ALIASES) == expected

    def test_unknown_provider(self):
        assert resolve_engine("cassandra", aliases=PROVIDER_ALIASES) is None
        assert resolve_engine("", aliases=PROVIDER_ALIASES) is None


class TestParseDBeaver:
    def test_workspace_layout(self, tmp_path):
        path = tmp_path / "data-sources.json"
        path.write_text(json.dumps(WORKSPACE), encoding="utf-8")
        result = parse_dbeaver(path)
        assert len(result.connections) == 4
        assert [c.engine for c in result.connections] == [
            "mysql", "postgresql", "redis", "sqlite",
        ]
        # Unknown providers are reported, not silently dropped.
        assert [s.reason for s in result.skipped] == ["unknown provider 'cassandra'"]

    def test_password_imported_only_when_present(self, tmp_path):
        path = tmp_path / "data-sources.json"
        path.write_text(json.dumps(WORKSPACE), encoding="utf-8")
        result = parse_dbeaver(path)
        shop = result.connections[0]
        assert shop.password == "s3cret"
        assert shop.note == ""
        network_others = [
            c for c in result.connections if c.engine not in ("mysql", "sqlite")
        ]
        assert network_others  # pg + redis
        assert all(c.password == "" for c in network_others)
        assert all("password not stored" in c.note for c in network_others)
        # File engines need no password, so they must not be nagged about one.
        sqlite = next(c for c in result.connections if c.engine == "sqlite")
        assert "password not stored" not in sqlite.note

    def test_tunnel_is_noted_and_kept_in_options(self, tmp_path):
        path = tmp_path / "data-sources.json"
        path.write_text(json.dumps(WORKSPACE), encoding="utf-8")
        result = parse_dbeaver(path)
        pg = next(c for c in result.connections if c.engine == "postgresql")
        assert "SSH tunnel not imported" in pg.note
        # host/port/database/user/password are identity fields and are lifted
        # out of options; everything else the source carried survives there.
        assert pg.options == {"tunnel": "tun-1"}

    def test_sqlite_entry_becomes_file_based(self, tmp_path):
        path = tmp_path / "data-sources.json"
        path.write_text(json.dumps(WORKSPACE), encoding="utf-8")
        result = parse_dbeaver(path)
        info = next(c for c in result.connections if c.engine == "sqlite").to_connection_info()
        assert info.database == "/home/me/notes.db"
        assert info.host == ""  # leftover loopback host would shadow the path
        assert info.port == 0

    def test_project_layout(self, tmp_path):
        path = tmp_path / "data-sources.json"
        path.write_text(json.dumps(PROJECT), encoding="utf-8")
        result = parse_dbeaver(path)
        assert [c.name for c in result.connections] == ["Proj PG"]
        assert result.connections[0].host == "pg.proj"

    def test_missing_section_is_a_clear_error(self, tmp_path):
        path = tmp_path / "data-sources.json"
        path.write_text(json.dumps({"folders": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="no 'connections' or 'dataSources'"):
            parse_dbeaver(path)

    def test_array_top_level_is_a_clear_error(self, tmp_path):
        path = tmp_path / "data-sources.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(ValueError, match="expected a JSON object"):
            parse_dbeaver(path)


class TestParseNavicatNcx:
    def test_xml_export(self, tmp_path):
        path = tmp_path / "connections.ncx"
        path.write_text(NCX, encoding="utf-8")
        result = parse_navicat_ncx(path)
        assert len(result.connections) == 1
        entry = result.connections[0]
        assert (entry.engine, entry.host, entry.port, entry.database) == (
            "mysql", "prod.db", 3306, "erp",
        )
        # Navicat encrypts passwords; a broken blob is worse than none.
        assert entry.password == ""
        assert "encrypted" in entry.note
        assert [s.reason for s in result.skipped] == ["unknown type 'DB2'"]

    def test_encrypted_file_is_refused_with_a_reason(self, tmp_path):
        path = tmp_path / "connections.ncx"
        path.write_bytes(b"\x00\x01binary-garbage-not-xml")
        with pytest.raises(ValueError, match="not an XML Navicat export"):
            parse_navicat_ncx(path)

    def test_malformed_xml_reports_the_parse_error(self, tmp_path):
        path = tmp_path / "connections.ncx"
        path.write_text("<Connections><Connection></Connections>", encoding="utf-8")
        with pytest.raises(ValueError, match="not well-formed XML"):
            parse_navicat_ncx(path)


class TestReadNavicatRegistry:
    TREE = {
        "MySQL_1": {"host": "reg.db", "port": "3306", "username": "admin",
                    "database": "erp", "password": "!!enc!!"},
        "PostgreSQL_2": {"host": "reg.pg", "port": "5432", "username": "pg",
                         "database": "x"},
        "SQLite_1": {"database": "/home/me/x.db"},
        "DB2_1": {"host": "mainframe"},
    }

    def test_subkeys_become_connections(self):
        result = read_navicat_registry(self.TREE)
        assert [c.engine for c in result.connections] == [
            "mysql", "postgresql", "sqlite",
        ]
        assert all(c.password == "" for c in result.connections)
        assert all("encrypted" in c.note for c in result.connections)
        # The provider keeps its source spelling; only the lookup lower-cases.
        assert [s.reason for s in result.skipped] == ["unknown type 'DB2'"]

    def test_missing_host_and_database_is_skipped(self):
        result = read_navicat_registry({"MySQL_1": {"username": "root"}})
        assert result.connections == []
        assert [s.reason for s in result.skipped] == ["no host and no database"]


class TestImportFile:
    def test_dispatch_by_content(self, tmp_path):
        json_path = tmp_path / "data-sources.json"
        json_path.write_text(json.dumps(PROJECT), encoding="utf-8")
        assert import_file(json_path).source.endswith("data-sources.json")

        ncx_path = tmp_path / "connections.ncx"
        ncx_path.write_text(NCX, encoding="utf-8")
        assert import_file(ncx_path).connections[0].engine == "mysql"

    def test_unknown_format(self, tmp_path):
        path = tmp_path / "whatever.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(ValueError, match="unrecognised connection-export format"):
            import_file(path)


class TestFindDuplicates:
    def test_same_target_is_a_duplicate(self):
        existing = [ConnectionInfo(id="a", name="shop", engine="mysql", host="h",
                                   port=3306, database="d", user="u")]
        imported = [make("mysql", "new name", host="h", port=3306, database="d", user="u")]
        assert set(find_duplicates(imported, existing)) == {0}

    def test_same_name_is_a_duplicate(self):
        existing = [ConnectionInfo(id="a", name="shop", engine="mysql", host="other")]
        imported = [make("mysql", "shop", host="h")]
        assert set(find_duplicates(imported, existing)) == {0}

    def test_different_target_is_not_a_duplicate(self):
        existing = [ConnectionInfo(id="a", name="shop", engine="mysql", host="h")]
        imported = [make("mysql", "other", host="h2")]
        assert find_duplicates(imported, existing) == {}


class TestSaveImported:
    CONNS = [make("mysql", "one", host="h1"), make("postgresql", "two", host="h2")]

    def test_dry_run_saves_nothing(self):
        outcomes = save_imported(self.CONNS, existing=[], dry_run=True)
        assert [o.status for o in outcomes] == ["saved", "saved"]
        assert all("would be saved" in o.detail for o in outcomes)

    def test_duplicates_are_skipped(self):
        existing = [ConnectionInfo(id="a", name="one", engine="mysql", host="h1")]
        outcomes = save_imported(self.CONNS, existing=existing, dry_run=True)
        assert [o.status for o in outcomes] == ["duplicate", "saved"]
        assert "already configured" in outcomes[0].detail

    def test_saves_into_the_profile_store(self, tmp_path, monkeypatch):
        saved: list[ConnectionInfo] = []

        class FakeDb:
            def list_connections(self):
                return list(saved)

            def save_connection(self, info):
                saved.append(info)

        import open_navicat.dal.local_config as local_config

        monkeypatch.setattr(local_config, "local_db", FakeDb())
        outcomes = save_imported(self.CONNS)
        assert [o.status for o in outcomes] == ["saved", "saved"]
        assert [i.name for i in saved] == ["one", "two"]
        assert [i.engine for i in saved] == ["mysql", "postgresql"]

    def test_save_failure_does_not_stop_the_rest(self, monkeypatch):
        class FlakyDb:
            def list_connections(self):
                return []

            def save_connection(self, info):
                if info.name == "one":
                    raise OSError("disk full")
                return None

        import open_navicat.dal.local_config as local_config

        monkeypatch.setattr(local_config, "local_db", FlakyDb())
        outcomes = save_imported(self.CONNS)
        assert [o.status for o in outcomes] == ["failed", "saved"]
        assert "disk full" in outcomes[0].detail

