"""Snippet manager dialog — CRUD for reusable SQL snippets."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.local_config import local_db
from open_navicat.i18n import t


class SnippetManagerDialog(QDialog):
    """Modal dialog to manage SQL snippets with preview."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("snippet.manager"))
        self.resize(680, 480)
        self._current_id: int | None = None
        self._setup_ui()
        self._load_snippets()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left: list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel(t("snippet.snippets"), left))
        self._list = QListWidget(left)
        self._list.currentRowChanged.connect(self._on_select)
        left_layout.addWidget(self._list)

        # Add/remove buttons
        btn_row = QHBoxLayout()
        self._btn_add = QPushButton(t("common.add"), left)
        self._btn_add.clicked.connect(self._add_snippet)
        self._btn_del = QPushButton(t("common.delete"), left)
        self._btn_del.clicked.connect(self._delete_snippet)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_del)
        left_layout.addLayout(btn_row)
        splitter.addWidget(left)

        # Right: editor
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel(t("snippet.name"), right))
        self._name_input = QLineEdit(right)
        self._name_input.setPlaceholderText("snippet_name")
        right_layout.addWidget(self._name_input)

        right_layout.addWidget(QLabel(t("snippet.description"), right))
        self._desc_input = QLineEdit(right)
        right_layout.addWidget(self._desc_input)

        right_layout.addWidget(QLabel(t("snippet.sql"), right))
        self._sql_edit = QPlainTextEdit(right)
        self._sql_edit.setFont(QFont("Consolas", 10))
        self._sql_edit.setPlaceholderText("SELECT * FROM `{{table}}` WHERE ...")
        right_layout.addWidget(self._sql_edit, 1)

        # Save button
        self._btn_save = QPushButton(t("common.save"), right)
        self._btn_save.clicked.connect(self._save_snippet)
        right_layout.addWidget(self._btn_save)

        right_layout.addWidget(QLabel(
            t("snippet.variable_hint"), right,
        ))

        splitter.addWidget(right)
        splitter.setSizes([200, 480])
        layout.addWidget(splitter)

    def _load_snippets(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for snip in local_db.list_snippets():
            self._list.addItem(snip["name"])
        self._list.blockSignals(False)

    def _on_select(self, row: int) -> None:
        if row < 0:
            self._current_id = None
            self._name_input.clear()
            self._desc_input.clear()
            self._sql_edit.clear()
            return
        snippets = local_db.list_snippets()
        if row < len(snippets):
            snip = snippets[row]
            self._current_id = snip["id"]
            self._name_input.setText(snip["name"])
            self._desc_input.setText(snip.get("description", ""))
            self._sql_edit.setPlainText(snip["sql_text"])

    def _add_snippet(self) -> None:
        self._current_id = None
        self._name_input.clear()
        self._desc_input.clear()
        self._sql_edit.clear()
        self._name_input.setFocus()

    def _save_snippet(self) -> None:
        name = self._name_input.text().strip()
        sql = self._sql_edit.toPlainText().strip()
        if not name or not sql:
            QMessageBox.warning(self, t("common.notice"), t("snippet.required_fields"))
            return
        desc = self._desc_input.text().strip()
        if self._current_id:
            local_db.update_snippet(self._current_id, name, sql, desc)
        else:
            local_db.save_snippet(name, sql, desc)
        self._load_snippets()
        # Select the saved item
        for i in range(self._list.count()):
            if self._list.item(i).text() == name:
                self._list.setCurrentRow(i)
                break

    def _delete_snippet(self) -> None:
        if self._current_id is None:
            return
        reply = QMessageBox.question(
            self, t("common.confirm"),
            t("snippet.confirm_delete"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            local_db.delete_snippet(self._current_id)
            self._current_id = None
            self._load_snippets()
