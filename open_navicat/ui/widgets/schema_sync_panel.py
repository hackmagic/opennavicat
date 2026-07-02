"""Schema Sync Panel — compare and synchronize database structures."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from open_navicat.i18n import t
from open_navicat.services.metadata_service import metadata_service
from open_navicat.services.sync_engine import SyncDiff, sync_engine


class _ScriptPreviewDialog(QDialog):
    """Preview DDL script before applying."""

    def __init__(self, statements: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("同步脚本预览")
        self.resize(700, 500)
        layout = QVBoxLayout(self)

        editor = QPlainTextEdit(self)
        editor.setReadOnly(True)
        editor.setObjectName("monospaceText")
        editor.setPlainText("\n\n".join(statements))
        layout.addWidget(editor, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("schema_sync.msg.confirm"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("common.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class _DiffColors:
    ADD = QColor("#4ec9b0")
    REMOVE = QColor("#f44747")
    MODIFY = QColor("#dcdcaa")
    NORMAL = QColor("#cccccc")


class SchemaSyncPanel(QWidget):
    """Compare source and target databases, show diffs, apply changes."""

    def __init__(self, connection_id: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._diff_result: Optional[SyncDiff] = None
        self._setup_ui()
        self._load_databases()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ──
        header = QWidget(self)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 8, 12, 8)

        title = QLabel(t("schema_sync.title"), header)
        h_layout.addWidget(title)
        h_layout.addStretch()

        self._btn_compare = QPushButton(t("schema_sync.btn.compare"), header)
        self._btn_compare.setObjectName("primaryBtn")
        self._btn_compare.clicked.connect(self._compare)
        h_layout.addWidget(self._btn_compare)

        layout.addWidget(header)

        # ── Source / Target selector ──
        selector = QWidget(self)
        s_layout = QHBoxLayout(selector)
        s_layout.setContentsMargins(12, 8, 12, 8)

        for label_text, attr in [(t("data_sync.label.source"), "_src_combo"), (t("data_sync.label.target"), "_tgt_combo")]:
            box = QWidget(selector)
            b_layout = QVBoxLayout(box)
            b_layout.setContentsMargins(0, 0, 0, 0)
            b_layout.addWidget(QLabel(label_text, box))
            combo = QComboBox(box)
            b_layout.addWidget(combo)
            s_layout.addWidget(box)
            setattr(self, attr, combo)

        s_layout.addStretch()
        layout.addWidget(selector)

        # ── Diff result tree ──
        self._diff_tree = QTreeWidget(self)
        self._diff_tree.setHeaderLabels(["差异项", "说明"])
        self._diff_tree.setColumnWidth(0, 350)
        self._diff_tree.setAlternatingRowColors(False)
        layout.addWidget(self._diff_tree, 1)

        # ── Status bar ──
        self._status_label = QLabel(t("schema_sync.status.ready"), self)
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        # ── Action bar ──
        actions = QWidget(self)
        a_layout = QHBoxLayout(actions)
        a_layout.setContentsMargins(12, 8, 12, 8)

        self._btn_apply = QPushButton(t("schema_sync.btn.apply"), actions)
        self._btn_apply.setObjectName("primaryBtn")
        self._btn_apply.clicked.connect(self._apply_changes)
        self._btn_apply.setEnabled(False)
        a_layout.addWidget(self._btn_apply)

        self._btn_preview = QPushButton(t("schema_sync.btn.preview"), actions)
        self._btn_preview.clicked.connect(self._preview_script)
        self._btn_preview.setEnabled(False)
        a_layout.addWidget(self._btn_preview)

        a_layout.addStretch()

        self._summary_label = QLabel("", actions)
        a_layout.addWidget(self._summary_label)

        layout.addWidget(actions)

    # ── Data loading ──────────────────────────────────────────────────

    def _load_databases(self) -> None:
        """Populate database combo boxes from the active connection."""
        db_list = metadata_service.list_databases(self._connection_id)
        names = [d.name for d in db_list] if db_list else []
        for combo in (self._src_combo, self._tgt_combo):
            combo.clear()
            combo.addItems(names)

    # ── Comparison ────────────────────────────────────────────────────

    def _compare(self) -> None:
        source_db = self._src_combo.currentText()
        target_db = self._tgt_combo.currentText()

        if not source_db or not target_db:
            QMessageBox.warning(self, t("common.notice"), t("schema_sync.msg.select_db"))
            return

        self._btn_compare.setText(t("schema_sync.msg.comparing"))
        self._btn_compare.setEnabled(False)
        self._diff_tree.clear()
        self._btn_apply.setEnabled(False)
        self._btn_preview.setEnabled(False)
        self._summary_label.setText("")
        self._status_label.setVisible(False)

        # Run comparison asynchronously via QTimer
        self._pending_cmp = (source_db, target_db)
        QTimer.singleShot(50, self._do_compare)

    def _do_compare(self) -> None:
        source_db, target_db = self._pending_cmp
        try:
            diff = sync_engine.compare_databases(
                self._connection_id, source_db, target_db,
            )
            self._diff_result = diff
            self._render_diff(diff, source_db, target_db)
        except Exception as exc:
            QMessageBox.critical(self, t("schema_sync.msg.compare_failed"), f"无法完成结构比较:\n{exc}")
        finally:
            self._btn_compare.setText(t("schema_sync.btn.recompare"))
            self._btn_compare.setEnabled(True)

    # ── Rendering ─────────────────────────────────────────────────────

    def _render_diff(self, diff: SyncDiff, source_db: str, target_db: str) -> None:
        self._diff_tree.clear()

        if not diff.has_changes:
            item = QTreeWidgetItem(self._diff_tree, [
                t("schema_sync.msg.identical"),
                f"{source_db} ↔ {target_db} {t('schema_sync.msg.no_diff')}",
            ])
            item.setForeground(0, _DiffColors.ADD)
            self._btn_apply.setEnabled(False)
            self._btn_preview.setEnabled(False)
            self._summary_label.setText(t("schema_sync.msg.no_diff"))
            return

        # Added tables
        if diff.added_tables:
            parent = QTreeWidgetItem(self._diff_tree, [
                f"新增表 ({len(diff.added_tables)})", ""
            ])
            parent.setForeground(0, _DiffColors.ADD)
            parent.setExpanded(True)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            for t in diff.added_tables:
                child = QTreeWidgetItem(parent, [
                    f"  {t.name}",
                    f"CREATE TABLE ({len(t.columns)} 列, {len(t.indexes)} 索引)",
                ])
                child.setForeground(0, _DiffColors.ADD)

        # Removed tables
        if diff.removed_tables:
            parent = QTreeWidgetItem(self._diff_tree, [
                f"删除表 ({len(diff.removed_tables)})", ""
            ])
            parent.setForeground(0, _DiffColors.REMOVE)
            parent.setExpanded(True)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            for t in diff.removed_tables:
                child = QTreeWidgetItem(parent, [f"  {t}", "DROP TABLE"])
                child.setForeground(0, _DiffColors.REMOVE)

        # Modified tables
        if diff.modified_tables:
            parent = QTreeWidgetItem(self._diff_tree, [
                f"修改的表 ({len(diff.modified_tables)})", ""
            ])
            parent.setForeground(0, _DiffColors.MODIFY)
            parent.setExpanded(True)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            for td in diff.modified_tables:
                table_item = QTreeWidgetItem(parent, [
                    f"  {td.table_name}", ""
                ])
                table_item.setForeground(0, _DiffColors.NORMAL)

                for col in td.added_columns:
                    QTreeWidgetItem(table_item, [
                        f"    + 列: {col.name} {col.data_type}",
                        "ADD COLUMN",
                    ]).setForeground(0, _DiffColors.ADD)

                for col_name in td.removed_columns:
                    QTreeWidgetItem(table_item, [
                        f"    - 列: {col_name}",
                        "DROP COLUMN",
                    ]).setForeground(0, _DiffColors.REMOVE)

                for cd in td.modified_columns:
                    QTreeWidgetItem(table_item, [
                        f"    ~ 列: {cd.column_name}  {cd.old_type} → {cd.new_type}",
                        "MODIFY COLUMN",
                    ]).setForeground(0, _DiffColors.MODIFY)

                for idx in td.added_indexes:
                    cols = ", ".join(idx.columns)
                    QTreeWidgetItem(table_item, [
                        f"    + 索引: {idx.name} ({cols})",
                        "ADD INDEX",
                    ]).setForeground(0, _DiffColors.ADD)

                for idx_name in td.removed_indexes:
                    QTreeWidgetItem(table_item, [
                        f"    - 索引: {idx_name}",
                        "DROP INDEX",
                    ]).setForeground(0, _DiffColors.REMOVE)

                for fk in td.added_foreign_keys:
                    QTreeWidgetItem(table_item, [
                        f"    + 外键: {fk.name}  {fk.column} → {fk.ref_table}({fk.ref_column})",
                        "ADD FOREIGN KEY",
                    ]).setForeground(0, _DiffColors.ADD)

                for fk_name in td.removed_foreign_keys:
                    QTreeWidgetItem(table_item, [
                        f"    - 外键: {fk_name}",
                        "DROP FOREIGN KEY",
                    ]).setForeground(0, _DiffColors.REMOVE)

        # Summary
        self._btn_apply.setEnabled(True)
        self._btn_preview.setEnabled(True)
        changes = diff.total_changes
        self._summary_label.setText(
            f"共 {changes} 处差异  "
            f"(+{sum(1 for _ in diff.added_tables)}表 "
            f"-{len(diff.removed_tables)}表 "
            f"~{len(diff.modified_tables)}表)"
        )

        # Status
        self._status_label.setText(
            f"来源: {diff.source_db}  →  目标: {diff.target_db}"
        )
        self._status_label.setVisible(True)

    # ── Actions ───────────────────────────────────────────────────────

    def _preview_script(self) -> None:
        """Show the generated DDL script in a dialog."""
        if not self._diff_result:
            return
        target_db = self._tgt_combo.currentText()
        statements = sync_engine.generate_sync_script(self._diff_result, target_db)
        if not statements:
            QMessageBox.information(self, t("schema_sync.btn.preview_script"), t("schema_sync.msg.no_changes"))
            return

        dialog = _ScriptPreviewDialog(statements, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._apply_changes()

    def _apply_changes(self) -> None:
        """Execute the sync script on the target database."""
        if not self._diff_result:
            return

        target_db = self._tgt_combo.currentText()
        statements = sync_engine.generate_sync_script(self._diff_result, target_db)
        if not statements:
            QMessageBox.information(self, t("common.notice"), t("schema_sync.msg.no_changes"))
            return

        confirm = QMessageBox.question(
            self, t("schema_sync.msg.confirm"),
            f"即将对数据库「{target_db}」执行 {len(statements)} 条 DDL 语句。\n"
            "此操作不可撤销，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        from open_navicat.services.query_engine import query_engine

        errors = []
        for i, stmt in enumerate(statements):
            result = query_engine.execute(self._connection_id, stmt)
            if not result.success:
                errors.append(f"#{i + 1}: {result.error_message}")

        if errors:
            QMessageBox.critical(
                self, t("schema_sync.msg.completed_with_errors"),
                f"已执行 {len(statements) - len(errors)}/{len(statements)} 条语句。\n\n"
                + "\n".join(errors[:5]),
            )
        else:
            QMessageBox.information(
                self, t("schema_sync.msg.completed"),
                f"成功执行 {len(statements)} 条 DDL 语句，目标数据库「{target_db}」已与来源同步。",
            )

        # Refresh diff view
        self._compare()
