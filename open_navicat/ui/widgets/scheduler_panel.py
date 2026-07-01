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
        title = QLabel("定时任务管理", self)
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #ccc;")
        header.addWidget(title)
        header.addStretch()

        self._btn_add = QPushButton("+ 新建任务", self)
        self._btn_add.setStyleSheet(
            "background: #0078d4; color: #fff; border: none; border-radius: 3px; "
            "padding: 5px 14px; font-size: 11px;")
        self._btn_add.clicked.connect(self._add_job)
        header.addWidget(self._btn_add)

        self._btn_start = QPushButton("▶ 启动调度器", self)
        self._btn_start.setStyleSheet(
            "background: #0e639c; color: #fff; border: none; border-radius: 3px; "
            "padding: 5px 14px; font-size: 11px;")
        self._btn_start.clicked.connect(self._start_scheduler)
        header.addWidget(self._btn_start)

        self._btn_stop = QPushButton("⏹ 停止调度器", self)
        self._btn_stop.setStyleSheet(
            "background: #3c3c3c; color: #ccc; border: 1px solid #555; border-radius: 3px; "
            "padding: 5px 14px; font-size: 11px;")
        self._btn_stop.clicked.connect(self._stop_scheduler)
        header.addWidget(self._btn_stop)

        layout.addLayout(header)

        # ── Status ──
        self._status = QLabel("就绪", self)
        self._status.setStyleSheet("color: #888; font-size: 11px; padding: 2px 0;")
        layout.addWidget(self._status)

        # ── Jobs table ──
        self._table = QTableWidget(self)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setStyleSheet(
            "QTableWidget { background: #1e1e1e; color: #ccc; border: 1px solid #3c3c3c; gridline-color: #333; }"
            "QHeaderView::section { background: #2d2d30; color: #ccc; padding: 4px; border: 1px solid #3c3c3c; }")
        self._table.setAlternatingRowColors(True)
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["状态", "任务名称", "类型", "连接", "Cron", "上次执行", "操作"])
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
            type_map = {"backup": "备份", "sync": "同步", "query": "查询"}
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
            btn_toggle.setToolTip("启用" if not enabled else "禁用")
            btn_toggle.clicked.connect(lambda _, jid=job["id"], en=enabled: self._toggle_job(jid, en))
            actions_layout.addWidget(btn_toggle)

            btn_run = QPushButton("▶", actions_frame)
            btn_run.setFixedSize(28, 22)
            btn_run.setStyleSheet(btn_toggle.styleSheet())
            btn_run.setToolTip("立即执行")
            btn_run.clicked.connect(lambda _, j=job: self._run_now(j))
            actions_layout.addWidget(btn_run)

            btn_delete = QPushButton("🗑", actions_frame)
            btn_delete.setFixedSize(28, 22)
            btn_delete.setStyleSheet(btn_toggle.styleSheet())
            btn_delete.setToolTip("删除")
            btn_delete.clicked.connect(lambda _, jid=job["id"]: self._delete_job(jid))
            actions_layout.addWidget(btn_delete)

            actions_layout.addStretch()
            self._table.setCellWidget(i, 6, actions_frame)

        self._status.setText(f"共 {len(jobs)} 个定时任务")

    # ── Actions ───────────────────────────────────────────────────

    def _toggle_job(self, job_id: str, currently_enabled: bool) -> None:
        automation_service.enable_job(job_id, not currently_enabled)
        self._refresh()

    def _delete_job(self, job_id: str) -> None:
        reply = QMessageBox.question(
            self, "确认删除", "确定删除此定时任务？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            automation_service.remove_job(job_id)
            self._refresh()

    def _run_now(self, job: dict) -> None:
        self._status.setText(f"正在执行: {job.get('name', '')}...")
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
            self._status.setText(f"✅ {job.get('name', '')} 执行完成")
        except Exception as e:
            self._status.setText(f"❌ {job.get('name', '')} 执行失败: {e}")
        self._refresh()

    def _start_scheduler(self) -> None:
        automation_service.start()
        self._status.setText("✅ 调度器已启动")

    def _stop_scheduler(self) -> None:
        automation_service.stop()
        self._status.setText("⏹ 调度器已停止")

    # ── Add job dialog ────────────────────────────────────────────

    @Slot()
    def _add_job(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("新建定时任务")
        dlg.resize(420, 340)
        layout = QFormLayout(dlg)

        name_edit = QLineEdit(dlg)
        name_edit.setPlaceholderText("每日备份 prod")
        layout.addRow("任务名称:", name_edit)

        type_combo = QComboBox(dlg)
        type_combo.addItems(["备份", "同步", "查询"])
        layout.addRow("任务类型:", type_combo)

        conn_combo = QComboBox(dlg)
        saved = connection_manager.list_saved()
        conn_id_map = {s.name: s.id for s in saved}
        conn_combo.addItems([s.name for s in saved])
        layout.addRow("连接:", conn_combo)

        db_combo = QComboBox(dlg)
        db_combo.setStyleSheet(conn_combo.styleSheet())
        layout.addRow("数据库:", db_combo)

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
        cron_edit.setPlaceholderText("分 时 日 月 周 (如 0 2 * * *)")
        layout.addRow("Cron 表达式:", cron_edit)

        compress_check = QCheckBox("压缩备份", dlg)
        compress_check.setChecked(True)
        layout.addRow(compress_check)

        enabled_check = QCheckBox("立即启用", dlg)
        enabled_check.setChecked(True)
        layout.addRow(enabled_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        name = name_edit.text().strip() or "未命名任务"
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
