"""ER Model Designer — visual database schema design with QGraphicsScene.

Features:
- Drag-and-drop entity placement on an infinite canvas
- Column management (name, type, PK, nullable, default, comment)
- Relationship lines (1:1, 1:N, M:N) between entities
- Forward engineering (model → DDL)
- Reverse engineering (database → model)
"""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import (
    QLineF,
    QPointF,
    QRectF,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
    QVBoxLayout,
    QWidget,
)

from open_navicat.models.table_schema import (
    ColumnInfo,
    ForeignKeyInfo,
    IndexInfo,
    TableInfo,
)

# ── Constants ─────────────────────────────────────────────────────────────


class Style:
    BG_CANVAS = QColor("#1e1e1e")
    BG_ENTITY_HEADER = QColor("#2d2d30")
    BG_ENTITY_BODY = QColor("#252526")
    BORDER_ENTITY = QColor("#3c3c3c")
    BORDER_SELECTED = QColor("#0078d4")
    TEXT_HEADER = QColor("#ffffff")
    TEXT_COLUMN = QColor("#cccccc")
    TEXT_PK = QColor("#f0c040")
    TEXT_FK = QColor("#4ec9b0")
    LINE_RELATION = QColor("#6a9955")
    LINE_RELATION_1N = QColor("#dcdcaa")
    BRUSH_ENTITY = QColor("#2d2d30")

    FONT_HEADER = QFont("Segoe UI", 11, QFont.Weight.Bold)
    FONT_COLUMN = QFont("Consolas", 9)
    FONT_PK_ICON = QFont("Segoe UI", 9, QFont.Weight.Bold)

    ENTITY_WIDTH = 200
    HEADER_HEIGHT = 36
    ROW_HEIGHT = 22
    CORNER_RADIUS = 8


# ── Data models ───────────────────────────────────────────────────────────


class ModelEntity:
    """In-memory entity for the ER diagram canvas."""
    def __init__(self, name: str = "", comment: str = "") -> None:
        self.name = name
        self.comment = comment
        self.columns: list[ModelColumn] = []
        self.color: str = "#2d2d30"

    def to_table_info(self, database: str = "") -> TableInfo:
        """Convert to TableInfo for DDL generation."""
        pk_cols = [c for c in self.columns if c.is_primary_key]
        info = TableInfo(
            name=self.name,
            database=database,
            columns=[
                ColumnInfo(
                    name=c.name,
                    data_type=c.data_type,
                    char_max_length=c.char_max_length,
                    nullable=c.nullable,
                    default=c.default,
                    is_primary_key=c.is_primary_key,
                    is_auto_increment=c.is_auto_increment,
                    comment=c.comment,
                )
                for c in self.columns
            ],
        )
        # PK index
        if pk_cols:
            info.indexes.append(IndexInfo(
                name="PRIMARY",
                columns=[c.name for c in pk_cols],
                is_primary=True,
                is_unique=True,
            ))
        return info

    @staticmethod
    def from_table_info(info: TableInfo) -> ModelEntity:
        """Create ModelEntity from existing TableInfo (reverse engineering)."""
        entity = ModelEntity(name=info.name, comment=info.comment)
        entity.columns = [
            ModelColumn(
                name=c.name,
                data_type=c.data_type,
                char_max_length=c.char_max_length,
                nullable=c.nullable,
                default=str(c.default) if c.default is not None else "",
                is_primary_key=c.is_primary_key,
                is_auto_increment=c.is_auto_increment,
                comment=c.comment,
            )
            for c in info.columns
        ]
        # Also pick up FK info from metadata if needed
        return entity


class ModelColumn:
    """A column in an ER entity."""
    def __init__(self, name: str = "", data_type: str = "VARCHAR",
                 char_max_length: Optional[int] = 255,
                 nullable: bool = True,
                 default: str = "",
                 is_primary_key: bool = False,
                 is_auto_increment: bool = False,
                 comment: str = "") -> None:
        self.name = name
        self.data_type = data_type
        self.char_max_length = char_max_length
        self.nullable = nullable
        self.default = default
        self.is_primary_key = is_primary_key
        self.is_auto_increment = is_auto_increment
        self.comment = comment
        self.is_foreign_key = False


class ModelRelation:
    """Relationship between two entities."""
    def __init__(self, from_entity: str, to_entity: str,
                 from_column: str = "", to_column: str = "",
                 relation_type: str = "1:N") -> None:
        self.from_entity = from_entity
        self.to_entity = to_entity
        self.from_column = from_column
        self.to_column = to_column
        self.relation_type = relation_type  # 1:1, 1:N, M:N


# ── Graphics Items ────────────────────────────────────────────────────────


class EntityItem(QGraphicsItem):
    """A rounded-rectangle entity box on the ER canvas."""

    def __init__(self, entity: ModelEntity, pos: QPointF = QPointF(0, 0)) -> None:
        super().__init__()
        self._entity = entity
        self._width = Style.ENTITY_WIDTH
        self._selected = False
        self._model_level = "physical"  # conceptual | logical | physical
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setPos(pos)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setZValue(10)

    def entity(self) -> ModelEntity:
        return self._entity

    def set_model_level(self, level: str) -> None:
        self._model_level = level
        self.prepareGeometryChange()

    def boundingRect(self) -> QRectF:
        h = self._header_height() + self._body_height()
        return QRectF(0, 0, self._width, h).adjusted(-2, -2, 2, 2)

    def _header_height(self) -> int:
        return Style.HEADER_HEIGHT

    def _body_height(self) -> int:
        return max(1, len(self._entity.columns)) * Style.ROW_HEIGHT + 8

    def total_height(self) -> int:
        return self._header_height() + self._body_height()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        rect = self.boundingRect().adjusted(1, 1, -1, -1)
        hh = self._header_height()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Shadow
        shadow_rect = rect.translated(3, 3)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(shadow_rect, Style.CORNER_RADIUS, Style.CORNER_RADIUS)

        # Header gradient
        header_rect = QRectF(rect.x(), rect.y(), rect.width(), hh)
        grad = QLinearGradient(header_rect.topLeft(), header_rect.topRight())
        grad.setColorAt(0, QColor("#2d2d30"))
        grad.setColorAt(1, QColor("#383838"))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(Style.BORDER_ENTITY, 1))
        painter.drawRoundedRect(rect, Style.CORNER_RADIUS, Style.CORNER_RADIUS)

        # Paint header area separately (no corner radius on bottom)
        painter.setClipRect(header_rect)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(Style.BORDER_ENTITY, 1))
        painter.drawRoundedRect(rect, Style.CORNER_RADIUS, Style.CORNER_RADIUS)
        painter.setClipping(False)

        # Table name
        painter.setFont(Style.FONT_HEADER)
        painter.setPen(Style.TEXT_HEADER)
        name = self._entity.name or "New Table"
        painter.drawText(header_rect.adjusted(12, 0, -12, 0),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         name)

        # Column rows
        painter.setFont(Style.FONT_COLUMN)
        body_rect = QRectF(rect.x(), rect.y() + hh, rect.width(), rect.height() - hh)
        painter.setBrush(Style.BG_ENTITY_BODY)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(body_rect)

        for i, col in enumerate(self._entity.columns):
            y = rect.y() + hh + 4 + i * Style.ROW_HEIGHT
            col_rect = QRectF(rect.x() + 8, y, rect.width() - 16, Style.ROW_HEIGHT)

            if self._model_level == "conceptual":
                painter.setPen(Style.TEXT_COLUMN)
                painter.drawText(col_rect,
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 f"  {col.name}")
            elif self._model_level == "logical":
                if col.is_primary_key:
                    painter.setPen(Style.TEXT_PK)
                    painter.drawText(QRectF(rect.x() + 8, y, 24, Style.ROW_HEIGHT), "PK")
                    painter.setPen(Style.TEXT_COLUMN)
                    painter.drawText(QRectF(rect.x() + 32, y, rect.width() - 40, Style.ROW_HEIGHT),
                                     f"{col.name}")
                elif col.is_foreign_key:
                    painter.setPen(Style.TEXT_FK)
                    painter.drawText(QRectF(rect.x() + 8, y, 24, Style.ROW_HEIGHT), "FK")
                    painter.setPen(Style.TEXT_COLUMN)
                    painter.drawText(QRectF(rect.x() + 32, y, rect.width() - 40, Style.ROW_HEIGHT),
                                     f"{col.name}")
                else:
                    painter.setPen(Style.TEXT_COLUMN)
                    painter.drawText(col_rect,
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     f"  {col.name}")
            else:
                # physical — full detail
                if col.is_primary_key:
                    painter.setPen(Style.TEXT_PK)
                    painter.drawText(QRectF(rect.x() + 8, y, 24, Style.ROW_HEIGHT),
                                     "PK")
                    painter.setPen(Style.TEXT_COLUMN)
                    painter.drawText(QRectF(rect.x() + 32, y, rect.width() - 40, Style.ROW_HEIGHT),
                                     f"{col.name}  {col.data_type}")
                elif col.is_foreign_key:
                    painter.setPen(Style.TEXT_FK)
                    painter.drawText(QRectF(rect.x() + 8, y, 24, Style.ROW_HEIGHT),
                                     "FK")
                    painter.setPen(Style.TEXT_COLUMN)
                    painter.drawText(QRectF(rect.x() + 32, y, rect.width() - 40, Style.ROW_HEIGHT),
                                     f"{col.name}  {col.data_type}")
                else:
                    painter.setPen(Style.TEXT_COLUMN)
                    painter.drawText(col_rect,
                                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                     f"  {col.name}  {col.data_type}")

        # Selection border
        if self.isSelected():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(Style.BORDER_SELECTED, 2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(rect, Style.CORNER_RADIUS, Style.CORNER_RADIUS)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for rel_item in self.scene().items() if self.scene() else []:
                if isinstance(rel_item, RelationItem):
                    rel_item.updatePath()
        return super().itemChange(change, value)


class RelationItem(QGraphicsPathItem):
    """A bezier-curve connection line between two entities."""

    def __init__(self, source: EntityItem, target: EntityItem,
                 relation: ModelRelation) -> None:
        super().__init__()
        self._source = source
        self._target = target
        self._relation = relation
        self.setZValue(5)
        self.setAcceptHoverEvents(True)
        self._hovered = False
        self.updatePath()

    def source(self) -> EntityItem:
        return self._source

    def target(self) -> EntityItem:
        return self._target

    def relation(self) -> ModelRelation:
        return self._relation

    def updatePath(self) -> None:
        if not self._source or not self._target:
            return

        src_center = self._source.scenePos() + QPointF(
            self._source.boundingRect().width() / 2,
            self._source.total_height() / 2,
        )
        tgt_center = self._target.scenePos() + QPointF(
            self._target.boundingRect().width() / 2,
            self._target.total_height() / 2,
        )

        dx = tgt_center.x() - src_center.x()

        # Determine best connection side (minimize line length)
        src_rect = QRectF(self._source.scenePos(),
                          QPointF(self._source.boundingRect().width(),
                                  self._source.total_height()))

        # Pick connection points on edges
        src_point = self._closest_edge_point(src_center, tgt_center, src_rect)
        tgt_rect = QRectF(self._target.scenePos(),
                          QPointF(self._target.boundingRect().width(),
                                  self._target.total_height()))
        tgt_point = self._closest_edge_point(tgt_center, src_center, tgt_rect)

        # Bezier curve
        path = QPainterPath()
        path.moveTo(src_point)

        ctrl_dist = abs(dx) * 0.4
        c1 = QPointF(src_point.x() + ctrl_dist * (1 if dx > 0 else -1), src_point.y())
        c2 = QPointF(tgt_point.x() + ctrl_dist * (1 if dx > 0 else -1), tgt_point.y())
        path.cubicTo(c1, c2, tgt_point)

        self.setPath(path)

        # Arrowhead at target
        pen_color = Style.LINE_RELATION_1N if self._relation.relation_type == "1:N" else Style.LINE_RELATION
        pen = QPen(pen_color, 1.5)
        self.setPen(pen)

    def _closest_edge_point(self, from_pt: QPointF, to_pt: QPointF,
                             rect: QRectF) -> QPointF:
        """Find the closest point on the rect edge to from_pt."""
        # Check all four edges
        candidates = []

        # Top edge
        if rect.top() <= from_pt.y() <= rect.bottom():
            candidates.append(QPointF(from_pt.x(), rect.top()))
            candidates.append(QPointF(from_pt.x(), rect.bottom()))

        # Left/Right edges
        if rect.left() <= from_pt.x() <= rect.right():
            candidates.append(QPointF(rect.left(), from_pt.y()))
            candidates.append(QPointF(rect.right(), from_pt.y()))

        # Corners
        for pt in [rect.topLeft(), rect.topRight(),
                   rect.bottomLeft(), rect.bottomRight()]:
            candidates.append(pt)

        # Pick the closest
        best = candidates[0]
        best_dist = (candidates[0] - to_pt).manhattanLength()
        for c in candidates[1:]:
            d = (c - to_pt).manhattanLength()
            if d < best_dist:
                best_dist = d
                best = c
        return best

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())

        # Draw relation type label at midpoint
        mid = self.path().pointAtPercent(0.5)
        label = self._relation.relation_type
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(Style.LINE_RELATION_1N)
        painter.drawText(QRectF(mid.x() - 20, mid.y() - 12, 40, 14),
                         Qt.AlignmentFlag.AlignCenter, label)

    def hoverEnterEvent(self, event) -> None:
        self._hovered = True
        pen = QPen(Style.BORDER_SELECTED, 2)
        self.setPen(pen)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hovered = False
        pen_color = Style.LINE_RELATION_1N if self._relation.relation_type == "1:N" else Style.LINE_RELATION
        self.setPen(QPen(pen_color, 1.5))
        super().hoverLeaveEvent(event)


# ── Property Editor Dialog ────────────────────────────────────────────────


class _ColumnEditorDialog(QDialog):
    """Dialog for editing a single column's properties."""

    DTYPES = [
        "INT", "BIGINT", "SMALLINT", "TINYINT",
        "VARCHAR", "CHAR", "TEXT", "LONGTEXT",
        "DECIMAL", "FLOAT", "DOUBLE",
        "DATE", "DATETIME", "TIMESTAMP", "TIME", "YEAR",
        "BLOB", "LONGBLOB",
        "BOOLEAN", "ENUM", "JSON",
    ]

    def __init__(self, column: Optional[ModelColumn] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑字段" if column else "新增字段")
        self.resize(400, 300)
        layout = QFormLayout(self)

        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("field_name")
        layout.addRow("字段名:", self._name_edit)

        self._type_combo = QComboBox(self)
        self._type_combo.addItems(self.DTYPES)
        self._type_combo.setEditable(True)
        layout.addRow("数据类型:", self._type_combo)

        self._len_edit = QLineEdit(self)
        self._len_edit.setPlaceholderText("255 (optional)")
        layout.addRow("长度:", self._len_edit)

        self._pk_check = QCheckBox("主键 (PRIMARY KEY)", self)
        layout.addRow(self._pk_check)

        self._ai_check = QCheckBox("自增 (AUTO_INCREMENT)", self)
        layout.addRow(self._ai_check)

        self._nullable_check = QCheckBox("允许空值 (NULL)", self)
        self._nullable_check.setChecked(True)
        layout.addRow(self._nullable_check)

        self._default_edit = QLineEdit(self)
        self._default_edit.setPlaceholderText("NULL")
        layout.addRow("默认值:", self._default_edit)

        self._comment_edit = QLineEdit(self)
        layout.addRow("注释:", self._comment_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        if column:
            self._name_edit.setText(column.name)
            self._type_combo.setCurrentText(column.data_type)
            self._len_edit.setText(str(column.char_max_length) if column.char_max_length else "")
            self._pk_check.setChecked(column.is_primary_key)
            self._ai_check.setChecked(column.is_auto_increment)
            self._nullable_check.setChecked(column.nullable)
            self._default_edit.setText(column.default or "")
            self._comment_edit.setText(column.comment)

    def get_column(self) -> ModelColumn:
        col = ModelColumn()
        col.name = self._name_edit.text().strip()
        col.data_type = self._type_combo.currentText().strip()
        len_text = self._len_edit.text().strip()
        col.char_max_length = int(len_text) if len_text.isdigit() else None
        col.is_primary_key = self._pk_check.isChecked()
        col.is_auto_increment = self._ai_check.isChecked()
        col.nullable = self._nullable_check.isChecked()
        col.default = self._default_edit.text().strip() or None
        col.comment = self._comment_edit.text().strip()
        return col


class _EntityPropertyDialog(QDialog):
    """Dialog for editing entity (table) properties and columns."""

    def __init__(self, entity: ModelEntity, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"编辑实体 — {entity.name or 'New Table'}")
        self.resize(550, 450)
        self._entity = entity
        layout = QVBoxLayout(self)

        # Entity name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("实体名:", self))
        self._name_edit = QLineEdit(entity.name, self)
        name_layout.addWidget(self._name_edit)
        layout.addLayout(name_layout)

        # Comment
        cmt_layout = QHBoxLayout()
        cmt_layout.addWidget(QLabel("注释:", self))
        self._comment_edit = QLineEdit(entity.comment, self)
        cmt_layout.addWidget(self._comment_edit)
        layout.addLayout(cmt_layout)

        # Columns table
        layout.addWidget(QLabel("字段列表:", self))
        self._col_table = QTableWidget(self)
        self._col_table.setColumnCount(6)
        self._col_table.setHorizontalHeaderLabels(["字段名", "类型", "PK", "自增", "可空", "默认值"])
        self._col_table.horizontalHeader().setStretchLastSection(True)
        self._col_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self._col_table, 1)

        # Column buttons
        btn_layout = QHBoxLayout()
        self._btn_add_col = QPushButton("+ 添加字段", self)
        self._btn_add_col.clicked.connect(self._add_column)
        self._btn_edit_col = QPushButton("编辑", self)
        self._btn_edit_col.clicked.connect(self._edit_column)
        self._btn_del_col = QPushButton("删除", self)
        self._btn_del_col.clicked.connect(self._delete_column)
        btn_layout.addWidget(self._btn_add_col)
        btn_layout.addWidget(self._btn_edit_col)
        btn_layout.addWidget(self._btn_del_col)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # OK/Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_table()

    def _refresh_table(self) -> None:
        self._col_table.setRowCount(len(self._entity.columns))
        for i, col in enumerate(self._entity.columns):
            self._col_table.setItem(i, 0, QTableWidgetItem(col.name))
            self._col_table.setItem(i, 1, QTableWidgetItem(col.data_type))
            self._col_table.setItem(i, 2, QTableWidgetItem("PK" if col.is_primary_key else ""))
            self._col_table.setItem(i, 3, QTableWidgetItem("AI" if col.is_auto_increment else ""))
            self._col_table.setItem(i, 4, QTableWidgetItem("YES" if col.nullable else "NO"))
            self._col_table.setItem(i, 5, QTableWidgetItem(col.default or ""))

    def _add_column(self) -> None:
        dlg = _ColumnEditorDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._entity.columns.append(dlg.get_column())
            self._refresh_table()

    def _edit_column(self) -> None:
        row = self._col_table.currentRow()
        if row < 0:
            return
        dlg = _ColumnEditorDialog(self._entity.columns[row], self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._entity.columns[row] = dlg.get_column()
            self._refresh_table()

    def _delete_column(self) -> None:
        row = self._col_table.currentRow()
        if row >= 0:
            self._entity.columns.pop(row)
            self._refresh_table()

    def get_entity(self) -> ModelEntity:
        self._entity.name = self._name_edit.text().strip()
        self._entity.comment = self._comment_edit.text().strip()
        return self._entity


# ── Main Model Designer Widget ────────────────────────────────────────────


class ModelDesignerWidget(QWidget):
    """The main ER diagram designer widget."""

    def __init__(self, connection_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._entities: dict[str, EntityItem] = {}
        self._relations: list[RelationItem] = []
        self._edit_mode = "select"  # select | add_entity | add_relation
        self._rel_source: Optional[EntityItem] = None
        self._model_level: str = "physical"  # conceptual | logical | physical

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ──
        toolbar = QWidget(self)
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(8, 4, 8, 4)
        t_layout.setSpacing(4)

        self._build_toolbar(t_layout)
        layout.addWidget(toolbar)

        # ── Canvas area ──
        self._scene = QGraphicsScene(self)
        self._scene.setBackgroundBrush(Style.BG_CANVAS)

        self._view = QGraphicsView(self._scene, self)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._view.scale(0.9, 0.9)

        # Click handler for adding entities
        self._view.mousePressEvent = self._on_view_click

        layout.addWidget(self._view, 1)

        # ── Status bar ──
        self._status = QLabel("选择工具: 点击画布空白处添加实体", self)
        self._status.setStyleSheet(
            "background: #007acc; color: #fff; padding: 4px 12px; font-size: 11px;"
        )
        layout.addWidget(self._status)

    def _build_toolbar(self, layout: QHBoxLayout) -> None:
        """Populate the toolbar with action buttons."""
        actions = [
            ("↖", "选择/移动", "select", "#0078d4"),
            ("⊞", "添加实体", "add_entity", "#4ec9b0"),
            ("⚡", "添加关系", "add_relation", "#dcdcaa"),
        ]

        for icon, tip, mode, color in actions:
            btn = QPushButton(icon, self)
            btn.setToolTip(tip)
            btn.setFixedSize(32, 28)
            btn.setStyleSheet(
                f"background: transparent; color: {color}; border: 1px solid #3c3c3c; "
                f"border-radius: 3px; font-size: 16px; cursor: pointer;"
            )
            btn.clicked.connect(lambda checked, m=mode: self._set_mode(m))
            layout.addWidget(btn)

        layout.addWidget(QLabel("|", self), 0, Qt.AlignmentFlag.AlignCenter)

        # Entity actions
        for text, tip, cb in [
            ("✏ 编辑", "编辑选中实体", self._edit_selected_entity),
            ("🗑 删除", "删除选中实体", self._delete_selected_entity),
            ("📐 布局", "自动排列", self._auto_layout),
        ]:
            btn = QPushButton(text, self)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "background: transparent; color: #ccc; border: 1px solid #3c3c3c; "
                "border-radius: 3px; padding: 2px 10px; font-size: 11px;"
            )
            btn.clicked.connect(cb)
            layout.addWidget(btn)

        # Model level selector
        layout.addWidget(QLabel("|", self), 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(QLabel("模型:", self))
        self._level_combo = QComboBox(self)
        self._level_combo.addItems(["概念模型", "逻辑模型", "物理模型"])
        self._level_combo.setCurrentIndex(2)  # physical by default
        self._level_combo.currentTextChanged.connect(self._on_level_changed)
        layout.addWidget(self._level_combo)

        layout.addStretch()

        for text, tip, cb in [
            ("← 逆向工程", "从数据库加载表", self._reverse_engineer),
            ("→ 正向工程", "生成 DDL", self._forward_engineer),
        ]:
            btn = QPushButton(text, self)
            btn.setToolTip(tip)
            btn.setStyleSheet(
                "background: #0078d4; color: #fff; border: none; border-radius: 3px; "
                "padding: 2px 12px; font-size: 11px;"
            )
            btn.clicked.connect(cb)
            layout.addWidget(btn)

    def _set_mode(self, mode: str) -> None:
        self._edit_mode = mode
        self._rel_source = None
        if mode == "select":
            self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self._status.setText("选择模式: 拖动实体或画布")
        elif mode == "add_entity":
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self._status.setText("添加实体: 点击画布空白位置")
        elif mode == "add_relation":
            self._view.setDragMode(QGraphicsView.DragMode.NoDrag)
            self._status.setText("添加关系: 先点来源实体，再点目标实体")

    def _on_level_changed(self, level: str) -> None:
        mapping = {"概念模型": "conceptual", "逻辑模型": "logical", "物理模型": "physical"}
        self._model_level = mapping.get(level, "physical")
        for ent in self._entities.values():
            ent.set_model_level(self._model_level)
            ent.update()
        for rel in self._relations:
            rel.update()

    # ── View click (for adding entities on canvas) ──

    _orig_mouse_press = None

    def _on_view_click(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self._view.mapToScene(event.pos())
            item = self._view.itemAt(event.pos())

            if self._edit_mode == "add_entity" and not item:
                self._add_entity(scene_pos)
                return

            if self._edit_mode == "add_relation":
                entity_item = self._item_to_entity(item)
                if entity_item:
                    if self._rel_source is None:
                        self._rel_source = entity_item
                        self._status.setText(f"来源: {entity_item.entity().name} — 点击目标实体")
                    elif entity_item != self._rel_source:
                        self._add_relation(self._rel_source, entity_item)
                        self._rel_source = None
                        self._set_mode("select")
                    return

        # Fallback to default behavior
        QGraphicsView.mousePressEvent(self._view, event)

    def _item_to_entity(self, item) -> Optional[EntityItem]:
        """If the clicked item is part of an EntityItem (or itself), return it."""
        if isinstance(item, EntityItem):
            return item
        if item and item.parentItem() and isinstance(item.parentItem(), EntityItem):
            return item.parentItem()
        return None

    # ── Entity operations ────────────────────────────────────────────

    def _add_entity(self, pos: QPointF) -> None:
        entity = ModelEntity(name="NewTable")
        # Add default PK column
        entity.columns.append(ModelColumn(
            name="id", data_type="INT",
            nullable=False, is_primary_key=True, is_auto_increment=True,
        ))
        entity.columns.append(ModelColumn(
            name="created_at", data_type="DATETIME",
            nullable=True,
        ))
        item = EntityItem(entity, pos)
        item.set_model_level(self._model_level)
        self._scene.addItem(item)
        self._entities[entity.name] = item

        # Open property dialog
        self._edit_entity(item)

    def _edit_selected_entity(self) -> None:
        items = self._scene.selectedItems()
        for item in items:
            if isinstance(item, EntityItem):
                self._edit_entity(item)
                return

    def _edit_entity(self, item: EntityItem) -> None:
        old_name = item.entity().name
        dlg = _EntityPropertyDialog(item.entity(), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            entity = dlg.get_entity()
            if entity.name != old_name:
                del self._entities[old_name]
                self._entities[entity.name] = item
            item.update()
        else:
            # If it's a new entity that was cancelled, remove it
            if not any(c.name for c in item.entity().columns):
                self._scene.removeItem(item)
                del self._entities[item.entity().name]

    def _delete_selected_entity(self) -> None:
        items = self._scene.selectedItems()
        for item in list(items):
            if isinstance(item, EntityItem):
                # Remove associated relations
                for rel in list(self._relations):
                    if rel.source() == item or rel.target() == item:
                        self._scene.removeItem(rel)
                        self._relations.remove(rel)
                self._scene.removeItem(item)
                del self._entities[item.entity().name]

    # ── Relation operations ──────────────────────────────────────────

    def _add_relation(self, source: EntityItem, target: EntityItem) -> None:
        from_name = source.entity().name
        to_name = target.entity().name

        # Check for duplicates
        for rel in self._relations:
            r = rel.relation()
            if (r.from_entity == from_name and r.to_entity == to_name) or \
               (r.from_entity == to_name and r.to_entity == from_name):
                QMessageBox.information(self, "提示", "这两个实体之间已存在关系。")
                return

        # Ask for relation type
        types = ["1:N", "1:1", "M:N"]
        rel_type, ok = QInputDialog.getItem(
            self, "关系类型", f"{from_name} → {to_name}",
            types, 0, False,
        )
        if not ok:
            return

        # Find common column names for FK suggestion
        fk_col = f"{to_name.lower()}_id"

        relation = ModelRelation(
            from_entity=from_name,
            to_entity=to_name,
            from_column=fk_col,
            to_column="id",
            relation_type=rel_type,
        )

        rel_item = RelationItem(source, target, relation)
        self._scene.addItem(rel_item)
        self._relations.append(rel_item)

        # Add FK column to source entity if not exists
        src_entity = source.entity()
        if not any(c.name == fk_col for c in src_entity.columns):
            src_entity.columns.insert(0, ModelColumn(
                name=fk_col,
                data_type="INT",
                nullable=True,
                is_foreign_key=True,
            ))
            source.update()

    # ── Auto layout ──────────────────────────────────────────────────

    def _auto_layout(self) -> None:
        """Arrange entities in a grid pattern."""
        items_list = list(self._entities.values())
        if not items_list:
            return
        cols = max(1, int(math.sqrt(len(items_list))))
        spacing_x = 260
        spacing_y = 180
        for i, item in enumerate(items_list):
            row = i // cols
            col = i % cols
            item.setPos(QPointF(col * spacing_x, row * spacing_y))
        self._scene.update()

    # ── Reverse engineering ──────────────────────────────────────────

    def _reverse_engineer(self) -> None:
        """Load tables from connected database and add as entities."""
        from open_navicat.services.metadata_service import metadata_service

        if not self._connection_id:
            from PySide6.QtWidgets import QInputDialog
            db, ok = QInputDialog.getText(
                self, "逆向工程", "输入数据库名称:",
            )
            if not ok or not db:
                return
            databases = [db]
        else:
            databases = [d.name for d in metadata_service.list_databases(self._connection_id)]

        if not databases:
            QMessageBox.information(self, "提示", "未发现可用数据库。")
            return

        db_name, ok = QInputDialog.getItem(
            self, "选择数据库", "选择要逆向的数据库:",
            databases, 0, False,
        )
        if not ok or not db_name:
            return

        QMessageBox.information(
            self, "逆向工程",
            f"正在从「{db_name}」加载表结构...",
        )

        try:
            tables = metadata_service.list_tables(self._connection_id, db_name)
            if not tables:
                QMessageBox.information(self, "提示", "该数据库中没有表。")
                return

            spacing_x, spacing_y = 260, 180
            cols = max(1, int(math.sqrt(len(tables))))

            for i, table_name in enumerate(tables):
                info = metadata_service.get_table_info(self._connection_id, db_name, table_name)
                if not info:
                    continue

                entity = ModelEntity.from_table_info(info)
                row = i // cols
                col = i % cols
                pos = QPointF(col * spacing_x, row * spacing_y)
                item = EntityItem(entity, pos)
                item.set_model_level(self._model_level)
                self._scene.addItem(item)
                self._entities[entity.name] = item

            self._scene.update()
            self._status.setText(f"已加载 {len(tables)} 张表到画布")
        except Exception as e:
            QMessageBox.warning(self, "逆向工程失败", str(e))

    # ── Forward engineering ──────────────────────────────────────────

    def _forward_engineer(self) -> None:
        """Generate DDL from the model and show it."""
        from open_navicat.utils.sql_generator import generate_create_table

        if not self._entities:
            QMessageBox.information(self, "提示", "画布上没有实体，无法生成 DDL。")
            return

        statements: list[str] = []
        for name, item in self._entities.items():
            entity = item.entity()
            table_info = entity.to_table_info()
            ddl = generate_create_table(table_info)
            statements.append(ddl)

        # Show in a dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("正向工程 — DDL 预览")
        dlg.resize(700, 500)
        dlg_layout = QVBoxLayout(dlg)

        editor = QTextEdit(dlg)
        editor.setReadOnly(True)
        editor.setStyleSheet(
            "background: #1e1e1e; color: #dcdcaa; font-family: Consolas; "
            "font-size: 12px; border: 1px solid #3c3c3c; padding: 8px;"
        )
        editor.setPlainText("\n\n".join(statements))
        dlg_layout.addWidget(editor, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close, dlg,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        dlg_layout.addWidget(buttons)

        dlg.exec()

    # ── Clear ────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Remove all items from the canvas."""
        self._scene.clear()
        self._entities.clear()
        self._relations.clear()
        self._rel_source = None


# ── Module-level convenience ──────────────────────────────────────────────

ENTITY_DTYPES = _ColumnEditorDialog.DTYPES
