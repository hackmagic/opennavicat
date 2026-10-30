"""Data access layer — connection pooling and local persistence.

Engine drivers now live in :mod:`open_navicat.drivers`; this package keeps the
pool, the SSH tunnel and the local config store, and re-exports the connectors
so existing imports such as ``from open_navicat.dal import MySQLConnector``
keep working.  New code should prefer ``open_navicat.drivers``.
"""

from __future__ import annotations

import importlib

from open_navicat.dal.connection_pool import ConnectionPool, connection_pool
from open_navicat.dal.local_config import LocalConfigDB, local_db
from open_navicat.dal.ssh_tunnel import SSHTunnel
from open_navicat.drivers.base_connector import BaseConnector

__all__ = [
    "BaseConnector",
    "SSHTunnel",
    "connection_pool",
    "ConnectionPool",
    "local_db",
    "LocalConfigDB",
]

# Re-export the connectors lazily.  ``open_navicat.dal`` is imported by the
# CLI on every run, and eagerly importing all nine connector modules pulled in
# every optional driver (and its transitive dependencies) whether or not the
# command needed it.  PEP 562 module ``__getattr__`` keeps
# ``from open_navicat.dal import MySQLConnector`` working while deferring the
# import until the name is actually touched.
_CONNECTORS: dict[str, str] = {
    "MySQLConnector": "open_navicat.drivers.mysql_connector",
    "PostgreSQLConnector": "open_navicat.drivers.postgresql_connector",
    "SQLiteConnector": "open_navicat.drivers.sqlite_connector",
    "DuckDBConnector": "open_navicat.drivers.duckdb_connector",
    "MongoConnector": "open_navicat.drivers.mongo_connector",
    "RedisConnector": "open_navicat.drivers.redis_connector",
    "SQLServerConnector": "open_navicat.drivers.sqlserver_connector",
    "ClickHouseConnector": "open_navicat.drivers.clickhouse_connector",
    "OracleConnector": "open_navicat.drivers.oracle_connector",
}

__all__.extend(_CONNECTORS)


def __getattr__(name: str) -> object:
    """Import a connector module on first attribute access."""
    module_path = _CONNECTORS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path)
    return getattr(module, name)
