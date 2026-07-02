"""Side-by-side query comparison dialog."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from open_navicat.i18n import t


class QueryCompareDialog(QDialog):
    """Compare two SQL queries side by side with diff highlighting."""
    def __init__(self, sql_a: str = "", sql_b: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("query_compare.title"))
        self.resize(900, 500)
        layout = QVBoxLayout(self)
        h_layout = QHBoxLayout()
        left = QTextEdit()
        left.setReadOnly(True)
        left.setPlainText(sql_a)
        left.setObjectName("monospaceText")
        h_layout.addWidget(left)
        right = QTextEdit()
        right.setReadOnly(True)
        right.setPlainText(sql_b)
        right.setObjectName("monospaceText")
        h_layout.addWidget(right)
        layout.addLayout(h_layout)
        close_btn = QPushButton(t("common.close"))
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
