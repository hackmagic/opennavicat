"""Data model for a database connection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class ConnectionInfo:
    """Represents a single database connection configuration."""

    # ---- identity ----
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    color: str = "#4A90D9"
    engine: str = "mysql"

    # ---- target ----
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = ""
    charset: str = "utf8mb4"

    # ---- SSH tunnel ----
    use_ssh: bool = False
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_password: str = ""
    ssh_key_file: str = ""

    # ---- SSL ----
    use_ssl: bool = False
    ssl_ca: str = ""
    ssl_cert: str = ""
    ssl_key: str = ""

    # ---- connection pool ----
    pool_min: int = 1
    pool_max: int = 10
    connect_timeout: int = 10

    # ---- UI state ----
    is_favorite: bool = False
    group: str = ""

    @property
    def display_name(self) -> str:
        return self.name or f"{self.user}@{self.host}:{self.port}"

    @property
    def dsn(self) -> str:
        """Return a human-readable connection identifier."""
        return f"{self.engine}://{self.user}@{self.host}:{self.port}/{self.database or '(no db)'}"
