"""Data Sync Panel — compare and synchronize row-level data between databases."""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from open_navicat.i18n import t
from open_navicat.services.connection_manager import connection_manager
from open_navicat.services.data_sync_engine import DataCompareResult, data_sync_engine
from open_navicat.services.metadata_service import metadata_service

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
        src_group.addWidget(QLabel(t("data_sync.label.source"), sel_frame))
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
        tgt_group.addWidget(QLabel(t("data_sync.label.target"), sel_frame))
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
        self._btn_compare = QPushButton(t("data_sync.btn.compare"), self)
        self._btn_compare.setObjectName("primaryBtn")
        self._btn_compare.clicked.connect(self._compare)
        btn_row.addWidget(self._btn_compare)

        self._btn_sync = QPushButton(t("data_sync.btn.sync"), self)
        self._btn_sync.setObjectName("primaryBtn")
        self._btn_sync.setEnabled(False)
        self._btn_sync.clicked.connect(self._sync)
        btn_row.addWidget(self._btn_sync)

        btn_row.addStretch()
        self._status = QLabel(t("data_sync.status.select_tables"), self)
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
        self._tabs.addTab(self._table_inserts, t("data_sync.tab.inserts"))

        self._table_updates = self._make_table(self._tabs)
        self._tabs.addTab(self._table_updates, t("data_sync.tab.updates"))

        self._table_deletes = self._make_table(self._tabs)
        self._tabs.addTab(self._table_deletes, t("data_sync.tab.deletes"))

        self._summary_label = QLabel(self._tabs)
        self._summary_label.setWordWrap(True)
        self._tabs.addTab(self._summary_label, t("data_sync.tab.summary"))

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
            QMessageBox.warning(self, t("common.notice"), t("data_sync.msg.select_source_target"))
            return

        self._progress.show()
        self._progress.setRange(0, 0)
        self._btn_compare.setEnabled(False)
        self._status.setText(t("data_sync.msg.comparing"))

        try:
            self._result = data_sync_engine.compare_tables(
                src_conn, src_db, src_tbl, tgt_conn, tgt_db, tgt_tbl,
            )
            self._render_results()
        except Exception as e:
            QMessageBox.critical(self, t("data_sync.msg.compare_failed"), str(e))
            self._status.setText(t("data_sync.msg.compare_failed"))
        finally:
            self._progress.hide()
            self._btn_compare.setEnabled(True)

    def _render_results(self) -> None:
        r = self._result
        if not r:
            return

        self._btn_sync.setEnabled(r.total_diffs > 0)
        self._status.setText(
            t("data_sync.msg.detail",
              source_rows=r.source_rows, target_rows=r.target_rows,
              inserts=len(r.inserts), updates=len(r.updates), deletes=len(r.deletes))
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
            t("data_sync.source_detail", tbl=r.source_table, n=r.source_rows),
            t("data_sync.target_detail", tbl=r.target_table, n=r.target_rows),
            t("data_sync.pk_detail", cols=', '.join(r.pk_columns)),
            "",
            t("data_sync.diff_insert", n=len(r.inserts)),
            t("data_sync.diff_update", n=len(r.updates)),
            t("data_sync.diff_delete", n=len(r.deletes)),
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
            self, t("data_sync.msg.confirm_sync"),
            t("data_sync.confirm_detail", n=n, inserts=len(self._result.inserts), updates=len(self._result.updates), deletes=len(self._result.deletes)) + "\n\n"
            + t("data_sync.msg.confirm_execute"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        tgt_conn = self._conn_id_map.get(self._tgt_conn.currentText(), "")
        if not tgt_conn:
            return

        from open_navicat.dal.connection_pool import _loop as pool_loop
        from open_navicat.dal.connection_pool import connection_pool
        connector = connection_pool.get(tgt_conn)
        if not connector:
            QMessageBox.warning(self, t("common.error"), t("data_sync.msg.target_unavailable"))
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
            QMessageBox.warning(self, t("data_sync.msg.partial_failure"),
                                t("data_sync.partial_failure_detail", n=len(errors)) + "\n" + "\n".join(errors[:5]))
        else:
            QMessageBox.information(self, t("data_sync.msg.complete"),
                                    t("data_sync.sync_complete", n=n))

        self._compare()
