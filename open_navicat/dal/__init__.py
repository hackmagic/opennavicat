"""Data Access Layer — all database drivers and local persistence."""

from __future__ import annotations

from open_navicat.dal.base_connector import BaseConnector
from open_navicat.dal.connection_pool import ConnectionPool, connection_pool
from open_navicat.dal.local_config import LocalConfigDB, local_db
from open_navicat.dal.mysql_connector import MySQLConnector
from open_navicat.dal.ssh_tunnel import SSHTunnel

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
    from open_navicat.dal.mongo_connector import MongoConnector
    __all__.append("MongoConnector")
except ImportError:
    pass

try:
    from open_navicat.dal.redis_connector import RedisConnector
    __all__.append("RedisConnector")
except ImportError:
    pass
