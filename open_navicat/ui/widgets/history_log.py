"""History Log — display query execution history."""

from __future__ import annotations

import logging

from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QTextEdit, QSplitter, QMessageBox,
)

from open_navicat.dal.local_config import local_db
from open_navicat.i18n import t

_log = logging.getLogger(__name__)


class HistoryLogWidget(QWidget):
    """Shows query execution history with details."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._load_history()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.addWidget(QLabel("📋 历史日志"))
        h_layout.addStretch()
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.clicked.connect(self._load_history)
        h_layout.addWidget(btn_refresh)
        btn_clear = QPushButton("🗑️ 清除全部")
        btn_clear.clicked.connect(self._clear_history)
        h_layout.addWidget(btn_clear)
        layout.addWidget(header)

        # Splitter
        splitter = QSplitter(Qt.Orientation.Vertical)

        # History table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["时间", "连接", "数据库", "SQL预览"])
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.currentCellChanged.connect(self._show_detail)
        splitter.addWidget(self._table)

        # Detail area
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        splitter.addWidget(self._detail)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    def _load_history(self) -> None:
        try:
            rows = local_db.get_all_query_history()
        except Exception as e:
            _log.warning("Failed to load query history: %s", e)
            rows = []
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            # row: (id, connection_id, database, sql, execution_time, created_at)
            self._table.setItem(i, 0, QTableWidgetItem(str(row[5]) if row[5] else ""))
            self._table.setItem(i, 1, QTableWidgetItem(str(row[1])[:16] if row[1] else ""))
            self._table.setItem(i, 2, QTableWidgetItem(str(row[2]) if row[2] else ""))
            sql_preview = str(row[3])[:100] + "..." if row[3] and len(str(row[3])) > 100 else str(row[3]) if row[3] else ""
            self._table.setItem(i, 3, QTableWidgetItem(sql_preview))
        if rows:
            self._table.selectRow(0)

    def _show_detail(self, row: int, col: int, prev_row: int, prev_col: int) -> None:
        if row < 0:
            return
        time_item = self._table.item(row, 0)
        db_item = self._table.item(row, 2)
        preview_item = self._table.item(row, 3)
        if time_item and preview_item:
            self._detail.setPlainText(
                f"时间: {time_item.text()}\n"
                f"数据库: {db_item.text() if db_item else ''}\n\n"
                f"SQL:\n{preview_item.text()}"
            )

    def _clear_history(self) -> None:
        reply = QMessageBox.question(
            self, "确认清除",
            "确定要清除所有历史记录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                local_db.clear_query_history()
                self._load_history()
            except Exception as e:
                _log.warning("Failed to clear query history: %s", e)
