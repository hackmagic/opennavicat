"""Scheduler Panel — manage scheduled automation jobs (backup, sync, query)."""
from __future__ import annotations

import logging

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from open_navicat.i18n import t
from open_navicat.services.automation_service import automation_service
from open_navicat.services.connection_manager import connection_manager
from open_navicat.services.metadata_service import metadata_service

_log = logging.getLogger(__name__)


class SchedulerPanel(QWidget):
    """Panel for viewing and managing scheduled automation jobs."""

    def __init__(self, connection_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._setup_ui()
        self._refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Header ──
        header = QHBoxLayout()
        title = QLabel(t("scheduler.title"), self)
        title.setStyleSheet("font-size: 14px; font-weight: bold;")
        header.addWidget(title)
        header.addStretch()

        self._btn_add = QPushButton(t("scheduler.btn.new_task"), self)
        self._btn_add.setObjectName("primaryBtn")
        self._btn_add.clicked.connect(self._add_job)
        header.addWidget(self._btn_add)

        self._btn_start = QPushButton(t("scheduler.btn.start"), self)
        self._btn_start.setObjectName("primaryBtn")
        self._btn_start.clicked.connect(self._start_scheduler)
        header.addWidget(self._btn_start)

        self._btn_stop = QPushButton(t("scheduler.btn.stop"), self)
        self._btn_stop.clicked.connect(self._stop_scheduler)
        header.addWidget(self._btn_stop)

        layout.addLayout(header)

        # ── Status ──
        self._status = QLabel(t("status.ready"), self)
        layout.addWidget(self._status)

        # ── Jobs table ──
        self._table = QTableWidget(self)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            [t("scheduler.column.status"), t("scheduler.column.task_name"), t("scheduler.column.type"), t("scheduler.column.connection"), t("scheduler.column.cron"), t("scheduler.column.last_run"), t("scheduler.column.operation")])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

    # ── Refresh ───────────────────────────────────────────────────

    def _refresh(self) -> None:
        jobs = automation_service.list_jobs()
        conn_names = {s.id: s.name for s in connection_manager.list_saved()}

        self._table.setRowCount(len(jobs))
        for i, job in enumerate(jobs):
            # Status indicator
            enabled = job.get("enabled", False)
            last_status = job.get("last_status", "")
            if last_status.startswith("failed"):
                status_item = QTableWidgetItem("❌")
                status_item.setToolTip(last_status)
            elif enabled:
                status_item = QTableWidgetItem("✅")
            else:
                status_item = QTableWidgetItem("⏸")
            self._table.setItem(i, 0, status_item)

            # Name
            self._table.setItem(i, 1, QTableWidgetItem(job.get("name", "")))

            # Type
            type_map = {"backup": t("scheduler.type.backup"), "sync": t("scheduler.type.sync"), "query": t("scheduler.type.query")}
            type_text = type_map.get(job.get("job_type", ""), job.get("job_type", ""))
            self._table.setItem(i, 2, QTableWidgetItem(type_text))

            # Connection
            conn_id = job.get("connection_id", "")
            conn_name = conn_names.get(conn_id, conn_id[:8] if conn_id else "—")
            self._table.setItem(i, 3, QTableWidgetItem(conn_name))

            # Cron
            self._table.setItem(i, 4, QTableWidgetItem(job.get("cron_expr", "")))

            # Last status
            self._table.setItem(i, 5, QTableWidgetItem(last_status or "—"))

            # Actions
            actions_frame = QWidget(self._table)
            actions_layout = QHBoxLayout(actions_frame)
            actions_layout.setContentsMargins(2, 2, 2, 2)
            actions_layout.setSpacing(4)

            btn_toggle = QPushButton("⏸" if enabled else "▶", actions_frame)
            btn_toggle.setFixedSize(28, 22)
            btn_toggle.setStyleSheet(
                "border: 1px solid #3c3c3c; border-radius: 2px; font-size: 10px; background: #2d2d30; color: #ccc;")
            btn_toggle.setToolTip(t("context.enable") if not enabled else t("context.disable"))
            btn_toggle.clicked.connect(lambda _, jid=job["id"], en=enabled: self._toggle_job(jid, en))
            actions_layout.addWidget(btn_toggle)

            btn_run = QPushButton("▶", actions_frame)
            btn_run.setFixedSize(28, 22)
            btn_run.setStyleSheet(btn_toggle.styleSheet())
            btn_run.setToolTip(t("scheduler.btn.run_now"))
            btn_run.clicked.connect(lambda _, j=job: self._run_now(j))
            actions_layout.addWidget(btn_run)

            btn_delete = QPushButton("🗑", actions_frame)
            btn_delete.setFixedSize(28, 22)
            btn_delete.setStyleSheet(btn_toggle.styleSheet())
            btn_delete.setToolTip(t("common.delete"))
            btn_delete.clicked.connect(lambda _, jid=job["id"]: self._delete_job(jid))
            actions_layout.addWidget(btn_delete)

            actions_layout.addStretch()
            self._table.setCellWidget(i, 6, actions_frame)

        self._status.setText(t("scheduler.status.total", count=len(jobs)))

    # ── Actions ───────────────────────────────────────────────────

    def _toggle_job(self, job_id: str, currently_enabled: bool) -> None:
        automation_service.enable_job(job_id, not currently_enabled)
        self._refresh()

    def _delete_job(self, job_id: str) -> None:
        reply = QMessageBox.question(
            self, t("common.confirm"), t("scheduler.msg.confirm_delete"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            automation_service.remove_job(job_id)
            self._refresh()

    def _run_now(self, job: dict) -> None:
        self._status.setText(t("scheduler.msg.executing", name=job.get('name', '')))
        try:
            job_type = job.get("job_type", "backup")
            if job_type == "backup":
                automation_service._run_backup_job(job)
            elif job_type == "query":
                automation_service._run_query_job(job)
            elif job_type == "sync":
                automation_service._run_sync_job(job)
            else:
                automation_service._run_backup_job(job)
            self._status.setText(t("scheduler.msg.completed", name=job.get('name', '')))
        except Exception as e:
            self._status.setText(t("scheduler.msg.failed", name=job.get('name', ''), error=e))
        self._refresh()

    def _start_scheduler(self) -> None:
        automation_service.start()
        self._status.setText(t("scheduler.msg.started"))

    def _stop_scheduler(self) -> None:
        automation_service.stop()
        self._status.setText(t("scheduler.msg.stopped"))

    # ── Add job dialog ────────────────────────────────────────────

    @Slot()
    def _add_job(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(t("scheduler.dialog.new_task"))
        dlg.resize(420, 340)
        layout = QFormLayout(dlg)

        name_edit = QLineEdit(dlg)
        name_edit.setPlaceholderText(t("scheduler.placeholder.task_name"))
        layout.addRow(t("scheduler.label.task_name"), name_edit)

        type_combo = QComboBox(dlg)
        type_combo.addItems([t("scheduler.type.backup"), t("scheduler.type.sync"), t("scheduler.type.query")])
        layout.addRow(t("scheduler.label.task_type"), type_combo)

        conn_combo = QComboBox(dlg)
        saved = connection_manager.list_saved()
        conn_id_map = {s.name: s.id for s in saved}
        conn_combo.addItems([s.name for s in saved])
        layout.addRow(t("scheduler.label.connection"), conn_combo)

        db_combo = QComboBox(dlg)
        db_combo.setStyleSheet(conn_combo.styleSheet())
        layout.addRow(t("scheduler.label.database"), db_combo)

        def load_databases():
            db_combo.clear()
            conn_name = conn_combo.currentText()
            cid = conn_id_map.get(conn_name, "")
            if cid:
                try:
                    dbs = metadata_service.list_databases(cid)
                    db_combo.addItems([d.name for d in dbs])
                except Exception as e:
                    _log.warning("Failed to load databases: %s", e)
        conn_combo.currentIndexChanged.connect(load_databases)
        if saved:
            load_databases()

        cron_edit = QLineEdit(dlg)
        cron_edit.setText("0 2 * * *")
        cron_edit.setPlaceholderText(t("scheduler.placeholder.cron"))
        layout.addRow(t("scheduler.label.cron"), cron_edit)

        compress_check = QCheckBox(t("scheduler.checkbox.gzip"), dlg)
        compress_check.setChecked(True)
        layout.addRow(compress_check)

        enabled_check = QCheckBox(t("scheduler.checkbox.enabled"), dlg)
        enabled_check.setChecked(True)
        layout.addRow(enabled_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        name = name_edit.text().strip() or t("scheduler.default_task_name")
        conn_name = conn_combo.currentText()
        conn_id = conn_id_map.get(conn_name, "")
        database = db_combo.currentText()
        cron = cron_edit.text().strip() or "0 2 * * *"
        compress = compress_check.isChecked()
        enabled = enabled_check.isChecked()

        automation_service.add_backup_job(
            name=name,
            connection_id=conn_id,
            database=database,
            cron_expr=cron,
            compress=compress,
            enabled=enabled,
        )
        self._refresh()
