"""AI Copilot sidebar — always-accessible AI assistant for database operations."""

from __future__ import annotations

import logging

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from open_navicat.i18n import t
from open_navicat.services.ai_service import ai_service
from open_navicat.services.connection_manager import connection_manager
from open_navicat.services.metadata_service import metadata_service

_log = logging.getLogger(__name__)
from open_navicat.ui.glass_theme import (
    BORDER_LIGHT,
    BORDER_MEDIUM,
    GLASS_DARK,
    GLASS_LIGHT,
    TEXT_ACCENT,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)


class ChatBubble(QFrame):
    """A single message bubble in the AI chat."""

    def __init__(self, text: str, is_user: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._is_user = is_user
        self._setup_ui(text)

    def _setup_ui(self, text: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # Role label
        role = QLabel("你" if self._is_user else "🤖 AI", self)
        role.setStyleSheet(
            f"font-size: 10px; color: {TEXT_MUTED};" if self._is_user
            else f"font-size: 10px; color: {TEXT_ACCENT};"
        )
        layout.addWidget(role)

        # Message text
        msg = QLabel(text, self)
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"font-size: 12px; color: {TEXT_PRIMARY}; background: rgba(9, 71, 113, 0.6); "
            f"border-radius: 8px; padding: 8px 12px; border: 1px solid {BORDER_LIGHT};"
            if self._is_user else
            f"font-size: 12px; color: {TEXT_SECONDARY}; background: {GLASS_DARK}; "
            f"border-radius: 8px; padding: 8px 12px; border: 1px solid {BORDER_MEDIUM};"
        )
        msg.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(msg)

        self.setMaximumWidth(500)


class AICopilotSidebar(QWidget):
    """Collapsible AI assistant sidebar — always accessible from the right edge."""

    sql_generated = Signal(str)  # Emitted when AI generates SQL to execute

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._is_open = False
        self._anim: QPropertyAnimation | None = None
        self._conversation_history: list[dict] = []  # For save/load
        self._setup_ui()

    # ---- public API ----

    def open_panel(self, prompt: str = "") -> None:
        """Open the panel and optionally pre-fill a prompt."""
        if not self._is_open:
            self.toggle_panel()
        if prompt:
            self._input.setText(prompt)
            self._input.setFocus()

    def close_panel(self) -> None:
        if self._is_open:
            self.toggle_panel()

    def toggle_panel(self) -> None:
        self._is_open = not self._is_open
        target_width = 380 if self._is_open else 0
        self._animate_width(target_width)

    @property
    def is_open(self) -> bool:
        return self._is_open

    # ---- UI setup ----

    def _setup_ui(self) -> None:
        self.setFixedWidth(0)
        self.setStyleSheet(f"""
            background: rgba(22, 33, 62, 0.85);
            border-left: 1px solid {BORDER_LIGHT};
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header — glass gradient
        header = QWidget(self)
        header.setStyleSheet(
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            "stop:0 rgba(233,69,96,0.6), stop:1 rgba(83,52,131,0.6)); "
            "padding: 12px 16px;"
        )
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(12, 10, 12, 10)

        title = QLabel("🤖 AI Copilot", header)
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {TEXT_PRIMARY};")
        h_layout.addWidget(title)

        h_layout.addStretch()

        # Settings button
        self._settings_btn = QPushButton("⚙️", header)
        self._settings_btn.setFixedSize(24, 24)
        self._settings_btn.setToolTip("AI 配置")
        self._settings_btn.setStyleSheet(
            "background: transparent; color: rgba(255,255,255,0.7); "
            "border: none; font-size: 14px;"
        )
        self._settings_btn.clicked.connect(self._open_ai_config)
        h_layout.addWidget(self._settings_btn)

        self._save_btn = QPushButton("💾", header)
        self._save_btn.setFixedSize(24, 24)
        self._save_btn.setToolTip("保存对话")
        self._save_btn.setStyleSheet(
            "background: transparent; color: rgba(255,255,255,0.7); "
            "border: none; font-size: 14px;"
        )
        self._save_btn.clicked.connect(self._save_conversation)
        h_layout.addWidget(self._save_btn)

        self._load_btn = QPushButton("📂", header)
        self._load_btn.setFixedSize(24, 24)
        self._load_btn.setToolTip("加载对话")
        self._load_btn.setStyleSheet(
            "background: transparent; color: rgba(255,255,255,0.7); "
            "border: none; font-size: 14px;"
        )
        self._load_btn.clicked.connect(self._load_conversation)
        h_layout.addWidget(self._load_btn)

        self._close_btn = QPushButton("✕", header)
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setStyleSheet(
            "background: transparent; color: rgba(255,255,255,0.7); "
            "border: none; font-size: 16px;"
        )
        self._close_btn.clicked.connect(self.toggle_panel)
        h_layout.addWidget(self._close_btn)

        layout.addWidget(header)

        # Mode tabs — glass
        modes = QWidget(self)
        modes.setStyleSheet(f"background: {GLASS_DARK}; border-bottom: 1px solid {BORDER_MEDIUM};")
        m_layout = QHBoxLayout(modes)
        m_layout.setContentsMargins(4, 6, 4, 6)
        m_layout.setSpacing(4)

        self._mode_btns: dict[str, QPushButton] = {}
        for mode_id, icon, label in [
            ("ask", "💬", "问答"),
            ("optimize", "⚡", "优化"),
            ("design", "📐", "设计"),
            ("generate", "🧪", "生成"),
            ("review", "🔍", "审查"),
        ]:
            btn = QPushButton(f"{icon} {label}", modes)
            btn.setCheckable(True)
            btn.setChecked(mode_id == "ask")
            btn.setStyleSheet(self._mode_style(mode_id == "ask"))
            btn.clicked.connect(lambda checked, m=mode_id: self._switch_mode(m))
            self._mode_btns[mode_id] = btn
            m_layout.addWidget(btn)

        self._mode_btns["ask"].setChecked(True)
        self._current_mode = "ask"
        layout.addWidget(modes)

        # Messages area — glass
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._messages_widget = QWidget(scroll)
        self._messages_widget.setStyleSheet("background: transparent;")
        self._messages_layout = QVBoxLayout(self._messages_widget)
        self._messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._messages_layout.setSpacing(8)
        self._messages_layout.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(self._messages_widget)

        layout.addWidget(scroll, 1)

        # Input area — glass
        input_area = QWidget(self)
        input_area.setStyleSheet(f"background: {GLASS_LIGHT}; border-top: 1px solid {BORDER_MEDIUM};")
        i_layout = QVBoxLayout(input_area)
        i_layout.setContentsMargins(8, 8, 8, 8)
        i_layout.setSpacing(6)

        self._input = QLineEdit(input_area)
        self._input.setPlaceholderText(t("ai.placeholder"))
        self._input.setStyleSheet(f"""
            padding: 8px 12px;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid {BORDER_LIGHT};
            border-radius: 6px;
            color: {TEXT_PRIMARY};
            font-size: 12px;
        """)
        self._input.returnPressed.connect(self._send_message)
        i_layout.addWidget(self._input)

        # Quick action buttons
        quick = QWidget(input_area)
        quick.setStyleSheet("background: transparent;")
        q_layout = QHBoxLayout(quick)
        q_layout.setContentsMargins(0, 0, 0, 0)
        q_layout.setSpacing(4)

        for text, tip in [
            ("📊 最近注册", "查询最近7天注册用户数"),
            ("⚡ SQL 优化", "优化当前 SQL"),
            ("📐 设计 Schema", "设计数据库表结构"),
            ("🔍 SQL 审查", "安全与性能审查 SQL"),
            ("💡 SQL 教学", "SQL 概念解释"),
        ]:
            btn = QPushButton(text, quick)
            btn.setFixedHeight(22)
            btn.setStyleSheet(f"""
                padding: 2px 8px;
                border: 1px solid {BORDER_LIGHT};
                border-radius: 10px;
                background: {GLASS_DARK};
                color: {TEXT_MUTED};
                font-size: 10px;
            """)
            btn.clicked.connect(lambda checked, t=tip: self._quick_action(t))
            q_layout.addWidget(btn)

        i_layout.addWidget(quick)
        layout.addWidget(input_area)

        # Initial welcome message
        self._add_system_message(t("ai.welcome"))

    def _open_ai_config(self) -> None:
        """Open AI configuration dialog."""
        from open_navicat.ui.dialogs.ai_config_dialog import AIConfigDialog
        dlg = AIConfigDialog(self.window())
        dlg.exec()

    # ---- mode management ----

    def _switch_mode(self, mode_id: str) -> None:
        self._current_mode = mode_id
        for mid, btn in self._mode_btns.items():
            active = mid == mode_id
            btn.setChecked(active)
            btn.setStyleSheet(self._mode_style(active))

        hints = {
            "ask": "💬 问我任何关于数据库的问题",
            "optimize": "⚡ 粘贴 SQL，我会分析性能问题",
            "design": "📐 描述业务需求，设计表结构",
            "generate": "🧪 选择表，生成测试数据",
            "review": "🔍 粘贴 SQL，我会做安全与性能审查",
        }
        mode_names = {"ask": "问答", "optimize": "优化", "design": "设计", "generate": "生成", "review": "审查"}
        self._clear_messages()
        self._add_system_message(f"切换到 <b>{mode_names[mode_id]}</b> 模式<br><br>{hints[mode_id]}")

    def _mode_style(self, active: bool) -> str:
        if active:
            return (
                f"padding: 6px 8px; border: none; border-bottom: 2px solid {TEXT_ACCENT}; "
                f"background: {GLASS_LIGHT}; color: {TEXT_ACCENT}; font-size: 11px;"
            )
        return (
            f"padding: 6px 8px; border: none; border-bottom: 2px solid transparent; "
            f"background: transparent; color: {TEXT_MUTED}; font-size: 11px;"
        )

    # ---- message management ----

    def _clear_messages(self) -> None:
        while self._messages_layout.count():
            item = self._messages_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._conversation_history.clear()

    def _save_conversation(self) -> None:
        """Save conversation history to local config."""
        if not self._conversation_history:
            return
        from PySide6.QtWidgets import QLineEdit

        from open_navicat.config import config
        name, ok = QInputDialog.getText(self, "保存对话", "对话名称:", QLineEdit.EchoMode.Normal,
                                        f"对话 {len(self._conversation_history)} 条")
        if ok and name:
            saved = config.get("ai_conversations", [])
            saved.append({"name": name.strip(), "messages": self._conversation_history})
            config.set("ai_conversations", saved)
            self._remove_thinking() if hasattr(self, '_remove_thinking') else None

    def _load_conversation(self) -> None:
        """Load a saved conversation from local config."""
        from open_navicat.config import config
        saved = config.get("ai_conversations", [])
        if not saved:
            return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QVBoxLayout
        dlg = QDialog(self.window())
        dlg.setWindowTitle("加载对话")
        dlg.setMinimumWidth(350)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("选择要加载的对话："))
        lst = QListWidget(dlg)
        for s in saved:
            lst.addItem(f"{s['name']} ({len(s['messages'])} 条)")
        lst.setCurrentRow(0)
        layout.addWidget(lst)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            row = lst.currentRow()
            if 0 <= row < len(saved):
                self._clear_messages()
                # Directly set history without triggering add methods
                for msg in saved[row]["messages"]:
                    if msg["role"] == "user":
                        bubble = ChatBubble(msg["content"], is_user=True, parent=self._messages_widget)
                        self._messages_layout.addWidget(bubble)
                    else:
                        bubble = ChatBubble(msg["content"], is_user=False, parent=self._messages_widget)
                        self._messages_layout.addWidget(bubble)
                self._conversation_history = list(saved[row]["messages"])

    def _add_system_message(self, html: str) -> None:
        msg = QLabel(self._messages_widget)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        msg.setWordWrap(True)
        msg.setStyleSheet(
            "font-size: 12px; color: #ccc; background: #2d2d30; "
            "border-radius: 8px; padding: 10px 12px; border: 1px solid #3c3c3c; "
            "line-height: 1.6;"
        )
        msg.setMaximumWidth(500)
        self._messages_layout.addWidget(msg)

    def _add_user_message(self, text: str) -> None:
        bubble = ChatBubble(text, is_user=True, parent=self._messages_widget)
        self._messages_layout.addWidget(bubble)
        self._conversation_history.append({"role": "user", "content": text})

    def _add_ai_response(self, text: str) -> None:
        """Add AI response with optional SQL blocks as rich text."""
        self._conversation_history.append({"role": "assistant", "content": text})
        # Simple markdown-like rendering: ```sql → styled block
        parts = text.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 0:
                # Normal text
                if part.strip():
                    msg = QLabel(self._messages_widget)
                    msg.setTextFormat(Qt.TextFormat.RichText)
                    msg.setText(part.replace("\n", "<br>"))
                    msg.setWordWrap(True)
                    msg.setStyleSheet(
                        "font-size: 12px; color: #ccc; background: #2d2d30; "
                        "border-radius: 8px; padding: 10px 12px; border: 1px solid #3c3c3c; "
                        "line-height: 1.6;"
                    )
                    msg.setMaximumWidth(500)
                    self._messages_layout.addWidget(msg)
            else:
                # SQL code block
                if part.startswith("sql\n"):
                    part = part[4:]
                sql_widget = QLabel(self._messages_widget)
                sql_widget.setTextFormat(Qt.TextFormat.RichText)
                sql_widget.setText(
                    f'<pre style="background:#1e1e1e; color:#569cd6; '
                    f'padding:8px 12px; border-radius:4px; '
                    f'font-family:Consolas,monospace; font-size:11px; '
                    f'line-height:1.5; overflow-x:auto;">'
                    f'{part.strip()}</pre>'
                )
                sql_widget.setMaximumWidth(500)
                sql_widget.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                self._messages_layout.addWidget(sql_widget)

    def _show_thinking(self) -> None:
        self._thinking = QLabel(self._messages_widget)
        self._thinking.setText("🤔 AI 思考中...")
        self._thinking.setStyleSheet(
            "font-size: 12px; color: #888; padding: 8px 12px;"
        )
        self._messages_layout.addWidget(self._thinking)

    def _remove_thinking(self) -> None:
        if hasattr(self, "_thinking") and self._thinking is not None:
            self._thinking.deleteLater()
            self._thinking = None

    # ---- actions ----

    @Slot()
    def _send_message(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()

        self._add_user_message(text)

        # Build schema context
        schema_context = ""
        active_ids = connection_manager.active_ids
        if active_ids:
            try:
                dbs = metadata_service.list_databases(active_ids[0])
                lines = []
                for db in dbs[:3]:
                    tables = metadata_service.list_tables(active_ids[0], db.name)
                    for table in tables[:10]:
                        info = metadata_service.get_table_info(
                            active_ids[0], db.name, table
                        )
                        if info:
                            cols = ", ".join(
                                f"{c.name}({c.data_type})" for c in info.columns[:8]
                            )
                            lines.append(f"{db.name}.{table}: {cols}")
                schema_context = "\n".join(lines)
            except Exception as e:
                _log.warning("Failed to load schema context: %s", e)
                schema_context = "(无法加载 Schema)"

        self._show_thinking()
        QApplication.processEvents()

        # Run AI call in background thread, then update UI on main thread
        mode = self._current_mode
        import threading
        thread = threading.Thread(target=self._async_ai_call, args=(text, schema_context, mode), daemon=True)
        thread.start()

    def _async_ai_call(self, text: str, schema_context: str, mode: str) -> None:
        """Run AI call in background thread, then update UI via timer."""
        response = ""
        try:
            if mode == "optimize":
                result = ai_service.optimize(text)
                response = result if result else "无法分析该 SQL。"
            elif mode == "design":
                result = ai_service.design_schema(text)
                response = f"📐 AI 设计的 Schema：\n\n```sql\n{result}\n```" if result else "无法生成 Schema。"
            elif mode == "generate":
                result = ai_service.generate_data(None, 10, text)
                response = f"🧪 生成 {len(result)} 条测试数据。\n```json\n{str(result[:3])}\n```"
            elif mode == "review":
                result = ai_service.review_sql(text, schema_context=schema_context)
                response = f"🔍 SQL 审查报告：\n\n{result}" if result else "无法审查该 SQL。"
            else:
                result = ai_service.nl2sql(text, schema_context)
                if result:
                    response = f"✅ 生成的 SQL：\n\n```sql\n{result}\n```\n\n点「▶ 执行」运行此查询。"
                else:
                    response = "抱歉，我无法理解这个请求。请换个方式描述。"
        except Exception as e:
            response = f"⚠️ AI 服务错误: {e}"

        # Update UI on main thread
        QTimer.singleShot(0, lambda r=response: self._show_ai_response(r))

    def _show_ai_response(self, text: str) -> None:
        """Display AI response (called on main thread after async completion)."""
        self._remove_thinking()
        self._add_ai_response(text)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        scroll = self.parent().findChild(QScrollArea)
        if scroll:
            scroll.verticalScrollBar().setValue(
                scroll.verticalScrollBar().maximum()
            )

    def _quick_action(self, prompt: str) -> None:
        self._input.setText(prompt)
        self._send_message()

    def _animate_width(self, target: int) -> None:
        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()

        self._anim = QPropertyAnimation(self, b"panel_width")
        self._anim.setDuration(250)
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(target)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def _get_panel_width(self) -> int:
        return self.width()

    def _set_panel_width(self, w: int) -> None:
        self.setFixedWidth(w)

    panel_width = Property(int, _get_panel_width, _set_panel_width)
