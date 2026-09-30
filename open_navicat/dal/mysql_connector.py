"""Compatibility shim.

The implementation moved to :mod:`open_navicat.drivers.mysql_connector` as part
of the drivers layer refactor.  This module is kept so existing imports such as

    from open_navicat.dal.mysql_connector import MySQLConnector

keep working.  New code should import from ``open_navicat.drivers`` or,
preferably, go through ``get_connector_class(engine)``.
"""

from __future__ import annotations

from open_navicat.drivers.mysql_connector import MySQLConnector

__all__ = ["MySQLConnector"]
