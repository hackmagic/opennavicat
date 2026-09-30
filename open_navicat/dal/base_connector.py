"""Compatibility shim.

``BaseConnector`` moved to :mod:`open_navicat.drivers.base_connector` as part
of the drivers layer refactor.  This module is kept so existing imports such as

    from open_navicat.drivers.base_connector import BaseConnector

keep working.  New code should import from ``open_navicat.drivers``.
"""

from __future__ import annotations

from open_navicat.drivers.base_connector import BaseConnector

__all__ = ["BaseConnector"]
