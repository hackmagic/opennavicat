"""Data Dictionary — show table/column metadata documentation for a database."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.connection_pool import _loop as pool_loop
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.i18n import t

_log = logging.getLogger(__name__)


class DataDictionaryWidget(QWidget):
    """Displays metadata documentation for all tables in a database."""

    def __init__(self, connection_id: str, database: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        self._tables: list[dict] = []
        self._setup_ui()
        self._load_tables()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.addWidget(QLabel(t("data_dictionary.title", database=self._database)))
        h_layout.addStretch()
        btn_refresh = QPushButton(t("data_dictionary.btn.refresh"))
        btn_refresh.clicked.connect(self._load_tables)
        h_layout.addWidget(btn_refresh)
        btn_export = QPushButton(t("data_dictionary.btn.export_html"))
        btn_export.clicked.connect(self._export_html)
        h_layout.addWidget(btn_export)
        btn_export_pdf = QPushButton(t("data_dictionary.btn.export_pdf"))
        btn_export_pdf.clicked.connect(self._export_pdf)
        h_layout.addWidget(btn_export_pdf)
        layout.addWidget(header)

        # Splitter: table list + detail
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Table list
        self._table_list = QTableWidget()
        self._table_list.setColumnCount(4)
        self._table_list.setHorizontalHeaderLabels([t("data_dictionary.column.table_name"), t("data_dictionary.column.engine"), t("data_dictionary.column.row_count"), t("data_dictionary.column.comment")])
        self._table_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table_list.setAlternatingRowColors(True)
        self._table_list.currentCellChanged.connect(self._on_table_selected)
        splitter.addWidget(self._table_list)

        # Detail view
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(4, 4, 4, 4)

        self._detail_title = QLabel(t("data_dictionary.status.select_table"))
        self._detail_title.setStyleSheet("font-weight: bold; font-size: 14px;")
        detail_layout.addWidget(self._detail_title)

        self._col_table = QTableWidget()
        self._col_table.setColumnCount(7)
        self._col_table.setHorizontalHeaderLabels([t("data_dictionary.column_detail.field_name"), t("data_dictionary.column_detail.type"), t("data_dictionary.column_detail.nullable"), t("data_dictionary.column_detail.default"), t("data_dictionary.column_detail.primary_key"), t("data_dictionary.column_detail.auto_increment"), t("data_dictionary.column_detail.comment")])
        self._col_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._col_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._col_table.setAlternatingRowColors(True)
        detail_layout.addWidget(self._col_table)

        self._ddl_text = QTextEdit()
        self._ddl_text.setReadOnly(True)
        self._ddl_text.setMaximumHeight(120)
        self._ddl_text.setObjectName("monospaceText")
        detail_layout.addWidget(self._ddl_text)

        splitter.addWidget(detail)
        splitter.setSizes([300, 500])
        layout.addWidget(splitter)

    def _load_tables(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            tables = pool_loop.run_until_complete(connector.list_tables_with_info(self._database))
            self._tables = tables
            self._table_list.setRowCount(len(tables))
            for i, info in enumerate(tables):
                self._table_list.setItem(i, 0, QTableWidgetItem(info["name"]))
                self._table_list.setItem(i, 1, QTableWidgetItem(info.get("engine", "")))
                self._table_list.setItem(i, 2, QTableWidgetItem(str(info.get("data_length", 0))))
                self._table_list.setItem(i, 3, QTableWidgetItem(""))
        except Exception as e:
            _log.warning("Failed to load table list: %s", e)
            self._tables = []

    def _on_table_selected(self, row: int, col: int, prev_row: int, prev_col: int) -> None:
        if row < 0 or row >= len(self._tables):
            return
        table_name = self._tables[row]["name"]
        self._detail_title.setText(f"📋 {table_name}")

        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            info = pool_loop.run_until_complete(
                connector.get_table_info(self._database, table_name)
            )
            # Fill columns
            self._col_table.setRowCount(len(info.columns))
            for i, col in enumerate(info.columns):
                self._col_table.setItem(i, 0, QTableWidgetItem(col.name))
                self._col_table.setItem(i, 1, QTableWidgetItem(col.data_type))
                self._col_table.setItem(i, 2, QTableWidgetItem("YES" if col.nullable else "NO"))
                self._col_table.setItem(i, 3, QTableWidgetItem(str(col.default or "")))
                self._col_table.setItem(i, 4, QTableWidgetItem("PRI" if col.is_primary_key else ""))
                self._col_table.setItem(i, 5, QTableWidgetItem("AUTO" if col.is_auto_increment else ""))
                self._col_table.setItem(i, 6, QTableWidgetItem(col.comment))

            # DDL
            result = pool_loop.run_until_complete(
                connector.execute(f"SHOW CREATE TABLE `{self._database}`.`{table_name}`")
            )
            if result.rows:
                self._ddl_text.setPlainText(str(result.rows[0][1]) if len(result.rows[0]) > 1 else "")
        except Exception as e:
            _log.debug("Failed to load column details: %s", e)

    def _export_html(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, t("data_dictionary.export.dialog"), f"{self._database}_dictionary.html", t("data_dictionary.export.html_filter"))
        if not path:
            return

        lines = [
            "<!DOCTYPE html><html><head><meta charset='utf-8'>",
            f"<title>数据字典 - {self._database}</title>",
            "<style>body{font-family:sans-serif;margin:20px}table{border-collapse:collapse;width:100%;margin:10px 0}th,td{border:1px solid #ccc;padding:6px 10px;text-align:left}th{background:#f0f0f0}h2{color:#333}h3{color:#555}</style>",
            f"</head><body><h1>数据字典 — {self._database}</h1>",
        ]

        for info in self._tables:
            lines.append(f"<h2>{info['name']}</h2>")
            lines.append(f"<p>引擎: {info.get('engine', '')}</p>")
            lines.append("<table><tr><th>字段名</th><th>类型</th><th>可空</th><th>默认值</th><th>主键</th><th>自增</th><th>注释</th></tr>")

            try:
                connector = connection_pool.get(self._connection_id)
                table_info = pool_loop.run_until_complete(
                    connector.get_table_info(self._database, info["name"])
                )
                for col in table_info.columns:
                    lines.append(f"<tr><td>{col.name}</td><td>{col.data_type}</td>"
                                 f"<td>{'YES' if col.nullable else 'NO'}</td>"
                                 f"<td>{col.default or ''}</td>"
                                 f"<td>{'PRI' if col.is_primary_key else ''}</td>"
                                 f"<td>{'AUTO' if col.is_auto_increment else ''}</td>"
                                 f"<td>{col.comment}</td></tr>")
            except Exception as e:
                _log.debug("Failed to export column %s: %s", col.name, e)
        lines.append("</table>")

        lines.append("</body></html>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _export_pdf(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, t("data_dictionary.export.dialog_pdf"), f"{self._database}_dictionary.pdf", t("data_dictionary.export.pdf_filter"))
        if not path:
            return
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrinter
        html_lines = [
            "<html><head><meta charset='utf-8'><style>"
            "body{font-family:sans-serif;margin:20px}"
            "table{border-collapse:collapse;width:100%;margin:10px 0}"
            "th,td{border:1px solid #555;padding:4px 8px;text-align:left}"
            "th{background:#e0e0e0}h2{color:#333}"
            "</style></head><body>",
            f"<h1>数据字典 — {self._database}</h1>",
        ]
        for info in self._tables:
            html_lines.append(f"<h2>{info['name']}</h2>")
            html_lines.append("<table><tr><th>字段名</th><th>类型</th><th>可空</th><th>默认值</th><th>主键</th><th>自增</th><th>注释</th></tr>")
            try:
                connector = connection_pool.get(self._connection_id)
                table_info = pool_loop.run_until_complete(connector.get_table_info(self._database, info["name"]))
                for col in table_info.columns:
                    html_lines.append(f"<tr><td>{col.name}</td><td>{col.data_type}</td>"
                                     f"<td>{'YES' if col.nullable else 'NO'}</td>"
                                     f"<td>{col.default or ''}</td>"
                                     f"<td>{'PRI' if col.is_primary_key else ''}</td>"
                                     f"<td>{'AUTO' if col.is_auto_increment else ''}</td>"
                                     f"<td>{col.comment}</td></tr>")
            except Exception:
                pass
            html_lines.append("</table>")
        html_lines.append("</body></html>")
        doc = QTextDocument()
        doc.setHtml("\n".join(html_lines))
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(path)
        doc.print_(printer)
