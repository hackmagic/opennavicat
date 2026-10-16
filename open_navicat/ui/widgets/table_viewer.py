"""Data viewer — grid-style table browser with pagination, sorting, and inline editing."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.connection_pool import _get_loop as _pool_loop_getter

pool_loop = _pool_loop_getter()
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.formats import (
    PANEL_KEY,
    ExportFormat,
    Filter,
    build_filter_clause,
    export_rows,
)
from open_navicat.i18n import t
from open_navicat.models import QueryResult
from open_navicat.sql.quoting import (
    limit_clause,
    quote_identifier,
    quote_literal,
    quote_qualified,
)
from open_navicat.ui.widgets.grid_editor import (
    MAX_PINNED_COLUMNS,
    ChangeKind,
    PendingChange,
    cell_value_from_text,
    copy_as_where,
    merge_cell_edits,
    order_columns,
    plan_changes,
    toggle_pin,
)

_log = logging.getLogger(__name__)


def _fmt_bytes(n: int | float) -> str:
    """Format byte count to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class FilterRow(QWidget):
    """A single filter condition row: [column] [operator] [value] [remove]."""

    OPERATORS = [
        ("=", "="),
        ("!=", "!="),
        (">", ">"),
        ("<", "<"),
        (">=", ">="),
        ("<=", "<="),
        ("LIKE", "LIKE"),
        ("NOT LIKE", "NOT LIKE"),
        ("IN", "IN"),
        ("NOT IN", "NOT IN"),
        ("BETWEEN", "BETWEEN"),
        ("IS NULL", "IS NULL"),
        ("IS NOT NULL", "IS NOT NULL"),
        ("STARTS WITH", "STARTS WITH"),
        ("ENDS WITH", "ENDS WITH"),
        ("CONTAINS", "CONTAINS"),
    ]

    def __init__(self, columns: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns = columns
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._combo_col = QComboBox(self)
        self._combo_col.addItems(columns)
        self._combo_col.setMinimumWidth(120)
        layout.addWidget(self._combo_col)

        self._combo_op = QComboBox(self)
        for label, value in self.OPERATORS:
            self._combo_op.addItem(label, value)
        self._combo_op.setMinimumWidth(100)
        layout.addWidget(self._combo_op)

        self._edit_value = QLineEdit(self)
        self._edit_value.setPlaceholderText(t("filter.value_placeholder"))
        layout.addWidget(self._edit_value, 1)

        self._chk_negate = QCheckBox(t("filter.negate"), self)
        self._chk_negate.setToolTip(t("filter.negate_tooltip"))
        layout.addWidget(self._chk_negate)

        self._btn_remove = QPushButton("✕", self)
        self._btn_remove.setFixedWidth(28)
        self._btn_remove.setToolTip(t("filter.remove_condition"))
        layout.addWidget(self._btn_remove)

        # Hide value for IS NULL / IS NOT NULL
        self._combo_op.currentIndexChanged.connect(self._on_op_changed)

    def _on_op_changed(self, index: int) -> None:
        op_value = self._combo_op.currentData()
        hide_value = op_value in ("IS NULL", "IS NOT NULL")
        self._edit_value.setVisible(not hide_value)
        self._chk_negate.setVisible(
            op_value not in ("IS NULL", "IS NOT NULL", "IN", "NOT IN", "BETWEEN")
        )

    def to_sql(self) -> str | None:
        """Convert this filter row to a SQL WHERE fragment."""
        col = self._combo_col.currentText()
        op = self._combo_op.currentData()
        val = self._edit_value.text().strip()
        negate = self._chk_negate.isChecked()

        if op in ("IS NULL", "IS NOT NULL"):
            clause = f"`{col}` IS {'NOT' if op == 'IS NOT NULL' else ''} NULL"
        elif op == "LIKE" or op == "NOT LIKE":
            if not val:
                return None
            actual_op = "NOT LIKE" if negate else "LIKE"
            clause = f"`{col}` {actual_op} '{val}%'"
        elif op == "STARTS WITH":
            if not val:
                return None
            actual_op = "NOT LIKE" if negate else "LIKE"
            clause = f"`{col}` {actual_op} '{val}%'"
        elif op == "ENDS WITH":
            if not val:
                return None
            actual_op = "NOT LIKE" if negate else "LIKE"
            clause = f"`{col}` {actual_op} '%{val}'"
        elif op == "CONTAINS":
            if not val:
                return None
            actual_op = "NOT LIKE" if negate else "LIKE"
            clause = f"`{col}` {actual_op} '%{val}%'"
        elif op == "IN" or op == "NOT IN":
            if not val:
                return None
            actual_op = "NOT IN" if negate else "IN"
            # Parse comma-separated values
            items = [v.strip().strip("'\"") for v in val.split(",")]
            formatted = ", ".join(f"'{v}'" for v in items)
            clause = f"`{col}` {actual_op} ({formatted})"
        elif op == "BETWEEN":
            parts = [p.strip() for p in val.split(",")]
            if len(parts) != 2:
                return None
            clause = f"`{col}` BETWEEN '{parts[0]}' AND '{parts[1]}'"
        else:
            # =, !=, >, <, >=, <=
            if not val:
                return None
            actual_op = (
                f"NOT {op}" if negate and op == "=" else ("!=" if negate and op == "!=" else op)
            )
            if negate and op == "=":
                clause = f"`{col}` != '{val}'"
            elif negate and op == "!=":
                clause = f"`{col}` = '{val}'"
            else:
                clause = f"`{col}` {op} '{val}'"

        return clause

    def set_columns(self, columns: list[str]) -> None:
        """Update the column combo with new columns."""
        self._columns = columns
        self._combo_col.clear()
        self._combo_col.addItems(columns)


class FilterPanel(QWidget):
    """Collapsible visual filter panel above the data grid."""

    filter_applied = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._columns: list[str] = []
        self._rows: list[FilterRow] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header bar
        header = QHBoxLayout()
        self._toggle_btn = QPushButton("▾ " + t("filter.panel_title"), self)
        self._toggle_btn.setStyleSheet("font-weight: bold; border: none; text-align: left;")
        self._toggle_btn.clicked.connect(self._toggle_visibility)
        header.addWidget(self._toggle_btn)

        # Mode toggle
        self._mode_text = QPushButton(t("filter.text_mode"), self)
        self._mode_text.setCheckable(True)
        self._mode_text.clicked.connect(lambda: self._set_mode("text"))
        header.addWidget(self._mode_text)

        self._mode_builder = QPushButton(t("filter.builder_mode"), self)
        self._mode_builder.setCheckable(True)
        self._mode_builder.setChecked(True)
        self._mode_builder.clicked.connect(lambda: self._set_mode("builder"))
        header.addWidget(self._mode_builder)

        header.addStretch()

        self._btn_add = QPushButton("+ " + t("filter.add_condition"), self)
        self._btn_add.clicked.connect(self._add_row)
        header.addWidget(self._btn_add)

        self._btn_apply = QPushButton(t("filter.apply_filters"), self)
        self._btn_apply.setProperty("class", "primary")
        self._btn_apply.clicked.connect(self._apply_filters)
        header.addWidget(self._btn_apply)

        self._btn_clear = QPushButton(t("filter.clear_all"), self)
        self._btn_clear.clicked.connect(self._clear_all)
        header.addWidget(self._btn_clear)

        layout.addLayout(header)

        # Text mode input
        self._text_input = QLineEdit(self)
        self._text_input.setPlaceholderText(t("filter.text_placeholder"))
        self._text_input.setVisible(False)
        layout.addWidget(self._text_input)

        # Scrollable filter rows (builder mode)
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(2)

        self._scroll = QScrollArea(self)
        self._scroll.setWidget(self._rows_container)
        self._scroll.setWidgetResizable(True)
        self._scroll.setMaximumHeight(200)
        layout.addWidget(self._scroll)

        # Default: collapsed
        self._scroll.setVisible(False)
        self._collapsed = True

        # Active filter display
        self._active_label = QLabel(t("filter.no_filters"), self)
        self._active_label.setStyleSheet("color: #888; font-size: 11px; font-style: italic;")
        layout.addWidget(self._active_label)

    def _toggle_visibility(self) -> None:
        self._collapsed = not self._collapsed
        self._scroll.setVisible(not self._collapsed)
        arrow = "▾" if not self._collapsed else "▸"
        self._toggle_btn.setText(f"{arrow} {t('filter.panel_title')}")

    def set_columns(self, columns: list[str]) -> None:
        """Update all filter rows with new column list."""
        self._columns = columns
        for row in self._rows:
            row.set_columns(columns)

    def _add_row(self) -> None:
        """Insert a row of defaults, then reload.

        The column list is read from the table metadata rather than assumed, so
        a table with NOT NULL columns without defaults still gets a valid
        statement (with explicit NULLs) and works on every engine.
        """
        connector = connection_pool.get(self._connection_id)
        if connector is None:
            return

        engine = self._engine()
        try:
            info = pool_loop.run_until_complete(
                connector.get_table_info(self._database, self._table)
            )
        except Exception as exc:
            self._status_msg.setText(t("table_viewer.add_row_failed", error=exc))
            return

        if not info.columns:
            self._status_msg.setText(t("table_viewer.add_row_failed", error="no columns"))
            return

        columns = [c.name for c in info.columns]
        # Every column gets an explicit value: an empty column list is not valid
        # on most engines, and leaving columns out lets the server apply its own
        # defaults, which is exactly what "add a blank row" means.
        literals = ", ".join(quote_literal(None, engine) for _ in columns)
        col_list = ", ".join(quote_identifier(c, engine) for c in columns)
        sql = f"INSERT INTO {self._table_ref()} ({col_list}) VALUES ({literals})"

        try:
            result = pool_loop.run_until_complete(connector.execute(sql))
            if result.insert_id:
                self._status_msg.setText(t("table_viewer.inserted_row", id=result.insert_id))
            self._current_page = 0
            self._load_page()
        except Exception as exc:
            self._status_msg.setText(t("table_viewer.add_row_failed", error=exc))

    def _remove_row(self, row: FilterRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            self._rows_layout.removeWidget(row)
            row.deleteLater()

    def _clear_all(self) -> None:
        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._active_label.setText(t("filter.no_filters"))
        self.filter_applied.emit()

    def _apply_filters(self) -> None:
        conditions = []
        for row in self._rows:
            sql = row.to_sql()
            if sql:
                conditions.append(sql)

        if conditions:
            self._active_label.setText(
                t(
                    "filter.active_filters",
                    count=len(conditions),
                    conditions=" AND ".join(conditions),
                )
            )
            self._active_label.setStyleSheet("color: #4fc3f7; font-size: 11px;")
        else:
            self._active_label.setText(t("filter.no_filters"))
            self._active_label.setStyleSheet("color: #888; font-size: 11px; font-style: italic;")

        self.filter_applied.emit()

    def _set_mode(self, mode: str) -> None:
        """Switch between text and builder filter modes."""
        if mode == "text":
            self._text_input.setVisible(True)
            self._scroll.setVisible(False)
            self._btn_add.setVisible(False)
            self._mode_text.setChecked(True)
            self._mode_builder.setChecked(False)
        else:
            self._text_input.setVisible(False)
            self._scroll.setVisible(self._collapsed is False)
            self._btn_add.setVisible(True)
            self._mode_text.setChecked(False)
            self._mode_builder.setChecked(True)

    def get_sql_conditions(self) -> list[str]:
        """Return list of SQL WHERE conditions from all rows."""
        if self._mode_text.isChecked():
            text = self._text_input.text().strip()
            return [text] if text else []
        conditions = []
        for row in self._rows:
            sql = row.to_sql()
            if sql:
                conditions.append(sql)
        return conditions

    def has_filters(self) -> bool:
        return bool(self.get_sql_conditions())


class _HeaderCapturingBatches:
    """Wraps the export batch generator and remembers the first header.

    ``_export_batches`` yields ``(columns, rows)``; the export layer only wants
    rows, but the column names are needed for the header.  Capturing them here
    avoids a second query when the table has data.
    """

    def __init__(self, source) -> None:
        self._source = source
        self.header: list[str] = []

    def __iter__(self):
        for columns, rows in self._source:
            if not self.header and columns:
                self.header = [c.name for c in columns]
            yield rows


class TableViewerWidget(QWidget):
    """Displays table data in a spreadsheet-like grid with filtering and pagination."""

    PAGE_SIZES = [100, 200, 500, 1000, 5000]

    def __init__(
        self,
        connection_id: str,
        database: str,
        table: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        self._table = table

        from open_navicat.config import config as _cfg

        self._page_size = (
            _cfg.get("records.limit", 500) if _cfg.get("records.limit_enabled", True) else 500
        )
        self._current_page = 0
        self._total_rows = 0
        self._filters: dict[str, str] = {}
        self._order_by: str | None = None
        self._order_dir: str = "ASC"
        self._loaded_column_names: list[str] = []
        self._loaded_rows: list[list] = []
        self._form_current_row: int = 0

        # ponytail: batch edit stack for undo/redo
        self._edit_stack: list[dict] = []  # {"row": r, "col": c, "old": v, "new": v}
        self._edit_pos: int = -1
        self._dirty: bool = False
        self._original_values: dict[tuple[int, int], str] = {}

        # Primary-key columns, learned from the table's metadata.  Row edits and
        # deletes are addressed by these, not by "whatever is in column 0" as
        # before - on a table whose first column is not the key, that silently
        # wrote to the wrong row.
        self._primary_keys: list[str] = []

        # Columns the user pinned to the leading edge.
        self._pinned_columns: list[str] = []

        self._format_rules: list[dict] = []

        self._setup_ui()
        self._load_page()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # -- Filter Panel (collapsible, above toolbar) --
        self._filter_panel = FilterPanel(self)
        self._filter_panel.filter_applied.connect(self._on_filter_panel_apply)
        layout.addWidget(self._filter_panel)

        # -- Toolbar --
        toolbar = QToolBar(self)

        # Group 1: Profile & Transaction
        self._btn_profile = QPushButton(t("data_viewer.table_profile"), self)
        self._profile_menu = QMenu(self)
        self._btn_profile.setMenu(self._profile_menu)
        self._profile_menu.addAction(t("data_viewer.table_info"), self._show_table_profile)
        self._profile_menu.addSeparator()
        self._act_save_profile = self._profile_menu.addAction(t("data_viewer.save_view_profile"))
        self._act_save_profile.triggered.connect(self._save_view_profile)
        self._act_load_profile = self._profile_menu.addAction(t("data_viewer.load_view_profile"))
        self._act_load_profile.triggered.connect(self._load_view_profile)
        toolbar.addWidget(self._btn_profile)

        toolbar.addSeparator()

        # Group 2: Edit operations
        self._btn_refresh = QPushButton(t("data_viewer.refresh"), self)
        self._btn_refresh.clicked.connect(self._load_page)
        toolbar.addWidget(self._btn_refresh)

        self._btn_add = QPushButton(t("data_viewer.add_row"), self)
        self._btn_add.clicked.connect(self._add_row)
        toolbar.addWidget(self._btn_add)

        self._btn_delete = QPushButton(t("data_viewer.delete"), self)
        self._btn_delete.clicked.connect(self._delete_selected)
        toolbar.addWidget(self._btn_delete)

        self._btn_cell_editor = QPushButton(t("data_viewer.cell_editor"), self)
        self._btn_cell_editor.setCheckable(True)
        self._btn_cell_editor.setChecked(True)
        self._btn_cell_editor.clicked.connect(self._toggle_cell_editor)
        toolbar.addWidget(self._btn_cell_editor)

        # Undo / Redo
        self._btn_undo = QPushButton(t("table_viewer.undo"), self)
        self._btn_undo.clicked.connect(self._undo)
        self._btn_undo.setEnabled(False)
        toolbar.addWidget(self._btn_undo)
        self._btn_redo = QPushButton(t("table_viewer.redo"), self)
        self._btn_redo.clicked.connect(self._redo)
        self._btn_redo.setEnabled(False)
        toolbar.addWidget(self._btn_redo)

        # Review the statements before running them
        self._btn_preview = QPushButton(t("table_viewer.preview_sql"), self)
        self._btn_preview.clicked.connect(self._show_sql_preview)
        toolbar.addWidget(self._btn_preview)

        # Batch Commit / Rollback
        self._btn_batch_commit = QPushButton(t("data_viewer.commit"), self)
        self._btn_batch_commit.setProperty("class", "primary")
        self._btn_batch_commit.clicked.connect(self._commit_batch)
        toolbar.addWidget(self._btn_batch_commit)
        self._btn_batch_rollback = QPushButton(t("data_viewer.rollback"), self)
        self._btn_batch_rollback.clicked.connect(self._rollback_batch)
        toolbar.addWidget(self._btn_batch_rollback)

        toolbar.addSeparator()

        # Transaction control
        self._btn_tx_begin = QPushButton(t("data_viewer.tx_begin"), self)
        self._btn_tx_begin.clicked.connect(self._tx_begin)
        toolbar.addWidget(self._btn_tx_begin)
        self._btn_tx_commit = QPushButton(t("data_viewer.tx_commit"), self)
        self._btn_tx_commit.clicked.connect(self._tx_commit)
        toolbar.addWidget(self._btn_tx_commit)
        self._btn_tx_rollback = QPushButton(t("data_viewer.tx_rollback"), self)
        self._btn_tx_rollback.clicked.connect(self._tx_rollback)
        toolbar.addWidget(self._btn_tx_rollback)

        toolbar.addSeparator()

        # View mode toggle
        self._btn_form_view = QPushButton(t("table_viewer.form_view"), self)
        self._btn_form_view.setCheckable(True)
        self._btn_form_view.clicked.connect(self._toggle_view_mode)
        toolbar.addWidget(self._btn_form_view)

        toolbar.addSeparator()

        # Group 3: Filter, Sort, Columns
        toolbar.addWidget(QLabel(t("data_viewer.filter") + ":", self))
        self._filter_input = QLineEdit(self)
        self._filter_input.setPlaceholderText(t("table_viewer.filter_placeholder"))
        self._filter_input.setMinimumWidth(260)
        self._filter_input.returnPressed.connect(self._apply_filter)
        toolbar.addWidget(self._filter_input)

        self._btn_filter = QPushButton(t("data_viewer.apply"), self)
        self._btn_filter.clicked.connect(self._apply_filter)
        toolbar.addWidget(self._btn_filter)

        self._btn_sort = QPushButton(t("data_viewer.sort"), self)
        self._btn_sort.setCheckable(True)
        self._btn_sort.clicked.connect(self._show_sort_popup)
        toolbar.addWidget(self._btn_sort)

        self._btn_columns = QPushButton(t("data_viewer.columns"), self)
        self._btn_columns.clicked.connect(self._show_columns_manager)
        toolbar.addWidget(self._btn_columns)

        self._btn_cond_fmt = QPushButton(t("table_viewer.conditional_format"), self)
        self._btn_cond_fmt.clicked.connect(self._show_conditional_formatting)
        toolbar.addWidget(self._btn_cond_fmt)

        toolbar.addSeparator()

        # Group 4: Import, Export, Analysis, Gen, BI
        self._btn_export = QPushButton("📤 " + t("menu.file.export"), self)
        self._btn_export.clicked.connect(self._export_data)
        toolbar.addWidget(self._btn_export)

        self._btn_import = QPushButton("📥 " + t("menu.file.import"), self)
        self._btn_import.clicked.connect(self._import_data)
        toolbar.addWidget(self._btn_import)

        self._btn_gen_data = QPushButton(t("data_viewer.gen_data"), self)
        self._btn_gen_data.clicked.connect(self._generate_test_data)
        toolbar.addWidget(self._btn_gen_data)

        self._btn_analysis = QPushButton(t("data_viewer.data_analysis"), self)
        self._btn_analysis.clicked.connect(self._show_data_analysis)
        toolbar.addWidget(self._btn_analysis)

        self._btn_bi = QPushButton(t("data_viewer.bi_workspace"), self)
        self._btn_bi.clicked.connect(self._show_bi_workspace)
        toolbar.addWidget(self._btn_bi)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel(t("data_viewer.per_page") + ":", self))
        self._combo_page_size = QComboBox(self)
        self._combo_page_size.addItems([str(s) for s in self.PAGE_SIZES])
        self._combo_page_size.setCurrentText(str(self._page_size))
        self._combo_page_size.currentTextChanged.connect(self._change_page_size)
        toolbar.addWidget(self._combo_page_size)

        toolbar.addSeparator()
        self._status_msg = QLabel("", self)
        self._status_msg.setStyleSheet("color: #888; font-size: 11px;")
        toolbar.addWidget(self._status_msg)
        self._dirty_label = QLabel("", self)
        self._dirty_label.setStyleSheet("color: #ffa500; font-weight: bold; font-size: 11px;")
        toolbar.addWidget(self._dirty_label)

        layout.addWidget(toolbar)

        # -- Stacked widget: table grid (0) + form view (1) --
        self._view_stack = QStackedWidget(self)

        # Page 0: Table grid
        self._table_widget = QTableWidget(self)
        from open_navicat.config import config as _cfg

        stripe = _cfg.get("records.row_stripe", t("settings.stripe.every_3"))
        self._table_widget.setAlternatingRowColors(stripe != t("settings.stripe.none"))
        self._table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table_widget.horizontalHeader().setStretchLastSection(True)
        self._table_widget.horizontalHeader().setSectionsMovable(True)
        self._table_widget.setSortingEnabled(True)
        self._table_widget.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        self._table_widget.cellChanged.connect(self._on_cell_changed)
        self._table_widget.cellDoubleClicked.connect(self._on_cell_double_click)
        self._table_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table_widget.customContextMenuRequested.connect(self._show_table_context_menu)
        self._table_widget.horizontalHeader().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table_widget.horizontalHeader().customContextMenuRequested.connect(
            self._show_table_header_menu
        )
        self._view_stack.addWidget(self._table_widget)

        # Page 1: Form view
        self._form_scroll = QScrollArea(self)
        self._form_scroll.setWidgetResizable(True)
        self._form_panel = QWidget()
        self._form_layout = QVBoxLayout(self._form_panel)
        self._form_fields = QWidget()
        self._form_fields_layout = QFormLayout(self._form_fields)
        self._form_fields_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._form_layout.addWidget(self._form_fields)
        # Form nav bar
        form_nav = QHBoxLayout()
        self._form_prev = QPushButton(t("table_viewer.form_prev"), self)
        self._form_prev.clicked.connect(self._form_prev_row)
        self._form_next = QPushButton(t("table_viewer.form_next"), self)
        self._form_next.clicked.connect(self._form_next_row)
        self._form_row_label = QLabel(t("table_viewer.form_row_info", current=0, total=0), self)
        self._form_row_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form_nav.addWidget(self._form_prev)
        form_nav.addWidget(self._form_row_label)
        form_nav.addWidget(self._form_next)
        form_nav.addStretch()
        self._form_close = QPushButton(t("table_viewer.back_to_table"), self)
        self._form_close.clicked.connect(lambda: self._toggle_view_mode(False))
        form_nav.addWidget(self._form_close)
        self._form_layout.addLayout(form_nav)
        self._form_layout.addStretch()

        self._form_scroll.setWidget(self._form_panel)
        self._view_stack.addWidget(self._form_scroll)

        layout.addWidget(self._view_stack, 1)

        # -- Pagination bar --
        pagination = QHBoxLayout()
        self._btn_first = QPushButton(t("data_viewer.first_page"), self)
        self._btn_first.clicked.connect(lambda: self._go_to_page(0))
        pagination.addWidget(self._btn_first)

        self._btn_prev = QPushButton(t("data_viewer.prev_page"), self)
        self._btn_prev.clicked.connect(self._prev_page)
        pagination.addWidget(self._btn_prev)

        self._page_info = QLabel(t("data_viewer.page", page=0, total=0), self)
        pagination.addWidget(self._page_info)

        self._btn_next = QPushButton(t("data_viewer.next_page"), self)
        self._btn_next.clicked.connect(self._next_page)
        pagination.addWidget(self._btn_next)

        self._btn_last = QPushButton(t("data_viewer.last_page"), self)
        self._btn_last.clicked.connect(self._go_to_last_page)
        pagination.addWidget(self._btn_last)

        pagination.addStretch()
        self._row_count_label = QLabel("", self)
        pagination.addWidget(self._row_count_label)

        layout.addLayout(pagination)

    # ---- data loading ----

    def _on_header_clicked(self, col: int) -> None:
        """Toggle sort by column."""
        header = self._table_widget.horizontalHeaderItem(col)
        if not header:
            return
        col_name = header.text()
        if self._order_by == col_name:
            self._order_dir = "DESC" if self._order_dir == "ASC" else "ASC"
        else:
            self._order_by = col_name
            self._order_dir = "ASC"
        self._current_page = 0
        self._load_page()

    # ---- statement building helpers ----

    def _engine(self) -> str:
        """The engine of the connection being browsed."""
        connector = connection_pool.get(self._connection_id)
        info = getattr(connector, "_info", None)
        return str(getattr(info, "engine", "") or "mysql")

    def _quote(self, name: str) -> str:
        """Quote an identifier for the current engine."""
        return quote_identifier(name, self._engine())

    def _table_ref(self) -> str:
        """The `db`.`table` reference for the current engine."""
        return quote_qualified(self._table, self._engine(), self._database or None)

    def _load_primary_keys(self) -> None:
        """Remember which columns form the primary key.

        Row edits and deletes are addressed by these.  Without this the widget
        used column 0, which is only correct by luck.
        """
        self._primary_keys = []
        connector = connection_pool.get(self._connection_id)
        if connector is None or not self._table:
            return
        try:
            info = pool_loop.run_until_complete(
                connector.get_table_info(self._database, self._table)
            )
        except Exception as exc:  # noqa: BLE001 - metadata is best effort
            _log.debug("could not read primary key for %s.%s: %s", self._database, self._table, exc)
            return
        self._primary_keys = [c.name for c in info.columns if c.is_primary_key]

    def _key_for_row(self, row: int) -> tuple[tuple[str, ...], dict[str, Any]]:
        """Primary-key columns and values for a displayed row.

        Returns empty containers when the key cannot be determined; callers must
        refuse to act rather than guess.
        """
        if not self._primary_keys:
            return (), {}
        values: dict[str, Any] = {}
        for name in self._primary_keys:
            if name not in self._loaded_column_names:
                return (), {}
            col = self._loaded_column_names.index(name)
            if row >= len(self._loaded_rows) or col >= len(self._loaded_rows[row]):
                return (), {}
            values[name] = self._loaded_rows[row][col]
        return tuple(self._primary_keys), values

    def _reference_for(self, row: int, col: int) -> Any:
        """The original value of a cell, used to infer the edited value's type."""
        if row < len(self._loaded_rows) and col < len(self._loaded_rows[row]):
            return self._loaded_rows[row][col]
        return None

    def _load_page(self) -> None:
        # Clear pending edits on reload
        self._edit_stack.clear()
        self._edit_pos = -1
        self._original_values.clear()
        self._update_dirty_state()

        connector = connection_pool.get(self._connection_id)
        if not connector:
            return

        self._load_primary_keys()

        # Build WHERE clause from filters
        engine = self._engine()
        where_clause = ""
        if self._filters:
            where_parts = []
            for k, v in self._filters.items():
                if k == "__panel__":
                    # Visual filter panel conditions (already SQL)
                    where_parts.append(f"({v})")
                elif any(
                    v.startswith(op) for op in [">=", "<=", "!=", ">", "<", "LIKE", "IN", "BETWEEN"]
                ):
                    where_parts.append(f"{quote_identifier(k, engine)} {v}")
                else:
                    # Bound-safe enough for the grid's simple equality filter;
                    # the panel route above exists for anything more complex.
                    where_parts.append(
                        f"{quote_identifier(k, engine)} = {quote_literal(v, engine)}"
                    )
            where_clause = "WHERE " + " AND ".join(where_parts)

        try:
            table_ref = self._table_ref()
            count_sql = f"SELECT COUNT(*) FROM {table_ref} {where_clause}"
            count_result = pool_loop.run_until_complete(connector.execute(count_sql))
            self._total_rows = count_result.rows[0][0] if count_result.rows else 0

            # Fetch page
            offset = self._current_page * self._page_size
            order = (
                f"ORDER BY {quote_identifier(self._order_by, engine)} {self._order_dir}"
                if self._order_by
                else ""
            )
            paging = limit_clause(self._page_size, offset, engine)
            page_sql = f"SELECT * FROM {table_ref} {where_clause} {order} {paging}".strip()
            result = pool_loop.run_until_complete(connector.execute(page_sql))

            self._render(result)
            self._update_pagination()
        except Exception as e:
            self._table_widget.setRowCount(0)
            self._table_widget.setColumnCount(0)
            self._row_count_label.setText(f"Error: {e}")

    def _render(self, result: QueryResult) -> None:
        self._table_widget.blockSignals(True)

        from open_navicat.config import config as _cfg

        thousand_sep = _cfg.get("records.thousand_sep", False)
        null_str = _cfg.get("data_viewer.null_string", "(NULL)")

        self._loaded_rows = result.rows or []

        if result.is_select:
            cols = [c.name for c in result.columns]
            self._loaded_column_names = cols

            # Fetch column types for type icons
            col_types = self._fetch_column_types()

            self._table_widget.setColumnCount(len(cols))
            # Add type icons to headers
            headers = []
            for c in cols:
                dtype = col_types.get(c, "")
                icon = self._type_icon(dtype)
                headers.append(f"{icon} {c}" if icon else c)
            self._table_widget.setHorizontalHeaderLabels(headers)
            self._table_widget.setRowCount(len(result.rows))

            # Update filter panel with column names
            self._filter_panel.set_columns(cols)

            for row_idx, row in enumerate(result.rows):
                for col_idx, val in enumerate(row):
                    if val is None:
                        display = null_str or "(NULL)"
                    elif isinstance(val, bytes):
                        display = self._fmt_blob(val)
                    elif isinstance(val, (int, float)) and thousand_sep:
                        display = f"{val:,}"
                    else:
                        display = str(val)
                    item = QTableWidgetItem(display)
                    if val is None:
                        item.setForeground(QColor("#808080"))
                    elif isinstance(val, bytes):
                        item.setData(Qt.ItemDataRole.UserRole, val)
                        item.setToolTip(t("table_viewer.view_blob_tooltip"))
                    self._table_widget.setItem(row_idx, col_idx, item)

            # Apply conditional formatting rules
            for rule in self._format_rules:
                col_idx = (
                    self._loaded_column_names.index(rule["col"])
                    if rule["col"] in self._loaded_column_names
                    else -1
                )
                if col_idx < 0:
                    continue
                op = rule["op"]
                val = rule["val"]
                color = QColor(rule["color"])
                for row_idx in range(len(result.rows)):
                    cell_val = (
                        str(result.rows[row_idx][col_idx])
                        if result.rows[row_idx][col_idx] is not None
                        else ""
                    )
                    match = False
                    if op == ">":
                        try:
                            match = float(cell_val) > float(val)
                        except ValueError:
                            match = cell_val > val
                    elif op == "<":
                        try:
                            match = float(cell_val) < float(val)
                        except ValueError:
                            match = cell_val < val
                    elif op == "=":
                        match = cell_val == val
                    elif op == "!=":
                        match = cell_val != val
                    elif op == "CONTAINS":
                        match = val in cell_val
                    if match:
                        item = self._table_widget.item(row_idx, col_idx)
                        if item:
                            item.setBackground(color)

            self._table_widget.horizontalHeader().resizeSections()
        else:
            self._table_widget.setRowCount(0)
            self._table_widget.setColumnCount(0)

        self._table_widget.blockSignals(False)

    def _fmt_blob(self, data: bytes) -> str:
        """Format bytes for display in table cell."""
        size = len(data)
        if size < 256:
            try:
                text = data.decode("utf-8")
                return text[:48] + "..." if len(text) > 48 else text
            except UnicodeDecodeError:
                pass
        return f"[BLOB {_fmt_bytes(size)}]"

    def _fetch_column_types(self) -> dict[str, str]:
        """Fetch column data types from information_schema."""
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return {}
        try:
            sql = (
                "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION"
            )
            result = pool_loop.run_until_complete(
                connector.execute(sql, (self._database, self._table))
            )
            return {row[0]: row[1].lower() for row in (result.rows or [])}
        except Exception:
            return {}

    def _type_icon(self, dtype: str) -> str:
        """Return a short type icon for a column data type."""
        if not dtype:
            return ""
        dtype = dtype.lower()
        if any(t in dtype for t in ("int", "serial")):
            return "#"  # numeric
        if any(t in dtype for t in ("float", "double", "decimal", "numeric", "real")):
            return "#"  # numeric
        if any(t in dtype for t in ("char", "text", "enum", "set", "varchar")):
            return "Abc"  # string
        if any(t in dtype for t in ("date", "time", "datetime", "timestamp")):
            return ""  # date/time — skip icon, too noisy
        if any(t in dtype for t in ("blob", "binary", "varbinary")):
            return " "  # binary
        if "json" in dtype:
            return "{}"  # json
        if "bool" in dtype:
            return ""  # bool
        return ""

    def _on_cell_double_click(self, row: int, col: int) -> None:
        """Open BLOB viewer, FK picker, or cell editor on double-click."""
        item = self._table_widget.item(row, col)
        if item and item.data(Qt.ItemDataRole.UserRole) is not None:
            blob_data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(blob_data, bytes):
                col_name = (
                    self._loaded_column_names[col] if col < len(self._loaded_column_names) else ""
                )
                from open_navicat.ui.dialogs.blob_viewer import BlobViewerDialog

                dlg = BlobViewerDialog(blob_data, col_name, self.window())
                dlg.exec()
                return
        col_name = self._loaded_column_names[col] if col < len(self._loaded_column_names) else ""
        if col_name.endswith("_id"):
            dlg = QDialog(self.window())
            dlg.setWindowTitle(t("table_viewer.fk_selector", column=col_name))
            dlg.resize(300, 400)
            vl = QVBoxLayout(dlg)
            lst = QListWidget(dlg)
            lst.addItem("FK picker would load from referenced table")
            vl.addWidget(lst)
            btn = QPushButton(t("common.close"), dlg)
            btn.clicked.connect(dlg.accept)
            vl.addWidget(btn)
            dlg.exec()
            return
        # Open cell editor for long text / JSON
        cell_text = item.text() if item else ""
        if len(cell_text) > 80 or cell_text.startswith("{") or cell_text.startswith("["):
            self._open_cell_editor(row, col)

    def _toggle_view_mode(self, form_mode: bool | None = None) -> None:
        """Switch between table grid (0) and form view (1)."""
        if form_mode is None:
            form_mode = not self._btn_form_view.isChecked()
        self._btn_form_view.setChecked(form_mode)
        self._view_stack.setCurrentIndex(1 if form_mode else 0)
        if form_mode:
            # Get selected row or use first row
            selected = self._table_widget.selectedItems()
            if selected:
                self._form_current_row = selected[0].row()
            else:
                self._form_current_row = 0
            self._render_form()

    def _render_form(self) -> None:
        """Render the current row in form view."""
        # Clear existing fields
        while self._form_fields_layout.count():
            child = self._form_fields_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        rows = self._loaded_rows
        if not rows or self._form_current_row >= len(rows):
            self._form_row_label.setText(t("table_viewer.no_data"))
            return

        row = rows[self._form_current_row]
        cols = self._loaded_column_names
        self._form_row_label.setText(
            t("table_viewer.form_row_info", current=self._form_current_row + 1, total=len(rows))
        )
        self._form_prev.setEnabled(self._form_current_row > 0)
        self._form_next.setEnabled(self._form_current_row < len(rows) - 1)

        for col_idx, col_name in enumerate(cols):
            val = row[col_idx] if col_idx < len(row) else None
            if val is None:
                widget = QLabel(t("common.null"), self._form_fields)
                widget.setStyleSheet("color: #808080;")
            elif isinstance(val, bytes):
                widget = self._blob_form_widget(val, col_name)
            elif isinstance(val, bool):
                widget = QLabel("✓" if val else "✗", self._form_fields)
            else:
                widget = QLabel(str(val), self._form_fields)
                widget.setWordWrap(True)
                widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._form_fields_layout.addRow(f"{col_name}:", widget)

    def _blob_form_widget(self, data: bytes, col_name: str) -> QWidget:
        """Create a widget for BLOB display in form view with a view button."""
        container = QWidget(self._form_fields)
        hl = QHBoxLayout(container)
        hl.setContentsMargins(0, 0, 0, 0)
        size_str = _fmt_bytes(len(data))
        hl.addWidget(QLabel(f"[{size_str}]", container))
        btn = QPushButton(t("table_viewer.view_blob"), container)
        btn.clicked.connect(lambda: self._open_blob_viewer(data, col_name))
        hl.addWidget(btn)
        hl.addStretch()
        return container

    def _open_blob_viewer(self, data: bytes, col_name: str) -> None:
        from open_navicat.ui.dialogs.blob_viewer import BlobViewerDialog

        dlg = BlobViewerDialog(data, col_name, self.window())
        dlg.exec()

    def _form_prev_row(self) -> None:
        if self._form_current_row > 0:
            self._form_current_row -= 1
            self._render_form()

    def _form_next_row(self) -> None:
        if self._form_current_row < len(self._loaded_rows) - 1:
            self._form_current_row += 1
            self._render_form()

    def _update_pagination(self) -> None:
        total_pages = max(1, (self._total_rows + self._page_size - 1) // self._page_size)
        self._page_info.setText(
            t("data_viewer.page", page=self._current_page + 1, total=total_pages)
        )
        self._row_count_label.setText(t("data_viewer.total_rows", count=self._total_rows))

        self._btn_first.setEnabled(self._current_page > 0)
        self._btn_prev.setEnabled(self._current_page > 0)
        self._btn_next.setEnabled(self._current_page < total_pages - 1)
        self._btn_last.setEnabled(self._current_page < total_pages - 1)

    # ---- pagination actions ----

    def _go_to_page(self, page: int) -> None:
        self._current_page = page
        self._load_page()

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._load_page()

    def _next_page(self) -> None:
        total_pages = max(1, (self._total_rows + self._page_size - 1) // self._page_size)
        if self._current_page < total_pages - 1:
            self._current_page += 1
            self._load_page()

    def _go_to_last_page(self) -> None:
        total_pages = max(1, (self._total_rows + self._page_size - 1) // self._page_size)
        self._current_page = total_pages - 1
        self._load_page()

    def _change_page_size(self, text: str) -> None:
        try:
            self._page_size = int(text)
            self._current_page = 0
            self._load_page()
        except ValueError:
            pass

    # ---- filter ----

    def _apply_filter(self) -> None:
        filter_text = self._filter_input.text().strip()
        if filter_text:
            # Support operators: =, !=, >, <, >=, <=, LIKE, IN, BETWEEN
            for op in ["!=", ">=", "<=", "=", ">", "<"]:
                if op in filter_text:
                    parts = filter_text.split(op, 1)
                    col = parts[0].strip().strip("`\"'")
                    val = parts[1].strip().strip("'\"")
                    if op == "=":
                        self._filters[col] = val
                    else:
                        self._filters[col] = f"{op} {val}"
                    break
            else:
                # Check for LIKE / IN / BETWEEN
                import re

                m = re.match(r"(\w+)\s+(LIKE|IN|BETWEEN)\s+(.+)", filter_text, re.IGNORECASE)
                if m:
                    self._filters[m.group(1)] = f"{m.group(2)} {m.group(3).strip()}"
                else:
                    self._filters.clear()
        else:
            self._filters.clear()
        self._current_page = 0
        self._load_page()

    # ---- CRUD operations ----

    def _on_cell_changed(self, row: int, col: int) -> None:
        """Track cell edits in the undo stack (batch mode — not saved until commit)."""
        item = self._table_widget.item(row, col)
        if not item:
            return

        new_value = item.text()
        col_name = self._table_widget.horizontalHeaderItem(col).text()
        if not col_name:
            return

        # Save original value on first edit
        key = (row, col)
        if key not in self._original_values:
            self._original_values[key] = (
                self._loaded_rows[row][col]
                if row < len(self._loaded_rows) and col < len(self._loaded_rows[row])
                else ""
            )

        old_value = self._original_values[key]
        if new_value == old_value:
            return  # unchanged

        # Truncate redo entries beyond current position
        del self._edit_stack[self._edit_pos + 1 :]
        self._edit_stack.append(
            {"row": row, "col": col, "old": old_value, "new": new_value, "col_name": col_name}
        )
        self._edit_pos = len(self._edit_stack) - 1
        self._update_dirty_state()

    def _update_dirty_state(self) -> None:
        """Update undo/redo button state and dirty indicator."""
        self._dirty = self._edit_pos >= 0
        self._btn_undo.setEnabled(self._edit_pos >= 0)
        self._btn_redo.setEnabled(self._edit_pos < len(self._edit_stack) - 1)
        count = self._edit_pos + 1
        self._dirty_label.setText(t("table_viewer.pending_changes", count=count) if count else "")
        for i, edit in enumerate(self._edit_stack):
            item = self._table_widget.item(edit["row"], edit["col"])
            if item:
                bg = QColor("#3a3a00") if i <= self._edit_pos else QColor("#2a2a2a")
                item.setBackground(bg)

    def _undo(self) -> None:
        if self._edit_pos < 0:
            return
        edit = self._edit_stack[self._edit_pos]
        self._edit_pos -= 1
        item = self._table_widget.item(edit["row"], edit["col"])
        if item:
            self._table_widget.blockSignals(True)
            item.setText(edit["old"])
            self._table_widget.blockSignals(False)
        self._update_dirty_state()

    def _redo(self) -> None:
        if self._edit_pos >= len(self._edit_stack) - 1:
            return
        self._edit_pos += 1
        edit = self._edit_stack[self._edit_pos]
        item = self._table_widget.item(edit["row"], edit["col"])
        if item:
            self._table_widget.blockSignals(True)
            item.setText(edit["new"])
            self._table_widget.blockSignals(False)
        self._update_dirty_state()

    def _pending_changes(self) -> list[PendingChange]:
        """Turn the edit stack into structured, typed changes.

        Values are coerced to the type the column already holds, so an integer
        key goes back as an int rather than the string the grid displayed.
        """
        if self._edit_pos < 0:
            return []

        changes: list[PendingChange] = []
        for edit in self._edit_stack[: self._edit_pos + 1]:
            row, col = edit["row"], edit["col"]
            key_cols, key_values = self._key_for_row(row)
            if not key_cols:
                # Without the key we cannot say which row this edit means.
                # Skipping is the only safe option.
                _log.warning("skipping edit at (%s,%s): primary key unavailable", row, col)
                continue
            reference = self._reference_for(row, col)
            value = cell_value_from_text(str(edit["new"]), reference)
            changes.append(
                PendingChange(
                    kind=ChangeKind.UPDATE,
                    table=self._table,
                    database=self._database,
                    key_columns=key_cols,
                    key_values=key_values,
                    values={edit["col_name"]: value},
                )
            )
        return changes

    def preview_sql(self) -> str:
        """The statements the pending edits would run, for review.

        Read-only text: values are inlined and escaped so the user can see the
        effect.  Execution always goes through bound parameters, never this.
        """
        previews = plan_changes(self._pending_changes(), self._engine())
        if not previews:
            return ""
        return "\n\n".join(p.sql_with_values for p in previews)

    def _show_sql_preview(self) -> None:
        """Show the statements the pending edits would run.

        Nothing is executed here; the point is that a destructive-looking commit
        can be read before it happens.
        """
        sql = self.preview_sql()
        if not sql:
            self._status_msg.setText(t("table_viewer.no_pending_changes"))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(t("table_viewer.preview_sql"))
        dialog.resize(720, 420)
        layout = QVBoxLayout(dialog)
        view = QTextEdit(dialog)
        view.setReadOnly(True)
        view.setPlainText(sql)
        try:
            view.setFont(QFont("Consolas", 10))
        except Exception:  # noqa: BLE001 - font is cosmetic
            pass
        layout.addWidget(view)

        from PySide6.QtWidgets import QDialogButtonBox

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _commit_batch(self) -> None:
        """Apply all pending edits.

        Builds the statements in :mod:`grid_editor` (engine-aware, primary-key
        addressed) and runs them with bound parameters.
        """
        if self._edit_pos < 0:
            return
        connector = connection_pool.get(self._connection_id)
        if connector is None:
            return

        changes = merge_cell_edits(self._pending_changes())
        if not changes:
            self._edit_stack.clear()
            self._edit_pos = -1
            self._original_values.clear()
            self._update_dirty_state()
            self._status_msg.setText(t("table_viewer.commit_errors", errors=len(self._edit_stack)))
            return

        previews = plan_changes(changes, self._engine())
        applied = 0
        errors = 0
        for preview in previews:
            try:
                pool_loop.run_until_complete(connector.execute(preview.sql, preview.params or None))
                applied += 1
            except Exception as exc:
                errors += 1
                _log.warning("commit failed for %s: %s", preview.sql, exc)

        if errors:
            self._status_msg.setText(t("table_viewer.commit_errors", errors=errors))
        else:
            self._status_msg.setText(t("table_viewer.commit_success", count=applied))

        self._edit_stack.clear()
        self._edit_pos = -1
        self._original_values.clear()
        self._update_dirty_state()
        if not errors:
            self._load_page()

    def _rollback_batch(self) -> None:
        """Discard all pending edits and reload from database."""
        if self._edit_pos < 0:
            return
        self._edit_stack.clear()
        self._edit_pos = -1
        self._original_values.clear()
        self._load_page()

    def _add_row(self) -> None:
        """Insert a new blank row into the table, then reload."""
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return

        # Build INSERT with default values — insert one row with no columns specified
        sql = f"INSERT INTO `{self._database}`.`{self._table}` () VALUES ()"
        try:
            result = pool_loop.run_until_complete(connector.execute(sql))
            if result.insert_id:
                self._status_msg.setText(t("table_viewer.inserted_row", id=result.insert_id))
            # Reload to show the new row
            self._current_page = 0
            self._load_page()
        except Exception:
            # If bare INSERT fails (e.g. NOT NULL columns), use a smarter approach:
            # get column names and insert with NULL/defaults for each
            try:
                info_sql = (
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                    "ORDER BY ORDINAL_POSITION"
                )
                rows = pool_loop.run_until_complete(
                    connector._fetch_all(info_sql, (self._database, self._table))
                )
                cols = [r[0] for r in rows]
                placeholders = ", ".join(["NULL"] * len(cols))
                col_names = ", ".join(f"`{c}`" for c in cols)
                sql2 = f"INSERT INTO `{self._database}`.`{self._table}` ({col_names}) VALUES ({placeholders})"
                pool_loop.run_until_complete(connector.execute(sql2))
                self._current_page = 0
                self._load_page()
            except Exception as e2:
                self._status_msg.setText(t("table_viewer.add_row_failed", error=e2))

    def _delete_selected(self) -> None:
        """Delete the selected rows, addressed by primary key.

        The confirmation shows the statements that will run, so a delete is never
        a leap of faith.
        """
        selected = self._table_widget.selectedItems()
        if not selected:
            return

        rows = sorted({item.row() for item in selected})
        if not rows:
            return

        changes: list[PendingChange] = []
        for row in rows:
            key_cols, key_values = self._key_for_row(row)
            if not key_cols:
                self._status_msg.setText(t("table_viewer.delete_no_key"))
                return
            changes.append(
                PendingChange(
                    kind=ChangeKind.DELETE,
                    table=self._table,
                    database=self._database,
                    key_columns=key_cols,
                    key_values=key_values,
                )
            )

        previews = plan_changes(changes, self._engine())
        from PySide6.QtWidgets import QMessageBox

        reply = QMessageBox.question(
            self,
            t("browser.truncate_table"),
            t("table_viewer.confirm_delete_rows", count=len(changes))
            + "\n\n"
            + "\n".join(p.sql_with_values for p in previews),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        connector = connection_pool.get(self._connection_id)
        if connector is None:
            return

        deleted = 0
        failures = 0
        for preview in previews:
            try:
                result = pool_loop.run_until_complete(
                    connector.execute(preview.sql, preview.params or None)
                )
                deleted += result.affected_rows
            except Exception as exc:
                failures += 1
                self._status_msg.setText(t("table_viewer.delete_failed", error=exc))

        if not failures:
            self._status_msg.setText(t("table_viewer.deleted_rows", count=deleted))
            self._load_page()

    def _export_filters(self) -> list[Filter]:
        """The active filters, in a form the export layer can quote safely."""
        filters: list[Filter] = []
        for key, value in self._filters.items():
            if key == "__panel__":
                filters.append(Filter(PANEL_KEY, value, "RAW"))
                continue
            for op in (">=", "<=", "!=", ">", "<", "LIKE", "NOT LIKE", "IN", "BETWEEN"):
                if value.startswith(op):
                    filters.append(Filter(key, value[len(op) :].strip(), op))
                    break
            else:
                filters.append(Filter(key, value))
        return filters

    def _export_batches(self, connector, chunk_rows: int = 5000):
        """Yield row batches, paging the table instead of loading it whole.

        A single ``SELECT *`` used to be materialised in RAM before writing a
        byte, so exporting a large table could exhaust memory.  Paging keeps peak
        usage at one batch.
        """
        engine = self._engine()
        where = build_filter_clause(self._export_filters(), engine)
        clause = f"WHERE {where}" if where else ""
        order = (
            f"ORDER BY {quote_identifier(self._order_by, engine)} {self._order_dir}"
            if self._order_by
            else ""
        )
        table_ref = self._table_ref()

        offset = 0
        while True:
            paging = limit_clause(chunk_rows, offset, engine)
            sql = f"SELECT * FROM {table_ref} {clause} {order} {paging}".strip()
            result = pool_loop.run_until_complete(connector.execute(sql))
            if not result.success or not result.rows:
                break
            yield result.columns, result.rows
            if len(result.rows) < chunk_rows:
                break
            offset += chunk_rows

    def _export_data(self) -> None:
        """Export the table (respecting filters) to a chosen format.

        Rows are streamed batch by batch, so a large export does not have to fit
        in memory.
        """
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        path, _selected = QFileDialog.getSaveFileName(
            self,
            t("table_viewer.export"),
            f"{self._table}",
            "CSV (*.csv);;TSV (*.tsv);;JSON (*.json);;Markdown (*.md);;"
            "Excel (*.xlsx);;SQL (*.sql);;All files (*)",
        )
        if not path:
            return

        connector = connection_pool.get(self._connection_id)
        if connector is None:
            return

        suffix = path.rsplit(".", 1)[-1].lower() if "." in path else "csv"
        fmt_map = {
            "csv": ExportFormat.CSV,
            "tsv": ExportFormat.TSV,
            "json": ExportFormat.JSON,
            "md": ExportFormat.MARKDOWN,
            "markdown": ExportFormat.MARKDOWN,
            "xlsx": ExportFormat.XLSX,
            "sql": ExportFormat.SQL,
        }
        fmt = fmt_map.get(suffix, ExportFormat.CSV)

        try:
            # The header comes from the first batch's column metadata; only an
            # empty result needs a separate probe.
            writer = _HeaderCapturingBatches(self._export_batches(connector))
            first_batch = next(writer, None)
            header = writer.header or self._export_columns(connector)

            def batches():
                if first_batch is not None:
                    yield first_batch
                yield from writer

            written = export_rows(path, header, batches(), fmt, table=self._table)
            self._status_msg.setText(t("table_viewer.export_success", count=written, path=path))
        except Exception as exc:
            QMessageBox.warning(self, t("table_viewer.export_failed"), str(exc))

    def _export_columns(self, connector) -> list[str]:
        """Column names for the export header.

        Only an empty page needs this: with rows in hand the header comes from the
        driver's own column metadata.
        """
        engine = self._engine()
        where = build_filter_clause(self._export_filters(), engine)
        clause = f"WHERE {where}" if where else ""
        sql = (f"SELECT * FROM {self._table_ref()} {clause} {limit_clause(1, 0, engine)}").strip()
        result = pool_loop.run_until_complete(connector.execute(sql))
        return [c.name for c in result.columns] if result.success else []

    def _export_excel(self, path: str, result) -> None:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = self._table
        ws.append([c.name for c in result.columns])
        for row in result.rows:
            ws.append([v for v in row])
        wb.save(path)

    def _import_data(self) -> None:
        """Import data from CSV or Excel file into the table."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        path, _ = QFileDialog.getOpenFileName(
            self,
            t("table_viewer.import"),
            "",
            "CSV 文件 (*.csv);;Excel 文件 (*.xlsx);;所有文件 (*)",
        )
        if not path:
            return

        try:
            rows = []
            if path.endswith(".xlsx"):
                from openpyxl import load_workbook

                wb = load_workbook(path, read_only=True, data_only=True)
                ws = wb.active
                headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
                for row in ws.iter_rows(min_row=2, values_only=True):
                    rows.append(
                        dict(zip(headers, [str(v) if v is not None else None for v in row]))
                    )
            else:
                import csv

                with open(path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    rows = [dict(r) for r in reader]

            if not rows:
                QMessageBox.information(
                    self, t("table_viewer.import_action"), t("table_viewer.file_empty")
                )
                return

            connector = connection_pool.get(self._connection_id)
            if not connector:
                return

            batch_size = 100
            total = 0
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                inserted = pool_loop.run_until_complete(
                    connector.batch_insert(self._database, self._table, batch)
                )
                total += inserted

            self._status_msg.setText(t("table_viewer.import_success", count=total))
            self._load_page()
        except Exception as e:
            QMessageBox.warning(self, t("table_viewer.import_failed"), str(e))

    def _generate_test_data(self) -> None:
        """Generate test data using pattern-based generator or AI."""
        from PySide6.QtWidgets import QInputDialog

        count, ok = QInputDialog.getInt(
            self, t("table_viewer.generate_data"), t("table_viewer.generate_rows"), 10, 1, 1000
        )
        if not ok:
            return

        connector = connection_pool.get(self._connection_id)
        if not connector:
            return

        self._status_msg.setText(t("table_viewer.generating_data"))
        try:
            # Get table info for schema
            info_sql = "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION"
            rows = pool_loop.run_until_complete(
                connector._fetch_all(info_sql, (self._database, self._table))
            )
            from open_navicat.models.table_schema import ColumnInfo, TableInfo

            table_info = TableInfo(name=self._table, database=self._database)
            for r in rows:
                table_info.columns.append(
                    ColumnInfo(
                        name=r[0],
                        data_type=r[1],
                        nullable=(r[2] == "YES"),
                        default=r[3],
                        is_auto_increment="auto_increment" in (r[4] or ""),
                        comment=r[5] or "",
                    )
                )

            # Use pattern-based generator (fast, no AI needed)
            from open_navicat.services.data_generator import data_generator

            generated = data_generator.generate(table_info, count)

            if not generated:
                self._status_msg.setText(t("table_viewer.generate_failed"))
                return

            # Insert
            total = pool_loop.run_until_complete(
                connector.batch_insert(self._database, self._table, generated)
            )
            self._status_msg.setText(t("table_viewer.generate_insert_success", count=total))
            self._load_page()
        except Exception as e:
            self._status_msg.setText(t("table_viewer.generate_error", error=e))

    # ---- new toolbar actions ----

    def _show_table_profile(self) -> None:
        """Show table metadata: engine, row count, data size, indexes, etc."""
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            sql = (
                "SELECT TABLE_NAME, ENGINE, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH, "
                "CREATE_TIME, UPDATE_TIME, TABLE_COLLATION, TABLE_COMMENT "
                "FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s"
            )
            r = pool_loop.run_until_complete(connector.execute(sql, (self._database, self._table)))
            if not r.rows:
                QMessageBox.information(
                    self, t("table_viewer.table_info"), t("table_viewer.table_info_unavailable")
                )
                return
            row = r.rows[0]
            dlg = QDialog(self)
            dlg.setWindowTitle(t("table_viewer.table_info_title", table=self._table))
            dlg.resize(450, 300)
            layout = QVBoxLayout(dlg)
            items = [
                (t("table_viewer.profile.table_name"), row[0]),
                (t("table_viewer.profile.engine"), row[1] or "—"),
                (t("table_viewer.profile.row_count"), f"{row[2]:,}" if row[2] is not None else "—"),
                (t("table_viewer.profile.data_size"), _fmt_bytes(row[3]) if row[3] else "—"),
                (t("table_viewer.profile.index_size"), _fmt_bytes(row[4]) if row[4] else "—"),
                (t("table_viewer.profile.create_time"), str(row[5] or "—")),
                (t("table_viewer.profile.update_time"), str(row[6] or "—")),
                (t("table_viewer.profile.collation"), row[7] or "—"),
                (t("table_viewer.profile.comment"), row[8] or "—"),
            ]
            for label, val in items:
                row_w = QHBoxLayout()
                lbl = QLabel(f"{label}:", dlg)
                lbl.setFixedWidth(100)
                row_w.addWidget(lbl)
                val_lbl = QLabel(str(val), dlg)
                val_lbl.setWordWrap(True)
                row_w.addWidget(val_lbl, 1)
                layout.addLayout(row_w)
            layout.addStretch()
            btn = QPushButton(t("common.close"), dlg)
            btn.clicked.connect(dlg.accept)
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignRight)
            dlg.exec()
        except Exception as e:
            QMessageBox.warning(self, t("common.error"), str(e))

    def _save_view_profile(self) -> None:
        """Save current view configuration (columns, sort, filter) as a profile."""
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self, t("data_viewer.save_view_profile"), t("data_viewer.profile_name")
        )
        if not ok or not name.strip():
            return

        # Get current column order
        headers = [
            self._table.horizontalHeaderItem(i).text() for i in range(self._table.columnCount())
        ]

        # Get current sort
        sort_col = self._table.horizontalHeader().sortIndicatorSection()
        sort_order = (
            "asc"
            if self._table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
            else "desc"
        )
        sort = [{"column": headers[sort_col], "order": sort_order}] if sort_col >= 0 else []

        # Get current filter
        filter_sql = (
            self._filter_panel._build_where_clause()
            if hasattr(self._filter_panel, "_build_where_clause")
            else ""
        )

        profile = {
            "name": name.strip(),
            "conn_id": self._connection_id,
            "database": self._database,
            "table": self._table_name,
            "columns": headers,
            "sort": sort,
            "filter": filter_sql,
        }

        from open_navicat.dal.local_config import local_db

        local_db.save_profile(profile)
        QMessageBox.information(
            self, t("data_viewer.profile_saved"), t("data_viewer.profile_saved_msg", name=name)
        )

    def _load_view_profile(self) -> None:
        """Load a saved view profile."""
        from open_navicat.dal.local_config import local_db

        table_ref = f"{self._connection_id}/{self._database}/{self._table_name}"
        profiles = local_db.list_profiles(table_ref)

        if not profiles:
            QMessageBox.information(
                self, t("data_viewer.no_profiles"), t("data_viewer.no_profiles_msg")
            )
            return

        from PySide6.QtWidgets import QInputDialog

        names = [p["name"] for p in profiles]
        name, ok = QInputDialog.getItem(
            self,
            t("data_viewer.load_view_profile"),
            t("data_viewer.select_profile"),
            names,
            0,
            False,
        )
        if not ok:
            return

        profile = next((p for p in profiles if p["name"] == name), None)
        if not profile:
            return

        # Apply filter
        if profile.get("filter"):
            self._filter_panel._where_input.setText(profile["filter"])
            self._on_filter_apply()

        # Apply sort
        if profile.get("sort"):
            sort_info = profile["sort"][0]
            col_name = sort_info.get("column", "")
            headers = [
                self._table.horizontalHeaderItem(i).text() for i in range(self._table.columnCount())
            ]
            if col_name in headers:
                col_idx = headers.index(col_name)
                order = (
                    Qt.SortOrder.AscendingOrder
                    if sort_info.get("order") == "asc"
                    else Qt.SortOrder.DescendingOrder
                )
                self._table.sortByColumn(col_idx, order)

    def _commit_transaction(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if connector:
            try:
                pool_loop.run_until_complete(connector.execute("COMMIT"))
                self._status_msg.setText(t("table_viewer.committed"))
            except Exception as e:
                self._status_msg.setText(t("table_viewer.commit_failed", error=e))

    def _rollback_transaction(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if connector:
            try:
                pool_loop.run_until_complete(connector.execute("ROLLBACK"))
                self._status_msg.setText(t("table_viewer.rolled_back"))
            except Exception as e:
                self._status_msg.setText(t("table_viewer.rollback_failed", error=e))

    # ---- transaction control (explicit) ----

    def _tx_begin(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            pool_loop.run_until_complete(connector.execute("BEGIN"))
            self._status_msg.setText(t("table_viewer.tx_started"))
        except Exception as e:
            self._status_msg.setText(t("table_viewer.tx_begin_failed", error=e))

    def _tx_commit(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            pool_loop.run_until_complete(connector.execute("COMMIT"))
            self._status_msg.setText(t("table_viewer.committed"))
        except Exception as e:
            self._status_msg.setText(t("table_viewer.commit_failed", error=e))

    def _tx_rollback(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            pool_loop.run_until_complete(connector.execute("ROLLBACK"))
            self._status_msg.setText(t("table_viewer.rolled_back"))
        except Exception as e:
            self._status_msg.setText(t("table_viewer.rollback_failed", error=e))

    # ---- filter panel integration ----

    def _on_filter_panel_apply(self) -> None:
        """Apply visual filter panel conditions and reload."""
        panel_conditions = self._filter_panel.get_sql_conditions()
        # Merge with text filter
        if panel_conditions:
            self._filters = {"__panel__": " AND ".join(panel_conditions)}
        else:
            self._filters.pop("__panel__", None)
        self._current_page = 0
        self._load_page()

    # ---- cell editor dialog ----

    def _open_cell_editor(self, row: int, col: int) -> None:
        """Open a full-featured cell editor dialog for large text/JSON."""
        item = self._table_widget.item(row, col)
        if not item:
            return
        col_name = self._loaded_column_names[col] if col < len(self._loaded_column_names) else ""
        current_val = item.text()
        is_json = False
        try:
            import json

            json.loads(current_val)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            pass

        dlg = QDialog(self.window())
        dlg.setWindowTitle(t("cell_editor.title", column=col_name))
        dlg.resize(600, 450)
        layout = QVBoxLayout(dlg)

        # Info bar
        info = QLabel(t("cell_editor.info", row=row + 1, column=col_name), dlg)
        info.setStyleSheet("color: #888; font-size: 11px; padding: 4px;")
        layout.addWidget(info)

        # Text editor
        text_edit = QLineEdit(dlg) if len(current_val) < 200 else None
        if text_edit is None:
            from PySide6.QtWidgets import QTextEdit

            text_edit = QTextEdit(dlg)
            text_edit.setPlainText(current_val)
            text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
            layout.addWidget(text_edit, 1)
        else:
            text_edit.setText(current_val)
            layout.addWidget(text_edit)

        # Buttons
        btn_layout = QHBoxLayout()
        if is_json:
            btn_format = QPushButton(t("cell_editor.format_json"), dlg)
            btn_format.clicked.connect(lambda: self._format_json_in_editor(text_edit))
            btn_layout.addWidget(btn_format)

        btn_layout.addStretch()
        btn_cancel = QPushButton(t("common.cancel"), dlg)
        btn_cancel.clicked.connect(dlg.reject)
        btn_layout.addWidget(btn_cancel)
        btn_save = QPushButton(t("common.save"), dlg)
        btn_save.setProperty("class", "primary")
        btn_save.clicked.connect(dlg.accept)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            if isinstance(text_edit, QLineEdit):
                new_val = text_edit.text()
            else:
                new_val = text_edit.toPlainText()
            if new_val != current_val:
                self._table_widget.blockSignals(True)
                item.setText(new_val)
                self._table_widget.blockSignals(False)
                self._on_cell_changed(row, col)

    def _format_json_in_editor(self, editor) -> None:
        """Format JSON content in the editor."""
        from PySide6.QtWidgets import QTextEdit

        if isinstance(editor, QTextEdit):
            text = editor.toPlainText()
        else:
            text = editor.text()
        try:
            import json

            parsed = json.loads(text)
            formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
            if isinstance(editor, QTextEdit):
                editor.setPlainText(formatted)
            else:
                editor.setText(formatted)
        except (json.JSONDecodeError, ValueError):
            pass

    def _toggle_cell_editor(self, checked: bool) -> None:
        if checked:
            self._table_widget.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked
                | QAbstractItemView.EditTrigger.EditKeyPressed
            )
            self._status_msg.setText(t("table_viewer.cell_edit_on"))
        else:
            self._table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self._status_msg.setText(t("table_viewer.cell_edit_off"))

    def _show_conditional_formatting(self) -> None:
        dlg = QDialog(self.window())
        dlg.setWindowTitle(t("table_viewer.conditional_format"))
        dlg.resize(400, 300)
        layout = QVBoxLayout(dlg)

        fl = QFormLayout()
        cb_col = QComboBox(dlg)
        for c in self._loaded_column_names:
            cb_col.addItem(c)
        fl.addRow(t("table_viewer.column_label"), cb_col)

        cb_op = QComboBox(dlg)
        for op in (">", "<", "=", "!=", "CONTAINS"):
            cb_op.addItem(op)
        fl.addRow(t("table_viewer.operator"), cb_op)

        ed_val = QLineEdit(dlg)
        fl.addRow(t("table_viewer.value"), ed_val)

        cb_color = QComboBox(dlg)
        for name, code in [
            ("红色", "#ff4444"),
            ("绿色", "#44ff44"),
            ("黄色", "#ffff44"),
            ("蓝色", "#4444ff"),
        ]:
            cb_color.addItem(t(f"table_viewer.color.{name}"), code)
        fl.addRow(t("table_viewer.color"), cb_color)

        layout.addLayout(fl)

        rules_list = QListWidget(dlg)
        layout.addWidget(rules_list)

        def _add_rule() -> None:
            col = cb_col.currentText()
            op = cb_op.currentText()
            val = ed_val.text()
            color = cb_color.currentData()
            rule = {"col": col, "op": op, "val": val, "color": color}
            self._format_rules.append(rule)
            rules_list.addItem(f"{col} {op} {val} → {cb_color.currentText()}")
            self._render(self._get_current_result())

        btn_add = QPushButton(t("table_viewer.add_rule"), dlg)
        btn_add.clicked.connect(_add_rule)
        layout.addWidget(btn_add)

        btn_close = QPushButton(t("common.close"), dlg)
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close)
        dlg.exec()

    def _get_current_result(self):
        from open_navicat.models import QueryResult

        cols = [type("Col", (), {"name": n})() for n in self._loaded_column_names]
        return QueryResult(rows=self._loaded_rows, columns=cols, is_select=True)

    def _show_sort_popup(self) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        for i in range(self._table_widget.columnCount()):
            h = self._table_widget.horizontalHeaderItem(i)
            if not h:
                continue
            col_name = h.text()
            asc_act = menu.addAction(f"↑ {col_name} ASC")
            asc_act.triggered.connect(lambda checked, c=col_name: self._apply_sort(c, "ASC"))
            desc_act = menu.addAction(f"↓ {col_name} DESC")
            desc_act.triggered.connect(lambda checked, c=col_name: self._apply_sort(c, "DESC"))
        btn = self.sender()
        if btn:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _apply_sort(self, col_name: str, direction: str) -> None:
        self._order_by = col_name
        self._order_dir = direction
        self._current_page = 0
        self._load_page()

    def _show_columns_manager(self) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        actions = []
        for i in range(self._table_widget.columnCount()):
            h = self._table_widget.horizontalHeaderItem(i)
            if not h:
                continue
            act = menu.addAction(h.text())
            act.setCheckable(True)
            act.setChecked(not self._table_widget.isColumnHidden(i))
            actions.append((i, act))
        for idx, act in actions:
            act.triggered.connect(
                lambda checked, col=idx: self._table_widget.setColumnHidden(col, not checked)
            )
        btn = self.sender()
        if btn:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _show_data_analysis(self) -> None:
        """Run analytical queries against the table and show results in a dialog."""
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(t("table_viewer.data_analysis", table=self._table))
        dlg.resize(780, 520)
        layout = QVBoxLayout(dlg)
        tabs = QTabWidget(dlg)

        try:
            db_table = f"`{self._database}`.`{self._table}`"

            # ── Tab 1: Overview ──
            overview = QTableWidget(tabs)
            overview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            tabs.addTab(overview, t("table_viewer.overview"))

            stats_sql = f"SELECT COUNT(*) as total FROM {db_table}"
            pool_loop.run_until_complete(connector.execute(stats_sql))

            # Per-column stats via information_schema
            info_sql = (
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, "
                "CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                "ORDER BY ORDINAL_POSITION"
            )
            col_meta = pool_loop.run_until_complete(
                connector.execute(info_sql, (self._database, self._table))
            )
            col_types = {}
            for r in col_meta.rows or []:
                col_types[r[0]] = r[1].lower() if r[1] else "text"

            # Build column stats
            overview.setColumnCount(6)
            overview.setHorizontalHeaderLabels(
                [
                    t("table_viewer.col_header.col_name"),
                    t("table_viewer.col_header.type"),
                    t("table_viewer.col_header.row_count"),
                    t("table_viewer.col_header.non_null"),
                    t("table_viewer.col_header.unique"),
                    t("table_viewer.col_header.null_count"),
                ]
            )
            overview.setRowCount(len(self._loaded_column_names))

            numeric_types = {
                "int",
                "tinyint",
                "smallint",
                "mediumint",
                "bigint",
                "float",
                "double",
                "decimal",
                "real",
            }
            data = []
            for i, col_name in enumerate(self._loaded_column_names):
                dtype = col_types.get(col_name, "text")
                try:
                    q = f"SELECT COUNT(*), COUNT(`{col_name}`), COUNT(DISTINCT `{col_name}`) FROM {db_table}"
                    r = pool_loop.run_until_complete(connector.execute(q))
                    if r.rows:
                        cnt, nonnull, distinct = r.rows[0]
                        null_cnt = (cnt or 0) - (nonnull or 0)
                        overview.setItem(i, 0, QTableWidgetItem(col_name))
                        overview.setItem(i, 1, QTableWidgetItem(dtype))
                        overview.setItem(i, 2, QTableWidgetItem(str(cnt or 0)))
                        overview.setItem(i, 3, QTableWidgetItem(str(nonnull or 0)))
                        overview.setItem(i, 4, QTableWidgetItem(str(distinct or 0)))
                        overview.setItem(i, 5, QTableWidgetItem(str(null_cnt)))
                        data.append((col_name, dtype, cnt, nonnull, distinct, null_cnt))

                        # Numeric stats
                        if dtype in numeric_types and nonnull and nonnull > 0:
                            q2 = f"SELECT MIN(`{col_name}`), MAX(`{col_name}`), AVG(`{col_name}`) FROM {db_table}"
                            r2 = pool_loop.run_until_complete(connector.execute(q2))
                            if r2.rows and r2.rows[0][0] is not None:
                                overview.setColumnCount(9)
                                overview.setHorizontalHeaderLabels(
                                    [
                                        t("table_viewer.col_header.col_name"),
                                        t("table_viewer.col_header.type"),
                                        t("table_viewer.col_header.row_count"),
                                        t("table_viewer.col_header.non_null"),
                                        t("table_viewer.col_header.unique"),
                                        t("table_viewer.col_header.null_count"),
                                        t("table_viewer.col_header.min"),
                                        t("table_viewer.col_header.max"),
                                        t("table_viewer.col_header.avg"),
                                    ]
                                )
                                mn, mx, avg = r2.rows[0]
                                overview.setItem(i, 6, QTableWidgetItem(str(mn)))
                                overview.setItem(i, 7, QTableWidgetItem(str(mx)))
                                overview.setItem(
                                    i,
                                    8,
                                    QTableWidgetItem(
                                        f"{avg:.4f}" if isinstance(avg, float) else str(avg)
                                    ),
                                )
                except Exception as e:
                    _log.debug("Column stats query failed for %s: %s", col_name, e)
            overview.resizeColumnsToContents()

            # ── Tab 2: Value Distribution (top 10 per column) ──
            freq_tab = QTableWidget(tabs)
            freq_tab.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            freq_tab.setStyleSheet(overview.styleSheet())
            tabs.addTab(freq_tab, t("table_viewer.value_distribution"))

            freq_parts: list[list[str]] = []
            for col_name in self._loaded_column_names:
                try:
                    q = (
                        f"SELECT `{col_name}`, COUNT(*) as cnt FROM {db_table} "
                        f"WHERE `{col_name}` IS NOT NULL "
                        f"GROUP BY `{col_name}` ORDER BY cnt DESC LIMIT 10"
                    )
                    r = pool_loop.run_until_complete(connector.execute(q))
                    if r.rows:
                        freq_parts.append(f"── {col_name} ──")
                        for row in r.rows:
                            freq_parts.append(f"  {row[0]}: {row[1]}")
                        freq_parts.append("")
                except Exception as e:
                    _log.debug("Frequency query failed for %s: %s", col_name, e)

            freq_tab.setColumnCount(1)
            freq_tab.setHorizontalHeaderLabels([t("table_viewer.value_frequency")])
            freq_tab.setRowCount(len(freq_parts))
            for i, line in enumerate(freq_parts):
                item = QTableWidgetItem(line)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                freq_tab.setItem(i, 0, item)
            freq_tab.resizeColumnsToContents()

        except Exception as e:
            error_widget = QLabel(f"{t('table_viewer.analysis_error')}: {e}", tabs)
            error_widget.setStyleSheet("color: #f44747; padding: 20px;")
            tabs.addTab(error_widget, t("common.error"))

        layout.addWidget(tabs, 1)
        btn = QPushButton(t("common.close"), dlg)
        btn.setStyleSheet(
            "background: #3c3c3c; color: #ccc; border: 1px solid #555; "
            "border-radius: 3px; padding: 4px 16px;"
        )
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    # ---- right-click context menu (same as ResultTable) ----

    def _show_table_context_menu(self, pos) -> None:
        menu = QMenu(self)
        rows_data = self._selected_rows_data()
        row = self._table_widget.indexAt(pos).row()

        if row < 0 and not rows_data:
            menu.addAction(t("context.refresh")).triggered.connect(self._load_page)
            menu.addSeparator()
            menu.addAction(t("context.copy_all_csv")).triggered.connect(self._copy_all_csv)
            menu.exec(self._table_widget.viewport().mapToGlobal(pos))
            return

        if not rows_data:
            return

        count = len(rows_data)
        single = rows_data[0] if count == 1 else None
        cell = self._table_widget.currentItem()

        if cell and single:
            menu.addAction(t("context.copy_cell")).triggered.connect(
                lambda: QApplication.clipboard().setText(cell.text())
            )
            menu.addSeparator()

        menu.addAction(t("context.selected_rows", count=count)).setEnabled(False)
        menu.addSeparator()

        if single:
            menu.addAction(t("context.copy_row_json")).triggered.connect(
                lambda: QApplication.clipboard().setText(str(single).replace("'", '"'))
            )
        else:
            menu.addAction(t("context.copy_rows_json", count=count)).triggered.connect(
                lambda: QApplication.clipboard().setText(
                    "[\n" + ",\n".join(str(d).replace("'", '"') for d in rows_data) + "\n]"
                )
            )
        menu.addSeparator()

        menu.addAction(t("context.copy_as_insert")).triggered.connect(
            lambda: self._copy_insert(rows_data)
        )
        menu.addAction(t("context.copy_as_update")).triggered.connect(
            lambda: self._copy_update(rows_data)
        )
        menu.addSeparator()

        if rows_data:
            fc = list(rows_data[0].keys())[0]
            menu.addAction(t("context.where_in", column=fc)).triggered.connect(
                lambda: self._copy_where_in(rows_data)
            )
            menu.addAction(t("context.copy_as_select")).triggered.connect(
                lambda: self._copy_select(rows_data)
            )
            menu.addSeparator()
            menu.addAction(t("context.copy_as_where")).triggered.connect(
                lambda: self._copy_where(rows_data)
            )
        menu.addSeparator()

        menu.addAction(t("context.copy_as_csv")).triggered.connect(
            lambda: self._copy_csv(rows_data)
        )
        menu.addAction(t("context.copy_as_json")).triggered.connect(
            lambda: QApplication.clipboard().setText(
                "[\n" + ",\n".join(str(d).replace("'", '"') for d in rows_data) + "\n]"
            )
        )
        menu.exec(self._table_widget.viewport().mapToGlobal(pos))

    def _show_table_header_menu(self, pos) -> None:
        col = self._table_widget.horizontalHeader().logicalIndexAt(pos)
        if col < 0:
            return
        col_name = self._table_widget.horizontalHeaderItem(col).text()
        engine = self._engine()
        menu = QMenu(self)
        menu.addAction(t("context.column_name", name=col_name)).setEnabled(False)
        menu.addSeparator()

        # Pin / unpin: keeps the column at the leading edge. QTableWidget has no
        # frozen panes, so this is a reorder rather than a true freeze.
        pinned = col_name in self._pinned_columns
        menu.addAction(
            t("table_viewer.unpin_column") if pinned else t("table_viewer.pin_column")
        ).triggered.connect(lambda: self._toggle_pinned_column(col_name))
        if pinned:
            menu.addAction(t("table_viewer.unpin_all_columns")).triggered.connect(
                self._clear_pinned_columns
            )
        menu.addSeparator()

        values = self._column_values(col, col_name)
        if not values:
            menu.exec(self._table_widget.horizontalHeader().viewport().mapToGlobal(pos))
            return

        menu.addAction(t("table_viewer.select_matching", count=len(values))).triggered.connect(
            lambda: self._select_rows_matching(col, set(values))
        )
        menu.addSeparator()

        # Statements are rendered for the connection's engine, not hard-coded
        # for MySQL as they used to be.
        menu.addAction(
            t("context.where_in_values", column=col_name, count=len(values))
        ).triggered.connect(
            lambda: QApplication.clipboard().setText(
                copy_as_where([col_name], [[v] for v in values], [col_name], engine)
            )
        )
        quoted = quote_identifier(col_name, engine)
        menu.addAction(t("table_viewer.copy_in_list", column=col_name)).triggered.connect(
            lambda: QApplication.clipboard().setText(
                quoted + " IN (" + ", ".join(quote_literal(v, engine) for v in values) + ")"
            )
        )

        for value in sorted(values)[:20]:
            menu.addAction(t("context.filter_value", value=value)).triggered.connect(
                lambda checked, v=value: QApplication.clipboard().setText(
                    quoted + " = " + quote_literal(v, engine)
                )
            )
        menu.exec(self._table_widget.horizontalHeader().viewport().mapToGlobal(pos))

    def _column_values(self, col: int, col_name: str) -> list:
        """Distinct non-empty values in a column, from the selection or the page."""
        values = []
        for row_data in self._selected_rows_data():
            value = row_data.get(col_name, "")
            if value and value != "NULL":
                values.append(value)
        if not values:
            for row in range(self._table_widget.rowCount()):
                item = self._table_widget.item(row, col)
                if item and item.text() and item.text() != "(NULL)":
                    values.append(item.text())
        return list(dict.fromkeys(values))

    def _select_rows_matching(self, col: int, wanted: set) -> None:
        """Select every displayed row whose cell value is in ``wanted``.

        This is what makes a bulk delete or export practical: the filter column
        menu picks the rows, then the toolbar acts on the selection.
        """
        self._table_widget.clearSelection()
        selected = 0
        for row in range(self._table_widget.rowCount()):
            item = self._table_widget.item(row, col)
            if item and item.text() in wanted:
                for c in range(self._table_widget.columnCount()):
                    cell = self._table_widget.item(row, c)
                    if cell:
                        cell.setSelected(True)
                selected += 1
        self._status_msg.setText(t("table_viewer.selected_rows", count=selected))

    # ---- pinned columns ----

    def _toggle_pinned_column(self, col_name: str) -> None:
        before = list(self._pinned_columns)
        self._pinned_columns = toggle_pin(self._pinned_columns, col_name)
        if self._pinned_columns == before:
            if len(before) >= MAX_PINNED_COLUMNS:
                self._status_msg.setText(t("table_viewer.pin_limit", count=MAX_PINNED_COLUMNS))
            return
        self._apply_column_order()

    def _clear_pinned_columns(self) -> None:
        if not self._pinned_columns:
            return
        self._pinned_columns = []
        self._apply_column_order()

    def _apply_column_order(self) -> None:
        """Reorder the grid columns so pinned ones lead."""
        header = self._table_widget.horizontalHeader()
        current = [
            self._table_widget.horizontalHeaderItem(i).text()
            for i in range(self._table_widget.columnCount())
        ]
        if not current:
            return
        wanted = order_columns(current, self._pinned_columns)
        self._table_widget.blockSignals(True)
        try:
            for target, name in enumerate(wanted):
                index = current.index(name)
                if target != index:
                    header.moveSection(index, target)
                    current.insert(target, current.pop(index))
        finally:
            self._table_widget.blockSignals(False)
        self._update_dirty_state()

    def _esc(self, v: str) -> str:
        if not v or v == "NULL":
            return "NULL"
        try:
            float(v)
            return v
        except ValueError:
            return "'" + v.replace("'", "\\'") + "'"

    def _selected_rows_data(self) -> list[dict[str, str]]:
        headers = [
            self._table_widget.horizontalHeaderItem(c).text()
            for c in range(self._table_widget.columnCount())
        ]
        rows = set()
        data = []
        for item in self._table_widget.selectedItems():
            r = item.row()
            if r in rows:
                continue
            rows.add(r)
            row_data = {}
            for c in range(self._table_widget.columnCount()):
                cell = self._table_widget.item(r, c)
                row_data[headers[c]] = cell.text() if cell else ""
            data.append(row_data)
        return data

    def _copy_insert(self, rows_data: list[dict]) -> None:
        if not rows_data:
            return
        cols = ",\n  ".join(f"`{k}`" for k in rows_data[0])
        vals = ",\n".join(
            "  (" + ", ".join(self._esc(v) for v in d.values()) + ")" for d in rows_data
        )
        QApplication.clipboard().setText(
            f"INSERT INTO `{self._table}` (\n  {cols}\n) VALUES\n{vals};"
        )

    def _copy_update(self, rows_data: list[dict]) -> None:
        if not rows_data:
            return
        pks = list(rows_data[0].keys())
        pk_col = pks[0]
        stmts = []
        for d in rows_data:
            sets = ",\n  ".join(f"`{k}` = {self._esc(v)}" for k, v in d.items() if k != pk_col)
            stmts.append(
                f"UPDATE `{self._table}`\nSET\n  {sets}\nWHERE `{pk_col}` = {self._esc(d[pk_col])};"
            )
        QApplication.clipboard().setText("\n\n".join(stmts))

    def _copy_where_in(self, rows_data: list[dict]) -> None:
        if not rows_data:
            return
        fc = list(rows_data[0].keys())[0]
        vals = [self._esc(d[fc]) for d in rows_data if fc in d and d[fc] != "NULL"]
        if vals:
            QApplication.clipboard().setText(f"`{fc}` IN ({', '.join(vals)})")

    def _copy_select(self, rows_data: list[dict]) -> None:
        if not rows_data:
            return
        fc = list(rows_data[0].keys())[0]
        vals = [self._esc(d[fc]) for d in rows_data if fc in d and d[fc] != "NULL"]
        where = (
            f"WHERE `{fc}` IN ({', '.join(vals)})" if len(vals) > 1 else f"WHERE `{fc}` = {vals[0]}"
        )
        QApplication.clipboard().setText(f"SELECT * FROM `{self._table}` {where};")

    def _copy_where(self, rows_data: list[dict]) -> None:
        """Copy selected rows as a WHERE clause (col1=val1 AND col2=val2 ...)."""
        if not rows_data:
            return
        d = rows_data[0]
        clauses = (f"`{k}` = {self._esc(v)}" for k, v in d.items())
        QApplication.clipboard().setText("WHERE " + " AND ".join(clauses))

    def _copy_csv(self, rows_data: list[dict]) -> None:
        if not rows_data:
            return
        lines = [",".join(f'"{h}"' for h in rows_data[0])]
        for d in rows_data:
            vals = []
            for v in d.values():
                s = str(v)
                vals.append('"' + s.replace('"', '""') + '"' if "," in s or '"' in s else s)
            lines.append(",".join(vals))
        QApplication.clipboard().setText("\n".join(lines))

    def _copy_all_csv(self) -> None:
        tw = self._table_widget
        rows = [",".join(f'"{tw.horizontalHeaderItem(c).text()}"' for c in range(tw.columnCount()))]
        for r in range(tw.rowCount()):
            vals = []
            for c in range(tw.columnCount()):
                item = tw.item(r, c)
                s = item.text() if item else ""
                vals.append('"' + s.replace('"', '""') + '"' if "," in s or '"' in s else s)
            rows.append(",".join(vals))
        QApplication.clipboard().setText("\n".join(rows))

    def _show_bi_workspace(self) -> None:
        mw = self.window()
        if hasattr(mw, "_show_bi_dashboard"):
            mw._show_bi_dashboard()
        else:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.information(
                self, t("data_viewer.bi_workspace"), t("table_viewer.coming_soon")
            )
