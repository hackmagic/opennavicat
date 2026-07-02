"""Backup Panel — backup, restore, and schedule database backups.

Uses BackupService for real mysqldump operations and
AutomationService for scheduled jobs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.local_config import local_db
from open_navicat.i18n import t
from open_navicat.services.automation_service import automation_service
from open_navicat.services.backup_service import backup_service

# ── Dialogs ──────────────────────────────────────────────────────────────


class _NewBackupDialog(QDialog):
    """Dialog for triggering a new backup."""

    def __init__(self, connection_id: str, databases: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("backup.dialog.new_backup"))
        self.resize(380, 250)
        layout = QFormLayout(self)

        self._db_combo = QComboBox(self)
        self._db_combo.addItems(databases)
        self._db_combo.setEditable(True)
        layout.addRow(t("backup.label.database"), self._db_combo)

        self._compress_check = QCheckBox(t("backup.checkbox.gzip"), self)
        self._compress_check.setChecked(True)
        layout.addRow(self._compress_check)

        self._out_edit = QLineEdit(self)
        self._out_edit.setPlaceholderText(t("backup.placeholder.output_path"))
        layout.addRow(t("backup.label.output_path"), self._out_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("backup.btn.start_backup"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_params(self) -> dict:
        return {
            "database": self._db_combo.currentText().strip(),
            "compress": self._compress_check.isChecked(),
            "output": self._out_edit.text().strip() or "",
        }


class _RestoreDialog(QDialog):
    """Dialog for choosing a backup file to restore."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("backup.dialog.restore"))
        self.resize(450, 200)
        layout = QFormLayout(self)

        self._file_edit = QLineEdit(self)
        self._file_edit.setReadOnly(True)
        self._file_edit.setPlaceholderText(t("backup.placeholder.backup_file"))
        layout.addRow(t("backup.label.backup_file"), self._file_edit)

        browse_btn = QPushButton(t("backup.btn.browse"), self)
        browse_btn.clicked.connect(self._browse)
        layout.addRow("", browse_btn)

        self._db_edit = QLineEdit(self)
        self._db_edit.setPlaceholderText(t("backup.placeholder.target_db"))
        layout.addRow(t("backup.label.target_db"), self._db_edit)

        self._create_db_check = QCheckBox(t("backup.checkbox.auto_create_db"), self)
        self._create_db_check.setChecked(True)
        layout.addRow(self._create_db_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("backup.btn.start_restore"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, t("backup.file_dialog.title"), "", t("backup.file_dialog.filter")
        )
        if path:
            self._file_edit.setText(path)

    def get_params(self) -> dict:
        return {
            "file": self._file_edit.text().strip(),
            "database": self._db_edit.text().strip(),
            "create_db": self._create_db_check.isChecked(),
        }


class _ScheduleDialog(QDialog):
    """Dialog for creating/editing a scheduled backup job."""

    def __init__(self, connection_id: str, databases: list[str],
                 job: Optional[dict] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("backup.dialog.scheduled_backup") if not job else t("backup.dialog.edit_scheduled"))
        self.resize(420, 300)
        self._connection_id = connection_id
        self._job = job
        layout = QFormLayout(self)

        self._name_edit = QLineEdit(job.get("name", "") if job else "", self)
        self._name_edit.setPlaceholderText(t("backup.placeholder.task_name"))
        layout.addRow(t("backup.label.task_name"), self._name_edit)

        self._db_combo = QComboBox(self)
        self._db_combo.addItems(databases)
        if job:
            cfg = job.get("config", {})
            idx = self._db_combo.findText(cfg.get("database", ""))
            if idx >= 0:
                self._db_combo.setCurrentIndex(idx)
        layout.addRow(t("backup.label.database"), self._db_combo)

        self._cron_edit = QLineEdit(
            job.get("cron_expr", "0 2 * * *") if job else "0 2 * * *", self
        )
        self._cron_edit.setPlaceholderText(t("backup.placeholder.cron"))
        layout.addRow(t("backup.label.cron"), self._cron_edit)

        # Presets
        preset_layout = QHBoxLayout()
        for label, expr in [
            (t("backup.cron.daily"), "0 2 * * *"),
            (t("backup.cron.6hours"), "0 */6 * * *"),
            (t("backup.cron.weekly"), "0 3 * * 0"),
        ]:
            btn = QPushButton(label, self)
            btn.clicked.connect(lambda checked, e=expr: self._cron_edit.setText(e))
            preset_layout.addWidget(btn)
        preset_layout.addStretch()
        layout.addRow(t("backup.label.quick_set"), preset_layout)

        self._compress_check = QCheckBox(t("backup.checkbox.gzip"), self)
        self._compress_check.setChecked(
            job.get("config", {}).get("compress", True) if job else True
        )
        layout.addRow(self._compress_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("common.save"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_params(self) -> dict:
        return {
            "name": self._name_edit.text().strip(),
            "database": self._db_combo.currentText().strip(),
            "cron_expr": self._cron_edit.text().strip(),
            "compress": self._compress_check.isChecked(),
        }


# ── Main Backup Panel ────────────────────────────────────────────────────


class BackupPanel(QWidget):
    """Database backup management — create, restore, list, schedule."""

    def __init__(self, connection_id: str, database: str = "", parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        # Ensure backup dir exists
        backup_service.backup_dir = Path("./backups")
        self._setup_ui()
        self._refresh_backups()
        self._refresh_schedules()

    # ── UI Setup ──────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Quick action cards ──
        cards = QWidget(self)
        c_layout = QHBoxLayout(cards)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(12)

        for cfg in [
            (t("backup.card.backup"), t("backup.card.backup_desc"), t("backup.card.backup_action"), "primaryBtn", self._do_backup),
            (t("backup.card.restore"), t("backup.card.restore_desc"), t("backup.card.restore_action"), "", self._do_restore),
            (t("backup.card.scheduled"), t("backup.card.scheduled_desc"), t("backup.card.scheduled_action"), "successBtn", self._new_schedule),
        ]:
            card = QFrame(cards)
            cd_layout = QVBoxLayout(card)
            cd_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            title_lbl = QLabel(cfg[0], card)
            title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cd_layout.addWidget(title_lbl)

            desc_lbl = QLabel(cfg[1], card)
            desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cd_layout.addWidget(desc_lbl)

            btn = QPushButton(cfg[2], card)
            if cfg[3]:
                btn.setObjectName(cfg[3])
            btn.clicked.connect(cfg[4])
            cd_layout.addWidget(btn)

            c_layout.addWidget(card)

        layout.addWidget(cards)

        # ── Tabs ──
        tabs = QTabWidget(self)

        # Backup list tab
        self._backup_tab = self._create_backup_tab()
        tabs.addTab(self._backup_tab, t("backup.tab.backup_list"))

        # Schedule tab
        self._schedule_tab = self._create_schedule_tab()
        tabs.addTab(self._schedule_tab, t("backup.tab.scheduled"))

        layout.addWidget(tabs, 1)

        # ── Status bar ──
        self._status = QLabel(t("status.ready"), self)
        self._status.setStyleSheet(
            "background: #007acc; color: #fff; padding: 4px 12px; font-size: 11px;"
        )
        layout.addWidget(self._status)

    def _create_backup_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        tb = QHBoxLayout()
        for text, cb in [
            (t("backup.btn.refresh"), self._refresh_backups),
            (t("backup.btn.delete_selected"), self._delete_selected),
            (t("backup.btn.cleanup_history"), self._clear_history),
        ]:
            btn = QPushButton(text, tab)
            btn.clicked.connect(cb)
            tb.addWidget(btn)
        tb.addStretch()
        layout.addLayout(tb)

        self._backup_table = QTableWidget(tab)
        self._backup_table.setColumnCount(5)
        self._backup_table.setHorizontalHeaderLabels([t("backup.column_backup.filename"), t("backup.column_backup.size"), t("backup.column_backup.database"), t("backup.column_backup.created_at"), t("backup.column_backup.operation")])
        self._backup_table.horizontalHeader().setStretchLastSection(True)
        self._backup_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for col in range(4):
            self._backup_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch
            )
        layout.addWidget(self._backup_table, 1)

        return tab

    def _create_schedule_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        tb = QHBoxLayout()
        for text, cb in [
            (t("backup.btn.new_scheduled"), self._new_schedule),
            (t("backup.btn.refresh"), self._refresh_schedules),
            (t("backup.btn.start_scheduler"), self._start_scheduler),
            (t("backup.btn.stop_scheduler"), self._stop_scheduler),
        ]:
            btn = QPushButton(text, tab)
            btn.clicked.connect(cb)
            tb.addWidget(btn)
        tb.addStretch()

        self._sched_status_lbl = QLabel(t("backup.scheduler.stopped"), tab)
        tb.addWidget(self._sched_status_lbl)

        layout.addLayout(tb)

        self._schedule_table = QTableWidget(tab)
        self._schedule_table.setColumnCount(6)
        self._schedule_table.setHorizontalHeaderLabels([
            t("backup.column_scheduled.task_name"), t("backup.column_scheduled.type"), t("backup.column_scheduled.database"), t("backup.column_scheduled.cron"), t("backup.column_scheduled.status"), t("backup.column_scheduled.last_run")
        ])
        self._schedule_table.horizontalHeader().setStretchLastSection(True)
        self._schedule_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for col in range(5):
            self._schedule_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch
            )
        self._schedule_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._schedule_table.customContextMenuRequested.connect(self._schedule_context_menu)
        layout.addWidget(self._schedule_table, 1)

        return tab

    # ── Backup operations ─────────────────────────────────────────────

    def _do_backup(self) -> None:
        """Trigger a new manual backup."""
        # Get databases from connection
        databases = []
        if self._database:
            databases.append(self._database)
        else:
            from open_navicat.services.metadata_service import metadata_service
            dbs = metadata_service.list_databases(self._connection_id)
            databases = [d.name for d in dbs] if dbs else ["db"]

        dlg = _NewBackupDialog(self._connection_id, databases, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        params = dlg.get_params()
        if not params["database"]:
            QMessageBox.warning(self, t("common.notice"), t("backup.msg.select_database"))
            return

        # Execute backup
        conn_info = local_db.get_connection(self._connection_id)
        if not conn_info:
            QMessageBox.critical(self, t("common.error"), t("backup.msg.no_connection"))
            return

        try:
            output = params["output"] or None
            record = backup_service.create_backup(
                conn_info, params["database"],
                output_file=output,
                compress=params["compress"],
            )
            QMessageBox.information(
                self, t("backup.msg.backup_complete"),
                t("backup.msg.backup_success_detail", database=params['database'], file=record.file_name, size=record.size_human)
            )
            self._refresh_backups()
        except FileNotFoundError as e:
            QMessageBox.critical(self, t("common.error"), str(e))
        except RuntimeError as e:
            QMessageBox.critical(self, t("backup.msg.backup_failed"), str(e))

    def _do_restore(self) -> None:
        """Restore a database from backup file."""
        dlg = _RestoreDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        params = dlg.get_params()
        if not params["file"] or not params["database"]:
            QMessageBox.warning(self, t("common.notice"), t("backup.msg.select_file_and_db"))
            return

        if not Path(params["file"]).exists():
            QMessageBox.warning(self, t("common.notice"), t("backup.msg.file_not_exists"))
            return

        conn_info = local_db.get_connection(self._connection_id)
        if not conn_info:
            QMessageBox.critical(self, t("common.error"), t("backup.msg.no_connection"))
            return

        try:
            backup_service.restore_backup(
                conn_info, params["database"],
                params["file"], create_db=params["create_db"],
            )
            QMessageBox.information(
                self, t("backup.msg.restore_complete"),
                t("backup.msg.restore_success_detail", database=params['database'], file=Path(params['file']).name)
            )
            self._refresh_backups()
        except Exception as e:
            QMessageBox.critical(self, t("backup.msg.restore_failed"), str(e))

    def _delete_selected(self) -> None:
        """Delete selected backup files."""
        rows = set()
        for item in self._backup_table.selectedItems():
            rows.add(item.row())

        if not rows:
            QMessageBox.information(self, t("common.notice"), t("backup.msg.select_to_delete"))
            return

        confirm = QMessageBox.question(
            self, t("backup.msg.confirm_delete"),
            t("backup.msg.confirm_delete_count", count=len(rows)),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        for row in rows:
            file_item = self._backup_table.item(row, 0)
            if file_item:
                # Find file path from data
                for record in backup_service.list_backups():
                    if record.file_name == file_item.text():
                        backup_service.delete_backup(record.file_path)
                        break

        self._refresh_backups()

    def _clear_history(self) -> None:
        """Clear backup history from local config."""
        from open_navicat.dal.local_config import local_db
        local_db.set_setting("backup_history", [])
        self._status.setText(t("backup.msg.history_cleared"))

    # ── Refresh backup list ───────────────────────────────────────────

    def _refresh_backups(self) -> None:
        """Reload and display backup files."""
        records = backup_service.list_backups()
        history = backup_service.get_history(50)

        self._backup_table.setRowCount(max(len(records), len(history)))

        for i, rec in enumerate(records):
            self._backup_table.setItem(i, 0, QTableWidgetItem(rec.file_name))
            self._backup_table.setItem(i, 1, QTableWidgetItem(rec.size_human))
            self._backup_table.setItem(i, 2, QTableWidgetItem(rec.database))
            self._backup_table.setItem(i, 3, QTableWidgetItem(rec.created_at))

            # Action buttons
            action_widget = QWidget()
            a_layout = QHBoxLayout(action_widget)
            a_layout.setContentsMargins(4, 2, 4, 2)
            for text in [t("common.restore"), t("common.delete")]:
                btn = QPushButton(text, action_widget)
                btn.setStyleSheet(
                    "padding: 2px 8px; border: 1px solid #3c3c3c; "
                    "background: transparent; color: #ccc; font-size: 10px; cursor: pointer;"
                )
                if text == t("common.restore"):
                    btn.clicked.connect(
                        lambda checked, f=rec.file_path,
                               db=rec.database: self._restore_single(f, db)
                    )
                else:
                    btn.clicked.connect(
                        lambda checked, f=rec.file_path: self._delete_single(f)
                    )
                a_layout.addWidget(btn)
            self._backup_table.setCellWidget(i, 4, action_widget)

        self._status.setText(t("backup.msg.found_count", count=len(records)))

    def _restore_single(self, file_path: str, database: str) -> None:
        """Restore a single backup file."""
        confirm = QMessageBox.question(
            self, t("backup.msg.confirm_restore"),
            t("backup.msg.confirm_restore_detail", file=Path(file_path).name, database=database),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        conn_info = local_db.get_connection(self._connection_id)
        if not conn_info:
            return

        try:
            backup_service.restore_backup(conn_info, database, file_path)
            QMessageBox.information(self, t("backup.msg.restore_complete"), t("backup.msg.restored_db", database=database))
            self._refresh_backups()
        except Exception as e:
            QMessageBox.critical(self, t("backup.msg.restore_failed"), str(e))

    def _delete_single(self, file_path: str) -> None:
        """Delete a single backup file."""
        confirm = QMessageBox.question(
            self, t("backup.msg.confirm_delete"), t("backup.msg.confirm_delete_file", file=Path(file_path).name)
        )
        if confirm == QMessageBox.StandardButton.Yes:
            backup_service.delete_backup(file_path)
            self._refresh_backups()

    # ── Schedule operations ───────────────────────────────────────────

    def _new_schedule(self) -> None:
        """Create a new scheduled backup job."""
        databases = []
        if self._database:
            databases.append(self._database)
        else:
            from open_navicat.services.metadata_service import metadata_service
            dbs = metadata_service.list_databases(self._connection_id)
            databases = [d.name for d in dbs] if dbs else ["db"]

        dlg = _ScheduleDialog(self._connection_id, databases, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        params = dlg.get_params()
        if not params["name"] or not params["database"]:
            QMessageBox.warning(self, t("common.notice"), t("backup.msg.fill_name_and_db"))
            return

        automation_service.add_backup_job(
            name=params["name"],
            connection_id=self._connection_id,
            database=params["database"],
            cron_expr=params["cron_expr"],
            compress=params["compress"],
        )
        QMessageBox.information(
            self, t("common.success"),
            t("backup.msg.created_detail", name=params['name'], cron=params['cron_expr'], database=params['database'])
        )
        self._refresh_schedules()

    def _refresh_schedules(self) -> None:
        """Reload and display scheduled jobs."""
        jobs = automation_service.list_jobs()

        self._schedule_table.setRowCount(len(jobs))
        for i, job in enumerate(jobs):
            config = job.get("config", {})
            self._schedule_table.setItem(i, 0, QTableWidgetItem(job.get("name", "")))
            self._schedule_table.setItem(i, 1, QTableWidgetItem(job.get("job_type", "backup")))
            self._schedule_table.setItem(i, 2, QTableWidgetItem(
                config.get("database", "") if isinstance(config, dict) else ""
            ))
            self._schedule_table.setItem(i, 3, QTableWidgetItem(job.get("cron_expr", "")))
            status = job.get("last_status", "")
            enabled = job.get("enabled", True)
            status_text = t("scheduler.status.enabled") if enabled else t("scheduler.status.disabled")
            if status:
                status_text += f" ({status})"
            self._schedule_table.setItem(i, 4, QTableWidgetItem(status_text))
            self._schedule_table.setItem(i, 5, QTableWidgetItem(
                job.get("last_run", "") or "-"
            ))

    def _start_scheduler(self) -> None:
        """Start the automation scheduler."""
        automation_service.start()
        self._sched_status_lbl.setText(t("backup.scheduler.running"))
        self._sched_status_lbl.setStyleSheet("color: #4ec9b0; font-size: 11px;")

    def _stop_scheduler(self) -> None:
        """Stop the automation scheduler."""
        automation_service.stop()
        self._sched_status_lbl.setText(t("backup.scheduler.stopped"))
        self._sched_status_lbl.setStyleSheet("color: #f44747; font-size: 11px;")

    def _schedule_context_menu(self, pos) -> None:
        """Right-click context menu for schedule table."""
        from PySide6.QtWidgets import QMenu

        item = self._schedule_table.itemAt(pos)
        if not item:
            return

        row = item.row()
        job_id_item = self._schedule_table.item(row, 0)
        if not job_id_item:
            return

        # Find the job
        jobs = automation_service.list_jobs()
        if row >= len(jobs):
            return
        job = jobs[row]

        menu = QMenu(self)

        toggle_text = t("context.disable") if job.get("enabled") else t("context.enable")
        toggle_action = menu.addAction(toggle_text)
        delete_action = menu.addAction(t("context.delete_task"))

        action = menu.exec(self._schedule_table.mapToGlobal(pos))

        if action == toggle_action:
            automation_service.enable_job(job["id"], not job.get("enabled", True))
            self._refresh_schedules()
        elif action == delete_action:
            automation_service.remove_job(job["id"])
            self._refresh_schedules()
