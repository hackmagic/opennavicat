"""Backup Service — database backup and restore via mysqldump/mysql or pg_dump/psql.

Provides:
- Full database backup using mysqldump (MySQL) or pg_dump (PostgreSQL)
- Restore from SQL backup files
- List/manage backup files on disk
- Gzip compression support
"""

from __future__ import annotations

import gzip
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from open_navicat.dal.connection_pool import connection_pool
from open_navicat.dal.local_config import local_db
from open_navicat.models.connection import ConnectionInfo

# ── Data model ───────────────────────────────────────────────────────────


class BackupRecord:
    """Metadata about a single backup file."""

    def __init__(self, file_path: str, database: str = "",
                 size_bytes: int = 0, created_at: str = "") -> None:
        self.file_path = file_path
        self.database = database
        self.size_bytes = size_bytes
        self.created_at = created_at

    @property
    def file_name(self) -> str:
        return Path(self.file_path).name

    @property
    def size_human(self) -> str:
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        elif self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        else:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"

    @property
    def is_compressed(self) -> bool:
        return self.file_path.endswith(".gz")

    def to_dict(self) -> dict:
        return {
            "file_name": self.file_name,
            "file_path": self.file_path,
            "database": self.database,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "created_at": self.created_at,
            "is_compressed": self.is_compressed,
        }


# ── Backup Service ────────────────────────────────────────────────────────


class BackupService:
    """Service for creating, restoring, and managing database backups.

    Uses the ``mysqldump`` and ``mysql`` CLI tools under the hood,
    since they are the most reliable way to produce consistent backups.
    """

    DEFAULT_OUTPUT_DIR = Path("./backups")

    def __init__(self) -> None:
        self._backup_dir: Path = self.DEFAULT_OUTPUT_DIR

    @property
    def backup_dir(self) -> Path:
        return self._backup_dir

    @backup_dir.setter
    def backup_dir(self, path: Path) -> None:
        self._backup_dir = path
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    # ── Backup ───────────────────────────────────────────────────────

    def create_backup(
        self,
        conn_info: ConnectionInfo,
        database: str,
        output_file: Optional[str] = None,
        compress: bool = True,
    ) -> BackupRecord:
        """Execute mysqldump (MySQL) or pg_dump (PostgreSQL) and return a BackupRecord.

        Raises FileNotFoundError if the dump tool is not installed.
        Raises RuntimeError if the dump fails.
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not output_file:
            self._backup_dir.mkdir(parents=True, exist_ok=True)
            ext = ".sql.gz" if compress else ".sql"
            output_file = str(self._backup_dir / f"{database}_{ts}{ext}")

        is_pg = conn_info.engine == "postgresql"
        tool_name = "pg_dump" if is_pg else "mysqldump"

        # Build command
        if is_pg:
            cmd = self._build_pg_dump_cmd(conn_info, database)
        else:
            cmd = self._build_mysqldump_cmd(conn_info, database)

        dump_path = output_file.replace(".gz", "") if compress else output_file
        try:
            import os
            env = os.environ.copy()
            if is_pg and conn_info.password:
                env["PGPASSWORD"] = conn_info.password

            with open(dump_path, "w", encoding="utf-8") as f:
                proc = subprocess.run(
                    cmd, stdout=f, stderr=subprocess.PIPE, text=True,
                    timeout=3600, env=env,
                )
                if proc.returncode != 0:
                    stderr = proc.stderr or "unknown error"
                    raise RuntimeError(f"{tool_name} failed: {stderr.strip()}")
        except FileNotFoundError:
            raise FileNotFoundError(
                f"{tool_name} not found. Ensure {'PostgreSQL' if is_pg else 'MySQL'} "
                "client tools are installed and available in PATH."
            )

        # Compress if requested
        if compress:
            with open(dump_path, "rb") as f_in:
                with gzip.open(output_file, "wb") as f_out:
                    f_out.writelines(f_in)
            Path(dump_path).unlink()
            final_path = output_file
        else:
            final_path = dump_path

        stat = Path(final_path)
        record = BackupRecord(
            file_path=str(stat.resolve()),
            database=database,
            size_bytes=stat.stat().st_size,
            created_at=ts,
        )
        self._save_record(record)
        return record

    @staticmethod
    def _build_mysqldump_cmd(info: ConnectionInfo, database: str) -> list[str]:
        """Build the mysqldump argument list from connection info."""
        cmd = [
            "mysqldump",
            f"--host={info.host}",
            f"--port={info.port}",
            f"--user={info.user}",
        ]
        if info.password:
            cmd.append(f"--password={info.password}")
        cmd.extend([
            "--routines",
            "--triggers",
            "--events",
            "--add-drop-table",
            "--single-transaction",
            "--quick",
            "--set-charset",
            database,
        ])
        return cmd

    @staticmethod
    def _build_pg_dump_cmd(info: ConnectionInfo, database: str) -> list[str]:
        """Build the pg_dump argument list from connection info."""
        cmd = [
            "pg_dump",
            f"--host={info.host}",
            f"--port={info.port}",
            f"--username={info.user}",
            "--no-owner",
            "--no-privileges",
            "--clean",
            "--if-exists",
            database,
        ]
        return cmd

    @staticmethod
    def _build_pg_restore_cmd(info: ConnectionInfo, database: str) -> list[str]:
        """Build the pg_restore argument list from connection info."""
        cmd = [
            "pg_restore",
            f"--host={info.host}",
            f"--port={info.port}",
            f"--username={info.user}",
            "--no-owner",
            "--no-privileges",
            "--clean",
            "--if-exists",
            "--dbname",
            database,
        ]
        return cmd

    @staticmethod
    def _build_psql_cmd(info: ConnectionInfo, database: str) -> list[str]:
        """Build the psql argument list for SQL text restore."""
        cmd = [
            "psql",
            f"--host={info.host}",
            f"--port={info.port}",
            f"--username={info.user}",
            "--no-psqlrc",
            "--set",
            "ON_ERROR_STOP=1",
            "--dbname",
            database,
        ]
        return cmd

    # ── Restore ──────────────────────────────────────────────────────

    def restore_backup(
        self,
        conn_info: ConnectionInfo,
        database: str,
        backup_file: str,
        create_db: bool = True,
    ) -> None:
        """Restore a database from a backup file using mysql/psql CLI."""
        backup_path = Path(backup_file)
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_file}")

        is_pg = conn_info.engine == "postgresql"

        # Create database if needed
        if create_db:
            connector = connection_pool.get(conn_info.id)
            if connector is None:
                from open_navicat.dal.connection_pool import _get_loop
                if is_pg:
                    from open_navicat.dal.postgresql_connector import PostgreSQLConnector
                    connector = PostgreSQLConnector()
                    _get_loop().run_until_complete(connector.connect(
                        host=conn_info.host,
                        port=conn_info.port,
                        user=conn_info.user,
                        password=conn_info.password,
                        database="postgres",
                    ))
                    _get_loop().run_until_complete(
                        connector.execute(f'CREATE DATABASE "{database}"')
                    )
                else:
                    from open_navicat.dal.mysql_connector import MySQLConnector
                    connector = MySQLConnector()
                    _get_loop().run_until_complete(connector.connect(
                        host=conn_info.host,
                        port=conn_info.port,
                        user=conn_info.user,
                        password=conn_info.password,
                        database="mysql",
                    ))
                    _get_loop().run_until_complete(
                        connector.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
                    )

        # Decompress if needed
        input_path = str(backup_path)
        if str(backup_path).endswith(".gz"):
            decompressed = str(backup_path.with_suffix(""))  # remove .gz
            with gzip.open(backup_path, "rb") as f_in:
                with open(decompressed, "wb") as f_out:
                    f_out.write(f_in.read())
            input_path = decompressed

        import os
        env = os.environ.copy()
        if is_pg and conn_info.password:
            env["PGPASSWORD"] = conn_info.password

        try:
            if is_pg:
                # pg_restore for .dump/.backup files, psql for .sql
                is_binary = backup_path.suffix in (".dump", ".backup", ".custom")
                if is_binary:
                    cmd = self._build_pg_restore_cmd(conn_info, database)
                    cmd.append(input_path)
                else:
                    cmd = self._build_psql_cmd(conn_info, database)
            else:
                cmd = [
                    "mysql",
                    f"--host={conn_info.host}",
                    f"--port={conn_info.port}",
                    f"--user={conn_info.user}",
                ]
                if conn_info.password:
                    cmd.append(f"--password={conn_info.password}")
                cmd.append(database)

            with open(input_path, "r", encoding="utf-8") as f:
                proc = subprocess.run(
                    cmd, stdin=f, capture_output=True, text=True,
                    timeout=7200, env=env,
                )
                if proc.returncode != 0:
                    stderr = proc.stderr or "unknown error"
                    tool = "pg_restore/psql" if is_pg else "mysql"
                    raise RuntimeError(f"{tool} restore failed: {stderr.strip()}")
        except FileNotFoundError:
            tool = "psql/pg_restore" if is_pg else "mysql"
            raise FileNotFoundError(
                f"{tool} client not found. Ensure {'PostgreSQL' if is_pg else 'MySQL'} "
                "client tools are installed."
            )
        finally:
            if input_path != backup_file and Path(input_path).exists():
                Path(input_path).unlink()

    # ── List backups ─────────────────────────────────────────────────

    def list_backups(self, directory: Optional[str] = None) -> list[BackupRecord]:
        """Scan a directory for backup files and return records."""
        scan_dir = Path(directory) if directory else self._backup_dir
        if not scan_dir.exists():
            return []

        records: list[BackupRecord] = []
        for f in sorted(scan_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.suffix in (".sql", ".gz") and not f.name.startswith("."):
                records.append(BackupRecord(
                    file_path=str(f.resolve()),
                    size_bytes=f.stat().st_size,
                    created_at=datetime.fromtimestamp(
                        f.stat().st_mtime
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                ))
        return records

    def delete_backup(self, file_path: str) -> bool:
        """Delete a backup file from disk."""
        try:
            Path(file_path).unlink()
            return True
        except FileNotFoundError:
            return False

    # ── Persist history ──────────────────────────────────────────────

    def _save_record(self, record: BackupRecord) -> None:
        """Save a backup record to local config history."""
        history = local_db.get_setting("backup_history", [])
        history.insert(0, record.to_dict())
        # Keep last 100 entries
        if len(history) > 100:
            history = history[:100]
        local_db.set_setting("backup_history", history)

    def get_history(self, limit: int = 50) -> list[dict]:
        """Get backup history from local config."""
        history = local_db.get_setting("backup_history", [])
        return history[:limit]


# Module-level singleton
backup_service = BackupService()
