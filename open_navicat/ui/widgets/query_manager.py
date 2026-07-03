"""Query Manager — list, create, rename, delete saved queries per database."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from open_navicat.dal.local_config import local_db
from open_navicat.i18n import t


class QueryManagerWidget(QWidget):
    """Panel showing all saved queries for a connection+database with management actions."""

    def __init__(self, connection_id: str, database: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        self._setup_ui()
        self._load_queries()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QWidget(self)
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(8, 4, 8, 4)

        title = QLabel(t("query_manager.title", database=self._database), toolbar)
        t_layout.addWidget(title)
        t_layout.addStretch()

        self._search_input = QLineEdit(toolbar)
        self._search_input.setPlaceholderText(t("query_manager.search_placeholder"))
        self._search_input.setMinimumWidth(200)
        self._search_input.textChanged.connect(self._filter_queries)
        t_layout.addWidget(self._search_input)

        btn_new = QPushButton(t("query_manager.new_query"), toolbar)
        btn_new.setObjectName("primaryBtn")
        btn_new.clicked.connect(self._new_query)
        t_layout.addWidget(btn_new)

        btn_design = QPushButton(t("query_manager.design_query"), toolbar)
        btn_design.clicked.connect(self._design_query)
        t_layout.addWidget(btn_design)

        btn_del = QPushButton(t("common.delete"), toolbar)
        btn_del.setObjectName("dangerBtn")
        btn_del.clicked.connect(self._delete_selected)
        t_layout.addWidget(btn_del)

        layout.addWidget(toolbar)

        # Table
        self._table = QTableWidget(self)
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels([t("query_manager.column.name"), t("query_manager.column.modified"), t("query_manager.column.size"), ""])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.doubleClicked.connect(self._open_selected)
        layout.addWidget(self._table)

        # Status
        self._status = QLabel("", self)
        layout.addWidget(self._status)

    def _load_queries(self, filter_text: str = "") -> None:
        queries = local_db.list_queries(self._connection_id, self._database)
        if filter_text:
            queries = [q for q in queries if filter_text.lower() in q["name"].lower()]

        self._table.setRowCount(len(queries))
        self._queries = queries
        for i, q in enumerate(queries):
            name_item = QTableWidgetItem(q["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, q["id"])
            self._table.setItem(i, 0, name_item)

            date_str = q.get("updated_at", "") or q.get("created_at", "")
            self._table.setItem(i, 1, QTableWidgetItem(date_str[:19] if date_str else ""))

            size = len(q.get("sql_text", ""))
            size_str = f"{size} B" if size < 1024 else f"{size//1024} KB"
            self._table.setItem(i, 2, QTableWidgetItem(size_str))

        self._status.setText(t("query_manager.status.total", count=len(queries)))

    def _filter_queries(self, text: str) -> None:
        self._load_queries(text.strip())

    def _new_query(self) -> None:
        """Open a new SQL editor tab for this connection."""
        mw = self.window()
        if hasattr(mw, 'open_query_tab'):
            mw.open_query_tab(self._connection_id, self._database)

    def _design_query(self) -> None:
        """Open SQL editor with SELECT template for visual query design."""
        mw = self.window()
        if hasattr(mw, 'open_query_tab'):
            template = t("query_manager.new_query_template")
            mw.open_query_tab(self._connection_id, self._database, template)

    def _open_selected(self) -> None:
        """Double-click: open query in SQL editor."""
        row = self._table.currentRow()
        if row < 0 or row >= len(self._queries):
            return
        q = self._queries[row]
        mw = self.window()
        if hasattr(mw, 'open_query_tab'):
            mw.open_query_tab(self._connection_id, self._database,
                              q.get("sql_text", ""), query_id=q.get("id", 0))

    def _delete_selected(self) -> None:
        """Delete selected queries after confirmation."""
        rows = set()
        for idx in self._table.selectedIndexes():
            rows.add(idx.row())
        if not rows:
            return
        reply = QMessageBox.question(
            self, t("query_manager.delete_title"), t("query_manager.delete_confirm", count=len(rows)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for row in sorted(rows, reverse=True):
            if row < len(self._queries):
                local_db.delete_query(self._queries[row]["id"])
        self._load_queries(self._search_input.text().strip())
