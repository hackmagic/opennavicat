"""Automation Service — schedule and manage recurring database tasks.

Uses APScheduler for cron-based job scheduling.
Persistence via local_config (SQLite).

Supported job types:
- backup:  Periodic database backup via mysqldump
- query:   Periodic SQL query execution
- sync:    Periodic schema/data synchronization
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, Callable

from open_navicat.dal.local_config import local_db
from open_navicat.services.backup_service import backup_service


# ── Automation Service ────────────────────────────────────────────────────


class AutomationService:
    """Schedule and manage recurring database tasks via APScheduler.

    Usage:
        automation = AutomationService()
        automation.add_backup_job("daily-backup", conn_id, "prod_db", "0 2 * * *")
        automation.start()
    """

    def __init__(self) -> None:
        self._scheduler: Any = None
        self._job_fns: dict[str, Callable] = {
            "backup": self._run_backup_job,
        }

    # ── Scheduler lifecycle ───────────────────────────────────────────

    @property
    def scheduler(self) -> Any:
        """Lazy-init the APScheduler QtScheduler."""
        if self._scheduler is None:
            try:
                from apscheduler.schedulers.qt import QtScheduler
                self._scheduler = QtScheduler()
            except ImportError:
                # Fallback: BackgroundScheduler if no Qt
                from apscheduler.schedulers.background import BackgroundScheduler
                self._scheduler = BackgroundScheduler()
        return self._scheduler

    def start(self) -> None:
        """Start the scheduler (load all enabled jobs)."""
        # Reload all persisted jobs
        for job in local_db.list_jobs():
            if job.get("enabled", False):
                self._schedule_job(job)
        if not self._scheduler.running:
            self.scheduler.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler and self._scheduler.running:
            self.scheduler.shutdown(wait=False)

    # ── Job management ────────────────────────────────────────────────

    def add_backup_job(
        self,
        name: str,
        connection_id: str,
        database: str,
        cron_expr: str = "0 2 * * *",
        compress: bool = True,
        output_dir: str = "./backups",
        enabled: bool = True,
    ) -> dict:
        """Create and persist a scheduled backup job."""
        job_id = f"backup_{uuid.uuid4().hex[:8]}"
        job = {
            "id": job_id,
            "name": name,
            "job_type": "backup",
            "connection_id": connection_id,
            "cron_expr": cron_expr,
            "enabled": enabled,
            "config": {
                "database": database,
                "compress": compress,
                "output_dir": output_dir,
            },
        }
        local_db.save_job(job)

        if enabled:
            self._schedule_job(job)

        return job

    def remove_job(self, job_id: str) -> None:
        """Remove a scheduled job."""
        if self._scheduler and self._scheduler.running:
            try:
                self._scheduler.remove_job(job_id)
            except Exception:
                pass
        local_db.delete_job(job_id)

    def enable_job(self, job_id: str, enabled: bool) -> None:
        """Enable or disable a job."""
        job = local_db.get_job(job_id)
        if not job:
            return
        job["enabled"] = enabled
        local_db.save_job(job)

        if enabled:
            self._schedule_job(job)
        else:
            if self._scheduler and self._scheduler.running:
                try:
                    self._scheduler.remove_job(job_id)
                except Exception:
                    pass

    def list_jobs(self) -> list[dict]:
        """List all persisted automation jobs."""
        return local_db.list_jobs()

    def get_job(self, job_id: str) -> dict | None:
        return local_db.get_job(job_id)

    # ── Internal: schedule ────────────────────────────────────────────

    def _schedule_job(self, job: dict) -> None:
        """Register a job with APScheduler."""
        job_id = job["id"]
        job_type = job.get("job_type", "backup")
        cron_expr = job.get("cron_expr", "0 2 * * *")
        fn = self._job_fns.get(job_type)
        if not fn:
            return

        try:
            from apscheduler.triggers.cron import CronTrigger
            parts = cron_expr.strip().split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0], hour=parts[1], day=parts[2],
                    month=parts[3], day_of_week=parts[4],
                )
                self.scheduler.add_job(
                    fn,
                    trigger,
                    args=[job],
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=300,
                )
        except Exception:
            pass  # Invalid cron expression, skip

    # ── Job runners ───────────────────────────────────────────────────

    def _run_backup_job(self, job: dict) -> None:
        """Execute a backup job."""
        conn_id = job.get("connection_id", "")
        config = job.get("config", {})
        database = config.get("database", "")
        compress = config.get("compress", True)
        output_dir = config.get("output_dir", "./backups")

        if not database:
            local_db.update_job_status(job["id"], "failed: no database")
            return

        try:
            from open_navicat.dal.local_config import local_db as _db
            conn_info = _db.get_connection(conn_id)
            if not conn_info:
                local_db.update_job_status(job["id"], "failed: no connection")
                return

            backup_service.backup_dir = output_dir
            backup_service.create_backup(conn_info, database, compress=compress)
            local_db.update_job_status(job["id"], "success")
        except Exception as exc:
            local_db.update_job_status(job["id"], f"failed: {exc}")


# Module-level singleton
automation_service = AutomationService()
