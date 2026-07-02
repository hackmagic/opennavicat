"""Cloud database discovery — scan cloud provider APIs for available databases."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

@dataclass
class CloudDBInstance:
    provider: str
    engine: str
    host: str
    port: int
    name: str = ""
    status: str = ""
    region: str = ""

class CloudDiscoveryService:
    """Discover database instances from cloud providers."""

    def discover_aws(self, access_key: str = "", secret_key: str = "", regions: list[str] | None = None) -> list[CloudDBInstance]:
        _log.info("AWS discovery not implemented — requires boto3")
        return []

    def discover_all(self, **kwargs: Any) -> list[CloudDBInstance]:
        result: list[CloudDBInstance] = []
        result.extend(self.discover_aws(**kwargs.get("aws", {})))
        return result

cloud_discovery = CloudDiscoveryService()
