"""Local configuration database (SQLite) — stores connections and settings."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from open_navicat.config import CONNECTION_DB
from open_navicat.models.connection import ConnectionInfo


class LocalConfigDB:
    """SQLite-backed persistence for connection profiles and user settings."""

    def __init__(self, db_path: Path = CONNECTION_DB) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS connections (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                host        TEXT NOT NULL DEFAULT '127.0.0.1',
                port        INTEGER NOT NULL DEFAULT 3306,
                user        TEXT NOT NULL DEFAULT 'root',
                password    TEXT DEFAULT '',
                database    TEXT DEFAULT '',
                charset     TEXT DEFAULT 'utf8mb4',
                use_ssh     INTEGER DEFAULT 0,
                ssh_host    TEXT DEFAULT '',
                ssh_port    INTEGER DEFAULT 22,
                ssh_user    TEXT DEFAULT '',
                ssh_password TEXT DEFAULT '',
                ssh_key_file TEXT DEFAULT '',
                use_ssl     INTEGER DEFAULT 0,
                ssl_ca      TEXT DEFAULT '',
                ssl_cert    TEXT DEFAULT '',
                ssl_key     TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS snippets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                sql_text    TEXT NOT NULL,
                description TEXT DEFAULT '',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS saved_queries (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                connection_id TEXT NOT NULL,
                database_name TEXT NOT NULL DEFAULT '',
                name          TEXT NOT NULL,
                sql_text      TEXT NOT NULL,
                description   TEXT DEFAULT '',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS automation_jobs (
                id           TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                job_type     TEXT NOT NULL,
                connection_id TEXT NOT NULL,
                config       TEXT NOT NULL DEFAULT '{}',
                cron_expr    TEXT NOT NULL DEFAULT '0 2 * * *',
                enabled      INTEGER DEFAULT 1,
                notify_email TEXT DEFAULT '',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_run     TIMESTAMP,
                last_status  TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS favorites (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                connection_id TEXT NOT NULL,
                database_name TEXT DEFAULT '',
                object_type   TEXT NOT NULL DEFAULT 'connection',
                object_name   TEXT NOT NULL,
                sort_order    INTEGER DEFAULT 0,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS query_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                connection_id TEXT NOT NULL,
                database_name TEXT DEFAULT '',
                sql_text      TEXT NOT NULL,
                execution_time_ms INTEGER DEFAULT 0,
                status        TEXT DEFAULT 'success',
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Schema migrations for upgrades from older versions
        for col in ['color', 'conn_group']:
            try:
                conn.execute(f"ALTER TABLE connections ADD COLUMN {col} TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
        conn.commit()

    # ---- connection CRUD ----

    def save_connection(self, info: ConnectionInfo) -> None:
        conn = self._connect()
        conn.execute(
            """INSERT OR REPLACE INTO connections
               (id, name, host, port, user, password, database, charset,
                use_ssh, ssh_host, ssh_port, ssh_user, ssh_password, ssh_key_file,
                use_ssl, ssl_ca, ssl_cert, ssl_key, color, conn_group)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                info.id, info.name, info.host, info.port,
                info.user, info.password, info.database, info.charset,
                1 if info.use_ssh else 0, info.ssh_host, info.ssh_port,
                info.ssh_user, info.ssh_password, info.ssh_key_file,
                1 if info.use_ssl else 0, info.ssl_ca, info.ssl_cert, info.ssl_key,
                info.color, info.group,
            ),
        )
        conn.commit()

    def delete_connection(self, connection_id: str) -> None:
        self._connect().execute("DELETE FROM connections WHERE id = ?", (connection_id,))
        self._conn.commit()

    def list_connections(self, group: str = "") -> list[ConnectionInfo]:
        if group:
            rows = self._connect().execute(
                "SELECT * FROM connections WHERE conn_group = ? ORDER BY name", (group,)
            ).fetchall()
        else:
            rows = self._connect().execute(
                "SELECT * FROM connections ORDER BY conn_group, name"
            ).fetchall()
        return [self._row_to_connection(r) for r in rows]

    def get_connection(self, connection_id: str) -> ConnectionInfo | None:
        row = self._connect().execute(
            "SELECT * FROM connections WHERE id = ?", (connection_id,)
        ).fetchone()
        return self._row_to_connection(row) if row else None

    @staticmethod
    def _row_to_connection(row: sqlite3.Row) -> ConnectionInfo:
        return ConnectionInfo(
            id=row["id"],
            name=row["name"],
            host=row["host"],
            port=row["port"],
            user=row["user"],
            password=row["password"] or "",
            database=row["database"] or "",
            charset=row["charset"] or "utf8mb4",
            use_ssh=bool(row["use_ssh"]),
            ssh_host=row["ssh_host"] or "",
            ssh_port=row["ssh_port"] or 22,
            ssh_user=row["ssh_user"] or "",
            ssh_password=row["ssh_password"] or "",
            ssh_key_file=row["ssh_key_file"] or "",
            use_ssl=bool(row["use_ssl"]),
            ssl_ca=row["ssl_ca"] or "",
            ssl_cert=row["ssl_cert"] or "",
            ssl_key=row["ssl_key"] or "",
            color=row["color"] or "#4A90D9",
            group=row["conn_group"] or "",
        )

    def list_groups(self) -> list[str]:
        """Return sorted list of all non-empty connection group names."""
        rows = self._connect().execute(
            "SELECT DISTINCT conn_group FROM connections WHERE conn_group != '' ORDER BY conn_group"
        ).fetchall()
        return [r["conn_group"] for r in rows]

    def rename_group(self, old_name: str, new_name: str) -> None:
        """Rename a connection group."""
        self._connect().execute(
            "UPDATE connections SET conn_group = ? WHERE conn_group = ?",
            (new_name, old_name),
        )
        self._conn.commit()

    def delete_group(self, name: str) -> None:
        """Delete a connection group (set group to empty for all connections in it)."""
        self._connect().execute(
            "UPDATE connections SET conn_group = '' WHERE conn_group = ?",
            (name,),
        )
        self._conn.commit()

    # ---- settings ----

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self._connect().execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
        return default

    def set_setting(self, key: str, value: Any) -> None:
        self._connect().execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        self._conn.commit()

    # ---- snippets ----

    def save_snippet(self, name: str, sql_text: str, description: str = "") -> int:
        cur = self._connect().execute(
            "INSERT INTO snippets (name, sql_text, description) VALUES (?, ?, ?)",
            (name, sql_text, description),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_snippets(self) -> list[dict]:
        rows = self._connect().execute(
            "SELECT id, name, sql_text, description FROM snippets ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_snippet(self, snippet_id: int, name: str, sql_text: str, description: str = "") -> None:
        self._connect().execute(
            "UPDATE snippets SET name = ?, sql_text = ?, description = ? WHERE id = ?",
            (name, sql_text, description, snippet_id),
        )
        self._conn.commit()

    def delete_snippet(self, snippet_id: int) -> None:
        self._connect().execute("DELETE FROM snippets WHERE id = ?", (snippet_id,))
        self._conn.commit()

    # ---- saved queries ----

    def save_query(self, connection_id: str, database: str, name: str, sql_text: str) -> int:
        """Save a named query for a specific connection/database."""
        conn = self._connect()
        # Check if same name exists for this connection+database
        existing = conn.execute(
            "SELECT id FROM saved_queries WHERE connection_id = ? AND database_name = ? AND name = ?",
            (connection_id, database, name),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE saved_queries SET sql_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (sql_text, existing["id"]),
            )
            conn.commit()
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO saved_queries (connection_id, database_name, name, sql_text) VALUES (?, ?, ?, ?)",
            (connection_id, database, name, sql_text),
        )
        conn.commit()
        return cur.lastrowid

    def list_queries(self, connection_id: str, database: str = "") -> list[dict]:
        """List saved queries, optionally filtered by connection/database."""
        if database:
            rows = self._connect().execute(
                "SELECT id, name, sql_text, description, created_at, updated_at FROM saved_queries "
                "WHERE connection_id = ? AND database_name = ? ORDER BY name",
                (connection_id, database),
            ).fetchall()
        else:
            rows = self._connect().execute(
                "SELECT id, name, sql_text, description, created_at, updated_at FROM saved_queries "
                "WHERE connection_id = ? ORDER BY name",
                (connection_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_query(self, query_id: int) -> dict | None:
        row = self._connect().execute(
            "SELECT * FROM saved_queries WHERE id = ?", (query_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_query(self, query_id: int) -> None:
        self._connect().execute("DELETE FROM saved_queries WHERE id = ?", (query_id,))
        self._conn.commit()

    def rename_query(self, query_id: int, new_name: str) -> None:
        self._connect().execute(
            "UPDATE saved_queries SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_name, query_id),
        )
        self._conn.commit()

    # ---- favorites ----

    def add_favorite(self, connection_id: str, database: str, obj_type: str, obj_name: str) -> None:
        self._connect().execute(
            "INSERT INTO favorites (connection_id, database_name, object_type, object_name) VALUES (?, ?, ?, ?)",
            (connection_id, database, obj_type, obj_name),
        )
        self._conn.commit()

    def remove_favorite(self, connection_id: str, database: str, obj_type: str, obj_name: str) -> None:
        self._connect().execute(
            "DELETE FROM favorites WHERE connection_id = ? AND database_name = ? AND object_type = ? AND object_name = ?",
            (connection_id, database, obj_type, obj_name),
        )
        self._conn.commit()

    def is_favorite(self, connection_id: str, database: str, obj_type: str, obj_name: str) -> bool:
        row = self._connect().execute(
            "SELECT 1 FROM favorites WHERE connection_id = ? AND database_name = ? AND object_type = ? AND object_name = ?",
            (connection_id, database, obj_type, obj_name),
        ).fetchone()
        return row is not None

    def list_favorites(self) -> list[dict]:
        rows = self._connect().execute(
            "SELECT * FROM favorites ORDER BY sort_order, object_name"
        ).fetchall()
        return [{"id": r["id"], "connection_id": r["connection_id"], "database": r["database_name"],
                 "type": r["object_type"], "name": r["object_name"]} for r in rows]

    # ---- automation jobs ----

    def save_job(self, job: dict) -> None:
        """Insert or replace an automation job record."""
        self._connect().execute(
            """INSERT OR REPLACE INTO automation_jobs
               (id, name, job_type, connection_id, config, cron_expr, enabled, notify_email, last_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.get("id", ""),
                job.get("name", ""),
                job.get("job_type", "backup"),
                job.get("connection_id", ""),
                json.dumps(job.get("config", {})),
                job.get("cron_expr", "0 2 * * *"),
                1 if job.get("enabled", True) else 0,
                job.get("notify_email", ""),
                job.get("last_status", ""),
            ),
        )
        self._conn.commit()

    def delete_job(self, job_id: str) -> None:
        self._connect().execute("DELETE FROM automation_jobs WHERE id = ?", (job_id,))
        self._conn.commit()

    def list_jobs(self) -> list[dict]:
        rows = self._connect().execute(
            "SELECT * FROM automation_jobs ORDER BY created_at DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["config"] = json.loads(d["config"]) if isinstance(d["config"], str) else d["config"]
            except (json.JSONDecodeError, TypeError):
                d["config"] = {}
            d["enabled"] = bool(d["enabled"])
            result.append(d)
        return result

    def get_job(self, job_id: str) -> dict | None:
        row = self._connect().execute(
            "SELECT * FROM automation_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["config"] = json.loads(d["config"]) if isinstance(d["config"], str) else d["config"]
        except (json.JSONDecodeError, TypeError):
            d["config"] = {}
        d["enabled"] = bool(d["enabled"])
        return d

    def update_job_status(self, job_id: str, status: str) -> None:
        from datetime import datetime
        self._connect().execute(
            "UPDATE automation_jobs SET last_status = ?, last_run = ? WHERE id = ?",
            (status, datetime.now().isoformat(), job_id),
        )
        self._conn.commit()

    # ---- query history ----

    def add_query_history(self, connection_id: str, database: str, sql: str, ms: int = 0, status: str = "success") -> None:
        self._connect().execute(
            "INSERT INTO query_history (connection_id, database_name, sql_text, execution_time_ms, status) VALUES (?,?,?,?,?)",
            (connection_id, database, sql, ms, status),
        )
        self._conn.commit()

    def get_all_query_history(self) -> list[tuple]:
        rows = self._connect().execute(
            "SELECT id, connection_id, database_name, sql_text, execution_time_ms, created_at FROM query_history ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
        return [tuple(r) for r in rows]

    def clear_query_history(self) -> None:
        self._connect().execute("DELETE FROM query_history")
        self._conn.commit()


# Module-level singleton
local_db = LocalConfigDB()
