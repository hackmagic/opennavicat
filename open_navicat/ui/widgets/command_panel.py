"""Command Panel — records GUI actions as equivalent CLI commands."""

from __future__ import annotations

import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from open_navicat.i18n import t


class CommandPanel(QWidget):
    """Bottom panel that records GUI actions as CLI commands."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._commands: list[dict] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        title = QPushButton(t("command_panel.title"))
        title.setObjectName("commandPanelTitle")
        title.setStyleSheet("font-weight: bold; border: none; text-align: left;")
        title.clicked.connect(self._clear)
        header.addWidget(title)
        header.addStretch()

        self._export_btn = QPushButton(t("command_panel.export"))
        self._export_btn.setObjectName("exportBtn")
        self._export_btn.clicked.connect(self._export_script)
        header.addWidget(self._export_btn)

        self._clear_btn = QPushButton(t("command_panel.clear"))
        self._clear_btn.setObjectName("clearBtn")
        self._clear_btn.clicked.connect(self._clear)
        header.addWidget(self._clear_btn)
        layout.addLayout(header)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels([
            t("command_panel.time"),
            t("command_panel.action"),
            t("command_panel.command"),
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        font = QFont("Consolas", 9)
        self._table.setFont(font)
        layout.addWidget(self._table)

    def record(self, action: str, command: str) -> None:
        """Record a GUI action and its CLI equivalent."""
        now = datetime.datetime.now().strftime("%H:%M:%S")
        self._commands.append({"time": now, "action": action, "command": command})
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QTableWidgetItem(now))
        self._table.setItem(row, 1, QTableWidgetItem(action))
        self._table.setItem(row, 2, QTableWidgetItem(command))
        self._table.scrollToBottom()

    def _export_script(self) -> None:
        """Export recorded commands as a shell script."""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, t("command_panel.export"),
            str(Path.home() / "opennavicat_script.sh"),
            "Shell Script (*.sh);;PowerShell (*.ps1);;Batch (*.bat);;All (*)",
        )
        if not path:
            return

        ext = Path(path).suffix.lower()
        if ext in (".ps1",):
            lines = ["# OpenNavicat automation script", f"# Generated: {datetime.date.today()}", ""]
            for cmd in self._commands:
                lines.append(cmd["command"])
        elif ext in (".bat", ".cmd"):
            lines = ["@echo off", "REM OpenNavicat automation script", f"REM Generated: {datetime.date.today()}", ""]
            for cmd in self._commands:
                lines.append(f"call {cmd['command']}")
        else:
            lines = ["#!/usr/bin/env bash", "# OpenNavicat automation script", f"# Generated: {datetime.date.today()}", ""]
            for cmd in self._commands:
                lines.append(cmd["command"])
            lines.append("")

        Path(path).write_text("\n".join(lines), encoding="utf-8")

    def _clear(self) -> None:
        self._commands.clear()
        self._table.setRowCount(0)
