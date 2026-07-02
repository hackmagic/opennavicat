"""Main application window — central hub with all components integrated."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from open_navicat import __app_name__, __version__
from open_navicat.config import config
from open_navicat.i18n import t
from open_navicat.ui.dialogs.connection_dialog import ConnectionDialog
from open_navicat.ui.dialogs.settings_dialog import SettingsDialog
from open_navicat.ui.themes import apply_theme
from open_navicat.ui.widgets import (
    AICopilotSidebar,
    BackupPanel,
    DataSyncPanel,
    ObjectBrowser,
    SchedulerPanel,
    SchemaSyncPanel,
    SQLEditorWidget,
    TableDesignerWidget,
)

logger = logging.getLogger("opennavicat.mainwindow")


class MainWindow(QMainWindow):
    """Top-level window integrating all components."""

    def __init__(self) -> None:
        super().__init__()
        # Apply the active theme (pro-dark by default)
        theme_name = config.get("theme", "pro-dark")
        apply_theme(theme_name, QApplication.instance(), self)
        self._setup_window()
        self._setup_ui()
        self._restore_geometry()

        # ponytail: pinned tabs set
        self._pinned_tabs: set[int] = set()

    # ---- window setup ----

    def _setup_window(self) -> None:
        self.setWindowTitle(t("app.title", name=__app_name__, version=__version__))
        # 不设置内联 stylesheet — 全部交给 QSS 主题管理
        # 动态计算窗口大小：屏幕的 80%，但不超过 1400×900，不低于 1000×700
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            w = min(int(geo.width() * 0.8), 1400)
            h = min(int(geo.height() * 0.8), 900)
            w = max(w, 1000)
            h = max(h, 700)
        else:
            w, h = 1200, 800
        self.resize(config.get("window.width", w), config.get("window.height", h))

    # ---- UI setup ----

    def _setup_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        self._main_layout = main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Native QMenuBar — 样式由 QSS 主题统一管理
        self._setup_menubar()

        # Toolbar — 样式由 QSS 主题统一管理
        self._toolbar = self._create_toolbar()
        main_layout.addWidget(self._toolbar)

        # Body: sidebar + content + AI copilot
        body = QWidget(central)
        body.setObjectName("bodyPanel")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        # Object browser (sidebar left)
        self._object_browser = ObjectBrowser(body)
        self._object_browser.setObjectName("objectBrowser")
        self._object_browser.setMinimumWidth(200)
        self._object_browser.setMaximumWidth(400)
        body_layout.addWidget(self._object_browser)

        # Main content area
        content = QWidget(body)
        content.setObjectName("contentPanel")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Tab workspace
        self._workspace = QTabWidget(content)
        self._workspace.setTabsClosable(True)
        self._workspace.setMovable(True)
        self._workspace.tabCloseRequested.connect(self._close_tab)
        self._workspace.tabBarDoubleClicked.connect(self._rename_tab)
        self._workspace.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._workspace.tabBar().customContextMenuRequested.connect(self._tab_context_menu)
        content_layout.addWidget(self._workspace, 1)

        # Status bar
        self._status = QStatusBar(content)
        self._status.showMessage(t("status.ready"))
        content_layout.addWidget(self._status)

        body_layout.addWidget(content, 1)

        # AI Copilot sidebar (right)
        self._ai_copilot = AICopilotSidebar(body)
        self._ai_copilot.setObjectName("aiCopilotSidebar")
        self._ai_copilot.sql_generated.connect(self._on_ai_sql_generated)
        body_layout.addWidget(self._ai_copilot)

        main_layout.addWidget(body, 1)

    def _refresh_ui(self) -> None:
        """Rebuild toolbar and menubar to reflect config changes (e.g. ai.enabled)."""
        # Rebuild menubar
        self.menuBar().clear()
        self._setup_menubar()
        # Rebuild toolbar
        self._main_layout.removeWidget(self._toolbar)
        self._toolbar.deleteLater()
        self._toolbar = self._create_toolbar()
        self._main_layout.insertWidget(1, self._toolbar)

    def _setup_menubar(self) -> None:
        menubar = self.menuBar()

        # ---- File ----
        file_menu = menubar.addMenu(t("menu.file"))
        self._act_connect = QAction(t("menu.file.new_connection"), self)
        self._act_connect.setShortcut(QKeySequence("Ctrl+N"))
        self._act_connect.triggered.connect(self._new_connection)
        file_menu.addAction(self._act_connect)
        file_menu.addSeparator()
        act_import = QAction(t("menu.file.import"), self)
        act_import.triggered.connect(self._show_import_wizard)
        file_menu.addAction(act_import)
        act_export = QAction(t("menu.file.export"), self)
        act_export.triggered.connect(self._show_export_wizard)
        file_menu.addAction(act_export)
        file_menu.addSeparator()
        act_settings = QAction(t("menu.file.settings"), self)
        act_settings.triggered.connect(self._show_settings)
        file_menu.addAction(act_settings)
        file_menu.addSeparator()
        act_exit = QAction(t("menu.file.exit"), self)
        act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # ---- Edit ----
        edit_menu = menubar.addMenu(t("menu.edit"))
        self._add_edit_action(edit_menu, "undo", QKeySequence.StandardKey.Undo)
        self._add_edit_action(edit_menu, "redo", QKeySequence.StandardKey.Redo)
        edit_menu.addSeparator()
        self._add_edit_action(edit_menu, "cut", QKeySequence.StandardKey.Cut)
        self._add_edit_action(edit_menu, "copy", QKeySequence.StandardKey.Copy)
        self._add_edit_action(edit_menu, "paste", QKeySequence.StandardKey.Paste)
        self._add_edit_action(edit_menu, "delete", QKeySequence(Qt.Key.Key_Delete))
        edit_menu.addSeparator()
        self._add_edit_action(edit_menu, "select_all", QKeySequence.StandardKey.SelectAll)
        edit_menu.addSeparator()
        act_find = QAction(t("menu.edit.find_replace"), self)
        act_find.setShortcut(QKeySequence("Ctrl+F"))
        act_find.triggered.connect(self._find_replace)
        edit_menu.addAction(act_find)
        act_adv_find = QAction(t("menu.edit.advanced_find"), self)
        act_adv_find.setShortcut(QKeySequence("Ctrl+Shift+F"))
        act_adv_find.triggered.connect(self._advanced_find)
        edit_menu.addAction(act_adv_find)

        # ---- View ----
        view_menu = menubar.addMenu(t("menu.view"))
        act_nav = QAction(t("menu.view.nav_pane"), self)
        act_nav.setCheckable(True)
        act_nav.setChecked(True)
        act_nav.triggered.connect(self._toggle_nav_pane)
        view_menu.addAction(act_nav)
        act_info = QAction(t("menu.view.info_pane"), self)
        act_info.setCheckable(True)
        act_info.triggered.connect(self._toggle_info_pane)
        view_menu.addAction(act_info)
        view_menu.addSeparator()
        act_list = QAction(t("menu.view.list"), self)
        act_list.setCheckable(True)
        act_list.setChecked(True)
        view_menu.addAction(act_list)
        act_detail = QAction(t("menu.view.detail"), self)
        act_detail.setCheckable(True)
        view_menu.addAction(act_detail)
        act_er = QAction(t("menu.view.er_diagram"), self)
        act_er.setCheckable(True)
        view_menu.addAction(act_er)
        view_menu.addSeparator()
        act_hide = QAction(t("menu.view.hide_groups"), self)
        act_hide.setCheckable(True)
        view_menu.addAction(act_hide)
        act_sort = QAction(t("menu.view.sort"), self)
        view_menu.addAction(act_sort)
        act_cols = QAction(t("menu.view.select_columns"), self)
        view_menu.addAction(act_cols)
        act_hidden = QAction(t("menu.view.show_hidden"), self)
        act_hidden.setCheckable(True)
        view_menu.addAction(act_hidden)
        view_menu.addSeparator()
        act_focus = QAction(t("menu.view.focus_mode"), self)
        act_focus.setCheckable(True)
        act_focus.triggered.connect(self._toggle_focus_mode)
        view_menu.addAction(act_focus)
        act_full = QAction(t("menu.view.full_screen"), self)
        act_full.setShortcut(QKeySequence("F11"))
        act_full.triggered.connect(self._toggle_full_screen)
        view_menu.addAction(act_full)

        # ---- Favorites ----
        fav_menu = menubar.addMenu(t("menu.favorites"))
        act_fav_add = QAction(t("menu.favorites.add"), self)
        fav_menu.addAction(act_fav_add)
        act_fav_manage = QAction(t("menu.favorites.manage"), self)
        fav_menu.addAction(act_fav_manage)

        # ---- Query ----
        query_menu = menubar.addMenu(t("menu.query"))
        act_new = QAction(t("menu.query.new"), self)
        act_new.setShortcut(QKeySequence("Ctrl+T"))
        act_new.triggered.connect(self._new_query)
        query_menu.addAction(act_new)
        act_run = QAction(t("menu.query.run"), self)
        act_run.setShortcut(QKeySequence("Ctrl+Return"))
        act_run.triggered.connect(self._run_query)
        query_menu.addAction(act_run)
        query_menu.addSeparator()
        act_builder = QAction(t("menu.query.builder"), self)
        act_builder.setShortcut(QKeySequence("Ctrl+Shift+Q"))
        act_builder.triggered.connect(self._show_query_builder)
        query_menu.addAction(act_builder)

        # ---- AI ----
        if config.get("ai.enabled", False):
            ai_menu = menubar.addMenu(t("menu.ai"))
            act_ai = QAction(t("menu.ai.copilot"), self)
            act_ai.setShortcut(QKeySequence("Ctrl+I"))
            act_ai.triggered.connect(lambda: self._ai_copilot.open_panel())
            ai_menu.addAction(act_ai)
            act_nl = QAction(t("menu.ai.nl_query"), self)
            act_nl.triggered.connect(self._ai_query)
            ai_menu.addAction(act_nl)
            ai_menu.addSeparator()
            act_ai_config = QAction(t("menu.ai.config"), self)
            act_ai_config.triggered.connect(lambda: self._show_settings())
            ai_menu.addAction(act_ai_config)

        # ---- Tools ----
        tools_menu = menubar.addMenu(t("menu.tools"))
        act_import_t = QAction(t("menu.tools.import_wizard"), self)
        act_import_t.triggered.connect(self._show_import_wizard)
        tools_menu.addAction(act_import_t)
        act_export_t = QAction(t("menu.tools.export_wizard"), self)
        act_export_t.triggered.connect(self._show_export_wizard)
        tools_menu.addAction(act_export_t)
        tools_menu.addSeparator()
        act_sync = QAction(t("menu.tools.structure_sync"), self)
        act_sync.triggered.connect(self._show_sync)
        tools_menu.addAction(act_sync)
        act_data_sync = QAction(t("menu.tools.data_sync"), self)
        act_data_sync.triggered.connect(self._show_data_sync)
        tools_menu.addAction(act_data_sync)
        act_backup = QAction(t("menu.tools.backup"), self)
        act_backup.triggered.connect(self._show_backup)
        tools_menu.addAction(act_backup)
        act_transfer = QAction(t("menu.tools.data_transfer"), self)
        act_transfer.triggered.connect(self._show_data_transfer)
        tools_menu.addAction(act_transfer)
        act_dict = QAction(t("menu.tools.data_dictionary"), self)
        act_dict.triggered.connect(self._show_data_dictionary)
        tools_menu.addAction(act_dict)
        tools_menu.addSeparator()
        act_scheduler = QAction("定时任务", self)
        act_scheduler.triggered.connect(self._show_scheduler)
        tools_menu.addAction(act_scheduler)
        act_bi = QAction(t("menu.tools.bi_dashboard"), self)
        act_bi.triggered.connect(self._show_bi_dashboard)
        tools_menu.addAction(act_bi)
        act_er = QAction(t("menu.tools.er_model"), self)
        act_er.triggered.connect(self._show_model_designer)
        tools_menu.addAction(act_er)
        act_obj = QAction(t("menu.tools.object_designer"), self)
        act_obj.triggered.connect(self._show_object_designer)
        tools_menu.addAction(act_obj)
        tools_menu.addSeparator()
        act_cmdline = QAction(t("menu.tools.command_line"), self)
        act_cmdline.setShortcut(QKeySequence("F6"))
        act_cmdline.triggered.connect(self._show_command_line)
        tools_menu.addAction(act_cmdline)
        act_monitor = QAction("服务器监控", self)
        act_monitor.triggered.connect(self._show_server_monitor)
        tools_menu.addAction(act_monitor)
        act_history = QAction(t("menu.tools.history_log"), self)
        act_history.setShortcut(QKeySequence("Ctrl+L"))
        act_history.triggered.connect(self._show_history_log)
        tools_menu.addAction(act_history)
        tools_menu.addSeparator()
        act_users = QAction(t("menu.tools.user_manager"), self)
        act_users.triggered.connect(self._show_user_manager)
        tools_menu.addAction(act_users)

        # ---- Window ----
        window_menu = menubar.addMenu(t("menu.window"))
        act_min = QAction(t("menu.window.minimize"), self)
        act_min.setShortcut(QKeySequence("Ctrl+M"))
        act_min.triggered.connect(self.showMinimized)
        window_menu.addAction(act_min)
        act_switch = QAction(t("menu.window.switch_tab"), self)
        act_switch.triggered.connect(self._switch_tab)
        window_menu.addAction(act_switch)
        window_menu.addSeparator()
        act_close = QAction(t("menu.window.close_tab"), self)
        act_close.setShortcut(QKeySequence("Ctrl+W"))
        act_close.triggered.connect(self._close_current_tab)
        window_menu.addAction(act_close)
        act_close_all = QAction(t("menu.window.close_all_tabs"), self)
        act_close_all.triggered.connect(self._close_all_tabs)
        window_menu.addAction(act_close_all)
        window_menu.addSeparator()
        act_next = QAction(t("menu.window.next_tab"), self)
        act_next.setShortcut(QKeySequence("Ctrl+Tab"))
        act_next.triggered.connect(lambda: self._switch_to_relative_tab(1))
        window_menu.addAction(act_next)
        act_prev = QAction(t("menu.window.prev_tab"), self)
        act_prev.setShortcut(QKeySequence("Ctrl+Shift+Tab"))
        act_prev.triggered.connect(lambda: self._switch_to_relative_tab(-1))
        window_menu.addAction(act_prev)

        # ---- Help ----
        help_menu = menubar.addMenu(t("menu.help"))
        act_docs = QAction(t("menu.help.online_docs"), self)
        help_menu.addAction(act_docs)
        act_update = QAction(t("menu.help.check_update"), self)
        help_menu.addAction(act_update)
        help_menu.addSeparator()
        act_about = QAction(t("menu.help.about"), self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _add_edit_action(self, menu: QMenu, key: str, shortcut) -> None:
        """Add a standard edit action to the given menu."""
        act = QAction(t(f"menu.edit.{key}"), self)
        act.setShortcut(shortcut)
        act.triggered.connect(lambda checked, k=key: self._forward_edit(k))
        menu.addAction(act)

    @Slot(str)
    def _forward_edit(self, method: str) -> None:
        """Forward an edit action to the currently focused widget."""
        w = QApplication.focusWidget()
        if w is None:
            return
        if method == "delete":
            from PySide6.QtGui import QKeyEvent
            QApplication.sendEvent(
                w,
                QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete,
                          Qt.KeyboardModifier.NoModifier),
            )
        elif hasattr(w, method):
            getattr(w, method)()

    def _create_toolbar(self) -> QWidget:
        bar = QWidget(self)
        bar.setObjectName("toolbarPanel")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        buttons = [
            (t("toolbar.connection"), self._new_connection, "primary"),
            ("|", None, "sep"),
            (t("menu.query.new"), self._new_query, "ghost"),
            (t("menu.query.run"), self._run_query, "primary"),
            (t("menu.query.builder"), self._show_query_builder, "ghost"),
            ("|", None, "sep"),
            (t("toolbar.design_table"), self._design_table, "ghost"),
            ("|", None, "sep"),
            (t("menu.tools.backup"), self._show_backup, "ghost"),
            (t("toolbar.sync"), self._show_sync, "ghost"),
        ]

        for text, handler, btn_type in buttons:
            if btn_type == "sep":
                sep = QFrame(bar)
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setObjectName("toolbarSep")
                layout.addWidget(sep)
                continue
            btn = QPushButton(text, bar)
            if btn_type == "primary":
                btn.setProperty("class", "primary")
            if handler:
                btn.clicked.connect(handler)
            layout.addWidget(btn)

        layout.addStretch()

        # AI query button (only if AI enabled)
        if config.get("ai.enabled", False):
            ai_btn = QPushButton(t("toolbar.ai_query"), bar)
            ai_btn.setObjectName("aiQueryBtn")
            ai_btn.clicked.connect(self._ai_query)
            layout.addWidget(ai_btn)

        return bar

    # ---- slots ----

    @Slot()
    def _new_connection(self) -> None:
        dialog = ConnectionDialog(self)
        if dialog.exec() == ConnectionDialog.DialogCode.Accepted:
            info = dialog.connection_info()
            logger.info("=== _new_connection: dialog accepted, info.id=%s host=%s port=%d user=%s db=%s",
                        info.id, info.host, info.port, info.user, info.database)
            from open_navicat.dal.connection_pool import connection_pool
            logger.info("_new_connection: calling connection_pool.open()...")
            ok = connection_pool.open(info)
            logger.info("_new_connection: connection_pool.open() returned %s", ok)
            if ok:
                self._object_browser.add_connection(info)
                self._status.showMessage(t("prompt.connected", host=info.host))
            else:
                QMessageBox.warning(self, t("connection.conn_failed"), t("prompt.conn_failed", host=info.host))

    @Slot()
    def _new_query(self) -> None:
        active = self._get_active_connection()
        if not active:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        db = self._get_current_database()
        editor = SQLEditorWidget(active, db, parent=self._workspace)
        editor.ai_requested.connect(self._on_ai_request)
        idx = self._workspace.addTab(editor, t("tab.new_query", n=self._workspace.count() + 1))
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _run_query(self) -> None:
        widget = self._workspace.currentWidget()
        if isinstance(widget, SQLEditorWidget):
            widget._execute()

    @Slot()
    def _design_table(self) -> None:
        active = self._get_active_connection()
        if not active:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        designer = TableDesignerWidget(active, "mydb", "users", parent=self._workspace)
        idx = self._workspace.addTab(designer, t("toolbar.design_table"))
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_sync(self) -> None:
        active = self._get_active_connection()
        if not active:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        sync = SchemaSyncPanel(active, parent=self._workspace)
        idx = self._workspace.addTab(sync, t("menu.tools.structure_sync"))
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_backup(self) -> None:
        active = self._get_active_connection()
        if not active:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        backup = BackupPanel(active, parent=self._workspace)
        idx = self._workspace.addTab(backup, t("menu.tools.backup"))
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_query_builder(self) -> None:
        active = self._get_active_connection()
        if not active:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        db = ""
        if hasattr(self, '_object_browser'):
            item = self._object_browser.currentItem()
            if item:
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data:
                    db = data.get("database", "")
        if not db:
            QMessageBox.warning(self, t("common.notice"), "请先在对象浏览器中选择一个数据库")
            return
        from open_navicat.ui.widgets.query_builder import QueryBuilderWidget
        builder = QueryBuilderWidget(active, db, parent=self._workspace)
        builder.sql_generated.connect(self._on_ai_sql_generated)
        idx = self._workspace.addTab(builder, t("tab.query_builder"))
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_data_sync(self) -> None:
        active = self._get_active_connection()
        if not active:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        panel = DataSyncPanel(active, parent=self._workspace)
        idx = self._workspace.addTab(panel, "数据同步")
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_data_dictionary(self) -> None:
        conn_id = self._get_active_connection()
        if not conn_id:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        from open_navicat.dal.connection_pool import connection_pool
        from open_navicat.ui.widgets.data_dictionary import DataDictionaryWidget
        connector = connection_pool.get(conn_id)
        if not connector:
            return
        # Try to get current database from object browser
        db = ""
        if hasattr(self, '_object_browser'):
            item = self._object_browser.currentItem()
            if item:
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data:
                    db = data.get("database", "")
        if not db:
            QMessageBox.warning(self, t("common.notice"), "请先选择数据库")
            return
        panel = DataDictionaryWidget(conn_id, db, parent=self._workspace)
        idx = self._workspace.addTab(panel, f"📖 数据字典 - {db}")
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_command_line(self) -> None:
        conn_id = self._get_active_connection()
        if not conn_id:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        from open_navicat.ui.widgets.command_line import CommandLineWidget
        db = ""
        if hasattr(self, '_object_browser'):
            item = self._object_browser.currentItem()
            if item:
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data:
                    db = data.get("database", "")
        panel = CommandLineWidget(conn_id, db, parent=self._workspace)
        idx = self._workspace.addTab(panel, "💻 命令列")
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_data_transfer(self) -> None:
        conn_id = self._get_active_connection()
        if not conn_id:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        from open_navicat.ui.widgets.data_transfer import DataTransferWidget
        panel = DataTransferWidget(conn_id, parent=self._workspace)
        idx = self._workspace.addTab(panel, "📦 数据传输")
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_server_monitor(self) -> None:
        conn_id = self._get_active_connection()
        if not conn_id:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        from open_navicat.ui.widgets.server_monitor import ServerMonitorWidget
        panel = ServerMonitorWidget(conn_id, parent=self._workspace)
        idx = self._workspace.addTab(panel, "🖥️ 服务器监控")
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_history_log(self) -> None:
        from open_navicat.ui.widgets.history_log import HistoryLogWidget
        panel = HistoryLogWidget(parent=self._workspace)
        idx = self._workspace.addTab(panel, "📋 历史日志")
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_scheduler(self) -> None:
        active = self._get_active_connection() or ""
        panel = SchedulerPanel(active, parent=self._workspace)
        idx = self._workspace.addTab(panel, "定时任务")
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _ai_query(self) -> None:
        self._ai_copilot.open_panel(t("ai.query_prompt"))

    @Slot(str)
    def _on_ai_request(self, prompt: str) -> None:
        self._ai_copilot.open_panel(prompt)

    @Slot(str)
    def _on_ai_sql_generated(self, sql: str) -> None:
        for i in range(self._workspace.count()):
            w = self._workspace.widget(i)
            if isinstance(w, SQLEditorWidget):
                w.set_sql(sql)
                self._workspace.setCurrentIndex(i)
                return

    @Slot(int)
    def _close_tab(self, index: int) -> None:
        if index in self._pinned_tabs:
            return  # pinned tabs cannot be closed
        widget = self._workspace.widget(index)
        self._workspace.removeTab(index)
        widget.deleteLater()
        # Re-index pinned tabs after removal
        self._pinned_tabs = {i if i < index else i - 1 for i in self._pinned_tabs if i != index}

    def _tab_context_menu(self, pos) -> None:
        index = self._workspace.tabBar().tabAt(pos)
        if index < 0:
            return
        menu = QMenu(self)
        is_pinned = index in self._pinned_tabs
        act_pin = QAction("📌 取消固定" if is_pinned else "📌 固定标签页", self)
        act_pin.triggered.connect(lambda: self._toggle_pin_tab(index))
        menu.addAction(act_pin)
        menu.exec(self._workspace.tabBar().mapToGlobal(pos))

    def _toggle_pin_tab(self, index: int) -> None:
        if index in self._pinned_tabs:
            self._pinned_tabs.discard(index)
            self._workspace.setTabText(index, self._workspace.tabText(index).replace(" 📌", ""))
        else:
            self._pinned_tabs.add(index)
            self._workspace.setTabText(index, self._workspace.tabText(index) + " 📌")

    def _rename_tab(self, index: int) -> None:
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        old = self._workspace.tabText(index)
        name, ok = QInputDialog.getText(self, t("common.rename"), t("common.rename_prompt"), QLineEdit.EchoMode.Normal, old)
        if ok and name:
            self._workspace.setTabText(index, name.strip())

    def open_table_tab(self, connection_id: str, database: str, table: str) -> None:
        if not config.get("general.allow_duplicate", False):
            for i in range(self._workspace.count()):
                w = self._workspace.widget(i)
                if hasattr(w, '_table_name') and w._table_name == table and hasattr(w, '_database') and w._database == database:
                    self._workspace.setCurrentIndex(i)
                    return
        from open_navicat.ui.widgets.table_viewer import TableViewerWidget
        viewer = TableViewerWidget(connection_id, database, table, parent=self._workspace)
        idx = self._workspace.addTab(viewer, t("tab.table_view", table=table))
        self._workspace.setCurrentIndex(idx)

    def open_query_tab(self, connection_id: str, database: str = "", sql_text: str = "", query_id: int = 0) -> None:
        from open_navicat.dal.local_config import local_db
        from open_navicat.ui.widgets.sql_editor import SQLEditorWidget
        editor = SQLEditorWidget(connection_id, database, parent=self._workspace)
        if sql_text:
            editor.set_sql(sql_text)
        if query_id:
            editor._current_query_id = query_id
            q = local_db.get_query(query_id)
            tab_name = q["name"] if q else t("tab.query_file", database=database)
        else:
            tab_name = t("tab.query_file", database=database)
        editor.ai_requested.connect(self._on_ai_request)
        idx = self._workspace.addTab(editor, tab_name)
        self._workspace.setCurrentIndex(idx)

    def _get_active_connection(self) -> str | None:
        from open_navicat.dal.connection_pool import connection_pool
        active = connection_pool.active_connections
        return active[0] if active else None

    def _get_current_database(self) -> str:
        """Get the database name from the object browser's current selection."""
        item = self._object_browser.currentItem()
        if not item:
            return ""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return ""
        # Database node
        if data.get("type") == "database":
            return data.get("name", "")
        # Category or child under a database
        if "database" in data:
            return data["database"]
        # Walk up to find a database ancestor
        parent = item.parent()
        while parent:
            pd = parent.data(0, Qt.ItemDataRole.UserRole)
            if pd and pd.get("type") == "database":
                return pd.get("name", "")
            parent = parent.parent()
        return ""

    @Slot()
    def _show_about(self) -> None:
        QMessageBox.about(
            self, t("menu.help.about"),
            f"<h3>{__app_name__} {__version__}</h3>"
            + t("about.description"),
        )

    @Slot()
    def _show_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()

    # ---- new menu slots ----

    @Slot()
    def _find_replace(self) -> None:
        w = self._workspace.currentWidget()
        if hasattr(w, "show_find_replace"):
            w.show_find_replace()

    @Slot()
    def _advanced_find(self) -> None:
        """Search across all tables/columns in the connected database."""
        active = self._get_active_connection()
        if not active:
            QMessageBox.information(self, t("menu.edit.advanced_find"), "请先连接到数据库。")
            return
        from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QListWidget, QVBoxLayout

        from open_navicat.dal.connection_pool import connection_pool
        from open_navicat.services.metadata_service import metadata_service
        connector = connection_pool.get(active)
        if not connector:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("高级查找")
        dlg.resize(500, 400)
        layout = QVBoxLayout(dlg)
        search_row = QHBoxLayout()
        inp = QLineEdit(dlg)
        inp.setPlaceholderText("输入搜索关键词...")
        search_row.addWidget(inp, 1)
        btn = QPushButton("搜索", dlg)
        btn.setObjectName("primaryBtn")
        search_row.addWidget(btn)
        layout.addLayout(search_row)
        results = QListWidget(dlg)
        layout.addWidget(results, 1)
        status = QLabel("", dlg)
        layout.addWidget(status)

        def do_search() -> None:
            q = inp.text().strip().lower()
            if not q:
                return
            results.clear()
            status.setText("搜索中...")
            databases = [d.name for d in metadata_service.list_databases(active)]
            found = 0
            for db in databases:
                tables = metadata_service.list_tables(active, db)
                for tbl in tables:
                    if q in tbl.lower():
                        results.addItem(f"表: {db}.{tbl}")
                        found += 1
                    try:
                        info = metadata_service.get_table_info(active, db, tbl)
                        if info:
                            for col in info.columns:
                                if q in col.name.lower():
                                    results.addItem(f"列: {db}.{tbl}.{col.name} ({col.data_type})")
                                    found += 1
                    except Exception:
                        pass
            status.setText(f"找到 {found} 个匹配")
        btn.clicked.connect(do_search)
        inp.returnPressed.connect(do_search)
        close_btn = QPushButton("关闭", dlg)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    @Slot()
    def _toggle_nav_pane(self) -> None:
        self._object_browser.setVisible(not self._object_browser.isVisible())

    @Slot()
    def _toggle_info_pane(self) -> None:
        pass  # ponytail: info pane not yet implemented

    @Slot()
    def _toggle_focus_mode(self) -> None:
        hidden = self._object_browser.isHidden()
        self._object_browser.setVisible(hidden)
        self._ai_copilot.setVisible(hidden)

    @Slot()
    def _toggle_full_screen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    @Slot()
    def _close_current_tab(self) -> None:
        idx = self._workspace.currentIndex()
        if idx >= 0:
            self._close_tab(idx)

    @Slot()
    def _close_all_tabs(self) -> None:
        for i in range(self._workspace.count() - 1, -1, -1):
            if i not in self._pinned_tabs:
                w = self._workspace.widget(i)
                self._workspace.removeTab(i)
                w.deleteLater()

    @Slot()
    def _switch_tab(self) -> None:
        count = self._workspace.count()
        if count <= 1:
            return
        items = [self._workspace.tabText(i) for i in range(count)]
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getItem(self, t("menu.window.switch_tab"), "选择标签页:", items, 0, False)
        if ok and name:
            for i in range(count):
                if self._workspace.tabText(i) == name:
                    self._workspace.setCurrentIndex(i)
                    break

    @Slot(int)
    def _switch_to_relative_tab(self, delta: int) -> None:
        count = self._workspace.count()
        if count <= 1:
            return
        cur = self._workspace.currentIndex()
        self._workspace.setCurrentIndex((cur + delta) % count)

    @Slot()
    def _show_import_wizard(self) -> None:
        active = self._get_active_connection()
        if not active:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        from open_navicat.ui.dialogs.import_export_wizard import ImportWizard
        wiz = ImportWizard(active, "", "", self)
        wiz.exec()

    @Slot()
    def _show_export_wizard(self) -> None:
        active = self._get_active_connection()
        if not active:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        from open_navicat.ui.dialogs.import_export_wizard import ExportWizard
        wiz = ExportWizard(active, "", "", self)
        wiz.exec()

    @Slot()
    def _show_bi_dashboard(self) -> None:
        active = self._get_active_connection()
        from open_navicat.ui.widgets.bi_dashboard import BIDashboardWidget
        dash = BIDashboardWidget(connection_id=active or "", parent=self._workspace)
        idx = self._workspace.addTab(dash, t("tab.bi_dashboard"))
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_model_designer(self) -> None:
        active = self._get_active_connection()
        from open_navicat.ui.widgets.model_designer import ModelDesignerWidget
        designer = ModelDesignerWidget(connection_id=active or "", parent=self._workspace)
        idx = self._workspace.addTab(designer, t("tab.er_model"))
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_object_designer(self) -> None:
        active = self._get_active_connection()
        from open_navicat.ui.widgets.object_designer import ObjectDesignerWidget
        od = ObjectDesignerWidget(connection_id=active or "", parent=self._workspace)
        idx = self._workspace.addTab(od, t("tab.object_designer"))
        self._workspace.setCurrentIndex(idx)

    @Slot()
    def _show_user_manager(self) -> None:
        active = self._get_active_connection()
        if not active:
            QMessageBox.warning(self, t("common.notice"), t("prompt.need_connection"))
            return
        from open_navicat.ui.widgets.user_manager import UserManagerWidget
        um = UserManagerWidget(active, parent=self._workspace)
        idx = self._workspace.addTab(um, t("tab.user_manager"))
        self._workspace.setCurrentIndex(idx)

    # ---- geometry ----

    def _restore_geometry(self) -> None:
        maximized = config.get("window.maximized", False)
        if maximized:
            self.showMaximized()

    def closeEvent(self, event):
        if self.isMaximized():
            config.set("window.maximized", True)
        else:
            geo = self.geometry()
            config.set("window.x", geo.x())
            config.set("window.y", geo.y())
            config.set("window.width", geo.width())
            config.set("window.height", geo.height())
            config.set("window.maximized", False)
        super().closeEvent(event)

    def showEvent(self, event):
        """Apply theme window effects once the window handle is valid."""
        super().showEvent(event)
        # Window handle is now valid — re-apply the current theme's window setup
        # (acrylic/blur/title-bar colour) which may have failed in __init__
        from open_navicat.ui.themes import apply_theme_window
        apply_theme_window(config.get("theme", "pro-dark"), self)
