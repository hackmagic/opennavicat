"""Unit tests for local configuration database."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from open_navicat.dal.local_config import LocalConfigDB
from open_navicat.models.connection import ConnectionInfo


@pytest.fixture
def db() -> LocalConfigDB:
    """Create a temporary LocalConfigDB for testing."""
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_config.sqlite"
    return LocalConfigDB(db_path)


class TestLocalConfigDB:
    def test_save_and_list_connections(self, db: LocalConfigDB) -> None:
        info = ConnectionInfo(
            name="Test Server",
            host="192.168.1.1",
            port=3306,
            user="root",
        )
        db.save_connection(info)
        connections = db.list_connections()
        assert len(connections) == 1
        assert connections[0].name == "Test Server"
        assert connections[0].host == "192.168.1.1"

    def test_delete_connection(self, db: LocalConfigDB) -> None:
        info = ConnectionInfo(name="To Delete", host="localhost")
        db.save_connection(info)
        assert len(db.list_connections()) == 1
        db.delete_connection(info.id)
        assert len(db.list_connections()) == 0

    def test_get_connection(self, db: LocalConfigDB) -> None:
        info = ConnectionInfo(name="Get Me", host="10.0.0.1", port=3307)
        db.save_connection(info)
        loaded = db.get_connection(info.id)
        assert loaded is not None
        assert loaded.name == "Get Me"
        assert loaded.port == 3307

    def test_get_nonexistent(self, db: LocalConfigDB) -> None:
        assert db.get_connection("nonexistent") is None

    def test_migrate_old_schema(self) -> None:
        """Verify schema migration from old DB missing color/conn_group columns."""
        import sqlite3
        tmp = tempfile.mkdtemp()
        old_db = Path(tmp) / "old_config.sqlite"
        conn = sqlite3.connect(str(old_db))
        conn.execute("""
            CREATE TABLE connections (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                host        TEXT NOT NULL,
                port        INTEGER NOT NULL,
                user        TEXT NOT NULL,
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
            )
        """)
        conn.execute(
            "INSERT INTO connections (id, name, host, port, user) VALUES (?, ?, ?, ?, ?)",
            ("old-1", "Legacy Server", "10.0.0.1", 3306, "admin"),
        )
        conn.commit()
        conn.close()

        migrated = LocalConfigDB(old_db)
        # list_connections should work (migration added conn_group)
        rows = migrated.list_connections()
        assert len(rows) == 1
        assert rows[0].name == "Legacy Server"
        assert rows[0].group == ""
        # save_connection should work too
        new_info = ConnectionInfo(name="New", host="10.0.0.2")
        migrated.save_connection(new_info)
        assert len(migrated.list_connections()) == 2

    def test_settings(self, db: LocalConfigDB) -> None:
        db.set_setting("theme", "dark")
        assert db.get_setting("theme") == "dark"

        db.set_setting("window_size", {"width": 1280, "height": 800})
        assert db.get_setting("window_size") == {"width": 1280, "height": 800}

    def test_snippets(self, db: LocalConfigDB) -> None:
        sid = db.save_snippet("count_users", "SELECT COUNT(*) FROM users", "Count all users")
        assert sid > 0
        snippets = db.list_snippets()
        assert len(snippets) == 1
        assert snippets[0]["name"] == "count_users"
