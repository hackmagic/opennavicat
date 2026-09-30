"""Engine driver registry.

Before this module existed, ``ConnectionPool.open`` selected a connector with a
chain of ``if info.engine == ...`` imports.  That made three things impossible:

* asking the user which engines this build can actually use,
* telling the user *why* one failed ("driver not installed" vs. "unknown engine"),
* adding a driver without editing the pool.

The registry is now the single place that maps an engine key to its connector
class.  Lookup is lazy so that an uninstalled optional driver never breaks
import time for the whole package.

To add an engine: write the connector module under ``open_navicat/drivers/`` and
add one :class:`DriverSpec` row below.  Nothing else needs to change.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from open_navicat.errors import (
    ERR_DRIVER_MISSING,
    ERR_ENGINE_UNSUPPORTED,
    DriverNotFoundError,
    EngineNotSupportedError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from open_navicat.drivers.base_connector import BaseConnector


@dataclass(frozen=True)
class DriverSpec:
    """Declarative description of one supported engine."""

    engine: str
    display_name: str
    default_port: int
    module: str
    class_name: str
    optional: bool = False
    pip_extra: str = ""
    #: Third-party package the connector needs.  Empty means the engine ships
    #: with the base install and has no extra dependency of its own.
    package: str = ""
    #: True for engines backed by a single file rather than host + port.
    file_based: bool = False

    @property
    def install_hint(self) -> str:
        """Human instruction for making this engine available."""
        if not self.optional:
            return ""
        return f"pip install open-navicat[{self.pip_extra}]" if self.pip_extra else self.pip_extra


#: Engine key -> spec.  Adding an engine is one row here plus the connector module.
DRIVER_REGISTRY: dict[str, DriverSpec] = {
    "mysql": DriverSpec(
        "mysql",
        "MySQL / MariaDB",
        3306,
        "open_navicat.drivers.mysql_connector",
        "MySQLConnector",
        package="aiomysql",
    ),
    "postgresql": DriverSpec(
        "postgresql",
        "PostgreSQL",
        5432,
        "open_navicat.drivers.postgresql_connector",
        "PostgreSQLConnector",
        optional=True,
        pip_extra="postgresql",
        package="asyncpg",
    ),
    "sqlite": DriverSpec(
        "sqlite",
        "SQLite",
        0,
        "open_navicat.drivers.sqlite_connector",
        "SQLiteConnector",
        package="aiosqlite",
        file_based=True,
    ),
    "duckdb": DriverSpec(
        "duckdb",
        "DuckDB",
        0,
        "open_navicat.drivers.duckdb_connector",
        "DuckDBConnector",
        package="duckdb",
        file_based=True,
    ),
    "mongodb": DriverSpec(
        "mongodb",
        "MongoDB",
        27017,
        "open_navicat.drivers.mongo_connector",
        "MongoConnector",
        optional=True,
        pip_extra="mongodb",
        package="motor",
    ),
    "redis": DriverSpec(
        "redis",
        "Redis",
        6379,
        "open_navicat.drivers.redis_connector",
        "RedisConnector",
        optional=True,
        pip_extra="redis",
        package="redis",
    ),
    "sqlserver": DriverSpec(
        "sqlserver",
        "Microsoft SQL Server",
        1433,
        "open_navicat.drivers.sqlserver_connector",
        "SQLServerConnector",
        optional=True,
        pip_extra="sqlserver",
        package="pyodbc",
    ),
    "clickhouse": DriverSpec(
        "clickhouse",
        "ClickHouse",
        8123,
        "open_navicat.drivers.clickhouse_connector",
        "ClickHouseConnector",
        optional=True,
        pip_extra="clickhouse",
        package="clickhouse_connect",
    ),
    "oracle": DriverSpec(
        "oracle",
        "Oracle Database",
        1521,
        "open_navicat.drivers.oracle_connector",
        "OracleConnector",
        optional=True,
        pip_extra="oracle",
        package="oracledb",
    ),
}

#: Friendly aliases accepted by the CLI and by DSN schemes, e.g. ``--engine pg``.
ENGINE_ALIASES: dict[str, str] = {
    "my": "mysql",
    "mariadb": "mysql",
    "mysqld": "mysql",
    "pg": "postgresql",
    "psql": "postgresql",
    "postgres": "postgresql",
    "tsql": "sqlserver",
    "mssql": "sqlserver",
    "mssqldb": "sqlserver",
    "sql-server": "sqlserver",
    "sqlite3": "sqlite",
    "duck": "duckdb",
    "mongo": "mongodb",
    "mqlite": "sqlite",
    "ch": "clickhouse",
    "clickhousedb": "clickhouse",
    "oracledb": "oracle",
    "plsql": "oracle",
    "oracle-db": "oracle",
}


#: Separators users sprinkle into engine names ("SQL Server", "sql-server").
_SEPARATORS = re.compile(r"[\s_-]+")


def normalize_engine(engine: str) -> str:
    """Lower-case and resolve aliases to the canonical engine key.

    Forgiving on purpose: ``"SQL Server"``, ``"sql-server"`` and ``"mssql"`` all
    resolve to ``"sqlserver"``.  Does not validate membership; call
    :func:`get_spec` for that (an unknown name is returned unchanged so the
    error message can quote what the user actually typed).
    """
    key = (engine or "").strip().lower()
    if key in DRIVER_REGISTRY:
        return key
    if key in ENGINE_ALIASES:
        return ENGINE_ALIASES[key]
    collapsed = _SEPARATORS.sub("", key)
    if collapsed in DRIVER_REGISTRY:
        return collapsed
    return ENGINE_ALIASES.get(collapsed, key)


def get_spec(engine: str) -> DriverSpec:
    """Return the spec for ``engine`` or raise :class:`EngineNotSupportedError`.

    The error lists the available engines so a typo is self-explanatory.
    """
    key = normalize_engine(engine)
    spec = DRIVER_REGISTRY.get(key)
    if spec is None:
        raise EngineNotSupportedError(
            f"engine '{engine}' is not supported; supported engines: {', '.join(SUPPORTED_ENGINES)}"
        )
    return spec


@lru_cache(maxsize=None)
def get_connector_class(engine: str) -> type["BaseConnector"]:
    """Import and return the connector class for ``engine``.

    Raises :class:`EngineNotSupportedError` for unknown keys and
    :class:`DriverNotFoundError` when an optional dependency is missing.
    """
    spec = get_spec(engine)
    try:
        module = importlib.import_module(spec.module)
    except ImportError as exc:
        raise DriverNotFoundError(
            f"{spec.display_name} driver is not installed ({spec.engine}); "
            f"install it with: {spec.install_hint}",
            code=ERR_DRIVER_MISSING,
            from_exc=exc,
        ) from exc
    try:
        return getattr(module, spec.class_name)
    except AttributeError as exc:  # pragma: no cover - defensive
        raise DriverNotFoundError(
            f"{spec.display_name} driver module does not export {spec.class_name}",
            code=ERR_DRIVER_MISSING,
            from_exc=exc,
        ) from exc


def is_installed(engine: str) -> bool:
    """True when the third-party package for ``engine`` is importable.

    Built-in engines without a ``package`` are always considered installed.
    """
    spec = get_spec(engine)
    if not spec.package:
        return True
    return importlib.util.find_spec(spec.package) is not None


def is_available(engine: str) -> bool:
    """True when this build can actually connect to ``engine``.

    Mandatory engines report available unconditionally (a missing base
    dependency means a broken install).  Optional engines must pass both
    checks: the declared ``package`` is importable *and* the connector module
    can actually be loaded.
    """
    spec = get_spec(engine)
    if not spec.optional:
        return True
    if spec.package and not is_installed(engine):
        return False
    try:
        get_connector_class(engine)
    except DriverNotFoundError:
        return False
    return True


def is_file_engine(engine: str) -> bool:
    """True when ``engine`` is backed by a single file (sqlite, duckdb)."""
    return get_spec(engine).file_based


def file_engines() -> tuple[str, ...]:
    """Engine keys that are file-backed rather than host+port."""
    return tuple(key for key, spec in DRIVER_REGISTRY.items() if spec.file_based)


def optional_engines() -> tuple[str, ...]:
    """Engine keys whose driver is an opt-in pip extra."""
    return tuple(key for key, spec in DRIVER_REGISTRY.items() if spec.optional)


def supported_engines() -> tuple[str, ...]:
    """Canonical engine keys registered in this build."""
    return tuple(DRIVER_REGISTRY)


SUPPORTED_ENGINES = supported_engines()


def available_engines() -> dict[str, bool]:
    """Mapping ``engine -> driver installed``, for ``opennavicat engines``."""
    return {key: is_available(key) for key in DRIVER_REGISTRY}


def clear_cache() -> None:
    """Drop cached connector classes (used by tests)."""
    get_connector_class.cache_clear()


__all__ = [
    "DRIVER_REGISTRY",
    "ENGINE_ALIASES",
    "DriverSpec",
    "SUPPORTED_ENGINES",
    "available_engines",
    "clear_cache",
    "get_connector_class",
    "get_spec",
    "is_available",
    "file_engines",
    "is_file_engine",
    "is_installed",
    "normalize_engine",
    "optional_engines",
    "supported_engines",
]
