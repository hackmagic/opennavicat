"""Server Monitor — show MySQL server status, processes, and variables."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
    QAbstractItemView, QComboBox,
)

from open_navicat.dal.connection_pool import connection_pool, _loop as pool_loop
from open_navicat.i18n import t

_log = logging.getLogger(__name__)


class ServerMonitorWidget(QWidget):
    """Displays MySQL server status information."""

    def __init__(self, connection_id: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._auto_refresh = False
        self._setup_ui()
        self._refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.addWidget(QLabel("🖥️ 服务器监控"))
        h_layout.addStretch()
        self._auto_btn = QPushButton("🔄 自动刷新: 关")
        self._auto_btn.setCheckable(True)
        self._auto_btn.toggled.connect(self._toggle_auto_refresh)
        h_layout.addWidget(self._auto_btn)
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self._refresh)
        h_layout.addWidget(btn_refresh)
        layout.addWidget(header)

        # Tabs
        tabs = QTabWidget()

        # Status tab
        self._status_table = QTableWidget()
        self._status_table.setColumnCount(2)
        self._status_table.setHorizontalHeaderLabels(["变量", "值"])
        self._status_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._status_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._status_table.setAlternatingRowColors(True)
        tabs.addTab(self._status_table, "📊 服务器状态")

        # Processes tab
        self._process_table = QTableWidget()
        self._process_table.setColumnCount(7)
        self._process_table.setHorizontalHeaderLabels(["ID", "用户", "主机", "数据库", "命令", "时间", "SQL"])
        self._process_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self._process_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._process_table.setAlternatingRowColors(True)
        tabs.addTab(self._process_table, "⚙️ 进程列表")

        # Variables tab
        self._vars_table = QTableWidget()
        self._vars_table.setColumnCount(2)
        self._vars_table.setHorizontalHeaderLabels(["变量名", "值"])
        self._vars_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._vars_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._vars_table.setAlternatingRowColors(True)
        tabs.addTab(self._vars_table, "🔧 系统变量")

        layout.addWidget(tabs)

        # Auto refresh timer
        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)

    def _refresh(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            # Status
            result = pool_loop.run_until_complete(connector.execute("SHOW STATUS"))
            if result.rows:
                self._status_table.setRowCount(len(result.rows))
                for i, row in enumerate(result.rows):
                    self._status_table.setItem(i, 0, QTableWidgetItem(str(row[0]) if row[0] else ""))
                    self._status_table.setItem(i, 1, QTableWidgetItem(str(row[1]) if len(row) > 1 and row[1] is not None else ""))

            # Processes
            result = pool_loop.run_until_complete(connector.execute("SHOW PROCESSLIST"))
            if result.rows:
                self._process_table.setRowCount(len(result.rows))
                for i, row in enumerate(result.rows):
                    for j in range(min(7, len(row))):
                        val = str(row[j]) if row[j] is not None else ""
                        self._process_table.setItem(i, j, QTableWidgetItem(val))

            # Variables
            result = pool_loop.run_until_complete(connector.execute("SHOW VARIABLES"))
            if result.rows:
                self._vars_table.setRowCount(len(result.rows))
                for i, row in enumerate(result.rows):
                    self._vars_table.setItem(i, 0, QTableWidgetItem(str(row[0]) if row[0] else ""))
                    self._vars_table.setItem(i, 1, QTableWidgetItem(str(row[1]) if len(row) > 1 and row[1] is not None else ""))

        except Exception as e:
            _log.warning("Server monitor refresh failed: %s", e)

    def _toggle_auto_refresh(self, checked: bool) -> None:
        self._auto_refresh = checked
        if checked:
            self._auto_btn.setText("🔄 自动刷新: 开")
            self._timer.start(5000)
        else:
            self._auto_btn.setText("🔄 自动刷新: 关")
            self._timer.stop()
