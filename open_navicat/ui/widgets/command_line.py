"""Command Line Interface — built-in MySQL terminal."""

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


class CommandLineWidget(QWidget):
    """Built-in MySQL command line interface."""

    def __init__(self, connection_id: str, database: str = "", parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._database = database
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.addWidget(QLabel("💻 命令列界面"))
        h_layout.addStretch()
        btn_clear = QPushButton("🗑️ 清除")
        btn_clear.clicked.connect(self._clear_output)
        h_layout.addWidget(btn_clear)
        layout.addWidget(header)

        # Output area
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setObjectName("monospaceText")
        self._output.setFont(QFont("Consolas", 11))
        self._output.setStyleSheet("background: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self._output, 1)

        # Input area
        input_widget = QWidget()
        input_layout = QHBoxLayout(input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)

        self._prompt_label = QLabel("mysql> ")
        self._prompt_label.setStyleSheet("color: #4EC9B0; font-weight: bold;")
        input_layout.addWidget(self._prompt_label)

        self._input = QLineEdit()
        self._input.setFont(QFont("Consolas", 11))
        self._input.setStyleSheet("background: #2d2d30; color: #d4d4d4; border: 1px solid #3c3c3c; padding: 4px;")
        self._input.returnPressed.connect(self._execute_command)
        input_layout.addWidget(self._input)

        btn_send = QPushButton("▶ 执行")
        btn_send.setObjectName("primaryBtn")
        btn_send.clicked.connect(self._execute_command)
        input_layout.addWidget(btn_send)

        layout.addWidget(input_widget)

        # History
        self._history: list[str] = []
        self._history_index = -1

        self._append_output("欢迎使用 OpenNavicat 命令列界面")
        self._append_output(f"连接: {self._connection_id}")
        if self._database:
            self._append_output(f"数据库: {self._database}")
        self._append_output("输入 SQL 语句执行，支持所有 MySQL 命令。\n")

    def _execute_command(self) -> None:
        cmd = self._input.text().strip()
        if not cmd:
            return

        self._history.append(cmd)
        self._history_index = len(self._history)
        self._input.clear()

        # Show command
        self._append_output(f"mysql> {cmd}")

        # Handle special commands
        if cmd.lower() in ("quit", "exit", "q"):
            self._append_output("再见！")
            return
        if cmd.lower() == "clear":
            self._clear_output()
            return
        if cmd.lower().startswith("use "):
            self._database = cmd.split()[1].strip().strip("`")
            self._prompt_label.setText(f"mysql({self._database})> ")
            self._append_output(f"数据库已切换到 {self._database}")
            return
        if cmd.lower() in ("help", "?"):
            self._append_output("可用命令:\n  use <db>  - 切换数据库\n  clear     - 清除屏幕\n  quit/exit - 退出\n  任何 SQL 语句")
            return

        # Execute SQL
        connector = connection_pool.get(self._connection_id)
        if not connector:
            self._append_output("❌ 未连接到数据库")
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
                        self._append_output(f"... ({len(result.rows)} 行，仅显示前 1000 行)")
                    self._append_output(f"({len(result.rows)} 行)")
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
