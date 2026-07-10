"""Automation Service — schedule and manage recurring database tasks.

Uses APScheduler for cron-based job scheduling.
Persistence via local_config (SQLite).

Supported job types:
- backup:  Periodic database backup via mysqldump/pg_dump
- query:   Periodic SQL query execution
- sync:    Periodic schema/data synchronization
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from open_navicat.dal.local_config import local_db

_log = logging.getLogger(__name__)

# ── Automation Service ────────────────────────────────────────────────────


class AutomationService:
    """Schedule and manage recurring database tasks via APScheduler.

    Usage:
        automation = AutomationService()
        automation.add_backup_job("daily-backup", conn_id, "prod_db", "0 2 * * *")
        automation.add_query_job("hourly-report", conn_id, "SELECT COUNT(*) FROM orders", "0 * * * *")
        automation.add_sync_job("schema-sync", conn_id, "source_db", "target_db", "0 3 * * *")
        automation.start()
    """

    def __init__(self) -> None:
        self._scheduler: Any = None
        self._job_fns: dict[str, Callable] = {
            "backup": self._run_backup_job,
            "query": self._run_query_job,
            "sync": self._run_sync_job,
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

    def add_query_job(
        self,
        name: str,
        connection_id: str,
        sql: str,
        cron_expr: str = "0 * * * *",
        database: str = "",
        enabled: bool = True,
    ) -> dict:
        """Create and persist a scheduled query execution job."""
        job_id = f"query_{uuid.uuid4().hex[:8]}"
        job = {
            "id": job_id,
            "name": name,
            "job_type": "query",
            "connection_id": connection_id,
            "cron_expr": cron_expr,
            "enabled": enabled,
            "config": {
                "sql": sql,
                "database": database,
            },
        }
        local_db.save_job(job)

        if enabled:
            self._schedule_job(job)

        return job

    def add_sync_job(
        self,
        name: str,
        connection_id: str,
        source_db: str,
        target_db: str,
        cron_expr: str = "0 3 * * *",
        sync_type: str = "schema",
        enabled: bool = True,
    ) -> dict:
        """Create and persist a scheduled sync job."""
        job_id = f"sync_{uuid.uuid4().hex[:8]}"
        job = {
            "id": job_id,
            "name": name,
            "job_type": "sync",
            "connection_id": connection_id,
            "cron_expr": cron_expr,
            "enabled": enabled,
            "config": {
                "source_db": source_db,
                "target_db": target_db,
                "sync_type": sync_type,
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
                _log.warning("Failed to remove scheduler job %s", job_id)
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
                    _log.warning("Failed to remove scheduler job %s", job_id)

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
            _log.warning("Invalid cron expression for job %s: %s", job_id, cron_expr)

    # ── Job runners ───────────────────────────────────────────────────

    def _send_notification(self, message: str) -> None:
        """Dispatch notification to all registered plugin backends."""
        try:
            from open_navicat.plugin.manager import plugin_manager
            backends = plugin_manager.get_notification_backends()
            cfg = {"url": ""}  # ponytail: read from job config in the future
            for name, send in backends.items():
                try:
                    send(message, cfg)
                except Exception as e:
                    _log.warning("Notification backend '%s' failed: %s", name, e)
        except ImportError:
            pass

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

            from open_navicat.services.backup_service import backup_service
            backup_service.backup_dir = output_dir
            backup_service.create_backup(conn_info, database, compress=compress)
            local_db.update_job_status(job["id"], "success")
            self._send_notification(f"Backup complete: {database}")
        except Exception as exc:
            local_db.update_job_status(job["id"], f"failed: {exc}")
            self._send_notification(f"Backup failed: {database} — {exc}")

    def _run_query_job(self, job: dict) -> None:
        """Execute a scheduled query job."""
        conn_id = job.get("connection_id", "")
        config = job.get("config", {})
        sql = config.get("sql", "")
        database = config.get("database", "")

        if not sql:
            local_db.update_job_status(job["id"], "failed: no SQL")
            return

        try:
            from open_navicat.dal.connection_pool import connection_pool
            from open_navicat.dal.local_config import local_db as _db

            conn_info = _db.get_connection(conn_id)
            if not conn_info:
                local_db.update_job_status(job["id"], "failed: no connection")
                return

            # Open connection if not already open
            connector = connection_pool.get(conn_id)
            if not connector:
                success = connection_pool.open(conn_info)
                if not success:
                    local_db.update_job_status(job["id"], "failed: connection failed")
                    return
                connector = connection_pool.get(conn_id)

            # Switch database if specified
            if database:
                from open_navicat.dal.connection_pool import _loop
                engine = conn_info.engine if conn_info else "mysql"
                if engine == "postgresql":
                    _loop.run_until_complete(connector.execute(f"SET search_path TO {database}"))
                else:
                    _loop.run_until_complete(connector.execute(f"USE `{database}`"))

            # Execute query
            from open_navicat.dal.connection_pool import _loop
            result = _loop.run_until_complete(connector.execute(sql))

            if result.success:
                local_db.update_job_status(job["id"], f"success: {result.row_count} rows")
            else:
                local_db.update_job_status(job["id"], f"failed: {result.error_message}")
        except Exception as exc:
            local_db.update_job_status(job["id"], f"failed: {exc}")

    def _run_sync_job(self, job: dict) -> None:
        """Execute a scheduled sync job."""
        conn_id = job.get("connection_id", "")
        config = job.get("config", {})
        source_db = config.get("source_db", "")
        target_db = config.get("target_db", "")
        sync_type = config.get("sync_type", "schema")

        if not source_db or not target_db:
            local_db.update_job_status(job["id"], "failed: missing source/target database")
            return

        try:
            from open_navicat.dal.connection_pool import connection_pool
            from open_navicat.dal.local_config import local_db as _db

            conn_info = _db.get_connection(conn_id)
            if not conn_info:
                local_db.update_job_status(job["id"], "failed: no connection")
                return

            # Open connection if not already open
            connector = connection_pool.get(conn_id)
            if not connector:
                success = connection_pool.open(conn_info)
                if not success:
                    local_db.update_job_status(job["id"], "failed: connection failed")
                    return

            engine = conn_info.engine if conn_info else "mysql"

            if sync_type == "schema":
                from open_navicat.dal.connection_pool import _loop as pool_loop
                from open_navicat.services.sync_engine import sync_engine
                diff = sync_engine.compare_databases(conn_id, source_db, target_db)
                if diff.has_changes:
                    stmts = sync_engine.generate_sync_script(diff, target_db, engine)
                    for stmt in stmts:
                        pool_loop.run_until_complete(connector.execute(stmt))
                    local_db.update_job_status(
                        job["id"], f"success: {len(diff.modified_tables)} tables synced"
                    )
                else:
                    local_db.update_job_status(job["id"], "success: no changes")
            else:
                from open_navicat.dal.connection_pool import _loop as pool_loop
                from open_navicat.services.data_sync_engine import data_sync_engine
                tables = pool_loop.run_until_complete(
                    connector.execute("SHOW TABLES" if engine != "postgresql"
                                      else "SELECT tablename FROM pg_tables WHERE schemaname='public'")
                )
                table_names = [row[0] for row in (tables.rows if tables and tables.rows else [])]
                for tbl in table_names:
                    if tbl in (source_db, target_db):
                        continue
                    diff = data_sync_engine.compare_tables(
                        conn_id, source_db, tbl, conn_id, target_db, tbl,
                    )
                    if diff.total_diffs > 0:
                        script = data_sync_engine.generate_sync_script(diff, engine)
                        if script:
                            pool_loop.run_until_complete(connector.execute(script))
                local_db.update_job_status(job["id"], "success: data synced")
        except Exception as exc:
            local_db.update_job_status(job["id"], f"failed: {exc}")


# Module-level singleton
automation_service = AutomationService()
