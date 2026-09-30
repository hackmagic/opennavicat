"""Tests for the engine driver registry (open_navicat.drivers.registry)."""

from __future__ import annotations

import pytest

from open_navicat.drivers import registry
from open_navicat.drivers.base_connector import BaseConnector as DriversBaseConnector
from open_navicat.drivers.registry import (
    DRIVER_REGISTRY,
    ERR_DRIVER_MISSING,
    SUPPORTED_ENGINES,
    DriverNotFoundError,
    DriverSpec,
    EngineNotSupportedError,
    available_engines,
    get_connector_class,
    get_spec,
    is_available,
    is_installed,
    normalize_engine,
    optional_engines,
    supported_engines,
)
from open_navicat.errors import ERR_ENGINE_UNSUPPORTED


class TestCatalog:
    def test_registered_engines(self) -> None:
        assert SUPPORTED_ENGINES == (
            "mysql",
            "postgresql",
            "sqlite",
            "duckdb",
            "mongodb",
            "redis",
            "sqlserver",
            "clickhouse",
            "oracle",
        )
        assert supported_engines() == tuple(DRIVER_REGISTRY)

    def test_optional_engines(self) -> None:
        assert optional_engines() == (
            "postgresql",
            "mongodb",
            "redis",
            "sqlserver",
            "clickhouse",
            "oracle",
        )
        assert "mysql" not in optional_engines()

    def test_every_spec_declares_its_package(self) -> None:
        for key, spec in DRIVER_REGISTRY.items():
            assert spec.engine == key
            assert spec.module.startswith("open_navicat.drivers.")
            assert spec.display_name
            # A blank package would make is_installed() always true, which is
            # how the mongodb/redis "driver missing" bug slipped through before.
            assert spec.package, f"{key} must declare its third-party package"

    def test_sqlserver_defaults(self) -> None:
        spec = get_spec("sqlserver")
        assert spec.default_port == 1433
        assert spec.package == "pyodbc"
        assert spec.install_hint == "pip install open-navicat[sqlserver]"

    def test_clickhouse_defaults(self) -> None:
        spec = get_spec("clickhouse")
        assert spec.default_port == 8123
        assert spec.package == "clickhouse_connect"
        assert spec.optional is True
        assert spec.install_hint == "pip install open-navicat[clickhouse]"

    def test_oracle_defaults(self) -> None:
        spec = get_spec("oracle")
        assert spec.default_port == 1521
        assert spec.package == "oracledb"
        assert spec.optional is True
        assert spec.install_hint == "pip install open-navicat[oracle]"

    def test_sqlserver_aliases(self) -> None:
        assert normalize_engine("mssql") == "sqlserver"
        assert normalize_engine("SQL Server") == "sqlserver"
        assert normalize_engine("tsql") == "sqlserver"

    def test_spec_defaults(self) -> None:
        assert get_spec("mysql").default_port == 3306
        assert get_spec("postgresql").default_port == 5432
        assert get_spec("redis").default_port == 6379
        assert get_spec("sqlite").default_port == 0

    def test_optional_engines_have_install_hint(self) -> None:
        for key in optional_engines():
            spec = get_spec(key)
            assert spec.optional is True
            assert spec.install_hint == f"pip install open-navicat[{key}]"
        assert get_spec("mysql").install_hint == ""

    def test_normalizes_case_and_aliases(self) -> None:
        assert normalize_engine("Pg") == "postgresql"
        assert normalize_engine("PSQL") == "postgresql"
        assert normalize_engine("mariadb") == "mysql"
        assert normalize_engine("mongo") == "mongodb"
        assert normalize_engine("sqlite3") == "sqlite"

    def test_normalizes_unknown_key_verbatim(self) -> None:
        assert normalize_engine("  CockroachDB ") == "cockroachdb"


class TestLookup:
    def test_get_connector_class_resolves(self) -> None:
        assert get_connector_class("mysql").__name__ == "MySQLConnector"
        assert get_connector_class("duckdb").__name__ == "DuckDBConnector"
        assert issubclass(get_connector_class("redis"), DriversBaseConnector)

    def test_alias_resolves_to_same_class(self) -> None:
        assert get_connector_class("pg") is get_connector_class("postgresql")

    def test_result_is_cached(self) -> None:
        assert get_connector_class("mysql") is get_connector_class("My")

    def test_clear_cache_drops_imports(self) -> None:
        get_connector_class.cache_clear()
        registry.clear_cache()
        assert get_connector_class("sqlite").__name__ == "SQLiteConnector"

    def test_unknown_engine_raises_with_catalog(self) -> None:
        with pytest.raises(EngineNotSupportedError) as exc:
            get_spec("cobol-db")
        err = exc.value
        assert err.code == ERR_ENGINE_UNSUPPORTED
        assert "cobol-db" in err.detail
        assert "mysql" in err.detail  # tells the user what *is* supported

    def test_missing_driver_raises_typed_error(self, monkeypatch) -> None:
        spec = DriverSpec(
            "nope",
            "NopeDB",
            1111,
            "open_navicat.drivers.nope_connector",
            "NopeConnector",
            optional=True,
            pip_extra="nope",
        )
        monkeypatch.setitem(DRIVER_REGISTRY, "nope", spec)
        get_connector_class.cache_clear()
        try:
            with pytest.raises(DriverNotFoundError) as exc:
                get_connector_class("nope")
            assert exc.value.code == ERR_DRIVER_MISSING
            assert "pip install open-navicat[nope]" in str(exc.value)
            assert is_available("nope") is False
        finally:
            get_connector_class.cache_clear()

    def test_is_installed_probes_the_package_not_the_shim(self) -> None:
        # mysql ships in the base install, so it is always "installed".
        assert is_installed("mysql") is True
        # A fake optional engine with an undeclared package must not look ready.
        spec = DriverSpec(
            "ghost", "GhostDB", 9999,
            "open_navicat.drivers.ghost_connector", "GhostConnector",
            optional=True, pip_extra="ghost",
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(DRIVER_REGISTRY, "ghost", spec)
            assert is_installed("ghost") is True  # no package declared
            assert is_available("ghost") is False  # module cannot be imported

    def test_available_engines_reports_all(self) -> None:
        assert available_engines().keys() == DRIVER_REGISTRY.keys()
        assert isinstance(available_engines()["mysql"], bool)


class TestCompatibility:
    def test_dal_shim_is_the_same_class(self) -> None:
        from open_navicat.dal.base_connector import BaseConnector as DalBaseConnector

        assert DalBaseConnector is DriversBaseConnector

    def test_dal_package_reexports_base_connector(self) -> None:
        import open_navicat.dal as dal

        assert dal.BaseConnector is DriversBaseConnector

    def test_pool_still_imports_the_loop_helper(self) -> None:
        # Integration tests import `_loop` from connection_pool; keep it exported.
        from open_navicat.dal.connection_pool import _get_loop, _loop

        assert _loop is None or _loop is _get_loop()
