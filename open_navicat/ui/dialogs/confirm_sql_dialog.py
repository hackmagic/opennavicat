"""Confirmation dialog for DDL/DML SQL execution."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from open_navicat.i18n import t
from open_navicat.ui.glass_theme import (
    BORDER_LIGHT,
    BORDER_MEDIUM,
    GLASS_DARK,
    TEXT_ACCENT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


class ConfirmSQLDialog(QDialog):
    """Dialog asking user to confirm DDL/DML before execution."""

    def __init__(self, sql: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("confirm_sql.title"))
        self.setMinimumSize(600, 350)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog {{
                background: {GLASS_DARK};
                border: 1px solid {BORDER_LIGHT};
                border-radius: 8px;
            }}
            QLabel {{
                color: {TEXT_PRIMARY};
                font-size: 12px;
            }}
            QPlainTextEdit {{
                background: rgba(0, 0, 0, 0.4);
                color: {TEXT_ACCENT};
                border: 1px solid {BORDER_MEDIUM};
                border-radius: 4px;
                padding: 8px;
                font-family: Consolas, monospace;
                font-size: 11px;
            }}
        """)
        self._confirmed = False
        self._setup_ui(sql)

    def _setup_ui(self, sql: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        warning = QLabel(t("confirm_sql.warning"))
        warning.setStyleSheet(f"""
            padding: 8px 12px;
            background: rgba(233, 69, 96, 0.15);
            border: 1px solid rgba(233, 69, 96, 0.4);
            border-radius: 6px;
            color: {TEXT_SECONDARY};
            font-size: 12px;
            font-weight: bold;
        """)
        warning.setWordWrap(True)
        layout.addWidget(warning)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        editor = QPlainTextEdit(scroll)
        editor.setPlainText(sql)
        editor.setReadOnly(True)
        editor.setStyleSheet(f"""
            QPlainTextEdit {{
                background: rgba(0, 0, 0, 0.4);
                color: {TEXT_ACCENT};
                border: 1px solid {BORDER_MEDIUM};
                border-radius: 4px;
                padding: 8px;
                font-family: Consolas, monospace;
                font-size: 11px;
            }}
        """)
        scroll.setWidget(editor)
        layout.addWidget(scroll, 1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton(t("common.cancel"), self)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                padding: 6px 20px;
                background: {GLASS_DARK};
                border: 1px solid {BORDER_LIGHT};
                border-radius: 4px;
                color: {TEXT_MUTED};
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.1);
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        exec_btn = QPushButton(t("confirm_sql.execute"), self)
        exec_btn.setStyleSheet("""
            QPushButton {
                padding: 6px 20px;
                background: rgba(233, 69, 96, 0.7);
                border: 1px solid rgba(233, 69, 96, 0.9);
                border-radius: 4px;
                color: white;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(233, 69, 96, 0.9);
            }
        """)
        exec_btn.clicked.connect(lambda: self._confirm())
        btn_layout.addWidget(exec_btn)

        layout.addLayout(btn_layout)

    def _confirm(self) -> None:
        self._confirmed = True
        self.accept()

    def is_confirmed(self) -> bool:
        return self._confirmed
