"""Object Designer — visual database object editor.

Supports:
- Table Designer: columns, indexes, foreign keys, table options
- View Designer: visual JOIN builder with SQL preview
- Routine Designer: stored procedure / function editor with syntax highlighting
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from open_navicat.i18n import t
from open_navicat.models.table_schema import (
    ColumnInfo,
    ForeignKeyInfo,
    IndexInfo,
    TableInfo,
)

# ── Data Types ────────────────────────────────────────────────────────────

SQL_TYPES = [
    "INT", "BIGINT", "SMALLINT", "TINYINT", "MEDIUMINT",
    "VARCHAR", "CHAR", "TEXT", "TINYTEXT", "MEDIUMTEXT", "LONGTEXT",
    "DECIMAL", "FLOAT", "DOUBLE",
    "DATE", "DATETIME", "TIMESTAMP", "TIME", "YEAR",
    "BLOB", "TINYBLOB", "MEDIUMBLOB", "LONGBLOB",
    "BOOLEAN", "BIT", "BINARY", "VARBINARY",
    "ENUM", "SET", "JSON",
    "GEOMETRY", "POINT", "LINESTRING", "POLYGON",
]

ENGINE_OPTIONS = ["InnoDB", "MyISAM", "MEMORY", "CSV", "ARCHIVE"]
CHARSET_OPTIONS = ["utf8mb4", "utf8", "latin1", "ascii", "utf16", "utf32"]
COLLATION_OPTIONS = [
    "utf8mb4_general_ci", "utf8mb4_unicode_ci", "utf8mb4_bin",
    "utf8_general_ci", "utf8_unicode_ci",
    "latin1_swedish_ci", "latin1_general_ci",
]

ON_ACTIONS = ["RESTRICT", "CASCADE", "SET NULL", "NO ACTION"]


# ── Table Designer Tab ────────────────────────────────────────────────────


class _ColumnListTable(QTableWidget):
    """Editable table for managing columns."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(8)
        self.setHorizontalHeaderLabels([
            "#", t("object_designer.col_name"), t("object_designer.col_type"),
            t("object_designer.col_length"), t("object_designer.col_nullable"),
            t("object_designer.col_default"), t("object_designer.col_auto_inc"),
            t("object_designer.col_comment"),
        ])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(0, 30)
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setStyleSheet(
            "QTableWidget { background: #1e1e1e; color: #ccc; border: 1px solid #3c3c3c; }"
            "QHeaderView::section { background: #2d2d30; color: #888; border: 1px solid #3c3c3c; padding: 4px; }"
            "QTableWidget::item { padding: 2px 6px; }"
        )

    def load_columns(self, columns: list[ColumnInfo]) -> None:
        self.setRowCount(len(columns))
        for i, col in enumerate(columns):
            self.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.setItem(i, 1, QTableWidgetItem(col.name))
            self.setItem(i, 2, QTableWidgetItem(col.data_type))
            self.setItem(i, 3, QTableWidgetItem(
                str(col.char_max_length) if col.char_max_length else ""))
            self.setItem(i, 4, QTableWidgetItem("YES" if col.nullable else "NO"))
            self.setItem(i, 5, QTableWidgetItem(
                str(col.default) if col.default is not None else ""))
            self.setItem(i, 6, QTableWidgetItem("AI" if col.is_auto_increment else ""))
            self.setItem(i, 7, QTableWidgetItem(col.comment))

    def get_columns(self) -> list[ColumnInfo]:
        cols: list[ColumnInfo] = []
        for i in range(self.rowCount()):
            name = self.item(i, 1).text().strip() if self.item(i, 1) else ""
            if not name:
                continue
            col = ColumnInfo(
                name=name,
                data_type=self.item(i, 2).text().strip() if self.item(i, 2) else "VARCHAR",
                char_max_length=int(self.item(i, 3).text()) if self.item(i, 3) and self.item(i, 3).text().isdigit() else None,
                nullable=(self.item(i, 4).text() == "YES") if self.item(i, 4) else True,
                default=self.item(i, 5).text().strip() or None if self.item(i, 5) else None,
                is_auto_increment=(self.item(i, 6).text() == "AI") if self.item(i, 6) else False,
                comment=self.item(i, 7).text().strip() if self.item(i, 7) else "",
                is_primary_key=False,
            )
            cols.append(col)
        return cols


class _IndexTable(QTableWidget):
    """Editable table for managing indexes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHorizontalHeaderLabels([t("object_designer.idx_name"), t("object_designer.idx_column"), t("object_designer.idx_unique"), t("object_designer.idx_type")])
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setStyleSheet(
            "QTableWidget { background: #1e1e1e; color: #ccc; border: 1px solid #3c3c3c; }"
            "QHeaderView::section { background: #2d2d30; color: #888; border: 1px solid #3c3c3c; padding: 4px; }"
            "QTableWidget::item { padding: 2px 6px; }"
        )

    def load_indexes(self, indexes: list[IndexInfo]) -> None:
        self.setRowCount(len(indexes))
        for i, idx in enumerate(indexes):
            self.setItem(i, 0, QTableWidgetItem(idx.name))
            self.setItem(i, 1, QTableWidgetItem(", ".join(idx.columns)))
            self.setItem(i, 2, QTableWidgetItem("UNIQUE" if idx.is_unique else ""))
            self.setItem(i, 3, QTableWidgetItem(idx.index_type))

    def get_indexes(self) -> list[IndexInfo]:
        indexes: list[IndexInfo] = []
        for i in range(self.rowCount()):
            name = self.item(i, 0).text().strip() if self.item(i, 0) else ""
            if not name:
                continue
            cols_str = self.item(i, 1).text().strip() if self.item(i, 1) else ""
            indexes.append(IndexInfo(
                name=name,
                columns=[c.strip() for c in cols_str.split(",") if c.strip()],
                is_unique=(self.item(i, 2).text() == "UNIQUE") if self.item(i, 2) else False,
                index_type=self.item(i, 3).text().strip() if self.item(i, 3) else "BTREE",
            ))
        return indexes


class _ForeignKeyTable(QTableWidget):
    """Editable table for managing foreign keys."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels([t("object_designer.fk_name"), t("object_designer.fk_column"), t("object_designer.fk_ref_table"), t("object_designer.fk_ref_column"), "ON DELETE", "ON UPDATE"])
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setStyleSheet(
            "QTableWidget { background: #1e1e1e; color: #ccc; border: 1px solid #3c3c3c; }"
            "QHeaderView::section { background: #2d2d30; color: #888; border: 1px solid #3c3c3c; padding: 4px; }"
            "QTableWidget::item { padding: 2px 6px; }"
        )

    def load_foreign_keys(self, fks: list[ForeignKeyInfo]) -> None:
        self.setRowCount(len(fks))
        for i, fk in enumerate(fks):
            self.setItem(i, 0, QTableWidgetItem(fk.name))
            self.setItem(i, 1, QTableWidgetItem(fk.column))
            self.setItem(i, 2, QTableWidgetItem(fk.ref_table))
            self.setItem(i, 3, QTableWidgetItem(fk.ref_column))
            self.setItem(i, 4, QTableWidgetItem(fk.on_delete))
            self.setItem(i, 5, QTableWidgetItem(fk.on_update))

    def get_foreign_keys(self) -> list[ForeignKeyInfo]:
        fks: list[ForeignKeyInfo] = []
        for i in range(self.rowCount()):
            name = self.item(i, 0).text().strip() if self.item(i, 0) else ""
            if not name:
                continue
            fks.append(ForeignKeyInfo(
                name=name,
                column=self.item(i, 1).text().strip() if self.item(i, 1) else "",
                ref_table=self.item(i, 2).text().strip() if self.item(i, 2) else "",
                ref_column=self.item(i, 3).text().strip() if self.item(i, 3) else "",
                on_delete=self.item(i, 4).text().strip() if self.item(i, 4) else "RESTRICT",
                on_update=self.item(i, 5).text().strip() if self.item(i, 5) else "RESTRICT",
            ))
        return fks


class _TableDesignerTab(QWidget):
    """Tab for designing a table: columns, indexes, foreign keys, options."""

    def __init__(self, table_info: Optional[TableInfo] = None, parent=None) -> None:
        super().__init__(parent)
        self._table_info = table_info or TableInfo(name="", database="")
        self._setup_ui()
        self._load_data()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Table name & DB
        top = QHBoxLayout()
        top.addWidget(QLabel(t("object_designer.table_name"), self))
        self._name_edit = QLineEdit(self._table_info.name, self)
        self._name_edit.setPlaceholderText("table_name")
        top.addWidget(self._name_edit)
        layout.addLayout(top)

        # Tabs for columns, indexes, FKs, options
        tabs = QTabWidget(self)

        # Columns tab
        col_tab = QWidget()
        col_layout = QVBoxLayout(col_tab)
        self._col_table = _ColumnListTable(col_tab)
        col_layout.addWidget(self._col_table, 1)

        col_btns = QHBoxLayout()
        for text, cb in [(t("object_designer.add_row"), self._col_add), (t("object_designer.delete_selected"), self._col_remove), (t("object_designer.move_up"), self._col_up), (t("object_designer.move_down"), self._col_down)]:
            btn = QPushButton(text, col_tab)
            btn.clicked.connect(cb)
            col_btns.addWidget(btn)
        col_btns.addStretch()
        col_layout.addLayout(col_btns)

        tabs.addTab(col_tab, t("object_designer.fields"))

        # Indexes tab
        idx_tab = QWidget()
        idx_layout = QVBoxLayout(idx_tab)
        self._idx_table = _IndexTable(idx_tab)
        idx_layout.addWidget(self._idx_table, 1)
        idx_btns = QHBoxLayout()
        for text, cb in [(t("object_designer.add_index"), self._idx_add), (t("common.delete"), self._idx_remove)]:
            btn = QPushButton(text, idx_tab)
            btn.clicked.connect(cb)
            idx_btns.addWidget(btn)
        idx_btns.addStretch()
        idx_layout.addLayout(idx_btns)
        tabs.addTab(idx_tab, t("object_designer.indexes"))

        # Foreign keys tab
        fk_tab = QWidget()
        fk_layout = QVBoxLayout(fk_tab)
        self._fk_table = _ForeignKeyTable(fk_tab)
        fk_layout.addWidget(self._fk_table, 1)
        fk_btns = QHBoxLayout()
        for text, cb in [(t("object_designer.add_fk"), self._fk_add), (t("common.delete"), self._fk_remove)]:
            btn = QPushButton(text, fk_tab)
            btn.clicked.connect(cb)
            fk_btns.addWidget(btn)
        fk_btns.addStretch()
        fk_layout.addLayout(fk_btns)
        tabs.addTab(fk_tab, t("object_designer.foreign_keys"))

        # Options tab
        opt_tab = QWidget()
        opt_layout = QFormLayout(opt_tab)
        self._engine_combo = QComboBox(opt_tab)
        self._engine_combo.addItems(ENGINE_OPTIONS)
        self._engine_combo.setCurrentText(self._table_info.engine or "InnoDB")
        opt_layout.addRow(t("object_designer.engine"), self._engine_combo)

        self._charset_combo = QComboBox(opt_tab)
        self._charset_combo.addItems(CHARSET_OPTIONS)
        self._charset_combo.setCurrentText(self._table_info.charset or "utf8mb4")
        opt_layout.addRow(t("object_designer.charset"), self._charset_combo)

        self._collation_combo = QComboBox(opt_tab)
        self._collation_combo.addItems(COLLATION_OPTIONS)
        self._collation_combo.setCurrentText(self._table_info.collation or "utf8mb4_general_ci")
        opt_layout.addRow(t("object_designer.collation"), self._collation_combo)

        self._comment_edit = QLineEdit(self._table_info.comment, opt_tab)
        opt_layout.addRow(t("object_designer.comment"), self._comment_edit)

        tabs.addTab(opt_tab, t("object_designer.options"))

        layout.addWidget(tabs, 1)

        # DDL Preview
        preview_group = QGroupBox(t("object_designer.ddl_preview"), self)
        p_layout = QVBoxLayout(preview_group)
        self._ddl_preview = QTextEdit(preview_group)
        self._ddl_preview.setReadOnly(True)
        self._ddl_preview.setStyleSheet(
            "background: #1e1e1e; color: #dcdcaa; font-family: Consolas; font-size: 12px; border: none;"
        )
        self._ddl_preview.setMaximumHeight(100)
        p_layout.addWidget(self._ddl_preview)
        layout.addWidget(preview_group)

        # Connect signals for live DDL preview
        self._name_edit.textChanged.connect(self._update_preview)
        self._col_table.itemChanged.connect(self._update_preview)

    def _load_data(self) -> None:
        if self._table_info.columns:
            self._col_table.load_columns(self._table_info.columns)
        if self._table_info.indexes:
            self._idx_table.load_indexes(self._table_info.indexes)
        if self._table_info.foreign_keys:
            self._fk_table.load_foreign_keys(self._table_info.foreign_keys)
        self._update_preview()

    def _col_add(self) -> None:
        row = self._col_table.rowCount()
        self._col_table.insertRow(row)
        self._col_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self._col_table.setItem(row, 1, QTableWidgetItem("new_field"))
        self._col_table.setItem(row, 2, QTableWidgetItem("VARCHAR"))
        self._col_table.setItem(row, 4, QTableWidgetItem("YES"))
        self._update_preview()

    def _col_remove(self) -> None:
        row = self._col_table.currentRow()
        if row >= 0:
            self._col_table.removeRow(row)
            self._update_preview()

    def _col_up(self) -> None:
        row = self._col_table.currentRow()
        if row > 0:
            for col in range(self._col_table.columnCount()):
                item = self._col_table.takeItem(row, col)
                self._col_table.setItem(row, col, self._col_table.takeItem(row - 1, col))
                self._col_table.setItem(row - 1, col, item)
            self._col_table.setCurrentCell(row - 1, 0)
            self._update_preview()

    def _col_down(self) -> None:
        row = self._col_table.currentRow()
        if 0 <= row < self._col_table.rowCount() - 1:
            for col in range(self._col_table.columnCount()):
                item = self._col_table.takeItem(row, col)
                self._col_table.setItem(row, col, self._col_table.takeItem(row + 1, col))
                self._col_table.setItem(row + 1, col, item)
            self._col_table.setCurrentCell(row + 1, 0)
            self._update_preview()

    def _idx_add(self) -> None:
        row = self._idx_table.rowCount()
        self._idx_table.insertRow(row)
        self._idx_table.setItem(row, 0, QTableWidgetItem("idx_" + self._name_edit.text().strip()))
        self._idx_table.setItem(row, 1, QTableWidgetItem(""))
        self._idx_table.setItem(row, 3, QTableWidgetItem("BTREE"))
        self._update_preview()

    def _idx_remove(self) -> None:
        row = self._idx_table.currentRow()
        if row >= 0:
            self._idx_table.removeRow(row)

    def _fk_add(self) -> None:
        row = self._fk_table.rowCount()
        self._fk_table.insertRow(row)
        self._fk_table.setItem(row, 0, QTableWidgetItem("fk_" + self._name_edit.text().strip()))
        self._fk_table.setItem(row, 4, QTableWidgetItem("RESTRICT"))
        self._fk_table.setItem(row, 5, QTableWidgetItem("RESTRICT"))

    def _fk_remove(self) -> None:
        row = self._fk_table.currentRow()
        if row >= 0:
            self._fk_table.removeRow(row)

    def _update_preview(self) -> None:
        from open_navicat.utils.sql_formatter import beautify
        from open_navicat.utils.sql_generator import generate_create_table
        info = self.get_table_info()
        if info and info.columns:
            ddl = generate_create_table(info)
            self._ddl_preview.setPlainText(beautify(ddl))
        else:
            self._ddl_preview.setPlainText("-- 添加字段后自动生成 DDL --")

    def get_table_info(self) -> TableInfo:
        return TableInfo(
            name=self._name_edit.text().strip() or "new_table",
            database=self._table_info.database,
            engine=self._engine_combo.currentText() if hasattr(self, '_engine_combo') else "InnoDB",
            charset=self._charset_combo.currentText() if hasattr(self, '_charset_combo') else "utf8mb4",
            collation=self._collation_combo.currentText() if hasattr(self, '_collation_combo') else "utf8mb4_general_ci",
            comment=self._comment_edit.text().strip() if hasattr(self, '_comment_edit') else "",
            columns=self._col_table.get_columns(),
            indexes=self._idx_table.get_indexes() if hasattr(self, '_idx_table') else [],
            foreign_keys=self._fk_table.get_foreign_keys() if hasattr(self, '_fk_table') else [],
        )


class _ViewDesignerTab(QWidget):
    """Tab for building views with visual table/column selection."""

    def __init__(self, connection_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # View name
        top = QHBoxLayout()
        top.addWidget(QLabel(t("object_designer.view_name"), self))
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("view_name")
        self._name_edit.setStyleSheet(
            "background: #1e1e1e; color: #ccc; border: 1px solid #3c3c3c; padding: 4px 8px;")
        top.addWidget(self._name_edit, 1)
        layout.addLayout(top)

        # Database selector + load button
        db_row = QHBoxLayout()
        db_row.addWidget(QLabel(t("object_designer.database"), self))
        self._db_combo = QComboBox(self)
        self._db_combo.setStyleSheet(
            "background: #1e1e1e; color: #ccc; border: 1px solid #3c3c3c; padding: 4px 8px;")
        db_row.addWidget(self._db_combo, 1)
        self._btn_load = QPushButton(t("object_designer.load_tables"), self)
        self._btn_load.setStyleSheet(
            "background: #0078d4; color: #fff; border: none; border-radius: 3px; "
            "padding: 4px 12px; font-size: 11px;")
        self._btn_load.clicked.connect(self._load_tables)
        db_row.addWidget(self._btn_load)
        layout.addLayout(db_row)

        # Split: left = table tree, right = conditions + preview
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left: table/column tree
        self._tree = QTreeWidget(splitter)
        self._tree.setHeaderLabel(t("object_designer.table_columns"))
        self._tree.itemChanged.connect(self._update_preview)

        # Right: WHERE, JOIN, preview
        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(4)

        right_layout.addWidget(QLabel(t("object_designer.where_clause"), right))
        self._where_edit = QTextEdit(right)
        self._where_edit.setPlaceholderText("t1.status = 'active'")
        self._where_edit.setMaximumHeight(60)
        self._where_edit.textChanged.connect(self._update_preview)
        right_layout.addWidget(self._where_edit)

        right_layout.addWidget(QLabel(t("object_designer.join_clause"), right))
        self._join_edit = QTextEdit(right)
        self._join_edit.setPlaceholderText(
            "LEFT JOIN table2 t2 ON t1.id = t2.ref_id\n"
            "INNER JOIN table3 t3 ON t1.code = t3.code")
        self._join_edit.setMaximumHeight(60)
        self._join_edit.textChanged.connect(self._update_preview)
        right_layout.addWidget(self._join_edit)

        right_layout.addWidget(QLabel(t("object_designer.sql_preview"), right))
        self._preview = QTextEdit(right)
        self._preview.setReadOnly(True)
        self._preview.setObjectName("monospaceText")
        right_layout.addWidget(self._preview, 1)

        # Preview data button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_preview = QPushButton(t("object_designer.preview_data"), right)
        self._btn_preview.setObjectName("primaryBtn")
        self._btn_preview.clicked.connect(self._preview_data)
        btn_row.addWidget(self._btn_preview)
        right_layout.addLayout(btn_row)

        splitter.addWidget(self._tree)
        splitter.addWidget(right)
        splitter.setSizes([280, 400])
        layout.addWidget(splitter, 1)

    def set_connection_id(self, connection_id: str) -> None:
        self._connection_id = connection_id

    def load_databases(self) -> None:
        """Populate the database combo from the connection."""
        if not self._connection_id:
            return
        from open_navicat.services.metadata_service import metadata_service
        dbs = metadata_service.list_databases(self._connection_id)
        self._db_combo.clear()
        for db in dbs:
            self._db_combo.addItem(db.name, db.name)
        if dbs:
            self._load_tables()

    def _load_tables(self) -> None:
        """Fetch tables and columns, populate the tree with checkable items."""
        db = self._db_combo.currentData()
        if not db or not self._connection_id:
            return
        from open_navicat.services.metadata_service import metadata_service
        tables = metadata_service.list_tables(self._connection_id, db)
        self._tree.clear()
        self._tree.blockSignals(True)
        for tbl in tables:
            info = metadata_service.get_table_info(self._connection_id, db, tbl)
            if not info:
                continue
            table_item = QTreeWidgetItem([tbl])
            table_item.setFlags(table_item.flags() | Qt.ItemFlag.ItemIsAutoTristate)
            table_item.setCheckState(0, Qt.CheckState.Unchecked)
            for col in info.columns:
                col_item = QTreeWidgetItem([col.name])
                col_item.setFlags(col_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                col_item.setCheckState(0, Qt.CheckState.Unchecked)
                col_item.setData(0, Qt.ItemDataRole.UserRole, col.data_type)
                table_item.addChild(col_item)
            self._tree.addTopLevelItem(table_item)
        self._tree.blockSignals(False)
        self._update_preview()

    def _update_preview(self) -> None:
        sql = self._build_sql()
        if sql:
            from open_navicat.utils.sql_formatter import beautify
            self._preview.setPlainText(beautify(sql))
        else:
            self._preview.setPlainText("-- 勾选列后自动生成 SELECT --")

    def _build_sql(self) -> str:
        """Build SELECT statement from checked items."""
        selected: list[tuple[str, str, str]] = []  # (table, column, type)
        tables: set[str] = set()
        for i in range(self._tree.topLevelItemCount()):
            table_item = self._tree.topLevelItem(i)
            if table_item.checkState(0) == Qt.CheckState.Unchecked:
                continue
            tbl = table_item.text(0)
            tables.add(tbl)
            for j in range(table_item.childCount()):
                col_item = table_item.child(j)
                if col_item.checkState(0) == Qt.CheckState.Checked:
                    selected.append((tbl, col_item.text(0),
                                     col_item.data(0, Qt.ItemDataRole.UserRole) or ""))

        if not selected:
            return ""

        tables_list = sorted(tables)
        aliases = {t: f"t{i+1}" for i, t in enumerate(tables_list)}

        # SELECT clause
        col_parts = []
        for tbl, col, _ in selected:
            alias = aliases[tbl]
            col_parts.append(f"{alias}.`{col}`")
        select_clause = "SELECT\n  " + ",\n  ".join(col_parts)

        # FROM clause
        from_parts = [f"`{tables_list[0]}` {aliases[tables_list[0]]}"]
        from_clause = "FROM " + "\n  ".join(from_parts)

        # JOIN clause
        join_text = self._join_edit.toPlainText().strip()
        join_clause = ("\n" + join_text) if join_text else ""

        # WHERE clause
        where_text = self._where_edit.toPlainText().strip()
        where_clause = ("\nWHERE " + where_text) if where_text else ""

        return f"{select_clause}\n{from_clause}{join_clause}{where_clause}"

    def get_view_name(self) -> str:
        return self._name_edit.text().strip()

    def get_create_view_sql(self) -> str:
        name = self.get_view_name()
        body = self._build_sql()
        if not name or not body:
            return ""
        return f"CREATE VIEW `{name}` AS\n{body}"

    def get_select_sql(self) -> str:
        return self._build_sql()

    def _preview_data(self) -> None:
        """Execute current SELECT and show results in a popup."""
        sql = self._build_sql()
        if not sql:
            QMessageBox.information(self, t("common.notice"), t("object_designer.select_columns_first"))
            return
        if not self._connection_id:
            QMessageBox.warning(self, t("common.error"), t("object_designer.not_connected"))
            return

        db = self._db_combo.currentData()
        if not db:
            QMessageBox.warning(self, t("common.error"), t("object_designer.select_database"))
            return

        from open_navicat.dal.connection_pool import _loop as pool_loop
        from open_navicat.dal.connection_pool import connection_pool
        connector = connection_pool.get(self._connection_id)
        if not connector:
            QMessageBox.warning(self, t("common.error"), t("object_designer.connection_lost"))
            return

        # Use database context — prefix tables if not qualified
        qualified_sql = sql
        try:
            result = pool_loop.run_until_complete(
                connector.execute(qualified_sql, database=db)
            )
        except Exception as e:
            QMessageBox.warning(self, t("object_designer.query_failed"), str(e))
            return

        if not result.success:
            QMessageBox.warning(self, t("object_designer.query_failed"), result.error_message or t("object_designer.unknown_error"))
            return

        # Show results in a resizable dialog
        dlg = QDialog(self)
        dlg.setWindowTitle(t("object_designer.preview_title", db=db))
        dlg.resize(700, 400)
        layout = QVBoxLayout(dlg)

        table = QTableWidget(dlg)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        bg = "#1e1e1e"
        fg = "#ccc"
        sel = "#264f78"
        table.setStyleSheet(
            f"QTableWidget {{ background: {bg}; color: {fg}; border: 1px solid #3c3c3c; gridline-color: #333; }}"
            f"QHeaderView::section {{ background: #2d2d2d; color: #ccc; padding: 4px; border: 1px solid #3c3c3c; }}"
            f"QTableWidget::item:selected {{ background: {sel}; }}"
        )

        if result.columns:
            table.setColumnCount(len(result.columns))
            table.setHorizontalHeaderLabels(result.columns)
        if result.rows:
            table.setRowCount(len(result.rows))
            for r, row in enumerate(result.rows):
                for c, val in enumerate(row):
                    item = QTableWidgetItem(str(val) if val is not None else "NULL")
                    item.setForeground(QColor("#6a9955") if val is None else QColor(fg))
                    table.setItem(r, c, item)
        else:
            table.setRowCount(0)

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        table.resizeColumnsToContents()

        layout.addWidget(table, 1)

        info_label = QLabel(t("object_designer.row_count", count=len(result.rows)), dlg)
        info_label.setStyleSheet("color: #888; padding: 2px 0;")
        layout.addWidget(info_label)

        btn_close = QPushButton(t("common.close"), dlg)
        btn_close.setStyleSheet(
            "background: #3c3c3c; color: #ccc; border: 1px solid #555; "
            "border-radius: 3px; padding: 4px 16px;")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignRight)

        dlg.exec()


class _SQLHighlighter(QSyntaxHighlighter):
    """Basic SQL syntax highlighter for the routine editor."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rules: list[tuple[str, QTextCharFormat]] = []

        kw_format = QTextCharFormat()
        kw_format.setForeground(QColor("#569cd6"))
        kw_format.setFontWeight(QFont.Weight.Bold)
        keywords = [
            "SELECT", "FROM", "WHERE", "INSERT", "UPDATE", "DELETE", "CREATE",
            "ALTER", "DROP", "TABLE", "INDEX", "VIEW", "INTO", "VALUES", "SET",
            "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AND", "OR", "NOT",
            "IN", "LIKE", "BETWEEN", "IS", "NULL", "AS", "ORDER", "BY", "GROUP",
            "HAVING", "LIMIT", "OFFSET", "DISTINCT", "COUNT", "SUM", "AVG",
            "MAX", "MIN", "EXISTS", "UNION", "ALL", "CASE", "WHEN", "THEN",
            "ELSE", "END", "BEGIN", "COMMIT", "ROLLBACK", "DECLARE", "CURSOR",
            "PROCEDURE", "FUNCTION", "RETURNS", "LANGUAGE", "SQL", "DETERMINISTIC",
            "READS", "MODIFIES", "DATA", "IF", "THEN", "ELSEIF", "END IF",
            "LOOP", "END LOOP", "WHILE", "DO", "REPEAT", "UNTIL", "LEAVE",
            "ITERATE", "SIGNAL", "RESIGNAL", "CONDITION", "HANDLER",
            "INTO", "USING", "OUT", "INOUT",
        ]
        for kw in keywords:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor("#569cd6"))
            self._rules.append((f"\\b{kw}\\b", fmt))

        str_format = QTextCharFormat()
        str_format.setForeground(QColor("#ce9178"))
        self._rules.append(("'[^']*'", str_format))

        num_format = QTextCharFormat()
        num_format.setForeground(QColor("#b5cea8"))
        self._rules.append(("\\b\\d+\\b", num_format))

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#6a9955"))
        self._rules.append(("--[^\n]*", comment_format))
        self._rules.append(("/\\*.*?\\*/", comment_format))

    def highlightBlock(self, text: str) -> None:
        import re
        for pattern, fmt in self._rules:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class _RoutineDesignerTab(QWidget):
    """Tab for editing stored procedures and functions."""

    ROUTINE_TYPES = ["PROCEDURE", "FUNCTION"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Routine name + type
        top = QHBoxLayout()

        top.addWidget(QLabel(t("object_designer.type"), self))
        self._type_combo = QComboBox(self)
        self._type_combo.addItems(self.ROUTINE_TYPES)
        top.addWidget(self._type_combo)

        top.addWidget(QLabel(t("object_designer.name"), self))
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("routine_name")
        top.addWidget(self._name_edit, 1)

        layout.addLayout(top)

        # Parameters
        layout.addWidget(QLabel(t("object_designer.parameters"), self))
        self._params_edit = QTextEdit(self)
        self._params_edit.setPlaceholderText(
            "IN p_user_id INT\n"
            "OUT p_count INT"
        )
        self._params_edit.setMaximumHeight(80)
        self._params_edit.setStyleSheet(
            "background: #1e1e1e; color: #ccc; font-family: Consolas; font-size: 11px; "
            "border: 1px solid #3c3c3c; padding: 4px;"
        )
        layout.addWidget(self._params_edit)

        # Body
        layout.addWidget(QLabel(t("object_designer.body"), self))
        self._body_edit = QTextEdit(self)
        self._body_edit.setPlaceholderText(
            "BEGIN\n"
            "  SELECT COUNT(*) INTO p_count\n"
            "  FROM users\n"
            "  WHERE id = p_user_id;\n"
            "END"
        )
        self._body_edit.setStyleSheet(
            "background: #1e1e1e; color: #dcdcaa; font-family: Consolas; font-size: 12px; "
            "border: 1px solid #3c3c3c; padding: 8px;"
        )
        # Apply syntax highlighter
        self._highlighter = _SQLHighlighter(self._body_edit.document())
        layout.addWidget(self._body_edit, 1)

        # DDL preview
        preview_group = QGroupBox(t("object_designer.ddl_preview"), self)
        p_layout = QVBoxLayout(preview_group)
        self._ddl_preview = QTextEdit(preview_group)
        self._ddl_preview.setReadOnly(True)
        self._ddl_preview.setObjectName("monospaceText")
        self._ddl_preview.setMaximumHeight(120)
        p_layout.addWidget(self._ddl_preview)
        layout.addWidget(preview_group)

        # Connect
        self._name_edit.textChanged.connect(self._update_preview)
        self._type_combo.currentTextChanged.connect(self._update_preview)
        self._params_edit.textChanged.connect(self._update_preview)
        self._body_edit.textChanged.connect(self._update_preview)

    def _update_preview(self) -> None:
        from open_navicat.utils.sql_formatter import beautify
        ddl = self.get_ddl()
        if ddl:
            self._ddl_preview.setPlainText(beautify(ddl))
        else:
            self._ddl_preview.setPlainText("-- 编辑程序体后自动生成 DDL --")

    def get_ddl(self) -> str:
        name = self._name_edit.text().strip()
        rtype = self._type_combo.currentText()
        params = self._params_edit.toPlainText().strip()
        body = self._body_edit.toPlainText().strip()

        if not name or not body:
            return ""

        param_str = f"({params.replace(chr(10), ', ')})" if params else "()"
        return (
            f"CREATE {rtype} `{name}`{param_str}\n"
            f"{body}\n"
        )


class _EventDesignerTab(QWidget):
    """Tab for editing MySQL events."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(t("object_designer.name"), self))
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("event_name")
        top.addWidget(self._name_edit, 1)
        top.addWidget(QLabel(t("object_designer.status"), self))
        self._status_combo = QComboBox(self)
        self._status_combo.addItems(["ENABLE", "DISABLE"])
        top.addWidget(self._status_combo)
        layout.addLayout(top)

        mid = QHBoxLayout()
        mid.addWidget(QLabel(t("object_designer.schedule"), self))
        self._schedule_edit = QLineEdit(self)
        self._schedule_edit.setPlaceholderText("EVERY 1 DAY STARTS '2026-01-01 02:00:00'")
        mid.addWidget(self._schedule_edit, 1)
        layout.addLayout(mid)

        layout.addWidget(QLabel(t("object_designer.do_body"), self))
        self._body_edit = QTextEdit(self)
        self._body_edit.setPlaceholderText("BEGIN\n  DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY;\nEND")
        self._body_edit.setStyleSheet("background:#1e1e1e;color:#dcdcaa;font-family:Consolas;font-size:12px;border:1px solid #3c3c3c;padding:8px;")
        layout.addWidget(self._body_edit, 1)
        layout.addWidget(QLabel(t("object_designer.comment"), self))
        self._comment_edit = QLineEdit(self)
        layout.addWidget(self._comment_edit)

        preview_group = QGroupBox(t("object_designer.ddl_preview"), self)
        p_layout = QVBoxLayout(preview_group)
        self._ddl_preview = QTextEdit(preview_group)
        self._ddl_preview.setReadOnly(True)
        self._ddl_preview.setObjectName("monospaceText")
        self._ddl_preview.setMaximumHeight(100)
        p_layout.addWidget(self._ddl_preview)
        layout.addWidget(preview_group)

        self._name_edit.textChanged.connect(self._update_preview)
        self._status_combo.currentTextChanged.connect(self._update_preview)
        self._schedule_edit.textChanged.connect(self._update_preview)
        self._body_edit.textChanged.connect(self._update_preview)
        self._comment_edit.textChanged.connect(self._update_preview)

    def _update_preview(self) -> None:
        ddl = self.get_ddl()
        self._ddl_preview.setPlainText(ddl or "-- 编辑后自动生成 DDL --")

    def get_ddl(self) -> str:
        name = self._name_edit.text().strip()
        schedule = self._schedule_edit.text().strip()
        body = self._body_edit.toPlainText().strip()
        if not name or not schedule or not body:
            return ""
        status = self._status_combo.currentText()
        ddl = f"CREATE EVENT `{name}`\nON SCHEDULE {schedule}\n"
        if status == "DISABLE":
            ddl += "ON COMPLETION PRESERVE\nDISABLE\n"
        comment = self._comment_edit.text().strip()
        if comment:
            ddl += f"COMMENT '{comment}'\n"
        ddl += f"DO\n{body}"
        return ddl


class _TriggerDesignerTab(QWidget):
    """Tab for editing MySQL triggers."""

    TRIGGER_TIMING = ["BEFORE", "AFTER"]
    TRIGGER_EVENTS = ["INSERT", "UPDATE", "DELETE"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(t("object_designer.name"), self))
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("trigger_name")
        top.addWidget(self._name_edit, 1)
        top.addWidget(QLabel(t("object_designer.timing"), self))
        self._timing_combo = QComboBox(self)
        self._timing_combo.addItems(self.TRIGGER_TIMING)
        top.addWidget(self._timing_combo)
        top.addWidget(QLabel(t("object_designer.event"), self))
        self._event_combo = QComboBox(self)
        self._event_combo.addItems(self.TRIGGER_EVENTS)
        top.addWidget(self._event_combo)
        top.addWidget(QLabel(t("object_designer.table"), self))
        self._table_edit = QLineEdit(self)
        self._table_edit.setPlaceholderText("table_name")
        top.addWidget(self._table_edit)
        layout.addLayout(top)

        layout.addWidget(QLabel(t("object_designer.body"), self))
        self._body_edit = QTextEdit(self)
        self._body_edit.setPlaceholderText("BEGIN\n  INSERT INTO audit_log(table_name, action) VALUES ('table_name', 'INSERT');\nEND")
        self._body_edit.setStyleSheet("background:#1e1e1e;color:#dcdcaa;font-family:Consolas;font-size:12px;border:1px solid #3c3c3c;padding:8px;")
        layout.addWidget(self._body_edit, 1)

        preview_group = QGroupBox(t("object_designer.ddl_preview"), self)
        p_layout = QVBoxLayout(preview_group)
        self._ddl_preview = QTextEdit(preview_group)
        self._ddl_preview.setReadOnly(True)
        self._ddl_preview.setObjectName("monospaceText")
        self._ddl_preview.setMaximumHeight(100)
        p_layout.addWidget(self._ddl_preview)
        layout.addWidget(preview_group)

        self._name_edit.textChanged.connect(self._update_preview)
        self._timing_combo.currentTextChanged.connect(self._update_preview)
        self._event_combo.currentTextChanged.connect(self._update_preview)
        self._table_edit.textChanged.connect(self._update_preview)
        self._body_edit.textChanged.connect(self._update_preview)

    def _update_preview(self) -> None:
        ddl = self.get_ddl()
        self._ddl_preview.setPlainText(ddl or "-- 编辑后自动生成 DDL --")

    def get_ddl(self) -> str:
        name = self._name_edit.text().strip()
        timing = self._timing_combo.currentText()
        event = self._event_combo.currentText()
        table = self._table_edit.text().strip()
        body = self._body_edit.toPlainText().strip()
        if not name or not table or not body:
            return ""
        return f"CREATE TRIGGER `{name}` {timing} {event} ON `{table}`\nFOR EACH ROW\n{body}"


# ── Main Object Designer Widget ──────────────────────────────────────────


class ObjectDesignerWidget(QWidget):
    """Main widget with tabs for Table/View/Routine design."""

    def __init__(self, connection_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ──
        toolbar = QWidget(self)
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(8, 4, 8, 4)

        self._obj_type_combo = QComboBox(toolbar)
        self._obj_type_combo.addItems([
            t("object_designer.tab_table"), t("object_designer.tab_view"),
            t("object_designer.tab_routine"), t("object_designer.tab_event"),
            t("object_designer.tab_trigger"),
        ])
        self._obj_type_combo.currentIndexChanged.connect(self._switch_tab)
        t_layout.addWidget(self._obj_type_combo)

        t_layout.addStretch()

        for text, cb in [
            (t("object_designer.generate_ddl"), self._generate_ddl),
        ]:
            btn = QPushButton(text, toolbar)
            btn.setObjectName("primaryBtn")
            btn.clicked.connect(cb)
            t_layout.addWidget(btn)

        layout.addWidget(toolbar)

        # ── Content area ──
        self._tab_widget = QTabWidget(self)
        self._tab_widget.setStyleSheet(
            "QTabWidget::pane { border: none; background: #252526; }"
            "QTabBar::tab { background: #2d2d30; color: #888; padding: 4px 10px; border: 1px solid #3c3c3c; }"
            "QTabBar::tab:selected { background: #1e1e1e; color: #ccc; }"
        )

        self._table_tab = _TableDesignerTab(parent=self)
        self._view_tab = _ViewDesignerTab(connection_id=self._connection_id, parent=self)
        self._routine_tab = _RoutineDesignerTab(parent=self)
        self._event_tab = _EventDesignerTab(parent=self)
        self._trigger_tab = _TriggerDesignerTab(parent=self)

        self._tab_widget.addTab(self._table_tab, t("object_designer.table_design"))
        self._tab_widget.addTab(self._view_tab, t("object_designer.view_design"))
        self._tab_widget.addTab(self._routine_tab, t("object_designer.routine_design"))
        self._tab_widget.addTab(self._event_tab, t("object_designer.event_design"))
        self._tab_widget.addTab(self._trigger_tab, t("object_designer.trigger_design"))

        layout.addWidget(self._tab_widget, 1)

        # Load databases for the view tab when it becomes visible
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

    def _on_tab_changed(self, index: int) -> None:
        if index == 1 and self._connection_id:
            self._view_tab.load_databases()

    def _switch_tab(self, index: int) -> None:
        self._tab_widget.setCurrentIndex(index)

    def load_table(self, table_info: TableInfo) -> None:
        """Load an existing table for editing."""
        self._table_tab = _TableDesignerTab(table_info, parent=self)
        self._tab_widget.removeTab(0)
        self._tab_widget.insertTab(0, self._table_tab, t("object_designer.table_design"))
        self._tab_widget.setCurrentIndex(0)

    def _generate_ddl(self) -> None:
        """Generate DDL for the current object type."""
        from open_navicat.utils.sql_formatter import beautify

        idx = self._tab_widget.currentIndex()
        ddl = ""

        if idx == 0:
            info = self._table_tab.get_table_info()
            if info.columns:
                from open_navicat.utils.sql_generator import generate_create_table
                ddl = generate_create_table(info)
        elif idx == 1:
            ddl = self._view_tab.get_create_view_sql()
        elif idx == 2:
            ddl = self._routine_tab.get_ddl()
        elif idx == 3:
            ddl = self._event_tab.get_ddl()
        elif idx == 4:
            ddl = self._trigger_tab.get_ddl()

        if not ddl:
            QMessageBox.information(self, t("common.notice"), t("object_designer.fill_required"))
            return

        # Show in a dialog with execute button
        dlg = QDialog(self)
        dlg.setWindowTitle(t("object_designer.ddl_preview"))
        dlg.resize(650, 400)
        dlg_layout = QVBoxLayout(dlg)
        editor = QTextEdit(dlg)
        editor.setReadOnly(True)
        editor.setStyleSheet(
            "background: #1e1e1e; color: #dcdcaa; font-family: Consolas; "
            "font-size: 12px; border: 1px solid #3c3c3c; padding: 8px;"
        )
        editor.setPlainText(beautify(ddl))
        dlg_layout.addWidget(editor, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dlg)
        buttons.rejected.connect(dlg.reject)
        # Add Execute button
        if self._connection_id:
            btn_exec = buttons.addButton(t("object_designer.execute_sql"), QDialogButtonBox.ButtonRole.ActionRole)
            btn_exec.clicked.connect(lambda: self._execute_ddl(ddl, dlg))
        dlg_layout.addWidget(buttons)
        dlg.exec()

    def _execute_ddl(self, ddl: str, dialog: QDialog) -> None:
        """Execute DDL against the connected database."""
        from open_navicat.dal.connection_pool import _loop as pool_loop
        from open_navicat.dal.connection_pool import connection_pool
        connector = connection_pool.get(self._connection_id)
        if not connector:
            QMessageBox.warning(self, t("object_designer.execute_failed"), t("object_designer.connection_lost"))
            return
        try:
            result = pool_loop.run_until_complete(connector.execute(ddl))
            if result.success:
                QMessageBox.information(self, t("object_designer.execute_success"), t("object_designer.ddl_executed"))
                dialog.accept()
            else:
                QMessageBox.warning(self, t("object_designer.execute_failed"), result.error_message or t("object_designer.sql_error"))
        except Exception as e:
            QMessageBox.warning(self, t("object_designer.execute_failed"), str(e))


# ── Convenience ───────────────────────────────────────────────────────────

__all__ = [
    "ObjectDesignerWidget",
    "_TableDesignerTab",
    "_ViewDesignerTab",
    "_RoutineDesignerTab",
    "_EventDesignerTab",
    "_TriggerDesignerTab",
    "SQL_TYPES",
]
