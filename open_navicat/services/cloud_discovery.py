"""Cloud database discovery — scan saved connections for cloud-hosted databases."""
from __future__ import annotations

import logging
import os
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

# Engine name mapping from RDS engine IDs
RDS_ENGINE_MAP = {
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgres": "postgresql",
    "aurora-mysql": "mysql",
    "aurora-postgresql": "postgresql",
}

RDS_PORT_MAP = {
    "mysql": 3306,
    "mariadb": 3306,
    "postgres": 5432,
    "aurora-mysql": 3306,
    "aurora-postgresql": 5432,
}


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

    def discover_aws(
        self,
        access_key: str = "",
        secret_key: str = "",
        regions: list[str] | None = None,
    ) -> list[CloudDBInstance]:
        """Discover AWS RDS instances via boto3.

        Falls back to env vars for credentials:
          AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION
        """
        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError:
            _log.info("boto3 not installed — install with: pip install boto3")
            return []

        ak = access_key or os.environ.get("AWS_ACCESS_KEY_ID", "")
        sk = secret_key or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        if not ak or not sk:
            _log.info("AWS credentials not provided — set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY")
            return []

        session = boto3.Session(
            aws_access_key_id=ak,
            aws_secret_access_key=sk,
        )

        if not regions:
            default_region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
            try:
                ec2 = session.client("ec2", region_name=default_region)
                resp = ec2.describe_regions()
                regions = [r["RegionName"] for r in resp.get("Regions", [])]
            except (BotoCoreError, ClientError) as e:
                _log.warning("Failed to list AWS regions: %s", e)
                regions = [default_region]

        instances: list[CloudDBInstance] = []
        for region in regions:
            try:
                rds = session.client("rds", region_name=region)
                paginator = rds.get_paginator("describe_db_instances")
                for page in paginator.paginate():
                    for db in page.get("DBInstances", []):
                        engine_id = db.get("Engine", "")
                        engine = RDS_ENGINE_MAP.get(engine_id, "mysql")
                        port = db.get("Port") or RDS_PORT_MAP.get(engine_id, 3306)
                        instances.append(CloudDBInstance(
                            provider="AWS",
                            engine=engine,
                            host=db.get("Endpoint", {}).get("Address", ""),
                            port=port,
                            name=db.get("DBInstanceIdentifier", ""),
                            status=db.get("DBInstanceStatus", ""),
                            region=region,
                        ))
            except (BotoCoreError, ClientError) as e:
                _log.warning("AWS RDS scan failed for region %s: %s", region, e)

        return instances

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
