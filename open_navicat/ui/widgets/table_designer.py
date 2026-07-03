"""Table Designer — visual column/index/FK editor with DDL preview."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from open_navicat.i18n import t

if TYPE_CHECKING:
    from open_navicat.models.table_schema import TableInfo

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


class _TypeDelegate(QStyledItemDelegate):
    """Combo box delegate for the '类型' column."""
    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.addItems(SQL_TYPES)
        editor.setEditable(True)
        return editor

    def setEditorData(self, editor, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        editor.setCurrentText(text)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.services.metadata_service import metadata_service
from open_navicat.utils.sql_generator import generate_create_table


class TableDesignerWidget(QWidget):
    """Visual table designer — add/remove/edit columns, indexes, FKs, view DDL."""

    def __init__(self, connection_id: str, database: str, table: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        self._table = table
        self._original_data: list[dict] = []
        self._original_info = None  # Store original table info for ALTER diff
        self._show_full_ddl = False
        self._setup_ui()
        self._load_schema()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget(self)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 6, 12, 6)

        title = QLabel(t("table_designer.title", database=self._database, table=self._table), header)
        h_layout.addWidget(title)
        h_layout.addStretch()

        for text, obj_name in [(t("table_designer.copy_ddl"), ""), (t("table_designer.save"), "primaryBtn")]:
            btn = QPushButton(text, header)
            if obj_name:
                btn.setObjectName(obj_name)
            btn.clicked.connect(self._copy_ddl if text == t("table_designer.copy_ddl") else self._save)
            h_layout.addWidget(btn)

        layout.addWidget(header)

        # Tabs
        self._tabs = QTabWidget(self)
        tabs = self._tabs

        # Column editor
        col_widget = QWidget()
        col_layout = QVBoxLayout(col_widget)
        col_layout.setContentsMargins(8, 8, 8, 0)

        self._col_table = QTableWidget(col_widget)
        self._col_table.setColumnCount(9)
        self._col_table.setHorizontalHeaderLabels(
            [t("table_designer.col_header.index"), t("table_designer.col_header.field_name"), t("table_designer.col_header.type"), t("table_designer.col_header.length"), t("table_designer.col_header.not_null"), t("table_designer.col_header.primary_key"), t("table_designer.col_header.auto_increment"), t("table_designer.col_header.default"), t("table_designer.col_header.comment")]
        )
        self._col_table.horizontalHeader().setStretchLastSection(True)
        self._col_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._col_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._col_table.cellChanged.connect(self._update_preview)
        self._col_table.itemChanged.connect(self._update_preview)
        self._col_table.cellClicked.connect(self._toggle_checkbox)
        self._col_table.setItemDelegateForColumn(2, _TypeDelegate(self._col_table))
        col_layout.addWidget(self._col_table)

        btn_row = QWidget(col_widget)
        br_layout = QHBoxLayout(btn_row)
        br_layout.setContentsMargins(0, 4, 0, 4)
        for text, cb in [
            (t("table_designer.add_field"), self._col_add),
            ("📌 " + t("design_table.insert_field"), self._col_insert),
            (t("table_designer.delete_field"), self._col_remove),
            ("🔑 " + t("design_table.primary_key"), self._col_toggle_pk),
            (t("table_designer.move_up"), self._col_up),
            (t("table_designer.move_down"), self._col_down),
        ]:
            btn = QPushButton(text, btn_row)
            btn.clicked.connect(cb)
            br_layout.addWidget(btn)
        br_layout.addStretch()
        btn_sql_preview = QPushButton("📝 " + t("design_table.sql_preview"), btn_row)
        btn_sql_preview.setObjectName("primaryBtn")
        btn_sql_preview.clicked.connect(self._show_sql_preview)
        br_layout.addWidget(btn_sql_preview)
        col_layout.addWidget(btn_row)

        tabs.addTab(col_widget, t("table_designer.fields"))

        # Indexes tab
        idx_widget = QWidget()
        idx_layout = QVBoxLayout(idx_widget)
        self._idx_table = QTableWidget(idx_widget)
        self._idx_table.setColumnCount(5)
        self._idx_table.setHorizontalHeaderLabels([t("table_designer.idx_header.index_name"), t("table_designer.idx_header.fields"), t("table_designer.idx_header.unique"), t("table_designer.idx_header.primary_key"), t("table_designer.idx_header.type")])
        self._idx_table.horizontalHeader().setStretchLastSection(True)
        self._idx_table.setStyleSheet(
            "QTableWidget { background: #1e1e1e; color: #ccc; border: 1px solid #3c3c3c; }"
            "QTableWidget::item { padding: 4px 8px; }"
            "QHeaderView::section { background: #2d2d30; color: #888; border: 1px solid #3c3c3c; padding: 4px; }"
        )
        idx_layout.addWidget(self._idx_table)
        tabs.addTab(idx_widget, t("table_designer.indexes"))

        # Foreign keys tab
        fk_widget = QWidget()
        fk_layout = QVBoxLayout(fk_widget)
        self._fk_table = QTableWidget(fk_widget)
        self._fk_table.setColumnCount(6)
        self._fk_table.setHorizontalHeaderLabels([t("table_designer.fk_header.constraint_name"), t("table_designer.fk_header.field"), t("table_designer.fk_header.ref_table"), t("table_designer.fk_header.ref_field"), t("table_designer.fk_header.on_delete"), t("table_designer.fk_header.on_update")])
        self._fk_table.horizontalHeader().setStretchLastSection(True)
        fk_layout.addWidget(self._fk_table)
        tabs.addTab(fk_widget, t("table_designer.foreign_keys"))

        # Options tab
        opt_widget = QWidget()
        opt_layout = QHBoxLayout(opt_widget)
        opts = {t("table_designer.opt.engine"): "InnoDB", t("table_designer.opt.charset"): "utf8mb4", t("table_designer.opt.collation"): "utf8mb4_general_ci", "AUTO_INCREMENT": "1"}
        for k, v in opts.items():
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.addWidget(QLabel(k))
            e = QLineEdit(v)
            wl.addWidget(e)
            opt_layout.addWidget(w)
        opt_layout.addStretch()
        tabs.addTab(opt_widget, t("table_designer.options"))

        # Comments tab
        comment_widget = QWidget()
        comment_layout = QVBoxLayout(comment_widget)
        comment_layout.addWidget(QLabel(t("table_designer.table_comment")))
        self._comment_edit = QTextEdit(comment_widget)
        self._comment_edit.setMaximumHeight(80)
        comment_layout.addWidget(self._comment_edit)
        comment_layout.addStretch()
        tabs.addTab(comment_widget, t("table_designer.comments"))

        # Checks tab
        check_widget = QWidget()
        check_layout = QVBoxLayout(check_widget)
        self._check_table = QTableWidget(check_widget)
        self._check_table.setColumnCount(3)
        self._check_table.setHorizontalHeaderLabels([t("table_designer.check_header.constraint_name"), t("table_designer.check_header.expression"), t("table_designer.check_header.description")])
        self._check_table.horizontalHeader().setStretchLastSection(True)
        check_layout.addWidget(self._check_table)
        check_btn_row = QWidget(check_widget)
        check_btn_layout = QHBoxLayout(check_btn_row)
        for text, cb in [(t("table_designer.check_add"), self._check_add), (t("table_designer.check_delete"), self._check_remove)]:
            btn = QPushButton(text, check_btn_row)
            btn.clicked.connect(cb)
            check_btn_layout.addWidget(btn)
        check_btn_layout.addStretch()
        check_layout.addWidget(check_btn_row)
        tabs.addTab(check_widget, t("table_designer.checks"))

        # Triggers tab
        trigger_widget = QWidget()
        trigger_layout = QVBoxLayout(trigger_widget)
        self._trigger_table = QTableWidget(trigger_widget)
        self._trigger_table.setColumnCount(4)
        self._trigger_table.setHorizontalHeaderLabels([t("table_designer.trigger_header.name"), t("table_designer.trigger_header.event"), t("table_designer.trigger_header.timing"), t("table_designer.trigger_header.sql")])
        self._trigger_table.horizontalHeader().setStretchLastSection(True)
        self._trigger_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        trigger_layout.addWidget(self._trigger_table)
        tabs.addTab(trigger_widget, t("table_designer.triggers"))

        # DDL Preview tab
        ddl_widget = QWidget()
        ddl_layout = QVBoxLayout(ddl_widget)

        # DDL mode toggle bar
        ddl_bar = QWidget(ddl_widget)
        ddb_layout = QHBoxLayout(ddl_bar)
        ddb_layout.setContentsMargins(4, 2, 4, 2)
        self._btn_toggle_ddl = QPushButton(t("table_designer.full_ddl"), ddl_bar)
        self._btn_toggle_ddl.setCheckable(True)
        self._btn_toggle_ddl.toggled.connect(self._toggle_ddl_mode)
        ddb_layout.addWidget(self._btn_toggle_ddl)
        ddb_layout.addStretch()
        ddb_layout.addWidget(QLabel(t("table_designer.mode.alter"), ddl_bar))
        ddl_bar._label = ddb_layout.itemAt(ddb_layout.count()-1).widget()
        ddl_layout.addWidget(ddl_bar)

        self._ddl_preview = QTextEdit(ddl_widget)
        self._ddl_preview.setReadOnly(True)
        self._ddl_preview.setObjectName("monospaceText")
        ddl_layout.addWidget(self._ddl_preview)
        tabs.addTab(ddl_widget, t("table_designer.ddl_preview"))

        layout.addWidget(tabs, 1)

    def _load_schema(self) -> None:
        info = metadata_service.get_table_info(self._connection_id, self._database, self._table)
        if not info:
            return
        self._original_info = info  # Store for ALTER diff

        # Columns
        self._col_table.setRowCount(len(info.columns))
        for i, col in enumerate(info.columns):
            self._col_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self._col_table.setItem(i, 1, QTableWidgetItem(col.name))
            self._col_table.setItem(i, 2, QTableWidgetItem(col.data_type))
            self._col_table.setItem(i, 3, QTableWidgetItem(str(col.char_max_length or "")))
            self._col_table.setItem(i, 4, QTableWidgetItem("☑" if not col.nullable else "☐"))
            self._col_table.setItem(i, 5, QTableWidgetItem("☑" if col.is_primary_key else "☐"))
            self._col_table.setItem(i, 6, QTableWidgetItem("☑" if col.is_auto_increment else "☐"))
            self._col_table.setItem(i, 7, QTableWidgetItem(str(col.default or "")))
            self._col_table.setItem(i, 8, QTableWidgetItem(col.comment))

        # Indexes
        self._idx_table.setRowCount(len(info.indexes))
        for i, idx in enumerate(info.indexes):
            self._idx_table.setItem(i, 0, QTableWidgetItem(idx.name))
            self._idx_table.setItem(i, 1, QTableWidgetItem(", ".join(idx.columns)))
            self._idx_table.setItem(i, 2, QTableWidgetItem("☑" if idx.is_unique else "☐"))
            self._idx_table.setItem(i, 3, QTableWidgetItem("☑" if idx.is_primary else "☐"))
            self._idx_table.setItem(i, 4, QTableWidgetItem(idx.index_type))

        # Foreign keys
        self._fk_table.setRowCount(len(info.foreign_keys))
        for i, fk in enumerate(info.foreign_keys):
            self._fk_table.setItem(i, 0, QTableWidgetItem(fk.name))
            self._fk_table.setItem(i, 1, QTableWidgetItem(fk.column))
            self._fk_table.setItem(i, 2, QTableWidgetItem(fk.ref_table))
            self._fk_table.setItem(i, 3, QTableWidgetItem(fk.ref_column))
            self._fk_table.setItem(i, 4, QTableWidgetItem(fk.on_delete))
            self._fk_table.setItem(i, 5, QTableWidgetItem(fk.on_update))

        self._ddl_preview.setPlainText(
            f"CREATE TABLE `{self._table}` (\n  "
            f"{t('table_designer.ddl_summary', fields=len(info.columns), indexes=len(info.indexes), fks=len(info.foreign_keys))}\n);"
        )
        # Generate actual DDL preview
        self._update_preview()

    def _copy_ddl(self) -> None:
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(self._ddl_preview.toPlainText())

    def _update_preview(self) -> None:
        """Live DDL preview - shows ALTER TABLE diff by default, full DDL optional."""
        try:
            from open_navicat.utils.sql_generator import generate_alter_table, generate_create_table
            new_info = self._collect_table_info()
            if not new_info or not new_info.columns:
                self._ddl_preview.setPlainText(t("table_designer.ddl_placeholder"))
                return

            if self._show_full_ddl or not self._original_info:
                ddl = generate_create_table(new_info)
            else:
                ddl = generate_alter_table(self._original_info, new_info) or t("table_designer.no_changes")
            self._ddl_preview.setPlainText(ddl)
        except Exception as e:
            self._ddl_preview.setPlainText(t("table_designer.ddl_generate_failed", error=e))

    def _toggle_ddl_mode(self, checked: bool) -> None:
        """Toggle between ALTER diff (default) and full CREATE TABLE."""
        self._show_full_ddl = checked
        self._btn_toggle_ddl.setText("📋 ALTER DDL" if checked else t("table_designer.full_ddl"))
        # Update status label
        for i in range(self._btn_toggle_ddl.parent().layout().count()):
            w = self._btn_toggle_ddl.parent().layout().itemAt(i).widget()
            if isinstance(w, QLabel):
                w.setText(t("table_designer.mode.full_ddl") if checked else t("table_designer.mode.alter"))
        self._update_preview()

    def _toggle_checkbox(self, row: int, col: int) -> None:
        """Toggle ☑/☐ for checkbox columns (4=非空, 5=主键, 6=自增)."""
        if col in (4, 5, 6):
            item = self._col_table.item(row, col)
            if item and item.text() == "☑":
                item.setText("☐")
            elif item:
                item.setText("☑")

    def _col_add(self) -> None:
        row = self._col_table.rowCount()
        self._col_table.blockSignals(True)
        self._col_table.insertRow(row)
        self._col_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self._col_table.setItem(row, 1, QTableWidgetItem("new_field"))
        self._col_table.setItem(row, 2, QTableWidgetItem("VARCHAR"))
        self._col_table.setItem(row, 3, QTableWidgetItem(""))
        self._col_table.setItem(row, 4, QTableWidgetItem("☐"))  # Nullable = unchecked
        self._col_table.setItem(row, 5, QTableWidgetItem("☐"))  # PK = unchecked
        self._col_table.setItem(row, 6, QTableWidgetItem("☐"))  # AI = unchecked
        self._col_table.setItem(row, 7, QTableWidgetItem(""))
        self._col_table.setItem(row, 8, QTableWidgetItem(""))
        self._col_table.blockSignals(False)
        self._update_preview()

    def _col_remove(self) -> None:
        row = self._col_table.currentRow()
        if row >= 0:
            self._col_table.removeRow(row)
            self._update_preview()

    def _col_up(self) -> None:
        row = self._col_table.currentRow()
        if row > 0:
            for c in range(self._col_table.columnCount()):
                item = self._col_table.takeItem(row, c)
                self._col_table.setItem(row, c, self._col_table.takeItem(row - 1, c))
                self._col_table.setItem(row - 1, c, item)
            self._col_table.setCurrentCell(row - 1, 0)
            self._update_preview()

    def _col_down(self) -> None:
        row = self._col_table.currentRow()
        if 0 <= row < self._col_table.rowCount() - 1:
            for c in range(self._col_table.columnCount()):
                item = self._col_table.takeItem(row, c)
                self._col_table.setItem(row, c, self._col_table.takeItem(row + 1, c))
                self._col_table.setItem(row + 1, c, item)
            self._col_table.setCurrentCell(row + 1, 0)
            self._update_preview()

    def _col_insert(self) -> None:
        row = self._col_table.currentRow()
        if row < 0:
            row = 0
        self._col_table.blockSignals(True)
        self._col_table.insertRow(row)
        self._col_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        self._col_table.setItem(row, 1, QTableWidgetItem("new_field"))
        self._col_table.setItem(row, 2, QTableWidgetItem("VARCHAR"))
        self._col_table.setItem(row, 3, QTableWidgetItem(""))
        self._col_table.setItem(row, 4, QTableWidgetItem("☐"))
        self._col_table.setItem(row, 5, QTableWidgetItem("☐"))
        self._col_table.setItem(row, 6, QTableWidgetItem("☐"))
        self._col_table.setItem(row, 7, QTableWidgetItem(""))
        self._col_table.setItem(row, 8, QTableWidgetItem(""))
        self._col_table.blockSignals(False)
        self._col_table.setCurrentCell(row, 1)
        self._update_preview()

    def _col_toggle_pk(self) -> None:
        row = self._col_table.currentRow()
        if row < 0:
            return
        item = self._col_table.item(row, 5)
        if item:
            item.setText("☑" if item.text() != "☑" else "☐")
            self._update_preview()

    def _check_add(self) -> None:
        row = self._check_table.rowCount()
        self._check_table.insertRow(row)
        self._check_table.setItem(row, 0, QTableWidgetItem(f"chk_{row+1}"))
        self._check_table.setItem(row, 1, QTableWidgetItem(""))
        self._check_table.setItem(row, 2, QTableWidgetItem(""))

    def _check_remove(self) -> None:
        row = self._check_table.currentRow()
        if row >= 0:
            self._check_table.removeRow(row)

    def _show_sql_preview(self) -> None:
        self._update_preview()
        self._tabs.setCurrentIndex(self._tabs.count() - 1)

    def _save(self) -> None:
        """Execute ALTER TABLE to save changes to the database."""
        from open_navicat.dal.connection_pool import _loop as pool_loop
        connector = connection_pool.get(self._connection_id)
        if not connector:
            QMessageBox.warning(self, t("table_designer.save_failed"), t("table_designer.connection_lost"))
            return

        from open_navicat.services.metadata_service import metadata_service
        from open_navicat.utils.sql_generator import generate_alter_table

        old_info = metadata_service.get_table_info(self._connection_id, self._database, self._table)
        new_info = self._collect_table_info()
        new_info.database = self._database

        try:
            if old_info:
                # Generate ALTER TABLE from diff
                sql = generate_alter_table(old_info, new_info)
                if sql:
                    result = pool_loop.run_until_complete(connector.execute(sql))
                    if result.success:
                        QMessageBox.information(self, t("table_designer.save_success"), t("table_designer.table_updated"))
                    else:
                        QMessageBox.warning(self, t("table_designer.save_failed"), result.error_message or t("table_designer.sql_error"))
                else:
                    QMessageBox.information(self, t("table_designer.no_changes"), t("table_designer.no_changes_detail"))
            else:
                # New table - CREATE
                sql = generate_create_table(new_info)
                result = pool_loop.run_until_complete(connector.execute(sql))
                if result.success:
                    QMessageBox.information(self, t("table_designer.save_success"), t("table_designer.table_created", table=self._table))
                else:
                    QMessageBox.warning(self, t("table_designer.save_failed"), result.error_message or t("table_designer.sql_error"))
        except Exception as e:
            QMessageBox.warning(self, t("table_designer.save_failed"), str(e))

    def _collect_table_info(self) -> TableInfo:
        """Collect current table info from the UI fields."""
        from open_navicat.models.table_schema import (
            ColumnInfo,
            TableInfo,
        )
        columns = []
        for i in range(self._col_table.rowCount()):
            name_item = self._col_table.item(i, 1)
            type_item = self._col_table.item(i, 2)
            if not name_item or not type_item:
                continue
            col = ColumnInfo(
                name=name_item.text(),
                data_type=type_item.text(),
                char_max_length=int(self._col_table.item(i, 3).text()) if self._col_table.item(i, 3) and self._col_table.item(i, 3).text().isdigit() else None,
                nullable=(self._col_table.item(i, 4).text() != "☑"),
                default=self._col_table.item(i, 7).text() if self._col_table.item(i, 7) and self._col_table.item(i, 7).text() else None,
                is_primary_key=(self._col_table.item(i, 5).text() == "☑"),
                is_auto_increment=(self._col_table.item(i, 6).text() == "☑"),
                comment=self._col_table.item(i, 8).text() if self._col_table.item(i, 8) else "",
            )
            columns.append(col)
        return TableInfo(
            name=self._table,
            database=self._database,
            columns=columns,
        )
