"""Data Sync Panel — compare and synchronize row-level data between databases."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem,
    QFrame, QMessageBox, QProgressBar, QTabWidget,
)

from open_navicat.services.connection_manager import connection_manager
from open_navicat.services.metadata_service import metadata_service
from open_navicat.services.data_sync_engine import data_sync_engine, DataCompareResult

_log = logging.getLogger(__name__)


class DataSyncPanel(QWidget):
    """Panel for comparing and synchronizing row-level data between two tables."""

    def __init__(self, connection_id: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._result: Optional[DataCompareResult] = None
        self._setup_ui()
        self._load_connections()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Top: source & target selection ──
        sel_frame = QFrame(self)
        sel_layout = QHBoxLayout(sel_frame)

        # Source
        src_group = QVBoxLayout()
        src_group.addWidget(QLabel("源 (Source)", sel_frame))
        src_row = QHBoxLayout()
        self._src_conn = QComboBox(sel_frame)
        self._src_conn.setMinimumWidth(120)
        self._src_conn.currentIndexChanged.connect(self._load_src_databases)
        src_row.addWidget(self._src_conn)
        self._src_db = QComboBox(sel_frame)
        self._src_db.setMinimumWidth(120)
        self._src_db.currentIndexChanged.connect(self._load_src_tables)
        src_row.addWidget(self._src_db)
        self._src_table = QComboBox(sel_frame)
        self._src_table.setMinimumWidth(120)
        src_row.addWidget(self._src_table)
        src_group.addLayout(src_row)
        sel_layout.addLayout(src_group, 1)

        # Arrow
        arrow = QLabel("  →  ", sel_frame)
        sel_layout.addWidget(arrow)

        # Target
        tgt_group = QVBoxLayout()
        tgt_group.addWidget(QLabel("目标 (Target)", sel_frame))
        tgt_row = QHBoxLayout()
        self._tgt_conn = QComboBox(sel_frame)
        self._tgt_conn.setMinimumWidth(120)
        self._tgt_conn.currentIndexChanged.connect(self._load_tgt_databases)
        tgt_row.addWidget(self._tgt_conn)
        self._tgt_db = QComboBox(sel_frame)
        self._tgt_db.setMinimumWidth(120)
        self._tgt_db.currentIndexChanged.connect(self._load_tgt_tables)
        tgt_row.addWidget(self._tgt_db)
        self._tgt_table = QComboBox(sel_frame)
        self._tgt_table.setMinimumWidth(120)
        tgt_row.addWidget(self._tgt_table)
        tgt_group.addLayout(tgt_row)
        sel_layout.addLayout(tgt_group, 1)

        layout.addWidget(sel_frame)

        # ── Buttons ──
        btn_row = QHBoxLayout()
        self._btn_compare = QPushButton("🔍 比较", self)
        self._btn_compare.setObjectName("primaryBtn")
        self._btn_compare.clicked.connect(self._compare)
        btn_row.addWidget(self._btn_compare)

        self._btn_sync = QPushButton("🚀 同步到目标", self)
        self._btn_sync.setObjectName("primaryBtn")
        self._btn_sync.setEnabled(False)
        self._btn_sync.clicked.connect(self._sync)
        btn_row.addWidget(self._btn_sync)

        btn_row.addStretch()
        self._status = QLabel("选择源和目标表后点击「比较」", self)
        btn_row.addWidget(self._status)
        layout.addLayout(btn_row)

        # ── Progress ──
        self._progress = QProgressBar(self)
        self._progress.setMaximumHeight(4)
        self._progress.setTextVisible(False)
        self._progress.hide()
        layout.addWidget(self._progress)

        # ── Results tabs ──
        self._tabs = QTabWidget(self)

        self._table_inserts = self._make_table(self._tabs)
        self._tabs.addTab(self._table_inserts, "新增 (+)")

        self._table_updates = self._make_table(self._tabs)
        self._tabs.addTab(self._table_updates, "修改 (~)")

        self._table_deletes = self._make_table(self._tabs)
        self._tabs.addTab(self._table_deletes, "删除 (-)")

        self._summary_label = QLabel(self._tabs)
        self._summary_label.setWordWrap(True)
        self._tabs.addTab(self._summary_label, "汇总")

        layout.addWidget(self._tabs, 1)

    def _make_table(self, parent) -> QTableWidget:
        table = QTableWidget(parent)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        return table

    # ── Data loading ──────────────────────────────────────────────

    def _load_connections(self) -> None:
        saved = connection_manager.list_saved()
        names = [s.name for s in saved]
        self._src_conn.clear()
        self._tgt_conn.clear()
        self._src_conn.addItems(names)
        self._tgt_conn.addItems(names)
        self._conn_id_map = {s.name: s.id for s in saved}
        if len(names) > 1:
            self._tgt_conn.setCurrentIndex(1)
        self._load_src_databases()
        self._load_tgt_databases()

    def _load_src_databases(self) -> None:
        conn_name = self._src_conn.currentText()
        cid = self._conn_id_map.get(conn_name, "")
        self._src_db.clear()
        if not cid:
            return
        try:
            dbs = metadata_service.list_databases(cid)
            self._src_db.addItems([d.name for d in dbs])
        except Exception as e:
            _log.warning("Failed to load source databases: %s", e)

    def _load_src_tables(self) -> None:
        conn_name = self._src_conn.currentText()
        db = self._src_db.currentText()
        cid = self._conn_id_map.get(conn_name, "")
        self._src_table.clear()
        if not cid or not db:
            return
        try:
            tables = metadata_service.list_tables(cid, db)
            self._src_table.addItems(tables)
        except Exception as e:
            _log.warning("Failed to load source tables: %s", e)

    def _load_tgt_databases(self) -> None:
        conn_name = self._tgt_conn.currentText()
        cid = self._conn_id_map.get(conn_name, "")
        self._tgt_db.clear()
        if not cid:
            return
        try:
            dbs = metadata_service.list_databases(cid)
            self._tgt_db.addItems([d.name for d in dbs])
        except Exception as e:
            _log.warning("Failed to load target databases: %s", e)

    def _load_tgt_tables(self) -> None:
        conn_name = self._tgt_conn.currentText()
        db = self._tgt_db.currentText()
        cid = self._conn_id_map.get(conn_name, "")
        self._tgt_table.clear()
        if not cid or not db:
            return
        try:
            tables = metadata_service.list_tables(cid, db)
            self._tgt_table.addItems(tables)
        except Exception as e:
            _log.warning("Failed to load target tables: %s", e)

    # ── Compare ───────────────────────────────────────────────────

    @Slot()
    def _compare(self) -> None:
        src_conn = self._conn_id_map.get(self._src_conn.currentText(), "")
        tgt_conn = self._conn_id_map.get(self._tgt_conn.currentText(), "")
        src_db = self._src_db.currentText()
        tgt_db = self._tgt_db.currentText()
        src_tbl = self._src_table.currentText()
        tgt_tbl = self._tgt_table.currentText()

        if not all([src_conn, tgt_conn, src_db, tgt_db, src_tbl, tgt_tbl]):
            QMessageBox.warning(self, "提示", "请选择源和目标的连接、数据库和表。")
            return

        self._progress.show()
        self._progress.setRange(0, 0)
        self._btn_compare.setEnabled(False)
        self._status.setText("正在比较...")

        try:
            self._result = data_sync_engine.compare_tables(
                src_conn, src_db, src_tbl, tgt_conn, tgt_db, tgt_tbl,
            )
            self._render_results()
        except Exception as e:
            QMessageBox.critical(self, "比较失败", str(e))
            self._status.setText("比较失败")
        finally:
            self._progress.hide()
            self._btn_compare.setEnabled(True)

    def _render_results(self) -> None:
        r = self._result
        if not r:
            return

        self._btn_sync.setEnabled(r.total_diffs > 0)
        self._status.setText(
            f"源: {r.source_rows} 行 | 目标: {r.target_rows} 行 | "
            f"差异: +{len(r.inserts)} ~{len(r.updates)} -{len(r.deletes)}"
        )

        # Inserts
        self._fill_table(self._table_inserts, r.inserts,
                         [c.name for c in r.columns],
                         lambda d: d.set_values)

        # Updates
        self._fill_table(self._table_updates, r.updates,
                         list({k for d in r.updates for k in d.set_values}),
                         lambda d: {k: f"{d.old_values.get(k, '?')} → {v}" for k, v in d.set_values.items()})

        # Deletes
        self._fill_table(self._table_deletes, r.deletes,
                         [c.name for c in r.columns],
                         lambda d: d.pk_values)

        # Summary
        lines = [
            f"<b>源表:</b> {r.source_table} ({r.source_rows} 行)",
            f"<b>目标表:</b> {r.target_table} ({r.target_rows} 行)",
            f"<b>主键:</b> {', '.join(r.pk_columns)}",
            "",
            f"<b>新增 (INSERT):</b> {len(r.inserts)} 行",
            f"<b>修改 (UPDATE):</b> {len(r.updates)} 行",
            f"<b>删除 (DELETE):</b> {len(r.deletes)} 行",
        ]
        self._summary_label.setText("<br>".join(lines))

    def _fill_table(self, table: QTableWidget, diffs, columns: list[str], get_vals) -> None:
        table.setColumnCount(len(columns) + 1)
        table.setHorizontalHeaderLabels(["PK"] + columns)
        table.setRowCount(len(diffs))
        for i, diff in enumerate(diffs):
            # PK column
            pk_str = ", ".join(f"{k}={v}" for k, v in diff.pk_values.items())
            pk_item = QTableWidgetItem(pk_str)
            pk_item.setForeground(QColor("#569cd6"))
            table.setItem(i, 0, pk_item)
            vals = get_vals(diff)
            for j, col in enumerate(columns):
                v = vals.get(col)
                item = QTableWidgetItem(str(v) if v is not None else "NULL")
                if v is None:
                    item.setForeground(QColor("#808080"))
                table.setItem(i, j + 1, item)
        table.resizeColumnsToContents()

    # ── Sync ──────────────────────────────────────────────────────

    @Slot()
    def _sync(self) -> None:
        if not self._result or self._result.total_diffs == 0:
            return

        script = data_sync_engine.generate_sync_script(self._result)
        n = self._result.total_diffs

        reply = QMessageBox.question(
            self, "确认同步",
            f"即将对目标表应用 {n} 处更改：\n"
            f"  +{len(self._result.inserts)} 新增\n"
            f"  ~{len(self._result.updates)} 修改\n"
            f"  -{len(self._result.deletes)} 删除\n\n"
            f"确定执行？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        tgt_conn = self._conn_id_map.get(self._tgt_conn.currentText(), "")
        if not tgt_conn:
            return

        from open_navicat.dal.connection_pool import connection_pool, _loop as pool_loop
        connector = connection_pool.get(tgt_conn)
        if not connector:
            QMessageBox.warning(self, "错误", "目标连接不可用。")
            return

        self._progress.show()
        self._progress.setRange(0, len(self._result.inserts) + len(self._result.updates) + len(self._result.deletes))
        errors = []
        done = 0
        for stmt in script.split("\n"):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                pool_loop.run_until_complete(connector.execute(stmt))
            except Exception as e:
                errors.append(f"{stmt[:60]}... → {e}")
            done += 1
            self._progress.setValue(done)

        self._progress.hide()
        if errors:
            QMessageBox.warning(self, "部分失败", f"{len(errors)} 条语句失败:\n" + "\n".join(errors[:5]))
        else:
            QMessageBox.information(self, "完成", f"成功同步 {n} 处更改到目标表。")

        self._compare()
