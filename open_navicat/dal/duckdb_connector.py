"""Compatibility shim.

The implementation moved to :mod:`open_navicat.drivers.duckdb_connector` as part
of the drivers layer refactor.  This module is kept so existing imports such as

    from open_navicat.dal.duckdb_connector import DuckDBConnector

keep working.  New code should import from ``open_navicat.drivers`` or,
preferably, go through ``get_connector_class(engine)``.
"""

from __future__ import annotations

from open_navicat.drivers.duckdb_connector import DuckDBConnector

__all__ = ["DuckDBConnector"]
