"""Unit tests for AutomationService."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from open_navicat.services.automation_service import AutomationService, automation_service


class TestAutomationService:
    def setup_method(self) -> None:
        self._svc = AutomationService()
        self._svc._scheduler = MagicMock()

    def test_singleton(self) -> None:
        assert automation_service is not None

    def test_start(self) -> None:
        self._svc._scheduler.running = False
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            mock_db.list_jobs.return_value = []
            self._svc.start()
            self._svc.scheduler.start.assert_called_once()

    def test_stop_when_running(self) -> None:
        self._svc._scheduler.running = True
        self._svc.stop()
        self._svc.scheduler.shutdown.assert_called_once_with(wait=False)

    def test_stop_when_not_running(self) -> None:
        self._svc._scheduler.running = False
        self._svc.stop()
        self._svc.scheduler.shutdown.assert_not_called()

    def test_add_backup_job(self) -> None:
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            job = self._svc.add_backup_job("nightly", "c1", "prod")
            assert job["name"] == "nightly"
            assert job["job_type"] == "backup"
            assert job["connection_id"] == "c1"
            assert "id" in job
            mock_db.save_job.assert_called_once()

    def test_add_backup_job_disabled(self) -> None:
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            job = self._svc.add_backup_job("off", "c1", "db", enabled=False)
            assert job["enabled"] is False
            mock_db.save_job.assert_called_once()

    def test_add_query_job(self) -> None:
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            job = self._svc.add_query_job("q1", "c1", "SELECT 1")
            assert job["job_type"] == "query"
            mock_db.save_job.assert_called_once()

    def test_add_sync_job(self) -> None:
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            job = self._svc.add_sync_job("sync1", "c1", "src", "tgt")
            assert job["job_type"] == "sync"
            mock_db.save_job.assert_called_once()

    def test_list_jobs(self) -> None:
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            mock_db.list_jobs.return_value = [{"id": "j1", "name": "test"}]
            jobs = self._svc.list_jobs()
            assert len(jobs) == 1
            assert jobs[0]["id"] == "j1"

    def test_remove_job(self) -> None:
        self._svc._scheduler.running = True
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            self._svc.remove_job("j1")
            self._svc._scheduler.remove_job.assert_called_once_with("j1")
            mock_db.delete_job.assert_called_once_with("j1")

    def test_remove_job_not_running(self) -> None:
        self._svc._scheduler.running = False
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            self._svc.remove_job("j1")
            self._svc._scheduler.remove_job.assert_not_called()
            mock_db.delete_job.assert_called_once_with("j1")

    def test_get_job(self) -> None:
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            mock_db.get_job.return_value = {"id": "j1"}
            assert self._svc.get_job("j1") == {"id": "j1"}

    def test_enable_job(self) -> None:
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            mock_db.get_job.return_value = {"id": "j1", "enabled": False}
            self._svc.enable_job("j1", True)
            mock_db.save_job.assert_called_once()
            saved = mock_db.save_job.call_args[0][0]
            assert saved["enabled"] is True

    def test_enable_job_nonexistent(self) -> None:
        with patch("open_navicat.services.automation_service.local_db") as mock_db:
            mock_db.get_job.return_value = None
            self._svc.enable_job("j1", True)
            mock_db.save_job.assert_not_called()

    def test_scheduler_lazy_init(self) -> None:
        svc = AutomationService()
        assert svc._scheduler is None
        sched = svc.scheduler
        assert sched is not None
        assert svc._scheduler is sched
