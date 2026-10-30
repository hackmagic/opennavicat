"""Metadata service — provides access to database structure information."""

from __future__ import annotations

import time
from typing import Any, Optional

from open_navicat.dal.connection_pool import _get_loop as _pool_loop
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.drivers.base_connector import BaseConnector
from open_navicat.models.table_schema import (
    DatabaseInfo,
    TableInfo,
)


class MetadataService:
    """Service layer for reading database schema metadata.

    Public methods use a simple TTL cache (default 60 s) to reduce
    round-trips for data that rarely changes mid-session.
    """

    CACHE_TTL = 60

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}

    def _connector(self, connection_id: str) -> BaseConnector | None:
        return connection_pool.get(connection_id)

    def _exec(self, connection_id: str, method: str, *args) -> Any:
        connector = self._connector(connection_id)
        if not connector:
            return None
        return _pool_loop().run_until_complete(getattr(connector, method)(*args))

    def _cached(self, key: str, connection_id: str, method: str, *args) -> Any:
        now = time.monotonic()
        if key in self._cache:
            ts, val = self._cache[key]
            if now - ts < self.CACHE_TTL:
                return val
        val = self._exec(connection_id, method, *args)
        if val is not None:
            self._cache[key] = (now, val)
        return val or []

    def invalidate(self, connection_id: str = "", database: str = "", table: str = "") -> None:
        if not connection_id:
            self._cache.clear()
            return
        self._cache = {k: v for k, v in self._cache.items() if not k.startswith(connection_id)}

    # ---- databases ----

    def list_databases(self, connection_id: str) -> list[DatabaseInfo]:
        key = f"{connection_id}:list_databases"
        return self._cached(key, connection_id, "list_databases")

    # ---- tables ----

    def list_tables(self, connection_id: str, database: str) -> list[str]:
        key = f"{connection_id}:list_tables:{database}"
        return self._cached(key, connection_id, "list_tables", database)

    def get_table_info(self, connection_id: str, database: str, table: str) -> Optional[TableInfo]:
        key = f"{connection_id}:get_table_info:{database}:{table}"
        now = time.monotonic()
        if key in self._cache:
            ts, val = self._cache[key]
            if now - ts < self.CACHE_TTL:
                return val
        val = self._exec(connection_id, "get_table_info", database, table)
        if val is not None:
            self._cache[key] = (now, val)
        return val

    # ---- views ----

    def list_views(self, connection_id: str, database: str) -> list[str]:
        key = f"{connection_id}:list_views:{database}"
        return self._cached(key, connection_id, "list_views", database)

    # ---- routines ----

    def list_routines(self, connection_id: str, database: str) -> list[tuple[str, str]]:
        key = f"{connection_id}:list_routines:{database}"
        return self._cached(key, connection_id, "list_routines", database)

    # ---- helpers ----

    @staticmethod
    def _engine_of(connector: BaseConnector) -> str:
        info = getattr(connector, "_info", None)
        return getattr(info, "engine", "mysql") if info else "mysql"

    @staticmethod
    def _quote(name: str, engine: str) -> str:
        q = '"' if engine == "postgresql" else "`"
        return f"{q}{name}{q}"

    def get_create_table_sql(self, connection_id: str, database: str, table: str) -> str:
        """The CREATE TABLE statement for ``table``, engine-appropriate.

        The PostgreSQL branch used ``pg_get_tabledef``, which is a pgAdmin
        helper procedure and does **not** exist in PostgreSQL itself -- every
        call failed and the caller silently received a ``-- Use pg_dump``
        placeholder, so "copy DDL" was dead on PostgreSQL. Delegate to the real
        ``pg_dump`` binary (schema-only, single table, no owner/privileges noise)
        and rebuild the statement from the catalog when it is not on PATH.
        """
        connector = self._connector(connection_id)
        if not connector:
            return ""
        engine = self._engine_of(connector)
        if engine == "postgresql":
            dumped = self._pg_dump_table(connector, database, table)
            if dumped:
                return dumped
            return self._pg_rebuild_ddl(connector, database, table)
        result = _pool_loop().run_until_complete(
            connector.execute(f"SHOW CREATE TABLE `{database}`.`{table}`")
        )
        if result.success and result.rows and len(result.rows[0]) > 1:
            return result.rows[0][1]
        return ""

    @staticmethod
    def _find_pg_dump() -> str:
        """Locate the ``pg_dump`` binary, including common install locations.

        ``shutil.which`` alone is not enough: on Windows the PostgreSQL bin
        directory is usually *not* on PATH, so a user with a perfectly good
        installation still got the "no DDL" path.  Check the install roots the
        official installers and package managers use before giving up.
        """
        import os
        import shutil
        from pathlib import Path

        env_override = os.environ.get("OPENNAVICAT_PG_DUMP", "")
        if env_override and Path(env_override).is_file():
            return env_override

        found = shutil.which("pg_dump")
        if found:
            return found

        candidates: list[Path] = []
        for root in (
            r"C:\Program Files\PostgreSQL",
            r"C:\Program Files (x86)\PostgreSQL",
            "/usr/lib/postgresql",
            "/usr/local/pgsql",
            "/opt/homebrew/opt",
            "/usr/local/opt",
        ):
            base = Path(root)
            if not base.is_dir():
                continue
            # Versioned subdirectories, newest first (18, 17, ... 9.6).
            versions = sorted(
                (p for p in base.iterdir() if p.is_dir()),
                key=lambda p: p.name,
                reverse=True,
            )
            for v in versions:
                candidates.append(v / "bin" / "pg_dump")
                candidates.append(v / "bin" / "pg_dump.exe")
        for cand in candidates:
            if cand.is_file():
                return str(cand)
        return ""

    @classmethod
    def _pg_dump_table(cls, connector, database: str, table: str) -> str:
        """Run ``pg_dump --schema-only`` for one table and return its DDL."""
        import os
        import subprocess

        binary = cls._find_pg_dump()
        info = getattr(connector, "_info", None)
        if not binary or info is None:
            return ""
        schema, _, name = table.partition(".")
        if not name:
            schema, name = "public", table
        cmd = [
            binary, "--schema-only", "--no-owner", "--no-privileges", "--no-comments",
            # A wildcard pattern, not the exact name: pg_dump matches tables only
            # by name, so `public.users` alone omits the table's OWNED sequences.
            # The dumped CREATE TABLE then references `users_id_seq` in
            # `DEFAULT nextval(...)`, and executing it on another server failed
            # with `relation "users_id_seq" does not exist`.  The trailing `*`
            # pulls in the sequence (and its indexes/constraints) with the table.
            "-t", f"{schema}.{name}*",
            "-h", str(info.host), "-p", str(info.port or 5432), "-d", database,
        ]
        if info.user:
            cmd += ["-U", str(info.user)]
        env = dict(os.environ)
        if info.password:
            env["PGPASSWORD"] = str(info.password)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60, env=env, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        if proc.returncode != 0 or not proc.stdout.strip():
            return ""
        # Keep every real statement, including the CREATE SEQUENCE that the
        # table's DEFAULT nextval() depends on; drop only pg_dump's session
        # setup and its comment banner.  `\restrict`/`\unrestrict` are psql
        # meta-commands, not SQL, and would fail if pasted into a query tool.
        kept = [
            line
            for line in proc.stdout.splitlines()
            if line.strip()
            and not line.startswith(("SET ", "SELECT pg_catalog", "--", "\\"))
        ]
        return "\n".join(kept).strip()

    def _pg_rebuild_ddl(self, connector, database: str, table: str) -> str:
        """Rebuild a CREATE TABLE from ``TableInfo`` when pg_dump is unavailable."""
        try:
            info = _pool_loop().run_until_complete(
                connector.get_table_info(database, table)
            )
        except Exception:  # noqa: BLE001 - DDL reconstruction is best effort
            return ""
        if info is None or not info.columns:
            return ""
        schema, _, name = table.partition(".")
        if not name:
            schema, name = "public", table
        q = lambda v: self._quote(v, "postgresql")  # noqa: E731
        cols = []
        for c in info.columns:
            piece = f"    {q(c.name)} {c.data_type}"
            if c.default is not None:
                piece += f" DEFAULT {c.default}"
            if not c.nullable:
                piece += " NOT NULL"
            cols.append(piece)
        pks = [q(c.name) for c in info.columns if c.is_primary_key]
        if pks:
            cols.append(f"    PRIMARY KEY ({', '.join(pks)})")
        body = ",\n".join(cols)
        return f"CREATE TABLE {q(schema)}.{q(name)} (\n{body}\n);"


# Module-level singleton
metadata_service = MetadataService()
