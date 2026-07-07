"""Command Line Interface — built-in SQL terminal."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.connection_pool import connection_pool
from open_navicat.i18n import t


class CommandLineWidget(QWidget):
    """Built-in MySQL command line interface."""

    def __init__(self, connection_id: str, database: str = "", parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        self._setup_ui()

    def _detect_engine(self) -> str:
        connector = connection_pool.get(self._connection_id)
        if connector:
            info = getattr(connector, "_info", None)
            return getattr(info, "engine", "mysql") if info else "mysql"
        return "mysql"

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.addWidget(QLabel(t("command_line.title")))
        h_layout.addStretch()
        btn_clear = QPushButton(t("command_line.btn.clear"))
        btn_clear.clicked.connect(self._clear_output)
        h_layout.addWidget(btn_clear)
        layout.addWidget(header)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setObjectName("monospaceText")
        self._output.setFont(QFont("Consolas", 11))
        layout.addWidget(self._output, 1)

        # Input area
        input_widget = QWidget()
        input_layout = QHBoxLayout(input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)

        engine = self._detect_engine()
        prompt_text = f"{engine}> " if self._database is None else f"{engine}({self._database})> " if self._database else f"{engine}> "
        self._prompt_label = QLabel(prompt_text)
        self._prompt_label.setObjectName("accentLabel")
        input_layout.addWidget(self._prompt_label)

        self._input = QLineEdit()
        self._input.setFont(QFont("Consolas", 11))
        self._input.returnPressed.connect(self._execute_command)
        input_layout.addWidget(self._input)

        btn_send = QPushButton(t("command_line.btn.execute"))
        btn_send.setObjectName("primaryBtn")
        btn_send.clicked.connect(self._execute_command)
        input_layout.addWidget(btn_send)

        layout.addWidget(input_widget)

        # History
        self._history: list[str] = []
        self._history_index = -1

        self._append_output(t("command_line.welcome"))
        self._append_output(t("command_line.info.connection", connection_id=self._connection_id))
        if self._database:
            self._append_output(t("command_line.info.database", database=self._database))
        self._append_output(t("command_line.info.hint"))

    def _execute_command(self) -> None:
        cmd = self._input.text().strip()
        if not cmd:
            return

        self._history.append(cmd)
        self._history_index = len(self._history)
        self._input.clear()

        # Show command
        engine = self._detect_engine()
        self._append_output(f"{engine}> {cmd}")

        # Handle special commands
        if cmd.lower() in ("quit", "exit", "q"):
            self._append_output(t("command_line.output.goodbye"))
            return
        if cmd.lower() == "clear":
            self._clear_output()
            return
        if cmd.lower().startswith("use "):
            self._database = cmd.split()[1].strip().strip("`")
            self._prompt_label.setText(f"{engine}({self._database})> ")
            self._append_output(t("command_line.output.db_switched", database=self._database))
            return
        if cmd.lower() in ("help", "?"):
            self._append_output(t("command_line.help.text"))
            return

        # Execute SQL
        connector = connection_pool.get(self._connection_id)
        if not connector:
            self._append_output(t("command_line.error.not_connected"))
            return

        try:
            from open_navicat.dal.connection_pool import _loop as pool_loop
            result = pool_loop.run_until_complete(connector.execute(cmd))
            if result.success:
                if result.columns and result.rows:
                    # Format as table
                    cols = [c.name for c in result.columns]
                    widths = [max(len(c), max((len(str(r[i])) for r in result.rows), default=0)) for i, c in enumerate(cols)]
                    header = " | ".join(c.ljust(w) for c, w in zip(cols, widths))
                    sep = "-+-".join("-" * w for w in widths)
                    self._append_output(header)
                    self._append_output(sep)
                    for row in result.rows[:1000]:
                        self._append_output(" | ".join(str(v).ljust(w) if v is not None else "NULL".ljust(w) for v, w in zip(row, widths)))
                    if len(result.rows) > 1000:
                        self._append_output(t("command_line.output.truncated", count=len(result.rows)))
                    self._append_output(t("command_line.output.rows", count=len(result.rows)))
                elif result.affected_rows is not None:
                    self._append_output(f"Query OK, {result.affected_rows} row(s) affected")
                else:
                    self._append_output("Query OK")
            else:
                self._append_output(f"❌ {result.error_message}")
        except Exception as e:
            self._append_output(f"❌ {e}")

    def _append_output(self, text: str) -> None:
        self._output.append(text)
        self._output.moveCursor(QTextCursor.MoveOperation.End)

    def _clear_output(self) -> None:
        self._output.clear()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Up and self._history:
            if self._history_index > 0:
                self._history_index -= 1
                self._input.setText(self._history[self._history_index])
        elif event.key() == Qt.Key.Key_Down and self._history:
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                self._input.setText(self._history[self._history_index])
            else:
                self._history_index = len(self._history)
                self._input.clear()
        else:
            super().keyPressEvent(event)
