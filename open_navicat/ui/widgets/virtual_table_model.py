"""Virtual table model — lazy-loading QAbstractTableModel for large datasets."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from open_navicat.models.query_result import ColumnMeta


class VirtualTableModel(QAbstractTableModel):
    """Model that loads rows in pages, keeping only the visible page in memory.

    Use with QTableView for virtual scrolling.
    """

    def __init__(self, columns: list[ColumnMeta], page_size: int = 500) -> None:
        super().__init__()
        self._columns = columns
        self._page_size = page_size
        self._rows: list[list[Any]] = []

    # ── QAbstractTableModel interface ──

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            val = self._rows[index.row()][index.column()]
            return str(val) if val is not None else ""
        if role == Qt.ItemDataRole.ToolTipRole:
            val = self._rows[index.row()][index.column()]
            return str(val) if val is not None else ""
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> str | None:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section].name
        return str(section + 1)

    # ── Data loading ──

    def load_page(self, rows: list[list[Any]]) -> None:
        """Replace all data (for paginated loading)."""
        self.beginResetModel()
        self._rows = [list(r) for r in rows]
        self.endResetModel()

    def append_rows(self, rows: list[list[Any]]) -> None:
        """Append rows incrementally (for fetchMore)."""
        if not rows:
            return
        start = self.rowCount()
        self.beginInsertRows(QModelIndex(), start, start + len(rows) - 1)
        self._rows.extend(list(r) for r in rows)
        self.endInsertRows()
