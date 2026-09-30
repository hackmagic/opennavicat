"""Data access layer — connection pooling and local persistence.

Engine drivers now live in :mod:`open_navicat.drivers`; this package keeps the
pool, the SSH tunnel and the local config store, and re-exports the connectors
so existing imports such as ``from open_navicat.dal import MySQLConnector``
keep working.  New code should prefer ``open_navicat.drivers``.
"""

from __future__ import annotations

from open_navicat.dal.connection_pool import ConnectionPool, connection_pool
from open_navicat.dal.local_config import LocalConfigDB, local_db
from open_navicat.dal.ssh_tunnel import SSHTunnel
from open_navicat.drivers.base_connector import BaseConnector
from open_navicat.drivers.mysql_connector import MySQLConnector

__all__ = [
    "BaseConnector",
    "MySQLConnector",
    "SSHTunnel",
    "connection_pool",
    "ConnectionPool",
    "local_db",
    "LocalConfigDB",
]

# Optional connectors — import will fail if driver not installed
try:
    from open_navicat.drivers.mongo_connector import MongoConnector
    __all__.append("MongoConnector")
except ImportError:
    pass

try:
    from open_navicat.drivers.redis_connector import RedisConnector
    __all__.append("RedisConnector")
except ImportError:
    pass
