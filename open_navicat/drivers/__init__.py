"""Driver layer — engine registry and the connector contract.

Program against ``get_connector_class(engine)`` rather than importing connector
modules directly; that keeps CLI, GUI, migration tooling and the future MCP
server on one seam.
"""

from __future__ import annotations

from open_navicat.drivers.base_connector import BaseConnector
from open_navicat.drivers.registry import (
    DRIVER_REGISTRY,
    ENGINE_ALIASES,
    SUPPORTED_ENGINES,
    DriverSpec,
    available_engines,
    get_connector_class,
    get_spec,
    is_available,
    normalize_engine,
    supported_engines,
)

__all__ = [
    "BaseConnector",
    "DRIVER_REGISTRY",
    "ENGINE_ALIASES",
    "DriverSpec",
    "SUPPORTED_ENGINES",
    "available_engines",
    "get_connector_class",
    "get_spec",
    "is_available",
    "normalize_engine",
    "supported_engines",
]
