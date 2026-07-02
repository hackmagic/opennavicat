"""Data Transfer Wizard — batch copy tables/structure between connections."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.connection_pool import _loop as pool_loop
from open_navicat.dal.connection_pool import connection_pool
from open_navicat.i18n import t
from open_navicat.services.connection_manager import connection_manager
from open_navicat.services.metadata_service import metadata_service

_log = logging.getLogger(__name__)


class _TransferWorker(QThread):
    """Background thread for executing transfer."""
    progress = Signal(int, str)
    finished = Signal(int, list)

    def __init__(self, src_id: str, tgt_id: str, src_db: str, tgt_db: str,
                 tables: list[str], opts: dict) -> None:
        super().__init__()
        self._src_id = src_id
        self._tgt_id = tgt_id
        self._src_db = src_db
        self._tgt_db = tgt_db
        self._tables = tables
        self._opts = opts
        self._processed = 0

    def run(self) -> None:
        src = connection_pool.get(self._src_id)
        tgt = connection_pool.get(self._tgt_id)
        errors: list[str] = []
        total = len(self._tables)

        for i, table in enumerate(self._tables):
            self.progress.emit(i, f"传输 {table}...")
            try:
                self._transfer_table(src, tgt, table, errors)
            except Exception as e:
                errors.append(f"{table}: {e}")
            self._processed += 1

        self.finished.emit(total, errors)

    def _transfer_table(self, src, tgt, table: str, errors: list[str]) -> None:
        opts = self._opts

        # 1. Get source structure
        if opts.get("structure", True):
            result = pool_loop.run_until_complete(
                src.execute(f"SHOW CREATE TABLE `{table}`")
            )
            if result.rows and result.rows[0]:
                ddl = result.rows[0][1]
                if opts.get("drop_if_exists", False):
                    pool_loop.run_until_complete(
                        tgt.execute(f"DROP TABLE IF EXISTS `{table}`")
                    )
                pool_loop.run_until_complete(tgt.execute(ddl))

        # 2. Copy data
        if opts.get("data", True):
            result = pool_loop.run_until_complete(
                src.execute(f"SELECT * FROM `{table}`")
            )
            if not result.rows:
                return

            cols = [c.name for c in result.columns] if result.columns else []
            if not cols:
                return

            batch_size = opts.get("batch_size", 1000)
            placeholders = ", ".join(["%s"] * len(cols))
            col_list = ", ".join(f"`{c}`" for c in cols)
            insert_sql = f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders})"

            if opts.get("truncate", False) and not opts.get("drop_if_exists", False):
                pool_loop.run_until_complete(tgt.execute(f"TRUNCATE TABLE `{table}`"))

            for start in range(0, len(result.rows), batch_size):
                batch = result.rows[start:start + batch_size]
                for row in batch:
                    try:
                        pool_loop.run_until_complete(tgt.execute(insert_sql, list(row)))
                    except Exception as e:
                        errors.append(f"{table} row insert: {e}")


class DataTransferWidget(QWidget):
    """Batch data transfer between database connections."""

    def __init__(self, connection_id: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._tables_list: list[str] = []
        self._worker: _TransferWorker | None = None
        self._setup_ui()
        self._load_connections()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.addWidget(QLabel(t("data_transfer.title")))
        h_layout.addStretch()
        layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Source & Target selection ──
        sel_frame = QGroupBox(t("data_transfer.label.source_target"))
        sel_layout = QHBoxLayout(sel_frame)

        # Source
        src_col = QVBoxLayout()
        src_col.addWidget(QLabel(t("data_transfer.label.source_conn")))
        self._src_conn = QComboBox()
        self._src_conn.currentIndexChanged.connect(self._load_src_dbs)
        src_col.addWidget(self._src_conn)
        self._src_db = QComboBox()
        self._src_db.currentIndexChanged.connect(self._load_src_tables)
        src_col.addWidget(self._src_db)
        sel_layout.addLayout(src_col)

        arrow = QLabel("  →  ")
        sel_layout.addWidget(arrow)

        # Target
        tgt_col = QVBoxLayout()
        tgt_col.addWidget(QLabel(t("data_transfer.label.target_conn")))
        self._tgt_conn = QComboBox()
        self._tgt_conn.currentIndexChanged.connect(self._load_tgt_dbs)
        tgt_col.addWidget(self._tgt_conn)
        self._tgt_db = QComboBox()
        tgt_col.addWidget(self._tgt_db)
        sel_layout.addLayout(tgt_col)

        splitter.addWidget(sel_frame)

        # ── Table list ──
        tbl_frame = QGroupBox(t("data_transfer.label.table_list"))
        tbl_layout = QVBoxLayout(tbl_frame)

        btn_row = QHBoxLayout()
        btn_select_all = QPushButton(t("data_transfer.btn.select_all"))
        btn_select_all.clicked.connect(lambda: self._toggle_all(True))
        btn_row.addWidget(btn_select_all)
        btn_deselect_all = QPushButton(t("data_transfer.btn.deselect_all"))
        btn_deselect_all.clicked.connect(lambda: self._toggle_all(False))
        btn_row.addWidget(btn_deselect_all)
        btn_row.addStretch()
        tbl_layout.addLayout(btn_row)

        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["", "表名"])
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl_layout.addWidget(self._table)

        splitter.addWidget(tbl_frame)

        # ── Options ──
        opt_frame = QGroupBox(t("data_transfer.label.options"))
        opt_layout = QHBoxLayout(opt_frame)

        self._opt_structure = QCheckBox(t("data_transfer.checkbox.structure"))
        self._opt_structure.setChecked(True)
        opt_layout.addWidget(self._opt_structure)
        self._opt_data = QCheckBox(t("data_transfer.checkbox.data"))
        self._opt_data.setChecked(True)
        opt_layout.addWidget(self._opt_data)
        self._opt_drop = QCheckBox("DROP IF EXISTS")
        opt_layout.addWidget(self._opt_drop)
        self._opt_truncate = QCheckBox(t("data_transfer.checkbox.truncate"))
        opt_layout.addWidget(self._opt_truncate)
        opt_layout.addWidget(QLabel(t("data_transfer.label.batch_size")))
        self._batch_size = QSpinBox()
        self._batch_size.setRange(1, 100000)
        self._batch_size.setValue(1000)
        opt_layout.addWidget(self._batch_size)
        opt_layout.addStretch()

        splitter.addWidget(opt_frame)

        layout.addWidget(splitter, 1)

        # ── Bottom buttons ──
        bottom = QHBoxLayout()
        self._btn_transfer = QPushButton(t("data_transfer.btn.start"))
        self._btn_transfer.setObjectName("primaryBtn")
        self._btn_transfer.clicked.connect(self._start_transfer)
        bottom.addWidget(self._btn_transfer)
        self._progress = QProgressBar()
        self._progress.hide()
        bottom.addWidget(self._progress, 1)
        self._status = QLabel(t("data_transfer.status.select_tables"))
        bottom.addWidget(self._status)
        layout.addLayout(bottom)

    # ── Data loading ──────────────────────────────────────────────

    def _load_connections(self) -> None:
        saved = connection_manager.list_saved()
        names = [s.name for s in saved]
        self._src_conn.addItems(names)
        self._tgt_conn.addItems(names)
        self._conn_map = {s.name: s.id for s in saved}
        if len(names) > 1:
            self._tgt_conn.setCurrentIndex(1)
        self._load_src_dbs()
        self._load_tgt_dbs()

    def _load_src_dbs(self) -> None:
        cid = self._conn_map.get(self._src_conn.currentText(), "")
        self._src_db.clear()
        if not cid:
            return
        try:
            dbs = metadata_service.list_databases(cid)
            self._src_db.addItems([d.name for d in dbs])
        except Exception as e:
            _log.warning("Failed to load source databases: %s", e)

    def _load_src_tables(self) -> None:
        cid = self._conn_map.get(self._src_conn.currentText(), "")
        db = self._src_db.currentText()
        self._tables_list = []
        if not cid or not db:
            return
        try:
            self._tables_list = metadata_service.list_tables(cid, db)
            self._fill_table_list()
        except Exception as e:
            _log.warning("Failed to load source tables: %s", e)

    def _load_tgt_dbs(self) -> None:
        cid = self._conn_map.get(self._tgt_conn.currentText(), "")
        self._tgt_db.clear()
        if not cid:
            return
        try:
            dbs = metadata_service.list_databases(cid)
            self._tgt_db.addItems([d.name for d in dbs])
        except Exception as e:
            _log.warning("Failed to load target databases: %s", e)

    def _fill_table_list(self) -> None:
        self._table.setRowCount(len(self._tables_list))
        for i, name in enumerate(self._tables_list):
            cb = QTableWidgetItem()
            cb.setCheckState(Qt.CheckState.Checked)
            self._table.setItem(i, 0, cb)
            self._table.setItem(i, 1, QTableWidgetItem(name))

    def _toggle_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._table.rowCount()):
            item = self._table.item(i, 0)
            if item:
                item.setCheckState(state)

    def _selected_tables(self) -> list[str]:
        result = []
        for i in range(self._table.rowCount()):
            item = self._table.item(i, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                name_item = self._table.item(i, 1)
                if name_item:
                    result.append(name_item.text())
        return result

    # ── Transfer ──────────────────────────────────────────────────

    @Slot()
    def _start_transfer(self) -> None:
        tables = self._selected_tables()
        if not tables:
            QMessageBox.warning(self, t("common.notice"), t("data_transfer.msg.no_tables"))
            return

        src_id = self._conn_map.get(self._src_conn.currentText(), "")
        tgt_id = self._conn_map.get(self._tgt_conn.currentText(), "")
        src_db = self._src_db.currentText()
        tgt_db = self._tgt_db.currentText()

        if not all([src_id, tgt_id, src_db, tgt_db]):
            QMessageBox.warning(self, t("common.notice"), t("data_transfer.msg.select_complete"))
            return

        opts = {
            "structure": self._opt_structure.isChecked(),
            "data": self._opt_data.isChecked(),
            "drop_if_exists": self._opt_drop.isChecked(),
            "truncate": self._opt_truncate.isChecked(),
            "batch_size": self._batch_size.value(),
        }

        tgt_conn_name = self._tgt_conn.currentText()
        reply = QMessageBox.question(
            self, t("data_transfer.msg.confirm"),
            f"即将传输 {len(tables)} 张表:\n" + "\n".join(f"  {tbl}" for tbl in tables[:10])
            + ("\n  ..." if len(tables) > 10 else "")
            + f"\n\n到 {tgt_conn_name}/{tgt_db}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._btn_transfer.setEnabled(False)
        self._progress.show()
        self._progress.setRange(0, len(tables))
        self._progress.setValue(0)
        self._status.setText(t("data_transfer.msg.transferring"))

        self._worker = _TransferWorker(src_id, tgt_id, src_db, tgt_db, tables, opts)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_progress(self, idx: int, msg: str) -> None:
        self._progress.setValue(idx)
        self._status.setText(msg)

    def _on_finished(self, total: int, errors: list[str]) -> None:
        self._progress.hide()
        self._btn_transfer.setEnabled(True)
        if errors:
            QMessageBox.warning(self, t("data_transfer.msg.partial_failure"),
                                f"{len(errors)}/{total} 张表传输失败:\n" + "\n".join(errors[:5]))
            self._status.setText(f"完成，{len(errors)} 张表失败")
        else:
            QMessageBox.information(self, t("data_transfer.msg.complete"),
                                    f"成功传输 {total} 张表。")
            self._status.setText(f"成功传输 {total} 张表")
