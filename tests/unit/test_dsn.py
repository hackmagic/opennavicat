"""Tests for connection-string parsing and formatting."""

from __future__ import annotations

import pytest

from open_navicat.drivers.dsn import (
    FILE_ENGINES,
    Dsn,
    dsn_to_connection,
    info_to_dsn,
    parse_dsn,
)
from open_navicat.errors import ConfigError, EngineNotSupportedError


class TestParseNetworkEngines:
    def test_full_mysql_url(self) -> None:
        d = parse_dsn("mysql://root:s3cr3t@db.local:3307/app")
        assert (d.engine, d.host, d.port) == ("mysql", "db.local", 3307)
        assert (d.user, d.password, d.database) == ("root", "s3cr3t", "app")

    def test_port_defaults_from_registry(self) -> None:
        assert parse_dsn("postgresql://pg@h/db").port == 5432
        assert parse_dsn("redis://h").port == 6379
        assert parse_dsn("sqlserver://h").port == 1433
        assert parse_dsn("mongodb://h").port == 27017
        assert parse_dsn("clickhouse://h").port == 8123
        assert parse_dsn("oracle://h").port == 1521

    def test_missing_host_falls_back_to_loopback(self) -> None:
        assert parse_dsn("mysql:///app").host == "127.0.0.1"

    def test_password_only_userinfo(self) -> None:
        d = parse_dsn("redis://:sekret@cache:6379/3")
        assert (d.user, d.password, d.database) == ("", "sekret", "3")

    def test_no_database(self) -> None:
        assert parse_dsn("mysql://root@h:3306").database == ""

    def test_percent_decoded_credentials(self) -> None:
        d = parse_dsn("sqlserver://sa:P%40ssw0rd%21@sql01/master")
        assert d.user == "sa"
        assert d.password == "P@ssw0rd!"

    def test_alias_scheme(self) -> None:
        assert parse_dsn("pg://u@h/db").engine == "postgresql"
        assert parse_dsn("mssql://u@h/db").engine == "sqlserver"
        assert parse_dsn("ch://u@h/db").engine == "clickhouse"
        assert parse_dsn("clickhouse://u@h/db").engine == "clickhouse"
        assert parse_dsn("oracle://hr:pw@db01:1521/ORCLPDB1").database == "ORCLPDB1"

    def test_separator_tolerant_scheme(self) -> None:
        assert parse_dsn("sql-server://u@h/db").engine == "sqlserver"

    def test_bracketed_ipv6_host(self) -> None:
        d = parse_dsn("mysql://root@[::1]:3307/app")
        assert d.host == "::1"
        assert d.port == 3307

    def test_rejects_unknown_scheme(self) -> None:
        with pytest.raises(EngineNotSupportedError) as exc:
            parse_dsn("cockroachdb://h:26257/db")
        assert "cockroachdb" in str(exc.value)

    def test_rejects_non_numeric_port(self) -> None:
        with pytest.raises(ConfigError):
            parse_dsn("mysql://root@h:notaport/db")

    @pytest.mark.parametrize("bad", ["", "   ", "mysql", "not a url"])
    def test_rejects_garbage(self, bad: str) -> None:
        with pytest.raises(ConfigError):
            parse_dsn(bad)


class TestParseQueryOptions:
    def test_collects_options(self) -> None:
        d = parse_dsn("mysql://u@h/db?charset=utf8mb4&pool_max=20")
        assert d.options == {"charset": "utf8mb4", "pool_max": "20"}

    def test_option_keys_are_lowercased(self) -> None:
        assert parse_dsn("mysql://u@h/db?SSL=require").options == {"ssl": "require"}

    def test_last_value_wins(self) -> None:
        assert parse_dsn("mysql://u@h/db?a=1&a=2").options == {"a": "2"}

    def test_valueless_flag(self) -> None:
        assert parse_dsn("mysql://u@h/db?ssl").options == {"ssl": ""}


class TestFileEngines:
    def test_file_engines_from_registry(self) -> None:
        assert FILE_ENGINES == frozenset({"sqlite", "duckdb"})

    def test_absolute_path_three_slashes(self) -> None:
        assert parse_dsn("sqlite:///tmp/app.db").database == "/tmp/app.db"

    def test_absolute_path_four_slashes(self) -> None:
        assert parse_dsn("sqlite:////var/lib/app.db").database == "/var/lib/app.db"

    def test_relative_path_two_slashes(self) -> None:
        assert parse_dsn("sqlite://rel/local.db").database == "rel/local.db"

    def test_scheme_colon_path(self) -> None:
        assert parse_dsn("sqlite:rel/local.db").database == "rel/local.db"

    def test_windows_drive(self) -> None:
        assert parse_dsn("sqlite:///C:/data/win.db").database == "C:/data/win.db"

    def test_memory_shorthand(self) -> None:
        assert parse_dsn("duckdb:///:memory:").database == ":memory:"
        assert parse_dsn("duckdb::memory:").database == ":memory:"

    def test_file_engines_have_no_host_or_port(self) -> None:
        d = parse_dsn("duckdb:///data/warehouse.duckdb")
        assert d.host == ""
        assert d.port == 0


class TestRoundTrip:
    @pytest.mark.parametrize(
        "url",
        [
            "mysql://root:s3cr3t@db.local:3307/app",
            "postgresql://pguser@db.example.com:5432/analytics",
            "sqlserver://sa@sql01:1433/master",
            "redis://:pw@127.0.0.1:6379/3",
            "mongodb://muser@mongo:27017/shop",
            "sqlite:///tmp/app.db",
            "sqlite:////var/lib/other.db",
            "sqlite:rel/local.db",
            "sqlite:///C:/data/win.db",
            "duckdb:///:memory:",
            "duckdb:///data/wh.duckdb",
        ],
    )
    def test_render_then_reparse_preserves_the_target(self, url: str) -> None:
        first = parse_dsn(url)
        second = parse_dsn(first.to_dsn())
        assert second.engine == first.engine
        assert second.database == first.database
        assert (second.host, second.port) == (first.host, first.port)

    def test_password_is_omitted_by_default(self) -> None:
        d = parse_dsn("mysql://root:s3cr3t@h:3306/app")
        assert "s3cr3t" not in d.to_dsn()
        assert "s3cr3t" in d.to_dsn(include_password=True)
        assert "s3cr3t" not in d.redacted()

    def test_password_is_percent_encoded_on_render(self) -> None:
        d = parse_dsn("mysql://root:p%40ss@h/app")
        rendered = d.to_dsn(include_password=True)
        assert "p%40ss" in rendered
        assert parse_dsn(rendered).password == "p@ss"

    def test_options_survive_round_trip(self) -> None:
        d = parse_dsn("mysql://u@h/db?charset=latin1&pool_max=5")
        again = parse_dsn(d.to_dsn())
        assert again.options == d.options


class TestDsnToConnection:
    def test_maps_every_field(self) -> None:
        info = dsn_to_connection(
            "mysql://root:pw@db.local:3307/app"
            "?charset=latin1&pool_min=2&pool_max=20&connect_timeout=7&ssl=true",
            name="prod",
        )
        assert info.engine == "mysql"
        assert (info.host, info.port) == ("db.local", 3307)
        assert (info.user, info.password, info.database) == ("root", "pw", "app")
        assert info.name == "prod"
        assert info.charset == "latin1"
        assert (info.pool_min, info.pool_max) == (2, 20)
        assert info.connect_timeout == 7
        assert info.use_ssl is True

    def test_ssl_off_variants(self) -> None:
        for value in ("false", "0", "disable", "no"):
            assert dsn_to_connection(f"mysql://u@h/db?ssl={value}").use_ssl is False

    def test_port_defaults_when_omitted(self) -> None:
        assert dsn_to_connection("postgresql://pg@h/db").port == 5432

    def test_file_engine_clears_host_and_port(self) -> None:
        """SQLiteConnector treats a non-empty host as the file path."""
        info = dsn_to_connection("sqlite:///tmp/app.db")
        assert info.host == ""
        assert info.port == 0
        assert info.database == "/tmp/app.db"

    def test_bad_numeric_option_raises_config_error(self) -> None:
        with pytest.raises(ConfigError):
            dsn_to_connection("mysql://u@h/db?pool_max=many")

    def test_overrides_win(self) -> None:
        info = dsn_to_connection("mysql://u@h/db", name="n", password="rotated")
        assert info.password == "rotated"


class TestInfoToDsn:
    def test_network_engine(self) -> None:
        from open_navicat.models.connection import ConnectionInfo

        info = ConnectionInfo(
            engine="postgresql", user="pg", host="db.example.com", port=5432, database="analytics"
        )
        assert info_to_dsn(info) == "postgresql://pg@db.example.com:5432/analytics"

    def test_password_only_when_asked(self) -> None:
        from open_navicat.models.connection import ConnectionInfo

        info = ConnectionInfo(
            engine="mysql", user="root", password="pw", host="h", port=3306, database="app"
        )
        assert info_to_dsn(info) == "mysql://root@h:3306/app"
        assert info_to_dsn(info, include_password=True) == "mysql://root:pw@h:3306/app"

    def test_file_engine_uses_database_field(self) -> None:
        from open_navicat.models.connection import ConnectionInfo

        info = ConnectionInfo(engine="sqlite", host="", port=0, database="/tmp/a.db")
        assert info_to_dsn(info) == "sqlite:///tmp/a.db"

    def test_sqlite_legacy_host_path_still_renders(self) -> None:
        from open_navicat.models.connection import ConnectionInfo

        info = ConnectionInfo(engine="sqlite", host="/tmp/legacy.db", database="")
        assert info_to_dsn(info) == "sqlite:///tmp/legacy.db"

    def test_round_trips_through_dsn_to_connection(self) -> None:
        for url in (
            "mysql://root:pw@h:3307/app",
            "postgresql://pg@h:5432/db",
            "sqlite:///tmp/a.db",
            "duckdb:///:memory:",
        ):
            info = dsn_to_connection(url)
            again = dsn_to_connection(info_to_dsn(info, include_password=True))
            assert again.engine == info.engine
            assert (again.host, again.port) == (info.host, info.port)
            assert again.database == info.database
            assert again.user == info.user
            assert again.password == info.password


class TestDsnDataclass:
    def test_redacted_hides_password(self) -> None:
        d = Dsn(
            engine="mysql", host="h", port=3306, user="root", password="hunter2", database="app"
        )
        assert "hunter2" not in d.redacted()
        assert d.is_file_based is False

    def test_is_file_based(self) -> None:
        assert Dsn(engine="sqlite").is_file_based is True
