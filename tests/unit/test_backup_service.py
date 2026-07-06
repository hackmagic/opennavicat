"""Unit tests for BackupService."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from open_navicat.models.connection import ConnectionInfo
from open_navicat.services.backup_service import BackupRecord, BackupService, backup_service


class TestBackupRecord:
    def test_file_name(self) -> None:
        r = BackupRecord(file_path="/tmp/test.sql", database="db", size_bytes=1024)
        assert r.file_name == "test.sql"

    def test_size_human(self) -> None:
        assert BackupRecord(file_path="", size_bytes=500).size_human == "500 B"
        assert BackupRecord(file_path="", size_bytes=2048).size_human == "2.0 KB"
        assert BackupRecord(file_path="", size_bytes=5 * 1024 * 1024).size_human == "5.0 MB"

    def test_is_compressed(self) -> None:
        assert BackupRecord(file_path="b.sql.gz").is_compressed is True
        assert BackupRecord(file_path="b.sql").is_compressed is False

    def test_to_dict(self) -> None:
        r = BackupRecord(file_path="/tmp/b.sql", database="db", size_bytes=100, created_at="ts")
        d = r.to_dict()
        assert d["file_name"] == "b.sql"
        assert d["database"] == "db"
        assert d["size_human"] == "100 B"


class TestBackupService:
    def setup_method(self) -> None:
        self._svc = BackupService()

    def test_singleton(self) -> None:
        assert backup_service is not None

    def test_default_backup_dir(self) -> None:
        assert self._svc.backup_dir == Path("./backups")

    def test_create_backup_calls_subprocess(self) -> None:
        info = ConnectionInfo(host="localhost", user="root", password="secret", engine="mysql")
        with (
            patch("open_navicat.services.backup_service.subprocess.run") as mock_run,
            patch("open_navicat.services.backup_service.local_db") as mock_db,
        ):
            mock_run.return_value = Mock(returncode=0, stderr="")
            mock_db.get_setting.return_value = []
            record = self._svc.create_backup(info, "testdb", compress=False)
            assert record.database == "testdb"
            mock_run.assert_called_once()

    def test_create_backup_postgresql(self) -> None:
        info = ConnectionInfo(host="localhost", user="postgres", password="pass", engine="postgresql", port=5432)
        with (
            patch("open_navicat.services.backup_service.subprocess.run") as mock_run,
            patch("open_navicat.services.backup_service.local_db") as mock_db,
        ):
            mock_run.return_value = Mock(returncode=0, stderr="")
            mock_db.get_setting.return_value = []
            record = self._svc.create_backup(info, "pgdb", compress=False)
            assert record.database == "pgdb"
            mock_run.assert_called_once()

    def test_list_backups(self) -> None:
        with (
            patch("pathlib.Path.iterdir") as mock_iter,
            patch("pathlib.Path.exists", return_value=True),
        ):
            f1 = Mock(spec=Path)
            f1.name = "dump.sql"
            f1.suffix = ".sql"
            f1.resolve.return_value = Path("/backups/dump.sql")
            f1.stat.return_value.st_size = 100
            f1.stat.return_value.st_mtime = 1000000
            mock_iter.return_value = [f1]
            records = self._svc.list_backups(str(Path("/backups")))
            assert len(records) == 1
            assert records[0].file_name == "dump.sql"

    def test_restore_backup_calls_subprocess(self) -> None:
        info = ConnectionInfo(host="localhost", user="root", password="secret", engine="mysql")
        with (
            patch("open_navicat.services.backup_service.subprocess.run") as mock_run,
            patch("open_navicat.services.backup_service.Path.exists", return_value=True),
            patch("open_navicat.services.backup_service.Path.unlink"),
            patch("open_navicat.services.backup_service.connection_pool") as mock_pool,
            patch("builtins.open", MagicMock()),
        ):
            mock_pool.get.return_value = Mock()
            mock_run.return_value = Mock(returncode=0, stderr="")
            self._svc.restore_backup(info, "testdb", "/tmp/test.sql", create_db=False)
            mock_run.assert_called_once()

    def test_delete_backup(self) -> None:
        with patch("pathlib.Path.unlink") as mock_unlink:
            assert self._svc.delete_backup("/tmp/test.sql") is True
            mock_unlink.assert_called_once()

    def test_delete_backup_not_found(self) -> None:
        with patch("pathlib.Path.unlink", side_effect=FileNotFoundError):
            assert self._svc.delete_backup("/tmp/nonexistent.sql") is False

    def test_get_history(self) -> None:
        with patch("open_navicat.services.backup_service.local_db") as mock_db:
            mock_db.get_setting.return_value = [{"file_name": "a.sql"}]
            history = self._svc.get_history(limit=5)
            assert len(history) == 1
            assert history[0]["file_name"] == "a.sql"
