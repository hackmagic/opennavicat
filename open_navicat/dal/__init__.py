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

# Re-export the connectors that are actually installed.  Every driver is an
# optional third-party package, so a missing one must never turn
# ``import open_navicat.dal`` into an ImportError for unrelated features —
# callers who really need a driver get a typed DriverNotFoundError from
# ``open_navicat.drivers.registry.get_connector_class`` instead.
for _module, _name in (
    ("open_navicat.drivers.mysql_connector", "MySQLConnector"),
    ("open_navicat.drivers.postgresql_connector", "PostgreSQLConnector"),
    ("open_navicat.drivers.sqlite_connector", "SQLiteConnector"),
    ("open_navicat.drivers.duckdb_connector", "DuckDBConnector"),
    ("open_navicat.drivers.mongo_connector", "MongoConnector"),
    ("open_navicat.drivers.redis_connector", "RedisConnector"),
    ("open_navicat.drivers.sqlserver_connector", "SQLServerConnector"),
    ("open_navicat.drivers.clickhouse_connector", "ClickHouseConnector"),
    ("open_navicat.drivers.oracle_connector", "OracleConnector"),
):
    try:
        _cls = getattr(importlib.import_module(_module), _name)
    except ImportError:  # pragma: no cover - depends on the local install
        continue
    globals()[_name] = _cls
    __all__.append(_name)

del _module, _name, _cls
