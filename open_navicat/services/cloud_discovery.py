"""Cloud database discovery — scan saved connections for cloud-hosted databases."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

# ponytail: hostname-based detection, no cloud SDKs required
CLOUD_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS", re.compile(r"\.rds\.amazonaws\.com$", re.I)),
    ("AWS", re.compile(r"\.cluster-[\w-]+\.rds\.amazonaws\.com$", re.I)),
    ("Google Cloud", re.compile(r"\.cloudsql\.googleapis\.com$", re.I)),
    ("Azure", re.compile(r"\.database\.windows\.net$", re.I)),
    ("Azure", re.compile(r"\.mysql\.database\.azure\.com$", re.I)),
    ("Azure", re.compile(r"\.postgres\.database\.azure\.com$", re.I)),
    ("DigitalOcean", re.compile(r"\.db\.ondigitalocean\.com$", re.I)),
    ("Vercel Postgres", re.compile(r"\.vercel-storage\.com$", re.I)),
    ("Neon", re.compile(r"\.neon\.tech$", re.I)),
]


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
    """Discover database instances by scanning saved connections."""

    def discover_aws(self, access_key: str = "", secret_key: str = "", regions: list[str] | None = None) -> list[CloudDBInstance]:
        """AWS discovery stub — install boto3 for full API-based discovery."""
        _log.info("AWS API discovery not implemented — install boto3 for this feature")
        return []

    def discover_all(self, **kwargs: Any) -> list[CloudDBInstance]:
        """Scan all saved connections and classify cloud-hosted ones by hostname pattern."""
        result: list[CloudDBInstance] = []
        result.extend(self.discover_aws(**kwargs.get("aws", {})))

        try:
            from open_navicat.dal.local_config import local_db
            for conn in local_db.list_connections():
                host = conn.host or ""
                engine = conn.engine or "mysql"
                port = conn.port or 3306
                name = conn.name or ""
                for provider, pattern in CLOUD_PATTERNS:
                    if pattern.search(host):
                        result.append(CloudDBInstance(
                            provider=provider, engine=engine,
                            host=host, port=port, name=name,
                            status="configured",
                        ))
                        break
        except Exception:
            _log.warning("Failed to scan saved connections", exc_info=True)

        return result


cloud_discovery = CloudDiscoveryService()
