"""Visual drag-and-drop query builder — canvas + table boxes + join lines + SQL generation."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from open_navicat.i18n import t
from open_navicat.models.table_schema import ColumnInfo, ForeignKeyInfo
from open_navicat.services.metadata_service import metadata_service

logger = logging.getLogger("opennavicat.query_builder")


class JoinLine(QGraphicsLineItem):
    """A join line between two table nodes on the canvas."""

    def __init__(self, src: str, src_col: str, dst: str, dst_col: str, parent=None):
        super().__init__(parent)
        self._src = src
        self._src_col = src_col
        self._dst = dst
        self._dst_col = dst_col
        pen = QPen(QColor("#4a9eff"), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(-1)

    def update_pos(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.setLine(x1, y1, x2, y2)


class TableBox(QWidget):
    """A table card shown on the canvas — title + draggable column list."""

    col_toggled = Signal(str, str, bool)  # table, column, checked

    def __init__(self, table: str, columns: list[ColumnInfo], parent=None):
        super().__init__(parent)
        self.table = table
        self._cols = columns
        self._setup()

    def _setup(self) -> None:
        self.setObjectName("tableBox")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        title = QLabel(f"  {self.table}")
        title.setObjectName("tableBoxTitle")
        layout.addWidget(title)
        for col in self._cols:
            row = QWidget()
            row.setObjectName("tableBoxRow")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 2, 6, 2)
            rl.setSpacing(4)
            cb = QCheckBox()
            cb.stateChanged.connect(lambda checked, c=col.name: self.col_toggled.emit(self.table, c, bool(checked)))
            rl.addWidget(cb)
            lbl = QLabel(f"{col.name}  <span style='color:#888'>{col.data_type}</span>")
            lbl.setTextFormat(Qt.TextFormat.RichText)
            rl.addWidget(lbl, 1)
            layout.addWidget(row)
        self.setFixedWidth(220)


class QueryBuilderWidget(QWidget):
    """Visual SQL query builder with drag-drop canvas."""

    sql_generated = Signal(str)  # emitted when user clicks Execute

    def __init__(self, connection_id: str, database: str, parent=None):
        super().__init__(parent)
        self._conn_id = connection_id
        self._database = database

        # State
        self._table_nodes: dict[str, QGraphicsProxyWidget] = {}
        self._table_data: dict[str, list[ColumnInfo]] = {}
        self._joins: list[JoinLine] = []
        self._join_info: list[tuple[str, str, str, str]] = []  # (t1, c1, t2, c2)
        self._selected_cols: set[tuple[str, str]] = set()
        self._node_positions: dict[str, tuple[float, float]] = {}
        self._drag_start: dict[str, tuple[float, float]] = {}

        self._setup_ui()
        self._load_tables()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = QFrame()
        toolbar.setObjectName("toolbarPanel")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)

        lbl = QLabel(f"数据库: {self._database}")
        lbl.setStyleSheet("font-weight:bold;color:#ccc;")
        tb_layout.addWidget(lbl)

        tb_layout.addStretch()

        self._btn_gen = QPushButton("生成 SQL")
        self._btn_gen.clicked.connect(self._generate_sql)
        tb_layout.addWidget(self._btn_gen)

        self._btn_exec = QPushButton("执行")
        self._btn_exec.setProperty("class", "primary")
        self._btn_exec.clicked.connect(self._execute)
        tb_layout.addWidget(self._btn_exec)

        self._btn_clear = QPushButton("清空画布")
        self._btn_clear.clicked.connect(self._clear_canvas)
        tb_layout.addWidget(self._btn_clear)

        main_layout.addWidget(toolbar)

        # Body: table list left, canvas center, props right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left — table list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("表 (双击添加)"))
        self._table_list = QListWidget()
        self._table_list.itemDoubleClicked.connect(self._add_table_to_canvas)
        left_layout.addWidget(self._table_list)
        splitter.addWidget(left_panel)

        # Center — canvas
        self._scene = QGraphicsScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHints(QPainter.RenderHint.Antialiasing)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setAcceptDrops(True)
        self._view.setObjectName("queryBuilderCanvas")
        splitter.addWidget(self._view)

        # Right — properties + SQL preview
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)

        # Selected columns
        grp_cols = QGroupBox("输出列")
        cols_layout = QVBoxLayout(grp_cols)
        self._cols_text = QTextEdit()
        self._cols_text.setReadOnly(True)
        self._cols_text.setMaximumHeight(80)
        cols_layout.addWidget(self._cols_text)
        right_layout.addWidget(grp_cols)

        # Conditions
        grp_where = QGroupBox("条件 (WHERE)")
        where_layout = QVBoxLayout(grp_where)
        self._where_edit = QTextEdit()
        self._where_edit.setPlaceholderText("例如: status = 'active'")
        self._where_edit.setMaximumHeight(60)
        where_layout.addWidget(self._where_edit)
        right_layout.addWidget(grp_where)

        # Sort
        grp_sort = QGroupBox("排序 (ORDER BY)")
        sort_layout = QVBoxLayout(grp_sort)
        self._order_edit = QLineEdit()
        self._order_edit.setPlaceholderText("例如: created_at DESC")
        sort_layout.addWidget(self._order_edit)
        right_layout.addWidget(grp_sort)

        # Group By
        grp_group = QGroupBox("分组 (GROUP BY)")
        group_layout = QVBoxLayout(grp_group)
        self._group_edit = QLineEdit()
        self._group_edit.setPlaceholderText("例如: category_id")
        group_layout.addWidget(self._group_edit)
        right_layout.addWidget(grp_group)

        # HAVING
        grp_having = QGroupBox("HAVING")
        having_layout = QVBoxLayout(grp_having)
        self._having_edit = QLineEdit()
        self._having_edit.setPlaceholderText("例如: COUNT(*) > 5")
        having_layout.addWidget(self._having_edit)
        right_layout.addWidget(grp_having)

        right_layout.addStretch()

        # SQL preview
        lbl_sql = QLabel("SQL 预览")
        right_layout.addWidget(lbl_sql)
        self._sql_preview = QTextEdit()
        self._sql_preview.setReadOnly(True)
        self._sql_preview.setMaximumHeight(120)
        self._sql_preview.setStyleSheet("font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 11px;")
        right_layout.addWidget(self._sql_preview)

        splitter.addWidget(right_panel)
        splitter.setSizes([180, 500, 280])
        main_layout.addWidget(splitter, 1)

    def _load_tables(self) -> None:
        try:
            tables = metadata_service.list_tables(self._conn_id, self._database)
            for t_name in tables:
                self._table_list.addItem(t_name)
        except Exception as e:
            logger.warning("Failed to list tables: %s", e)

    def _add_table_to_canvas(self, item) -> None:
        t_name = item.text()
        if t_name in self._table_nodes:
            return
        try:
            info = metadata_service.get_table_info(self._conn_id, self._database, t_name)
            if not info:
                return
        except Exception as e:
            logger.warning("Failed to get table info for %s: %s", t_name, e)
            return

        self._table_data[t_name] = info.columns
        box = TableBox(t_name, info.columns)
        box.col_toggled.connect(self._on_col_toggled)
        proxy = self._scene.addWidget(box)
        proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        proxy.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)

        # Position
        x = 20 + len(self._table_nodes) * 250
        y = 20
        proxy.setPos(x, y)
        self._table_nodes[t_name] = proxy
        self._node_positions[t_name] = (x, y)

        # Auto-detect joins
        self._auto_join(t_name, info.foreign_keys)

    def _on_col_toggled(self, table: str, col: str, checked: bool) -> None:
        key = (table, col)
        if checked:
            self._selected_cols.add(key)
        else:
            self._selected_cols.discard(key)
        self._update_cols_text()

    def _update_cols_text(self) -> None:
        if not self._selected_cols:
            self._cols_text.setText("* (所有列)")
            return
        cols = sorted(f"{tbl}.{c}" for tbl, c in self._selected_cols)
        self._cols_text.setText("\n".join(cols))

    def _auto_join(self, table: str, fks: list[ForeignKeyInfo]) -> None:
        for fk in fks:
            ref = fk.ref_table
            if ref in self._table_nodes:
                self._add_join(table, fk.column, ref, fk.ref_column)
            else:
                # Try resolving multi-db refs — ponytail: simple FK match
                for existing_t in self._table_nodes:
                    if existing_t == ref or existing_t.endswith(f".{ref}"):
                        self._add_join(table, fk.column, existing_t, fk.ref_column)
                        break

    def _add_join(self, t1: str, c1: str, t2: str, c2: str) -> None:
        # Avoid duplicates
        for jt1, jc1, jt2, jc2 in self._join_info:
            if {jt1, jt2} == {t1, t2}:
                return
        self._join_info.append((t1, c1, t2, c2))
        self._redraw_join_lines()

    def _redraw_join_lines(self) -> None:
        # Remove old lines
        for jl in self._joins:
            self._scene.removeItem(jl)
        self._joins.clear()

        for t1, c1, t2, c2 in self._join_info:
            n1 = self._table_nodes.get(t1)
            n2 = self._table_nodes.get(t2)
            if not n1 or not n2:
                continue
            line = JoinLine(t1, c1, t2, c2)
            self._update_line_pos(line, n1, n2)
            self._scene.addItem(line)
            self._joins.append(line)

    def _update_line_pos(self, line: JoinLine, n1: QGraphicsProxyWidget, n2: QGraphicsProxyWidget) -> None:
        r1 = n1.sceneBoundingRect()
        r2 = n2.sceneBoundingRect()
        x1 = r1.right()
        y1 = r1.center().y()
        x2 = r2.left()
        y2 = r2.center().y()
        line.update_pos(x1, y1, x2, y2)

    def _generate_sql(self) -> str:
        if not self._table_nodes:
            self._sql_preview.setText("-- 请先添加表到画布")
            return ""

        # SELECT clause
        if self._selected_cols:
            select_cols = ", ".join(f"`{tbl}`.`{c}`" for tbl, c in sorted(self._selected_cols))
        else:
            select_cols = "*"

        # FROM clause
        tables = list(self._table_nodes.keys())

        # JOIN clause (uses JOIN syntax if joins exist)
        use_join = len(self._join_info) > 0
        if use_join:
            from_clause = f"`{tables[0]}`"
            join_clauses = []
            for t1, c1, t2, c2 in self._join_info:
                join_clauses.append(f"LEFT JOIN `{t2}` ON `{t1}`.`{c1}` = `{t2}`.`{c2}`")
            from_clause += "\n" + "\n".join(join_clauses)
        else:
            from_clause = ", ".join(f"`{tbl}`" for tbl in tables)

        sql = f"SELECT {select_cols}\nFROM {from_clause}"

        # WHERE
        where_text = self._where_edit.toPlainText().strip()
        if where_text:
            sql += f"\nWHERE {where_text}"

        # GROUP BY
        group_text = self._group_edit.text().strip()
        if group_text:
            sql += f"\nGROUP BY {group_text}"

        # HAVING
        having_text = self._having_edit.text().strip()
        if having_text:
            sql += f"\nHAVING {having_text}"

        # ORDER BY
        order_text = self._order_edit.text().strip()
        if order_text:
            sql += f"\nORDER BY {order_text}"

        sql += ";"
        self._sql_preview.setText(sql)
        return sql

    def _execute(self) -> None:
        sql = self._generate_sql()
        if sql:
            self.sql_generated.emit(sql)

    def _clear_canvas(self) -> None:
        for proxy in self._table_nodes.values():
            self._scene.removeItem(proxy)
        for jl in self._joins:
            self._scene.removeItem(jl)
        self._table_nodes.clear()
        self._table_data.clear()
        self._joins.clear()
        self._join_info.clear()
        self._selected_cols.clear()
        self._cols_text.clear()
        self._sql_preview.clear()
