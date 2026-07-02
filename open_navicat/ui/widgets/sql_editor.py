"""Enhanced SQL Editor — syntax highlighting, AI toolbar, right-click copy."""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, QSize, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QSyntaxHighlighter,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.connection_pool import connection_pool
from open_navicat.dal.local_config import local_db
from open_navicat.i18n import t
from open_navicat.models import QueryResult

_log = logging.getLogger(__name__)


class SQLHighlighter(QSyntaxHighlighter):
    """SQL keyword/string/number/comment highlighting."""

    _KEYWORDS = {
        "SELECT", "FROM", "WHERE", "INSERT", "INTO", "VALUES", "UPDATE",
        "SET", "DELETE", "CREATE", "ALTER", "DROP", "TABLE", "INDEX",
        "VIEW", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AS",
        "AND", "OR", "NOT", "IN", "LIKE", "BETWEEN", "IS", "NULL",
        "ORDER", "BY", "GROUP", "HAVING", "LIMIT", "OFFSET", "UNION",
        "ALL", "DISTINCT", "CASE", "WHEN", "THEN", "ELSE", "END",
        "EXISTS", "FOREIGN", "KEY", "PRIMARY", "REFERENCES", "CONSTRAINT",
        "UNIQUE", "CHECK", "DEFAULT", "CASCADE", "TRIGGER", "FUNCTION",
        "PROCEDURE", "BEGIN", "COMMIT", "ROLLBACK", "EXPLAIN", "ANALYZE",
        "GRANT", "REVOKE", "DATABASE", "SCHEMA", "USE", "SHOW", "DESCRIBE",
        "TRUNCATE", "IF", "REPLACE", "TEMPORARY", "AUTO_INCREMENT",
        "ENGINE", "CHARSET", "INDEX", "LEFT", "RIGHT", "OUTER",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from open_navicat.config import config as _cfg
        self._fmt: dict[str, QTextCharFormat] = {}
        kw = QTextCharFormat()
        kw.setForeground(QColor(_cfg.get("editor.color_keyword", "#569cd6")))
        kw.setFontWeight(QFont.Weight.Bold)
        self._fmt["keyword"] = kw

        s = QTextCharFormat()
        s.setForeground(QColor(_cfg.get("editor.color_string", "#ce9178")))
        self._fmt["string"] = s

        c = QTextCharFormat()
        c.setForeground(QColor(_cfg.get("editor.color_comment", "#6a9955")))
        c.setFontItalic(True)
        self._fmt["comment"] = c

        n = QTextCharFormat()
        n.setForeground(QColor(_cfg.get("editor.color_number", "#b5cea8")))
        self._fmt["number"] = n

    def highlightBlock(self, text: str) -> None:
        import re

        # Single-line comment
        if re.match(r"--", text):
            self.setFormat(0, len(text), self._fmt["comment"])
            return

        # Keywords
        for word in self._KEYWORDS:
            for m in re.finditer(rf"\b{word}\b", text, re.IGNORECASE):
                self.setFormat(m.start(), m.end() - m.start(), self._fmt["keyword"])

        # Strings
        for m in re.finditer(r"'[^']*'|\"[^\"]*\"", text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt["string"])

        # Numbers
        for m in re.finditer(r"\b\d+(\.\d+)?\b", text):
            self.setFormat(m.start(), m.end() - m.start(), self._fmt["number"])


class LineNumberArea(QWidget):
    """Widget that paints line numbers for the SQL editor."""

    def __init__(self, editor_widget: SQLEditorWidget) -> None:
        super().__init__(editor_widget._editor)
        self._editor_widget = editor_widget

    def sizeHint(self) -> QSize:
        return QSize(self._editor_widget.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor_widget.line_number_area_paint_event(event)


class ResultTable(QTableWidget):
    """Query results table with multi-select, right-click copy, and column WHERE IN."""

    right_clicked = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from open_navicat.config import config as _cfg
        stripe = _cfg.get("records.row_stripe", "每三行")
        self.setAlternatingRowColors(stripe != "无")
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Vertical header (row numbers) — click to select row
        self.verticalHeader().setVisible(True)
        self.verticalHeader().setSectionsClickable(True)
        self.verticalHeader().sectionClicked.connect(lambda r: self.selectRow(r))

        # Horizontal header (column names) — click to select column
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionsMovable(True)
        self.horizontalHeader().setSectionsClickable(True)
        self.horizontalHeader().sectionClicked.connect(self._select_column)

        # Context menus
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.horizontalHeader().customContextMenuRequested.connect(self._show_header_menu)

        # Selection stylesheet — more visible
        self.setStyleSheet("""
            QTableWidget::item:selected {
                background-color: #094771;
                color: #ffffff;
            }
            QTableWidget::item:selected:active {
                background-color: #1a73e8;
            }
        """)

        self._table_name: str = ""
        self._headers: list[str] = []

    def set_table_meta(self, table_name: str, headers: list[str]) -> None:
        self._table_name = table_name
        self._headers = headers

    def _select_column(self, col: int) -> None:
        """Select entire column regardless of SelectRows behavior."""
        self.clearSelection()
        from PySide6.QtWidgets import QTableWidgetSelectionRange
        self.setRangeSelected(QTableWidgetSelectionRange(0, col, self.rowCount() - 1, col), True)

    def _selected_rows_data(self) -> list[dict[str, str]]:
        rows_data = []
        for row in sorted(set(r.row() for r in self.selectedIndexes())):
            row_data: dict[str, str] = {}
            for col in range(self.columnCount()):
                h = self.horizontalHeaderItem(col)
                item = self.item(row, col)
                if h and item:
                    row_data[h.text()] = item.text() if item.text() != "(NULL)" else "NULL"
            if row_data:
                rows_data.append(row_data)
        if not rows_data and self.currentRow() >= 0:
            row_data = {}
            for col in range(self.columnCount()):
                h = self.horizontalHeaderItem(col)
                item = self.item(self.currentRow(), col)
                if h and item:
                    row_data[h.text()] = item.text() if item.text() != "(NULL)" else "NULL"
            if row_data:
                rows_data.append(row_data)
        return rows_data

    @Slot(QPoint)
    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        rows_data = self._selected_rows_data()
        row = self.indexAt(pos).row()

        if row < 0 and not rows_data:
            menu.addAction(t("context.refresh")).triggered.connect(
                lambda: self.parent()._execute() if hasattr(self.parent(), '_execute') else None)
            menu.addSeparator()
            menu.addAction(t("context.copy_all_csv")).triggered.connect(self._copy_all_csv)
            menu.exec(self.viewport().mapToGlobal(pos))
            return

        if not rows_data:
            return

        count = len(rows_data)
        single = rows_data[0] if count == 1 else None

        cell = self.currentItem()
        if cell and single:
            menu.addAction(t("context.copy_cell")).triggered.connect(
                lambda: QApplication.clipboard().setText(cell.text()))
            menu.addSeparator()

        menu.addAction(t("context.selected_rows", count=count)).setEnabled(False)
        menu.addSeparator()

        if single:
            menu.addAction(t("context.copy_row_json")).triggered.connect(
                lambda: QApplication.clipboard().setText(str(single).replace("'", '"')))
        else:
            menu.addAction(t("context.copy_rows_json", count=count)).triggered.connect(
                lambda: QApplication.clipboard().setText(
                    "[\n" + ",\n".join(str(d).replace("'", '"') for d in rows_data) + "\n]"))
        menu.addSeparator()

        menu.addAction(t("context.copy_as_insert")).triggered.connect(lambda: self._copy_insert(rows_data))
        menu.addAction(t("context.copy_as_update")).triggered.connect(lambda: self._copy_update(rows_data))
        menu.addSeparator()

        if rows_data:
            fc = list(rows_data[0].keys())[0]
            menu.addAction(t("context.where_in", column=fc)).triggered.connect(
                lambda: self._copy_where_in(rows_data))
            menu.addAction(t("context.copy_as_select")).triggered.connect(lambda: self._copy_select(rows_data))
        menu.addSeparator()

        menu.addAction(t("context.copy_as_csv")).triggered.connect(lambda: self._copy_csv(rows_data))
        menu.addAction(t("context.copy_as_json")).triggered.connect(
            lambda: QApplication.clipboard().setText(
                "[\n" + ",\n".join(str(d).replace("'", '"') for d in rows_data) + "\n]"))
        menu.exec(self.viewport().mapToGlobal(pos))

    @Slot(QPoint)
    def _show_header_menu(self, pos) -> None:
        col = self.horizontalHeader().logicalIndexAt(pos)
        if col < 0:
            return
        col_name = self.horizontalHeaderItem(col).text()
        menu = QMenu(self)
        menu.addAction(t("context.column_name", name=col_name)).setEnabled(False)
        menu.addSeparator()

        vals = []
        for row_data in self._selected_rows_data():
            v = row_data.get(col_name, "")
            if v and v != "NULL":
                vals.append(v)
        if not vals:
            for row in range(self.rowCount()):
                item = self.item(row, col)
                if item and item.text() and item.text() != "(NULL)":
                    vals.append(item.text())
        if not vals:
            return

        esc_vals = ", ".join(self._esc(v) for v in vals)
        menu.addAction(t("context.where_in_values", column=col_name, count=len(vals))).triggered.connect(
            lambda: QApplication.clipboard().setText(f"`{col_name}` IN ({esc_vals})"))

        for v in sorted(set(vals))[:20]:
            ev = self._esc(v)
            menu.addAction(t("context.filter_value", value=ev)).triggered.connect(
                lambda checked, x=ev: QApplication.clipboard().setText(f"`{col_name}` = {x}"))
        menu.exec(self.horizontalHeader().viewport().mapToGlobal(pos))

    def _esc(self, v: str) -> str:
        if not v or v == "NULL":
            return "NULL"
        try:
            float(v)
            return v
        except ValueError:
            return "'" + v.replace("'", "\\'") + "'"

    def _copy_insert(self, rows_data: list[dict]) -> None:
        if not rows_data:
            return
        cols = ",\n  ".join(f"`{k}`" for k in rows_data[0])
        vals = ",\n".join("  (" + ", ".join(self._esc(v) for v in d.values()) + ")" for d in rows_data)
        QApplication.clipboard().setText(f"INSERT INTO `{self._table_name}` (\n  {cols}\n) VALUES\n{vals};")

    def _copy_update(self, rows_data: list[dict]) -> None:
        if not rows_data:
            return
        pks = list(rows_data[0].keys())
        pk_col = pks[0]
        stmts = []
        for d in rows_data:
            sets = ",\n  ".join(f"`{k}` = {self._esc(v)}" for k, v in d.items() if k != pk_col)
            stmts.append(f"UPDATE `{self._table_name}`\nSET\n  {sets}\nWHERE `{pk_col}` = {self._esc(d[pk_col])};")
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
        where = f"WHERE `{fc}` IN ({', '.join(vals)})" if len(vals) > 1 else f"WHERE `{fc}` = {vals[0]}"
        QApplication.clipboard().setText(f"SELECT * FROM `{self._table_name}` {where};")

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
        rows = [",".join(f'"{self.horizontalHeaderItem(c).text()}"' for c in range(self.columnCount()))]
        for r in range(self.rowCount()):
            vals = []
            for c in range(self.columnCount()):
                item = self.item(r, c)
                s = item.text() if item else ""
                vals.append('"' + s.replace('"', '""') + '"' if "," in s or '"' in s else s)
            rows.append(",".join(vals))
        QApplication.clipboard().setText("\n".join(rows))


class SQLEditorWidget(QWidget):
    """Single query-editor tab: SQL input + AI toolbar + results + right-click menu."""

    executed = Signal(object)
    ai_requested = Signal(str)  # Signal to open AI Copilot with a prompt

    def __init__(self, connection_id: str, database: str = "", parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        self._result: QueryResult | None = None
        self._explain_result: QueryResult | None = None
        self._current_query_id: int | None = None  # track for save-vs-update
        self._running = False
        self._cancelled = False
        self._thread_id: int | None = None
        self._setup_ui()
        self._load_databases()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- AI Toolbar --
        ai_bar = QWidget(self)
        ai_layout = QHBoxLayout(ai_bar)
        ai_layout.setContentsMargins(8, 4, 8, 4)
        ai_layout.setSpacing(4)

        ai_label = QLabel(t("sql_editor.ai_label"), ai_bar)
        ai_layout.addWidget(ai_label)

        for text, tip, mode in [
            (t("sql_editor.ai_explain"), t("sql_editor.ai_explain_tip"), "explain"),
            (t("sql_editor.ai_optimize"), t("sql_editor.ai_optimize_tip"), "optimize"),
            (t("sql_editor.ai_fix"), t("sql_editor.ai_fix_tip"), "fix"),
            (t("sql_editor.ai_nl"), t("sql_editor.ai_nl_tip"), "nl"),
        ]:
            btn = QPushButton(text, ai_bar)
            btn.setToolTip(tip)
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda checked, m=mode: self._ai_action(m))
            ai_layout.addWidget(btn)

        ai_layout.addStretch()

        self._btn_ai_run = QPushButton(t("sql_editor.run"), ai_bar)
        self._btn_ai_run.setObjectName("primaryBtn")
        self._btn_ai_run.clicked.connect(self._toggle_run_stop)
        ai_layout.addWidget(self._btn_ai_run)

        layout.addWidget(ai_bar)

        # -- Editor + Results splitter --
        splitter = QSplitter(Qt.Orientation.Vertical, self)

        # SQL input
        editor_container = QWidget(splitter)
        ed_layout = QVBoxLayout(editor_container)
        ed_layout.setContentsMargins(0, 0, 0, 0)

        # Mini toolbar: DB selector + beautify
        mini_bar = QWidget(editor_container)
        m_layout = QHBoxLayout(mini_bar)
        m_layout.setContentsMargins(8, 3, 8, 3)

        self._db_combo = QComboBox(mini_bar)
        self._db_combo.setMinimumWidth(160)
        self._db_combo.addItem(self._database or "(select database)")
        m_layout.addWidget(QLabel("DB:", mini_bar))
        m_layout.addWidget(self._db_combo)
        m_layout.addSpacing(8)

        # Run/Stop toggle
        self._btn_run = QPushButton("▶ " + t("menu.query.run"), mini_bar)
        self._btn_run.setObjectName("primaryBtn")
        self._btn_run.setToolTip(t("menu.query.run"))
        self._btn_run.clicked.connect(self._toggle_run_stop)
        self._run_menu = QMenu(self)
        for label, method_name in [
            (t("menu.query.run"), "_execute"),
            (t("sql_editor.run_selected"), "_execute_selected"),
            (t("sql_editor.run_all"), "_execute_all"),
            (t("sql_editor.explain_plan"), "_execute_explain"),
        ]:
            act = self._run_menu.addAction(label)
            act.triggered.connect(lambda checked, m=method_name: getattr(self, m)())
        self._btn_run.setMenu(self._run_menu)
        m_layout.addWidget(self._btn_run)

        btn_explain = QPushButton("📊 " + t("sql_editor.explain_plan"), mini_bar)
        btn_explain.setToolTip(t("sql_editor.explain_plan"))
        btn_explain.clicked.connect(self._execute_explain)
        m_layout.addWidget(btn_explain)

        # Snippets button
        self._btn_snippets = QPushButton("📋 " + t("sql_editor.snippets"), mini_bar)
        self._btn_snippets.setToolTip(t("sql_editor.snippets_tip"))
        self._snippet_menu = QMenu(self)
        self._btn_snippets.setMenu(self._snippet_menu)
        self._refresh_snippet_menu()
        m_layout.addWidget(self._btn_snippets)

        # Manage snippets
        btn_manage_snippets = QPushButton(t("sql_editor.manage_snippets"), mini_bar)
        btn_manage_snippets.clicked.connect(self._open_snippet_manager)
        m_layout.addWidget(btn_manage_snippets)

        m_layout.addStretch()

        btn_beautify = QPushButton(t("sql_editor.format"), mini_bar)
        btn_beautify.clicked.connect(self._beautify)
        m_layout.addWidget(btn_beautify)

        btn_simplify = QPushButton(t("sql_editor.simplify"), mini_bar)
        btn_simplify.setToolTip(t("sql_editor.simplify_tip"))
        btn_simplify.clicked.connect(self._simplify)
        m_layout.addWidget(btn_simplify)

        btn_compare = QPushButton("对比当前查询", mini_bar)
        btn_compare.setToolTip("Compare current SQL with another query side by side")
        btn_compare.clicked.connect(self._open_compare_dialog)
        m_layout.addWidget(btn_compare)

        btn_clear = QPushButton(t("sql_editor.clear"), mini_bar)
        btn_clear.clicked.connect(lambda: self._editor.clear())
        m_layout.addWidget(btn_clear)

        m_layout.addSpacing(8)

        btn_save = QPushButton(t("sql_editor.save"), mini_bar)
        btn_save.setToolTip(t("sql_editor.save_tip"))
        btn_save.clicked.connect(self._save_query)
        m_layout.addWidget(btn_save)

        btn_open = QPushButton(t("sql_editor.open"), mini_bar)
        btn_open.setToolTip(t("sql_editor.open_tip"))
        btn_open.clicked.connect(self._open_saved_query)
        m_layout.addWidget(btn_open)

        btn_shortcuts = QPushButton("⌨", mini_bar)
        btn_shortcuts.setToolTip(t("sql_editor.shortcuts_tip"))
        btn_shortcuts.setFixedSize(24, 22)
        btn_shortcuts.clicked.connect(self._show_shortcuts)
        m_layout.addWidget(btn_shortcuts)

        m_layout.addSpacing(4)
        btn_sql_file = QPushButton(t("sql_editor.sql_file"), mini_bar)
        btn_sql_file.setToolTip(t("sql_editor.sql_file_tip"))
        sql_file_menu = QMenu(self)
        act_export = sql_file_menu.addAction(t("sql_editor.export_sql"))
        act_export.triggered.connect(self._export_sql_file)
        act_import = sql_file_menu.addAction(t("sql_editor.import_sql"))
        act_import.triggered.connect(self._import_sql_file)
        btn_sql_file.setMenu(sql_file_menu)
        m_layout.addWidget(btn_sql_file)

        ed_layout.addWidget(mini_bar)

        self._editor = QPlainTextEdit(editor_container)
        # Apply editor settings from config
        from open_navicat.config import config as _cfg
        font_family = _cfg.get("editor.font_family", "Consolas")
        font_size = _cfg.get("editor.font_size", 12)
        tab_size = _cfg.get("editor.tab_size", 4)
        insert_spaces = _cfg.get("editor.insert_spaces", True)
        word_wrap = _cfg.get("editor.word_wrap", True)
        self._editor.setFont(QFont(font_family, font_size))
        self._editor.setTabStopDistance(
            self._editor.fontMetrics().horizontalAdvance(" ") * tab_size
        )
        if word_wrap:
            from PySide6.QtGui import QTextOption
            self._editor.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        if insert_spaces:
            self._editor.setTabChangesFocus(False)
        self._editor.setObjectName("sqlEditor")
        self._editor.setPlaceholderText(t("sql_editor.placeholder"))
        self._editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._editor.customContextMenuRequested.connect(self._show_editor_context_menu)
        # Syntax highlighting (respects config colors)
        if _cfg.get("editor.syntax_highlight", True):
            self._highlighter = SQLHighlighter(self._editor.document())
        else:
            self._highlighter = None
        ed_layout.addWidget(self._editor)

        # Line numbers
        self._line_area = LineNumberArea(self)
        self._editor.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
        self._editor.updateRequest.connect(self._line_area.update)
        self._editor.blockCountChanged.connect(self._update_line_number_area_width)
        self._editor.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_line_number_area_width(0)

        # Quick SQL snippet bar
        snippet_bar = QWidget(editor_container)
        sb_layout = QHBoxLayout(snippet_bar)
        sb_layout.setContentsMargins(8, 2, 8, 2)
        sb_layout.setSpacing(4)
        for label, sql in [
            ("SELECT", "SELECT * FROM `table` WHERE 1\nLIMIT 100;"),
            ("INSERT", "INSERT INTO `table` (`col1`, `col2`) VALUES ('val1', 'val2');"),
            ("UPDATE", "UPDATE `table` SET `col1` = 'val1' WHERE `id` = 1;"),
            ("DELETE", "DELETE FROM `table` WHERE `id` = 1;"),
            ("CREATE", "CREATE TABLE `table` (\n  `id` INT AUTO_INCREMENT PRIMARY KEY\n);"),
        ]:
            btn = QPushButton(label, snippet_bar)
            btn.setFixedHeight(20)
            btn.clicked.connect(lambda checked, s=sql: self._editor.insertPlainText(s))
            sb_layout.addWidget(btn)
        sb_layout.addStretch()
        ed_layout.addWidget(snippet_bar)

        # Ctrl+F shortcut for find
        from PySide6.QtGui import QShortcut
        self._find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._find_shortcut.activated.connect(lambda: self._find_bar.setVisible(not self._find_bar.isVisible()))

        # Ctrl+S shortcut for save
        self._save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self._save_shortcut.activated.connect(self._save_query)

        # Find/Replace bar
        self._find_bar = QWidget(editor_container)
        self._find_bar.setVisible(False)
        fb_layout = QHBoxLayout(self._find_bar)
        fb_layout.setContentsMargins(8, 3, 8, 3)
        fb_layout.setSpacing(4)

        self._find_input = QLineEdit(self._find_bar)
        self._find_input.setPlaceholderText(t("sql_editor.find_placeholder"))
        self._find_input.textChanged.connect(self._find_text)
        fb_layout.addWidget(self._find_input)

        self._replace_input = QLineEdit(self._find_bar)
        self._replace_input.setPlaceholderText(t("sql_editor.replace_placeholder"))
        fb_layout.addWidget(self._replace_input)

        btn_find_next = QPushButton("↓", self._find_bar)
        btn_find_next.setFixedSize(22, 22)
        btn_find_next.clicked.connect(lambda: self._find_text(self._find_input.text()))
        fb_layout.addWidget(btn_find_next)

        btn_replace = QPushButton(t("sql_editor.replace"), self._find_bar)
        btn_replace.clicked.connect(self._replace_text)
        fb_layout.addWidget(btn_replace)

        btn_replace_all = QPushButton(t("sql_editor.replace_all"), self._find_bar)
        btn_replace_all.clicked.connect(self._replace_all_text)
        fb_layout.addWidget(btn_replace_all)

        btn_close_find = QPushButton("✕", self._find_bar)
        btn_close_find.setFixedSize(22, 22)
        btn_close_find.clicked.connect(lambda: self._find_bar.setVisible(False))
        fb_layout.addWidget(btn_close_find)

        ed_layout.addWidget(self._find_bar)

        splitter.addWidget(editor_container)

        # -- Results area --
        results_widget = QWidget(splitter)
        r_layout = QVBoxLayout(results_widget)
        r_layout.setContentsMargins(0, 0, 0, 0)
        r_layout.setSpacing(0)

        # Results tab bar
        tab_bar = QWidget(results_widget)
        t_layout = QHBoxLayout(tab_bar)
        t_layout.setContentsMargins(8, 3, 8, 3)
        t_layout.setSpacing(8)

        self._result_tabs: dict[str, QLabel] = {}
        _tab_defs = [
            ("results", t("tab.results"), True),
            ("messages", t("tab.messages"), False),
            ("execution_plan", t("tab.execution_plan"), False),
        ]
        for key, text, active in _tab_defs:
            lbl = QLabel(text, tab_bar)
            if active:
                lbl.setObjectName("activeTab")
            lbl.mousePressEvent = lambda e, k=key: self._switch_result_tab(k)
            self._result_tabs[key] = lbl
            t_layout.addWidget(lbl)

        t_layout.addStretch()
        self._status_label = QLabel(t("status.ready"), tab_bar)
        t_layout.addWidget(self._status_label)

        btn_export = QPushButton("📤 " + t("menu.file.export"), tab_bar)
        btn_export.setFixedHeight(22)
        btn_export.clicked.connect(self._export_results)
        t_layout.addWidget(btn_export)

        r_layout.addWidget(tab_bar)

        # Stack: result table + plan text (one visible at a time)
        self._result_table = ResultTable(results_widget)
        r_layout.addWidget(self._result_table)

        self._plan_text = QTextEdit(results_widget)
        self._plan_text.setReadOnly(True)
        self._plan_text.setVisible(False)
        self._plan_text.setObjectName("monospaceText")
        r_layout.addWidget(self._plan_text)

        self._msg_text = QTextEdit(results_widget)
        self._msg_text.setReadOnly(True)
        self._msg_text.setVisible(False)
        self._msg_text.setObjectName("monospaceText")
        r_layout.addWidget(self._msg_text)

        splitter.addWidget(results_widget)
        splitter.setSizes([250, 250])

        layout.addWidget(splitter)

    def line_number_area_width(self) -> int:
        digits = len(str(self._editor.blockCount()))
        space = 10 + self._editor.fontMetrics().horizontalAdvance("9") * digits + 10
        return space

    def _update_line_number_area_width(self, _new_block_count: int) -> None:
        self._editor.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
        self._line_area.update()

    def _highlight_current_line(self) -> None:
        from PySide6.QtGui import QTextEdit
        extras = self._editor.selectedTexts()
        self._editor.setExtraSelections([])
        if not extras:
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#2a2d2e"))
            selection.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            selection.cursor = self._editor.textCursor()
            selection.cursor.clearSelection()
            self._editor.setExtraSelections([selection])

    def line_number_area_paint_event(self, event) -> None:
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor("#252526"))

        block = self._editor.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self._editor.blockBoundingGeometry(block).translated(self._editor.contentOffset()).top())
        bottom = top + round(self._editor.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(QColor("#858585"))
                painter.drawText(
                    0, top, self._line_area.width() - 5,
                    self._editor.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignRight, number,
                )
            block = block.next()
            top = bottom
            bottom = top + round(self._editor.blockBoundingRect(block).height())
            block_number += 1
        painter.end()

    def _load_databases(self) -> None:
        """Populate the database selector dropdown with available databases."""
        from open_navicat.dal.connection_pool import _loop as pool_loop
        from open_navicat.dal.connection_pool import connection_pool
        from open_navicat.models import DatabaseInfo

        connector = connection_pool.get(self._connection_id)
        if not connector:
            return

        try:
            dbs: list[DatabaseInfo] = pool_loop.run_until_complete(connector.list_databases())
            self._db_combo.clear()
            self._db_combo.addItem("(select database)", "")
            for db in dbs:
                self._db_combo.addItem(db.name, db.name)
                if db.name == self._database:
                    self._db_combo.setCurrentIndex(self._db_combo.count() - 1)

            # After loading databases, update completer with table names
            self._setup_completer(connector, dbs)
        except Exception as e:
            _log.warning("Failed to load databases: %s", e)

    def _setup_completer(self, connector, dbs) -> None:
        """Build autocomplete list: SQL keywords + table names + column names."""
        from PySide6.QtWidgets import QCompleter

        from open_navicat.config import config as _cfg
        from open_navicat.dal.connection_pool import _loop as pool_loop

        if not _cfg.get("code_completion.enabled", True):
            return

        words = [
            "SELECT", "FROM", "WHERE", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
            "DELETE", "CREATE", "ALTER", "DROP", "TABLE", "INDEX", "VIEW", "JOIN",
            "LEFT", "RIGHT", "INNER", "OUTER", "ON", "AND", "OR", "NOT", "IN",
            "LIKE", "BETWEEN", "IS", "NULL", "AS", "ORDER", "BY", "GROUP", "HAVING",
            "LIMIT", "OFFSET", "DISTINCT", "COUNT", "SUM", "AVG", "MAX", "MIN",
            "EXISTS", "UNION", "ALL", "CASE", "WHEN", "THEN", "ELSE", "END",
            "BEGIN", "COMMIT", "ROLLBACK", "INT", "VARCHAR", "TEXT", "BOOLEAN",
            "DATE", "DATETIME", "DECIMAL", "FLOAT", "BIGINT", "TINYINT",
            "PRIMARY", "KEY", "FOREIGN", "REFERENCES", "CASCADE", "RESTRICT",
            "GRANT", "REVOKE", "TRUNCATE", "EXPLAIN", "DESCRIBE", "SHOW",
            "USE", "DATABASE", "SCHEMA", "PROCEDURE", "FUNCTION", "TRIGGER",
            "IF", "ELSE", "WHILE", "LOOP", "THEN", "BEGIN", "END",
        ]

        # Add table names and column names from connected databases
        for db in dbs:
            try:
                tables = pool_loop.run_until_complete(connector.list_tables(db.name))
                for t in tables:
                    words.append(f"`{db.name}`.`{t}`")
                    words.append(t)
                    # Fetch column names for this table
                    try:
                        info = pool_loop.run_until_complete(
                            connector.get_table_info(db.name, t)
                        )
                        for col in info.columns:
                            words.append(col.name)
                            words.append(f"`{t}`.`{col.name}`")
                            words.append(f"{t}.{col.name}")
                    except Exception:
                        pass
            except Exception as e:
                _log.debug("Failed to list tables for %s: %s", db.name, e)

        self._completer = QCompleter(sorted(set(words)), self._editor)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._editor._completer = self._completer
        self._completer.setWidget(self._editor)
        self._completer.activated.connect(lambda text: self._insert_completion(text))

        # Override keyPress to trigger completer
        orig_key = self._editor.keyPressEvent
        def _key_press(event):
            if self._completer.popup().isVisible():
                if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return,
                                   Qt.Key.Key_Escape, Qt.Key.Key_Tab):
                    self._completer.popup().hide()
                    if event.key() == Qt.Key.Key_Tab:
                        return
            orig_key(event)
            cursor = self._editor.textCursor()
            block_text = cursor.block().text()
            # Get word under cursor
            pos = cursor.positionInBlock()
            prefix = ""
            for w in reversed(block_text[:pos].split()):
                prefix = w
                break
            if prefix and (prefix.isalnum() or prefix[0].isalnum() or '`' in prefix or '.' in prefix):
                self._completer.setCompletionPrefix(prefix)
                if self._completer.completionCount() > 0:
                    self._completer.complete()
        self._editor.keyPressEvent = _key_press

    # ---- actions ----

    def _switch_result_tab(self, tab_key: str) -> None:
        """Switch between result / message / plan tabs."""
        show_result = (tab_key == "results")
        show_msg = (tab_key == "messages")
        show_plan = (tab_key == "execution_plan")
        self._result_table.setVisible(show_result)
        self._msg_text.setVisible(show_msg)
        self._plan_text.setVisible(show_plan)
        for key, lbl in self._result_tabs.items():
            active = (key == tab_key)
            lbl.setStyleSheet(
                "font-size: 11px; color: #ccc; padding: 2px 8px; border-bottom: 2px solid #0078d4;"
                if active else
                "font-size: 11px; color: #888; padding: 2px 8px;"
            )

    @Slot()
    def _toggle_run_stop(self) -> None:
        if self._running:
            self._stop_execution()
        else:
            self._execute()

    def _set_running_state(self, running: bool) -> None:
        self._running = running
        self._btn_run.setMenu(self._run_menu if not running else None)
        if running:
            self._btn_run.setText("■ " + t("sql_editor.stop"))
            self._btn_run.setObjectName("dangerBtn")
            self._btn_run.setToolTip(t("sql_editor.stop_tip"))
            self._btn_ai_run.setText("■ " + t("sql_editor.stop"))
            self._btn_ai_run.setObjectName("dangerBtn")
        else:
            self._btn_run.setText("▶ " + t("menu.query.run"))
            self._btn_run.setObjectName("primaryBtn")
            self._btn_run.setToolTip(t("menu.query.run"))
            self._btn_ai_run.setText(t("sql_editor.run"))
            self._btn_ai_run.setObjectName("primaryBtn")
        self._btn_run.style().unpolish(self._btn_run)
        self._btn_run.style().polish(self._btn_run)
        self._btn_ai_run.style().unpolish(self._btn_ai_run)
        self._btn_ai_run.style().polish(self._btn_ai_run)

    def _execute(self) -> None:
        cursor = self._editor.textCursor()
        if cursor.hasSelection():
            sql = cursor.selectedText().strip()
        else:
            sql = self._editor.toPlainText().strip()
        if not sql:
            return

        connector = connection_pool.get(self._connection_id)
        if not connector:
            self._status_label.setText(t("sql_editor.status_disconnected"))
            return

        from open_navicat.dal.connection_pool import _loop as pool_loop

        self._cancelled = False
        self._set_running_state(True)
        self._status_label.setText(t("sql_editor.status_running"))

        db_name = self._db_combo.currentData() or ""
        if db_name:
            pool_loop.run_until_complete(connector.execute(f"USE `{db_name}`"))

        try:
            # Get thread ID for cancellation
            tid_result = pool_loop.run_until_complete(connector.execute("SELECT CONNECTION_ID()"))
            self._thread_id = tid_result.rows[0][0] if tid_result.rows else None

            if self._cancelled:
                return

            result: QueryResult = pool_loop.run_until_complete(connector.execute(sql))
            self._result = result
            self._display_result(result)
            self.executed.emit(result)

            if result.is_select:
                try:
                    explain_result = pool_loop.run_until_complete(connector.execute(f"EXPLAIN {sql}"))
                    self._explain_result = explain_result
                except Exception:
                    self._explain_result = None
            else:
                self._explain_result = None
        finally:
            self._set_running_state(False)
            self._thread_id = None

    @Slot()
    def _execute_all(self) -> None:
        sql = self._editor.toPlainText().strip()
        if not sql:
            return
        connector = connection_pool.get(self._connection_id)
        if not connector:
            self._status_label.setText(t("sql_editor.status_disconnected"))
            return
        import sqlparse

        from open_navicat.dal.connection_pool import _loop as pool_loop

        self._cancelled = False
        self._set_running_state(True)
        self._status_label.setText(t("sql_editor.status_running_multi"))

        try:
            # Get thread ID for cancellation
            tid_result = pool_loop.run_until_complete(connector.execute("SELECT CONNECTION_ID()"))
            self._thread_id = tid_result.rows[0][0] if tid_result.rows else None

            db_name = self._db_combo.currentData() or ""
            if db_name:
                pool_loop.run_until_complete(connector.execute(f"USE `{db_name}`"))

            statements = [s.strip() for s in sqlparse.split(sql) if s.strip()]
            results = []
            for stmt in statements:
                if self._cancelled:
                    break
                r = pool_loop.run_until_complete(connector.execute(stmt))
                results.append(r)
                if not r.success:
                    self._status_label.setText(t("sql_editor.status_error", error=r.error_message))
                    break
            if results:
                self._result = results[-1]
                self._display_result(results[-1])
                self._status_label.setText(t("sql_editor.status_executed", done=len(results), total=len(statements)))
            self.executed.emit(results[-1] if results else None)
        finally:
            self._set_running_state(False)
            self._thread_id = None

    def _insert_completion(self, text: str) -> None:
        """Insert a completion from the autocomplete popup."""
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveMode.KeepAnchor)
        # Remove partial word and insert completed word
        cursor.removeSelectedText()
        cursor.insertText(text.upper())

    def _export_sql_file(self) -> None:
        """Export current SQL editor content to a .sql file."""
        from PySide6.QtWidgets import QFileDialog
        sql = self._editor.toPlainText().strip()
        if not sql:
            return
        path, _ = QFileDialog.getSaveFileName(self, t("sql_editor.export_title"), "query.sql", t("sql_editor.sql_files"))
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(sql)
            self._status_label.setText(t("sql_editor.status_exported", path=path))

    def _export_results(self) -> None:
        """Export query results to CSV, Excel, or JSON file."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if not self._result or not self._result.columns:
            QMessageBox.information(self, t("sql_editor.export_title"), t("sql_editor.no_results"))
            return

        path, fmt = QFileDialog.getSaveFileName(
            self, t("sql_editor.export_title"), "query_result",
            "CSV 文件 (*.csv);;Excel 文件 (*.xlsx);;JSON 文件 (*.json)",
        )
        if not path:
            return

        cols = [c.name for c in self._result.columns]
        rows = self._result.rows

        try:
            if path.endswith(".xlsx"):
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                ws.title = "Query Result"
                ws.append(cols)
                for row in rows:
                    ws.append([v for v in row])
                wb.save(path)
            elif path.endswith(".json"):
                import json
                data = [dict(zip(cols, [str(v) if v is not None else None for v in row])) for row in rows]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                if not path.endswith(".csv"):
                    path += ".csv"
                import csv
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(cols)
                    for row in rows:
                        writer.writerow([str(v) if v is not None else "" for v in row])

            self._status_label.setText(t("sql_editor.status_exported", path=path))
        except Exception as e:
            QMessageBox.warning(self, t("sql_editor.export_title"), str(e))

    def _import_sql_file(self) -> None:
        """Import SQL from a .sql file into the editor."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, t("sql_editor.import_title"), "", t("sql_editor.sql_files"))
        if path:
            with open(path, "r", encoding="utf-8") as f:
                sql = f.read()
            self._editor.setPlainText(sql)
            self._status_label.setText(t("sql_editor.status_loaded", path=path))

    def _show_shortcuts(self) -> None:
        """Show keyboard shortcuts help dialog."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout
        dlg = QDialog(self.window())
        dlg.setWindowTitle(t("sql_editor.shortcuts_title"))
        dlg.setMinimumWidth(400)
        layout = QVBoxLayout(dlg)
        shortcuts = [
            ("Ctrl+Enter", t("sql_editor.shortcut_run_sql")),
            ("Ctrl+Shift+Enter", t("sql_editor.shortcut_run_all")),
            ("Ctrl+F", t("sql_editor.shortcut_find")),
            ("Ctrl+N", t("sql_editor.shortcut_new_conn")),
            ("Ctrl+T", t("sql_editor.shortcut_new_query")),
            ("Ctrl+Q", t("sql_editor.shortcut_exit")),
            ("Ctrl+I", t("sql_editor.shortcut_ai")),
            ("Ctrl+Return", t("sql_editor.shortcut_run_query")),
        ]
        for key, desc in shortcuts:
            layout.addWidget(QLabel(f"  {key:20s}  {desc}", dlg))
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dlg)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.exec()

    @Slot(QPoint)
    def _show_editor_context_menu(self, pos) -> None:
        """Right-click context menu in the SQL editor."""
        menu = self._editor.createStandardContextMenu()
        # Translate standard Qt actions
        _std_map = {
            "&Undo": t("editor.undo"),
            "&Redo": t("editor.redo"),
            "Cu&t": t("editor.cut"),
            "&Copy": t("editor.copy"),
            "&Paste": t("editor.paste"),
            "Delete": t("editor.delete"),
            "Select &All": t("editor.select_all"),
        }
        for action in menu.actions():
            txt = action.text()
            if txt in _std_map:
                action.setText(_std_map[txt])
        menu.addSeparator()

        # Run selected
        act_run = menu.addAction(t("context.run_selected"))
        act_run.triggered.connect(self._execute)

        # Save as snippet
        act_save = menu.addAction(t("context.create_snippet"))
        act_save.triggered.connect(self._save_as_snippet)

        menu.addSeparator()

        # Copy with quotes submenu
        copy_menu = menu.addMenu(t("context.copy_with_quotes"))
        cursor = self._editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            copy_menu.addAction(t("context.copy_double_quotes")).triggered.connect(
                lambda: QApplication.clipboard().setText(f'"{text}"'))
            copy_menu.addAction(t("context.copy_single_quotes")).triggered.connect(
                lambda: QApplication.clipboard().setText(f"'{text}'"))
            copy_menu.addAction(t("context.copy_backtick_quotes")).triggered.connect(
                lambda: QApplication.clipboard().setText(f"`{text}`"))

        menu.addSeparator()

        # Beautify
        menu.addAction(t("context.beautify_sql")).triggered.connect(self._beautify)

        # Select current statement
        menu.addAction(t("context.select_current_stmt")).triggered.connect(self._select_current_statement)

        menu.exec(self._editor.viewport().mapToGlobal(pos))

    def _select_current_statement(self) -> None:
        """Select the SQL statement under the cursor."""
        text = self._editor.toPlainText()
        cursor = self._editor.textCursor()
        pos = cursor.position()
        start = max(text.rfind(";", 0, pos), 0)
        if start > 0:
            start += 1
        end = text.find(";", pos)
        if end < 0:
            end = len(text)
        else:
            end += 1
        cursor.setPosition(start)
        cursor.movePosition(cursor.MoveOperation.Right, cursor.MoveMode.KeepAnchor, end - start)
        self._editor.setTextCursor(cursor)

    @Slot()
    def _beautify(self) -> None:
        import sqlparse
        raw = self._editor.toPlainText()
        formatted = sqlparse.format(raw, reindent=True, keyword_case="upper")
        self._editor.setPlainText(formatted)

    def _simplify(self) -> None:
        import sqlparse
        raw = self._editor.toPlainText()
        simplified = sqlparse.format(raw, reindent=False, keyword_case="upper")
        self._editor.setPlainText(simplified)

    def _open_compare_dialog(self) -> None:
        from open_navicat.ui.dialogs.query_compare_dialog import QueryCompareDialog
        dlg = QueryCompareDialog(sql_a=self._editor.toPlainText(), sql_b="", parent=self.window())
        dlg.exec()

    # ---- snippets ----

    def _refresh_snippet_menu(self) -> None:
        self._snippet_menu.clear()
        snippets = local_db.list_snippets()
        for snip in snippets:
            act = self._snippet_menu.addAction(snip["name"])
            act.setToolTip(snip.get("description", "") or snip["sql_text"][:80])
            act.triggered.connect(
                lambda checked, s=snip["sql_text"]: self._insert_snippet_with_vars(s)
            )
        if snippets:
            self._snippet_menu.addSeparator()
        # Built-in templates as fallback
        for label, sql in [
            ("SELECT", "SELECT * FROM `table` WHERE 1\nLIMIT 100;"),
            ("INSERT", "INSERT INTO `table` (`col1`, `col2`) VALUES ('val1', 'val2');"),
            ("UPDATE", "UPDATE `table` SET `col1` = 'val1' WHERE `id` = 1;"),
            ("DELETE", "DELETE FROM `table` WHERE `id` = 1;"),
            ("CREATE TABLE", "CREATE TABLE `table` (\n  `id` INT AUTO_INCREMENT PRIMARY KEY\n);"),
        ]:
            act = self._snippet_menu.addAction(f"📦 {label}")
            act.triggered.connect(lambda checked, s=sql: self._editor.insertPlainText(s))

    def _insert_snippet_with_vars(self, sql: str) -> None:
        """Insert snippet, prompting for {{variable}} placeholders."""
        import re
        vars_found = re.findall(r"\{\{(\w+)\}\}", sql)
        if vars_found:
            from PySide6.QtWidgets import QInputDialog
            values = {}
            for var_name in vars_found:
                val, ok = QInputDialog.getText(
                    self, t("snippet.variable_prompt"), f"{var_name}:",
                )
                if ok:
                    values[var_name] = val
                else:
                    return
            for var_name, val in values.items():
                sql = sql.replace(f"{{{{{var_name}}}}}", val)
        self._editor.insertPlainText(sql)

    def _open_snippet_manager(self) -> None:
        from open_navicat.ui.dialogs.snippet_manager import SnippetManagerDialog
        dlg = SnippetManagerDialog(self.window())
        dlg.exec()
        self._refresh_snippet_menu()

    def _save_as_snippet(self) -> None:
        """Save selected text (or entire editor) as a reusable snippet."""
        cursor = self._editor.textCursor()
        text = cursor.selectedText() if cursor.hasSelection() else self._editor.toPlainText()
        text = text.strip()
        if not text:
            return
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        name, ok = QInputDialog.getText(
            self, t("context.create_snippet"), t("snippet.name"),
            QLineEdit.EchoMode.Normal, "my_snippet",
        )
        if ok and name:
            from open_navicat.dal.local_config import local_db
            local_db.save_snippet(name.strip(), text)
            self._refresh_snippet_menu()

    # ---- find/replace ----

    def _find_text(self, text: str) -> None:
        if not text:
            return
        cursor = self._editor.textCursor()
        # Start from current position, search forward
        found = self._editor.find(text)
        if not found:
            # Wrap around
            cursor.movePosition(cursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)
            self._editor.find(text)

    def _replace_text(self) -> None:
        find = self._find_input.text()
        replace = self._replace_input.text()
        if not find:
            return
        cursor = self._editor.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == find:
            cursor.insertText(replace)
        self._find_text(find)

    def _replace_all_text(self) -> None:
        find = self._find_input.text()
        replace = self._replace_input.text()
        if not find:
            return
        text = self._editor.toPlainText()
        text = text.replace(find, replace)
        self._editor.setPlainText(text)

    def show_find_replace(self) -> None:
        """Show find/replace bar and focus the find input."""
        self._find_bar.setVisible(True)
        self._find_input.setFocus()
        self._find_input.selectAll()

    # ---- save/load queries ----

    @Slot()
    def _save_query(self) -> None:
        """Save the current SQL query — silent update if existing, ask name if new."""
        sql = self._editor.toPlainText().strip()
        if not sql:
            return

        # If editing an existing query, silently update it
        if self._current_query_id:
            q = local_db.get_query(self._current_query_id)
            if q:
                local_db.save_query(self._connection_id, self._database, q["name"], sql)
                self._status_label.setText(t("sql_editor.status_updated", name=q['name']))
                self._refresh_query_tree()
                return

        # New query — ask for name
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        name, ok = QInputDialog.getText(
            self, t("sql_editor.save_title"), t("sql_editor.save_prompt"), QLineEdit.EchoMode.Normal,
            t("sql_editor.save_default_name", n=len(local_db.list_queries(self._connection_id, self._database)) + 1)
        )
        if ok and name:
            name = name.strip()
            saved_id = local_db.save_query(self._connection_id, self._database, name, sql)
            self._current_query_id = saved_id
            self._status_label.setText(t("sql_editor.status_saved", name=name))
            self._refresh_query_tree()

    def _refresh_query_tree(self) -> None:
        """Refresh the ObjectBrowser query tree after save."""
        from open_navicat.ui.widgets.object_browser import ObjectBrowser
        mw = self.window()
        if not mw:
            return
        browser = mw.findChild(ObjectBrowser)
        if not browser:
            return
        for i in range(browser.topLevelItemCount()):
            conn_item = browser.topLevelItem(i)
            if conn_item and conn_item.data(0, Qt.ItemDataRole.UserRole).get("id") == self._connection_id:
                for j in range(conn_item.childCount()):
                    db_item = conn_item.child(j)
                    if db_item and db_item.data(0, Qt.ItemDataRole.UserRole).get("name") == self._database:
                        browser._expand_database(db_item)
                        break
                break

    @Slot()
    def _open_saved_query(self) -> None:
        """Open the query manager panel in the workspace."""
        mw = self.window()
        if hasattr(mw, '_workspace'):
            from open_navicat.ui.widgets.query_manager import QueryManagerWidget
            qm = QueryManagerWidget(self._connection_id, self._database, parent=mw._workspace)
            idx = mw._workspace.addTab(qm, t("sql_editor.query_manager_tab", database=self._database))
            mw._workspace.setCurrentIndex(idx)

    def _display_result(self, result: QueryResult) -> None:
        # Build table name for right-click copy functions
        tbl = ""
        if self._result and self._result.columns:
            tn = self._result.columns[0].table_name
            if tn:
                tbl = f"{self._database}.{tn}"

        # Try to extract table name from SQL as fallback
        if not tbl:
            sql = self._editor.toPlainText().strip()
            import re
            # Match FROM table, UPDATE table, INSERT INTO table, DELETE FROM table
            m = re.search(
                r"(?:FROM\s+|UPDATE\s+|INSERT\s+(?:IGNORE\s+)?INTO\s+|DELETE\s+FROM\s+)`?(\w+)`?",
                sql, re.IGNORECASE
            )
            if m:
                tbl = f"{self._database}.{m.group(1)}"

        self._result_table.set_table_meta(
            tbl or self._database,
            [c.name for c in result.columns] if result.columns else []
        )

        if not result.success:
            self._status_label.setText(f"❌ {result.error_message}")
            self._result_table.setRowCount(0)
            self._result_table.setColumnCount(0)
            return

        if result.is_select:
            self._result_table.setColumnCount(len(result.columns))
            self._result_table.setHorizontalHeaderLabels([c.name for c in result.columns])
            self._result_table.setRowCount(len(result.rows))
            for row_idx, row in enumerate(result.rows):
                for col_idx, val in enumerate(row):
                    display = str(val) if val is not None else "(NULL)"
                    item = QTableWidgetItem(display)
                    if val is None:
                        item.setForeground(QColor("#888"))
                        item.setFont(QFont(self.font().family(), italic=True))
                    self._result_table.setItem(row_idx, col_idx, item)
            self._result_table.horizontalHeader().resizeSections()
            self._status_label.setText(
                t("sql_editor.status_select_result", rows=result.row_count, ms=f"{result.execution_time_ms:.1f}")
            )
        else:
            self._result_table.setRowCount(0)
            self._result_table.setColumnCount(0)
            msg = t("sql_editor.status_affected", rows=result.affected_rows)
            if result.insert_id:
                msg += f", {t('sql_editor.status_last_id', id=result.insert_id)}"
            msg += f" ({result.execution_time_ms:.1f}ms)"
            self._status_label.setText(msg)

    def _ai_action(self, mode: str) -> None:
        sql = self._editor.toPlainText().strip()
        prompts = {
            "explain": t("sql_editor.ai_prompt_explain", sql=sql) if sql else t("sql_editor.ai_prompt_explain_general"),
            "optimize": t("sql_editor.ai_prompt_optimize", sql=sql),
            "fix": t("sql_editor.ai_prompt_fix", sql=sql),
            "nl": "",
        }
        prompt = prompts.get(mode, "")
        if mode == "nl":
            prompt = t("sql_editor.ai_prompt_query")
        self.ai_requested.emit(prompt)

    # ---- new toolbar actions ----

    def _execute_selected(self) -> None:
        cursor = self._editor.textCursor()
        selected = cursor.selectedText().strip()
        if not selected:
            self._execute()
            return
        connector = connection_pool.get(self._connection_id)
        if not connector:
            self._status_label.setText(t("sql_editor.status_disconnected"))
            return
        from open_navicat.dal.connection_pool import _loop as pool_loop
        result = pool_loop.run_until_complete(connector.execute(selected))
        self._result = result
        self._display_result(result)
        self.executed.emit(result)

    def _execute_explain(self) -> None:
        sql = self._editor.toPlainText().strip()
        if not sql:
            sql = self._editor.textCursor().selectedText()
        if not sql:
            return
        connector = connection_pool.get(self._connection_id)
        if connector:
            from open_navicat.dal.connection_pool import _loop as pool_loop
            explain_sql = f"EXPLAIN {sql}"
            result = pool_loop.run_until_complete(connector.execute(explain_sql))
            self._result = result
            # Render EXPLAIN output as plan text
            lines = []
            for row in result.rows:
                lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
            self._plan_text.setPlainText("\n".join(lines))
            self._switch_result_tab("execution_plan")

    def _stop_execution(self) -> None:
        if not self._running:
            return
        self._cancelled = True
        connector = connection_pool.get(self._connection_id)
        if connector and self._thread_id:
            try:
                from open_navicat.dal.connection_pool import _loop as pool_loop
                pool_loop.run_until_complete(
                    connector.execute(f"KILL QUERY {self._thread_id}")
                )
            except Exception as e:
                _log.debug("Failed to kill query: %s", e)
        self._set_running_state(False)

    # ---- public accessors ----

    def sql(self) -> str:
        return self._editor.toPlainText()

    def set_sql(self, text: str) -> None:
        self._editor.setPlainText(text)

    @property
    def result(self) -> QueryResult | None:
        return self._result
