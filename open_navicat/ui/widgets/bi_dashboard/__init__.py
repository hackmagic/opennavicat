"""BI Dashboard — data visualization and analytics dashboard.

Provides:
- SQL query as data source
- Multiple chart types: Bar, Line, Pie, Table
- Drag-and-drop chart arrangement
- Dashboard save/load
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from open_navicat.i18n import t

# ── Color Palette ─────────────────────────────────────────────────────────

CHART_COLORS = [
    "#0078d4", "#4ec9b0", "#dcdcaa", "#f44747", "#c586c0",
    "#d16969", "#6a9955", "#569cd6", "#ce9178", "#808080",
]


# ── Chart Types ───────────────────────────────────────────────────────────

class ChartType:
    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    AREA = "area"

    @staticmethod
    def all() -> list[str]:
        return ["bar", "line", "pie", "area"]


# ── Chart Widget ──────────────────────────────────────────────────────────


class ChartCanvas(QWidget):
    """Custom-painted chart widget (no external plotting lib needed)."""

    def __init__(self, title: str = "", chart_type: str = ChartType.BAR,
                 parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._chart_type = chart_type
        self._labels: list[str] = []
        self._values: list[float] = []
        self._colors: list[QColor] = []
        self.setMinimumSize(200, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, labels: list[str], values: list[float]) -> None:
        self._labels = labels
        self._values = values
        self._colors = [QColor(CHART_COLORS[i % len(CHART_COLORS)]) for i in range(len(labels))]
        self.update()

    def set_title(self, title: str) -> None:
        self._title = title
        self.update()

    def set_chart_type(self, chart_type: str) -> None:
        self._chart_type = chart_type
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin = 50
        title_h = 30

        # Background
        painter.fillRect(self.rect(), QColor("#252526"))

        # Title
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.setPen(QColor("#cccccc"))
        painter.drawText(QRectF(0, 8, w, title_h), Qt.AlignmentFlag.AlignCenter, self._title)

        if not self._values:
            painter.setFont(QFont("Segoe UI", 10))
            painter.setPen(QColor("#888888"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("bi_dashboard.no_data"))
            return

        if self._chart_type == ChartType.PIE:
            self._draw_pie(painter, w, h, margin, title_h)
        elif self._chart_type == ChartType.BAR:
            self._draw_bar(painter, w, h, margin, title_h)
        elif self._chart_type == ChartType.LINE:
            self._draw_line(painter, w, h, margin, title_h)
        elif self._chart_type == ChartType.AREA:
            self._draw_area(painter, w, h, margin, title_h)

    def _draw_pie(self, painter: QPainter, w: int, h: int, m: int, th: int) -> None:
        total = sum(self._values) or 1
        pie_size = min(w, h) - 2 * m
        pie_rect = QRectF((w - pie_size) / 2, (h - pie_size) / 2 + 10, pie_size, pie_size)
        start_angle = 90 * 16

        painter.setPen(QPen(QColor("#3c3c3c"), 1))
        for i, val in enumerate(self._values):
            span = int(val / total * 360 * 16)
            painter.setBrush(QBrush(self._colors[i]))
            painter.drawPie(pie_rect, start_angle, max(span, 1))
            start_angle += span

        # Legend
        legend_x = 10
        legend_y = h - len(self._labels) * 18 - 10
        painter.setFont(QFont("Segoe UI", 8))
        for i, (label, val) in enumerate(zip(self._labels, self._values)):
            y = legend_y + i * 18
            painter.fillRect(legend_x, y, 10, 10, self._colors[i])
            painter.setPen(QColor("#cccccc"))
            pct = val / total * 100
            painter.drawText(legend_x + 16, y + 10, f"{label} ({pct:.1f}%)")

    def _draw_bar(self, painter: QPainter, w: int, h: int, m: int, th: int) -> None:
        max_val = max(self._values) or 1
        chart_rect = QRectF(m, th + 10, w - 2 * m, h - th - m - 20)
        bar_count = len(self._values)
        bar_width = chart_rect.width() / bar_count * 0.7
        gap = chart_rect.width() / bar_count * 0.3

        # Y-axis
        painter.setPen(QPen(QColor("#3c3c3c"), 1))
        painter.drawLine(int(chart_rect.left()), int(chart_rect.bottom()),
                         int(chart_rect.right()), int(chart_rect.bottom()))

        # Grid lines
        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#3c3c3c"))
        for i in range(5):
            y = chart_rect.top() + chart_rect.height() * i / 4
            painter.drawLine(int(chart_rect.left()), int(y),
                             int(chart_rect.right()), int(y))
            val = max_val * (4 - i) / 4
            painter.setPen(QColor("#888888"))
            painter.drawText(int(chart_rect.left() - 40), int(y + 3), f"{val:.0f}")
            painter.setPen(QColor("#3c3c3c"))

        # Bars
        for i, val in enumerate(self._values):
            x = chart_rect.left() + i * (bar_width + gap) + gap / 2
            bar_h = val / max_val * chart_rect.height()
            bar_rect = QRectF(x, chart_rect.bottom() - bar_h, bar_width, bar_h)
            painter.setBrush(QBrush(self._colors[i]))
            painter.setPen(QPen(QColor("#3c3c3c"), 1))
            painter.drawRect(bar_rect)

            # Label
            painter.setFont(QFont("Segoe UI", 7))
            painter.setPen(QColor("#cccccc"))
            painter.drawText(QRectF(x - 5, chart_rect.bottom() + 2,
                                    bar_width + 10, 16),
                             Qt.AlignmentFlag.AlignCenter,
                             self._labels[i][:12])

    def _draw_line(self, painter: QPainter, w: int, h: int, m: int, th: int) -> None:
        max_val = max(self._values) or 1
        chart_rect = QRectF(m, th + 10, w - 2 * m, h - th - m - 20)

        # Grid
        painter.setPen(QColor("#3c3c3c"))
        for i in range(5):
            y = chart_rect.top() + chart_rect.height() * i / 4
            painter.drawLine(int(chart_rect.left()), int(y),
                             int(chart_rect.right()), int(y))

        # Axes
        painter.setPen(QPen(QColor("#3c3c3c"), 1))
        painter.drawLine(int(chart_rect.left()), int(chart_rect.bottom()),
                         int(chart_rect.right()), int(chart_rect.bottom()))

        if len(self._values) < 2:
            return

        # Line
        points: list[tuple[float, float]] = []
        for i, val in enumerate(self._values):
            x = chart_rect.left() + chart_rect.width() * i / (len(self._values) - 1)
            y = chart_rect.bottom() - val / max_val * chart_rect.height()
            points.append((x, y))

        # Fill
        path = self._build_path(points, chart_rect)
        painter.setBrush(QColor(0, 120, 212, 30))
        painter.setPen(QPen(QColor("#0078d4"), 2))
        painter.drawPath(path)

        # Points
        painter.setBrush(QBrush(QColor("#0078d4")))
        painter.setPen(QPen(QColor("#ffffff"), 1))
        for x, y in points:
            painter.drawEllipse(QPointF(x, y), 3, 3)

    def _draw_area(self, painter: QPainter, w: int, h: int, m: int, th: int) -> None:
        max_val = max(self._values) or 1
        chart_rect = QRectF(m, th + 10, w - 2 * m, h - th - m - 20)

        if len(self._values) < 2:
            return

        points: list[tuple[float, float]] = []
        for i, val in enumerate(self._values):
            x = chart_rect.left() + chart_rect.width() * i / (len(self._values) - 1)
            y = chart_rect.bottom() - val / max_val * chart_rect.height()
            points.append((x, y))

        path = self._build_path(points, chart_rect, close=True)
        grad = QLinearGradient(0, chart_rect.top(), 0, chart_rect.bottom())
        grad.setColorAt(0, QColor(0, 120, 212, 120))
        grad.setColorAt(1, QColor(0, 120, 212, 20))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor("#0078d4"), 2))
        painter.drawPath(path)

    def _build_path(self, points: list[tuple[float, float]],
                    rect: QRectF, close: bool = False):
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.moveTo(points[0][0], points[0][1])
        for i in range(1, len(points)):
            x1, y1 = points[i - 1]
            x2, y2 = points[i]
            cx = (x1 + x2) / 2
            path.quadTo(cx, y1, x2, y2)
        if close:
            path.lineTo(points[-1][0], rect.bottom())
            path.lineTo(points[0][0], rect.bottom())
            path.closeSubpath()
        return path


# ── Chart Card (container for a ChartCanvas with controls) ────────────────


class ChartCard(QFrame):
    """A single chart in the dashboard, with header and chart canvas."""

    closed = Signal(object)  # emits self

    def __init__(self, title: str = "", chart_type: str = ChartType.BAR,
                 parent=None) -> None:
        super().__init__(parent)
        self._title = title
        self._chart_type = chart_type
        self._canvas = ChartCanvas(title, chart_type, self)

        self.setFrameStyle(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Mini toolbar
        toolbar = QWidget(self)
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(8, 4, 8, 4)

        self._title_label = QLabel(title, toolbar)
        t_layout.addWidget(self._title_label, 1)

        for text, cb in [
            ("📊", lambda: self._cycle_type()),
            ("✖", lambda: self.closed.emit(self)),
        ]:
            btn = QPushButton(text, toolbar)
            btn.setFixedSize(22, 20)
            btn.setStyleSheet(
                "background: transparent; color: #888; border: none; "
                "font-size: 10px; cursor: pointer;"
            )
            btn.clicked.connect(cb)
            t_layout.addWidget(btn)

        layout.addWidget(toolbar)
        layout.addWidget(self._canvas, 1)

    def canvas(self) -> ChartCanvas:
        return self._canvas

    def _cycle_type(self) -> None:
        types = ChartType.all()
        idx = types.index(self._chart_type)
        self._chart_type = types[(idx + 1) % len(types)]
        self._canvas.set_chart_type(self._chart_type)
        type_names = {"bar": t("bi_dashboard.chart.bar"), "line": t("bi_dashboard.chart.line"),
                      "pie": t("bi_dashboard.chart.pie"), "area": t("bi_dashboard.chart.area")}
        self._title_label.setText(f"{self._title} ({type_names.get(self._chart_type, '')})")

    def set_data(self, labels: list[str], values: list[float]) -> None:
        self._canvas.set_data(labels, values)


# ── BI Dashboard Main Widget ─────────────────────────────────────────────


class BIDashboardWidget(QWidget):
    """Main BI dashboard with SQL query input and chart grid."""

    def __init__(self, connection_id: str = "", parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._charts: list[ChartCard] = []
        self._chart_counter = 0
        self._last_result: Optional[dict] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top toolbar ──
        toolbar = QWidget(self)
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(8, 4, 8, 4)

        title = QLabel(t("bi_dashboard.title"), toolbar)
        t_layout.addWidget(title)

        t_layout.addStretch()

        self._chart_type_combo = QComboBox(toolbar)
        self._chart_type_combo.addItems([
            t("bi_dashboard.chart.bar"), t("bi_dashboard.chart.line"),
            t("bi_dashboard.chart.pie"), t("bi_dashboard.chart.area")
        ])
        t_layout.addWidget(self._chart_type_combo)

        for text, cb in [
            (t("bi_dashboard.add_chart"), self._add_chart),
            (t("bi_dashboard.clear_all"), self._clear_all),
        ]:
            btn = QPushButton(text, toolbar)
            btn.clicked.connect(cb)
            t_layout.addWidget(btn)

        t_layout.addSpacing(8)
        btn_save = QPushButton(t("bi_dashboard.save"), toolbar)
        btn_save.setStyleSheet(
            "background: transparent; color: #ccc; border: 1px solid #3c3c3c; "
            "border-radius: 3px; padding: 4px 12px; font-size: 11px;"
        )
        btn_save.clicked.connect(self._save_dashboard)
        t_layout.addWidget(btn_save)

        btn_load = QPushButton(t("bi_dashboard.load"), toolbar)
        btn_load.setStyleSheet(
            "background: transparent; color: #ccc; border: 1px solid #3c3c3c; "
            "border-radius: 3px; padding: 4px 12px; font-size: 11px;"
        )
        btn_load.clicked.connect(self._load_dashboard)
        t_layout.addWidget(btn_load)

        layout.addWidget(toolbar)

        # ── SQL input area ──
        sql_panel = QWidget(self)
        sql_layout = QVBoxLayout(sql_panel)
        sql_layout.setContentsMargins(8, 6, 8, 6)

        sql_header = QHBoxLayout()
        sql_header.addWidget(QLabel(t("bi_dashboard.sql_label"), sql_panel))
        sql_header.addWidget(QLabel(t("bi_dashboard.sql_hint"), sql_panel),
                              0, Qt.AlignmentFlag.AlignRight)
        sql_layout.addLayout(sql_header)

        sql_input_row = QHBoxLayout()
        self._sql_edit = QTextEdit(sql_panel)
        self._sql_edit.setPlaceholderText(
            "SELECT DATE(created_at) AS label, COUNT(*) AS value\n"
            "FROM users\n"
            "WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)\n"
            "GROUP BY DATE(created_at)\n"
            "ORDER BY label"
        )
        self._sql_edit.setMaximumHeight(80)
        sql_input_row.addWidget(self._sql_edit, 1)

        self._btn_execute = QPushButton(t("bi_dashboard.execute"), sql_panel)
        self._btn_execute.setObjectName("primaryBtn")
        sql_input_row.addWidget(self._btn_execute)
        sql_layout.addLayout(sql_input_row)

        layout.addWidget(sql_panel)

        # ── Chart grid (scrollable) ──
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)

        self._chart_container = QWidget(scroll)
        self._chart_grid = QGridLayout(self._chart_container)
        self._chart_grid.setSpacing(8)
        self._chart_grid.setContentsMargins(8, 8, 8, 8)

        scroll.setWidget(self._chart_container)
        layout.addWidget(scroll, 1)

        # ── Status bar ──
        self._status_label = QLabel(t("bi_dashboard.status.ready"), self)
        layout.addWidget(self._status_label)

    def _type_to_key(self, name: str) -> str:
        mapping = {
            t("bi_dashboard.chart.bar"): "bar", t("bi_dashboard.chart.line"): "line",
            t("bi_dashboard.chart.pie"): "pie", t("bi_dashboard.chart.area"): "area",
        }
        return mapping.get(name, "bar")

    def _add_chart(self) -> None:
        self._chart_counter += 1
        chart_type = self._type_to_key(self._chart_type_combo.currentText())

        card = ChartCard(
            title=t("bi_dashboard.chart.default_name", n=self._chart_counter),
            chart_type=chart_type,
            parent=self._chart_container,
        )
        card.closed.connect(self._remove_chart)

        # Find position in grid (2 columns)
        idx = len(self._charts)
        row, col = divmod(idx, 2)
        self._chart_grid.addWidget(card, row, col)
        self._charts.append(card)

        # If we have data from previous query, apply it
        if self._last_result:
            card.set_data(self._last_result["labels"], self._last_result["values"])

    def _remove_chart(self, card: ChartCard) -> None:
        self._chart_grid.removeWidget(card)
        card.setParent(None)
        card.deleteLater()
        self._charts.remove(card)

        # Re-layout remaining
        self._relayout()

    def _clear_all(self) -> None:
        for card in list(self._charts):
            self._chart_grid.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._charts.clear()
        self._chart_counter = 0
        self._last_result = None
        self._status_label.setText(t("bi_dashboard.all_cleared"))

    def _relayout(self) -> None:
        # Remove all from grid
        for card in self._charts:
            self._chart_grid.removeWidget(card)
        # Re-add in order
        for idx, card in enumerate(self._charts):
            row, col = divmod(idx, 2)
            self._chart_grid.addWidget(card, row, col)

    def _execute_query(self) -> None:
        sql = self._sql_edit.toPlainText().strip()
        if not sql:
            QMessageBox.warning(self, t("common.notice"), t("bi_dashboard.enter_sql"))
            return

        if not self._connection_id:
            self._status_label.setText(t("bi_dashboard.mock_mode"))
            self._simulate_data()
            return

        self._status_label.setText(t("bi_dashboard.executing"))
        self._btn_execute.setEnabled(False)

        QTimer.singleShot(50, lambda: self._do_execute(sql))

    def _do_execute(self, sql: str) -> None:
        try:
            from open_navicat.services.query_engine import query_engine

            result = query_engine.execute(self._connection_id, sql)
            if not result.success:
                QMessageBox.critical(self, t("bi_dashboard.query_failed"),
                                     result.error_message or t("bi_dashboard.execution_error"))
                self._status_label.setText(t("bi_dashboard.query_execution_failed"))
                return

            if not result.rows:
                self._status_label.setText(t("bi_dashboard.query_empty"))
                return

            # First column = labels, remaining = values
            labels: list[str] = []
            values: list[float] = []
            for row in result.rows:
                if row:
                    labels.append(str(row[0]))
                    try:
                        values.append(float(row[1]) if len(row) > 1 and row[1] is not None else 0)
                    except (ValueError, TypeError):
                        values.append(0)

            self._last_result = {"labels": labels, "values": values}

            # Update all existing charts
            for card in self._charts:
                card.set_data(labels, values)

            # If no charts, add one automatically
            if not self._charts:
                self._chart_counter += 1
                card = ChartCard(
                    title=t("bi_dashboard.query_result", rows=result.row_count),
                    chart_type="bar",
                    parent=self._chart_container,
                )
                card.closed.connect(self._remove_chart)
                self._chart_grid.addWidget(card, 0, 0)
                self._charts.append(card)
                card.set_data(labels, values)

            self._status_label.setText(
                t("bi_dashboard.query_complete", rows=result.row_count, charts=len(self._charts))
            )

        except Exception as exc:
            QMessageBox.critical(self, t("common.error"), str(exc))
            self._status_label.setText(f"{t('common.error')}: {exc}")
        finally:
            self._btn_execute.setEnabled(True)

    def _simulate_data(self) -> None:
        """Generate sample data for demonstration."""
        import calendar
        from datetime import datetime, timedelta

        labels = []
        values = []
        for i in range(14):
            d = (datetime.now() - timedelta(days=13 - i))
            labels.append(d.strftime("%m-%d"))
            values.append(random.randint(50, 500))

        self._last_result = {"labels": labels, "values": values}

        for card in self._charts:
            card.set_data(labels, values)

        if not self._charts:
            self._chart_counter += 1
            card = ChartCard(title=t("bi_dashboard.mock_data"), chart_type="bar")
            card.closed.connect(self._remove_chart)
            self._chart_grid.addWidget(card, 0, 0)
            self._charts.append(card)
            card.set_data(labels, values)

        self._status_label.setText(t("bi_dashboard.mock_loaded"))
        self._btn_execute.setEnabled(True)

    # ---- save/load dashboard ----

    def _save_dashboard(self) -> None:
        """Save current dashboard config to local settings."""
        from open_navicat.config import config
        data = {
            "sql": self._sql_edit.toPlainText(),
            "charts": [
                {"title": c._title_label.text(), "type": c._canvas._chart_type}
                for c in self._charts
            ],
            "chart_counter": self._chart_counter,
        }
        config.set("bi_dashboard", data)
        self._status_label.setText(t("bi_dashboard.saved"))

    def _load_dashboard(self) -> None:
        """Load dashboard config from local settings and restore."""
        from open_navicat.config import config
        data = config.get("bi_dashboard")
        if not data:
            self._status_label.setText(t("bi_dashboard.no_saved"))
            return
        # Clear existing
        self._clear_all()
        # Restore SQL
        self._sql_edit.setPlainText(data.get("sql", ""))
        self._chart_counter = data.get("chart_counter", 0)
        # Restore charts
        for ci in data.get("charts", []):
            self._chart_counter += 1
            card = ChartCard(
                title=ci.get("title", t("bi_dashboard.chart.default_name", n=self._chart_counter)),
                chart_type=ci.get("type", "bar"),
                parent=self._chart_container,
            )
            card.closed.connect(self._remove_chart)
            idx = len(self._charts)
            row, col = divmod(idx, 2)
            self._chart_grid.addWidget(card, row, col)
            self._charts.append(card)
        self._relayout()
        self._status_label.setText(t("bi_dashboard.loaded_charts", count=len(self._charts)))


# ── Convenience ───────────────────────────────────────────────────────────

__all__ = [
    "BIDashboardWidget",
    "ChartCard",
    "ChartCanvas",
    "ChartType",
]
