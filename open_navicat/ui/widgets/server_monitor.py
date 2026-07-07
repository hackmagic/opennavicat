"""Server Monitor — show server status, processes, and variables."""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.connection_pool import _loop as pool_loop
from open_navicat.dal.connection_pool import connection_pool
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
        h_layout.addWidget(QLabel(t("tab.server_monitor")))
        h_layout.addStretch()
        self._auto_btn = QPushButton(t("server_monitor.auto_refresh.off"))
        self._auto_btn.setCheckable(True)
        self._auto_btn.toggled.connect(self._toggle_auto_refresh)
        h_layout.addWidget(self._auto_btn)
        btn_refresh = QPushButton(t("server_monitor.btn.refresh"))
        btn_refresh.clicked.connect(self._refresh)
        h_layout.addWidget(btn_refresh)
        layout.addWidget(header)

        # Tabs
        tabs = QTabWidget()

        # Status tab
        self._status_table = QTableWidget()
        self._status_table.setColumnCount(2)
        self._status_table.setHorizontalHeaderLabels([t("server_monitor.column.variable"), t("server_monitor.column.value")])
        self._status_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._status_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._status_table.setAlternatingRowColors(True)
        tabs.addTab(self._status_table, t("server_monitor.section.status"))

        # Processes tab
        self._process_table = QTableWidget()
        self._process_table.setColumnCount(7)
        self._process_table.setHorizontalHeaderLabels([t("server_monitor.column.id"), t("server_monitor.column.user"), t("server_monitor.column.host"), t("server_monitor.column.database"), t("server_monitor.column.command"), t("server_monitor.column.time"), t("server_monitor.column.sql")])
        self._process_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self._process_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._process_table.setAlternatingRowColors(True)
        tabs.addTab(self._process_table, t("server_monitor.section.processes"))

        # Variables tab
        self._vars_table = QTableWidget()
        self._vars_table.setColumnCount(2)
        self._vars_table.setHorizontalHeaderLabels([t("server_monitor.column.variable"), t("server_monitor.column.value")])
        self._vars_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._vars_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._vars_table.setAlternatingRowColors(True)
        tabs.addTab(self._vars_table, t("server_monitor.section.variables"))

        layout.addWidget(tabs)

        # Auto refresh timer
        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)

    def _refresh(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        info = getattr(connector, "_info", None)
        engine = getattr(info, "engine", "mysql") if info else "mysql"
        try:
            if engine == "postgresql":
                self._refresh_postgresql(connector)
            else:
                self._refresh_mysql(connector)
        except Exception as e:
            _log.warning("Server monitor refresh failed: %s", e)

    def _refresh_mysql(self, connector) -> None:
        result = pool_loop.run_until_complete(connector.execute("SHOW STATUS"))
        if result.rows:
            self._status_table.setRowCount(len(result.rows))
            for i, row in enumerate(result.rows):
                self._status_table.setItem(i, 0, QTableWidgetItem(str(row[0]) if row[0] else ""))
                self._status_table.setItem(i, 1, QTableWidgetItem(str(row[1]) if len(row) > 1 and row[1] is not None else ""))

        result = pool_loop.run_until_complete(connector.execute("SHOW PROCESSLIST"))
        if result.rows:
            self._process_table.setRowCount(len(result.rows))
            for i, row in enumerate(result.rows):
                for j in range(min(7, len(row))):
                    val = str(row[j]) if row[j] is not None else ""
                    self._process_table.setItem(i, j, QTableWidgetItem(val))

        result = pool_loop.run_until_complete(connector.execute("SHOW VARIABLES"))
        if result.rows:
            self._vars_table.setRowCount(len(result.rows))
            for i, row in enumerate(result.rows):
                self._vars_table.setItem(i, 0, QTableWidgetItem(str(row[0]) if row[0] else ""))
                self._vars_table.setItem(i, 1, QTableWidgetItem(str(row[1]) if len(row) > 1 and row[1] is not None else ""))

    def _refresh_postgresql(self, connector) -> None:
        # pg_stat_activity for processes
        result = pool_loop.run_until_complete(connector.execute(
            "SELECT pid, usename, client_addr, datname, state, "
            "NOW() - query_start AS duration, query "
            "FROM pg_stat_activity WHERE state IS NOT NULL ORDER BY pid"
        ))
        if result.rows:
            self._process_table.setRowCount(len(result.rows))
            for i, row in enumerate(result.rows):
                for j in range(min(7, len(row))):
                    val = str(row[j]) if row[j] is not None else ""
                    self._process_table.setItem(i, j, QTableWidgetItem(val))

        # pg_stat_database for status
        result = pool_loop.run_until_complete(connector.execute(
            "SELECT datname, numbackends, xact_commit, xact_rollback, "
            "blks_read, blks_hit, tup_returned, tup_fetched "
            "FROM pg_stat_database WHERE datname NOT LIKE 'template%'"
        ))
        if result.rows:
            self._status_table.setRowCount(len(result.rows))
            for i, row in enumerate(result.rows):
                self._status_table.setItem(i, 0, QTableWidgetItem(str(row[0]) if row[0] else ""))
                self._status_table.setItem(i, 1, QTableWidgetItem(
                    " | ".join(f"{k}={v}" for k, v in zip(
                        ["backends", "commits", "rollbacks", "reads", "hits", "returned", "fetched"],
                        row[1:]
                    ) if v is not None)
                ))

        # pg_settings for variables
        result = pool_loop.run_until_complete(connector.execute(
            "SELECT name, setting FROM pg_settings ORDER BY name"
        ))
        if result.rows:
            self._vars_table.setRowCount(len(result.rows))
            for i, row in enumerate(result.rows):
                self._vars_table.setItem(i, 0, QTableWidgetItem(str(row[0]) if row[0] else ""))
                self._vars_table.setItem(i, 1, QTableWidgetItem(str(row[1]) if row[1] is not None else ""))

    def _toggle_auto_refresh(self, checked: bool) -> None:
        self._auto_refresh = checked
        if checked:
            self._auto_btn.setText(t("server_monitor.auto_refresh.on"))
            self._timer.start(5000)
        else:
            self._auto_btn.setText(t("server_monitor.auto_refresh.off"))
            self._timer.stop()
