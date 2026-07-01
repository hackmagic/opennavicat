"""Object Browser — tree view of connections, databases, and database objects."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import (
    QTreeWidget,
    QTreeWidgetItem,
    QAbstractItemView,
    QMenu,
    QMessageBox,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from open_navicat.dal.connection_pool import connection_pool
from open_navicat.dal.local_config import local_db
from open_navicat.models.connection import ConnectionInfo
from open_navicat.ui.dialogs.connection_dialog import ConnectionDialog
from open_navicat.i18n import t, set_language

logger = logging.getLogger("opennavicat.browser")


def _fmt_bytes(n: int | float) -> str:
    """Format byte count to human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class ObjectBrowser(QTreeWidget):
    """Tree navigation pane showing all connections and their database objects."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._load_saved_connections()

    def _setup_ui(self) -> None:
        self.setHeaderHidden(True)
        self.setRootIsDecorated(True)
        self.setAnimated(True)
        self.setIndentation(16)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.itemDoubleClicked.connect(self._on_item_double_click)

    # ---- public API ----

    def add_connection(self, info: ConnectionInfo) -> None:
        """Add a connected server to the tree and expand."""
        logger.info("ObjectBrowser.add_connection: name=%s id=%s", info.name, info.id)
        item = QTreeWidgetItem(self)
        item.setText(0, info.display_name)
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "type": "connection",
            "id": info.id,
            "info": info,
        })
        item.setToolTip(0, info.dsn)
        item.setExpanded(True)

        # Add loading placeholder
        loading = QTreeWidgetItem(item)
        loading.setText(0, t("browser.loading"))

        # Persist
        local_db.save_connection(info)
        logger.info("ObjectBrowser.add_connection: tree item added, childCount=%d", item.childCount())

        # Auto-expand to load databases
        self._expand_connection(item)

    # ---- internal ----

    def _load_saved_connections(self) -> None:
        connections = local_db.list_connections()
        for conn in connections:
            item = QTreeWidgetItem(self)
            item.setText(0, conn.display_name)
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "connection",
                "id": conn.id,
                "info": conn,
            })
            item.setToolTip(0, conn.dsn)

    @Slot(object)
    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if not item:
            return

        menu = QMenu(self)
        data = item.data(0, Qt.ItemDataRole.UserRole)
        obj_type = data.get("type") if data else None

        if obj_type == "connection":
            act_close = menu.addAction("关闭连接")
            act_close.triggered.connect(lambda: self._disconnect_connection(item))
            act_new_conn = menu.addAction("新建连接...")
            act_new_conn.triggered.connect(lambda: self._new_connection(item))
            act_copy_conn = menu.addAction("复制连接...")
            act_copy_conn.triggered.connect(lambda: self._copy_connection(item))
            menu.addSeparator()
            act_edit = menu.addAction(t("browser.edit_connection"))
            act_edit.triggered.connect(lambda: self._edit_connection(item))
            act_delete = menu.addAction(t("browser.delete_connection"))
            act_delete.triggered.connect(lambda: self._remove_connection(item))
            menu.addSeparator()
            act_new_db = menu.addAction("新建数据库...")
            act_new_db.triggered.connect(lambda: self._new_database(item))
            act_query = menu.addAction(t("browser.new_query"))
            act_query.triggered.connect(lambda: self._open_query_tab(item))
            act_sql_file = menu.addAction("运行 SQL 文件...")
            act_sql_file.triggered.connect(lambda: self._run_sql_file(item))
            menu.addSeparator()
            act_import = menu.addAction("导入连接...")
            act_import.triggered.connect(lambda: self._wizard_import(item))
            act_export = menu.addAction("导出连接...")
            act_export.triggered.connect(lambda: self._wizard_export(item))
            menu.addSeparator()
            act_reload = menu.addAction("重载")
            act_reload.triggered.connect(lambda: self._refresh_connection(item))
            act_star = menu.addAction("添加星标")
            act_star.triggered.connect(lambda: self._toggle_favorite(item))
            menu.addSeparator()
            act_refresh = menu.addAction(t("browser.refresh"))
            act_refresh.triggered.connect(lambda: self._refresh_connection(item))
            act_disconnect = menu.addAction(t("browser.disconnect"))
            act_disconnect.triggered.connect(lambda: self._disconnect_connection(item))

        elif obj_type in ("database",):
            act_query = menu.addAction(t("browser.new_query"))
            act_query.triggered.connect(lambda: self._open_query_tab(item))
            act_sql_file = menu.addAction("运行 SQL 文件...")
            act_sql_file.triggered.connect(lambda: self._run_sql_file(item))
            menu.addSeparator()
            act_new_db = menu.addAction(t("browser.new_database"))
            act_new_db.triggered.connect(lambda: self._new_database(item))
            act_drop_db = menu.addAction(t("browser.drop_database"))
            act_drop_db.triggered.connect(lambda: self._drop_database(item))
            menu.addSeparator()
            act_import = menu.addAction("导入向导...")
            act_import.triggered.connect(lambda: self._wizard_import(item))
            act_export = menu.addAction("导出向导...")
            act_export.triggered.connect(lambda: self._wizard_export(item))
            menu.addSeparator()
            act_refresh = menu.addAction(t("browser.refresh"))
            act_refresh.triggered.connect(lambda: self._refresh_database(item))
            act_props = menu.addAction(t("browser.properties"))
            act_props.triggered.connect(lambda: self._show_properties(item))

        elif obj_type == "table":
            act_open = menu.addAction(t("browser.open_table"))
            act_open.triggered.connect(lambda: self._open_table(item))
            act_design = menu.addAction(t("browser.design_table"))
            act_design.triggered.connect(lambda: self._design_table(item))
            menu.addSeparator()
            act_new = menu.addAction(t("browser.new_table"))
            act_new.triggered.connect(lambda: self._new_table(item))
            act_drop = menu.addAction(t("browser.drop_table"))
            act_drop.triggered.connect(lambda: self._drop_table(item))
            act_truncate = menu.addAction(t("browser.truncate_table"))
            act_truncate.triggered.connect(lambda: self._truncate_table(item))
            menu.addSeparator()
            act_copy = menu.addAction(t("browser.copy_table"))
            act_copy.triggered.connect(lambda: self._copy_table(item))
            act_rename = menu.addAction("重命名...")
            act_rename.triggered.connect(lambda: self._rename_table(item))
            menu.addSeparator()
            act_import = menu.addAction(t("menu.file.import"))
            act_import.triggered.connect(lambda: self._wizard_import(item))
            act_export = menu.addAction(t("menu.file.export"))
            act_export.triggered.connect(lambda: self._wizard_export(item))
            menu.addSeparator()
            act_dump = menu.addAction("转储 SQL 文件...")
            act_dump.triggered.connect(lambda: self._dump_table_sql(item))
            act_perms = menu.addAction("设置权限...")
            act_perms.triggered.connect(lambda: self._set_table_permissions(item))
            menu.addSeparator()
            maint_menu = menu.addMenu(t("browser.maintenance"))
            for label_key, meth in [
                ("browser.check_table", self._check_table),
                ("browser.optimize_table", self._optimize_table),
                ("browser.repair_table", self._repair_table),
                ("browser.analyze_table", self._analyze_table),
            ]:
                act = maint_menu.addAction(t(label_key))
                act.triggered.connect(lambda checked, m=meth: m(item))
            menu.addSeparator()
            act_reverse = menu.addAction("逆向表到模型...")
            act_reverse.triggered.connect(lambda: self._reverse_to_model(item))
            act_bi = menu.addAction("创建 BI 工作区")
            act_bi.triggered.connect(lambda: self._create_bi_workspace(item))
            menu.addSeparator()
            act_copy_to = menu.addAction(t("browser.copy_object_to"))
            act_copy_to.triggered.connect(lambda: self._copy_object_to(item))
            act_refresh = menu.addAction("刷新")
            act_refresh.triggered.connect(lambda: self._refresh_connection(item.parent() if item.parent() else item))
            menu.addSeparator()
            act_props = menu.addAction(t("browser.properties"))
            act_props.triggered.connect(lambda: self._show_properties(item))

        elif obj_type == "view":
            act_open = menu.addAction(t("browser.open_view"))
            act_open.triggered.connect(lambda: self._open_view(item))
            act_design = menu.addAction(t("browser.design_view"))
            act_design.triggered.connect(lambda: self._design_view(item))
            menu.addSeparator()
            act_drop = menu.addAction(t("browser.drop_view"))
            act_drop.triggered.connect(lambda: self._drop_view(item))
            menu.addSeparator()
            act_copy_to = menu.addAction(t("browser.copy_object_to"))
            act_copy_to.triggered.connect(lambda: self._copy_object_to(item))
            menu.addSeparator()
            act_props = menu.addAction(t("browser.properties"))
            act_props.triggered.connect(lambda: self._show_properties(item))

        elif obj_type == "routine":
            act_open = menu.addAction(t("browser.open_function"))
            act_open.triggered.connect(lambda: self._open_function(item))
            menu.addSeparator()
            act_drop = menu.addAction(t("browser.drop_function"))
            act_drop.triggered.connect(lambda: self._drop_function(item))
            menu.addSeparator()
            act_copy_to = menu.addAction(t("browser.copy_object_to"))
            act_copy_to.triggered.connect(lambda: self._copy_object_to(item))
            menu.addSeparator()
            act_props = menu.addAction(t("browser.properties"))
            act_props.triggered.connect(lambda: self._show_properties(item))

        elif obj_type == "query":
            act_open_q = menu.addAction(t("browser.open_query"))
            act_open_q.triggered.connect(lambda: self._open_saved_query(item))
            menu.addSeparator()
            act_rename_q = menu.addAction(t("browser.rename_query"))
            act_rename_q.triggered.connect(lambda: self._rename_query(item))
            act_delete_q = menu.addAction(t("browser.delete_query"))
            act_delete_q.triggered.connect(lambda: self._delete_query(item))

        menu.exec(self.viewport().mapToGlobal(pos))

    @Slot(QTreeWidgetItem, int)
    def _on_item_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        obj_type = data.get("type")

        if obj_type == "connection":
            self._expand_connection(item)
        elif obj_type == "database":
            self._expand_database(item)
        elif obj_type == "category":
            self._open_category(item)
        elif obj_type == "table":
            self._open_table(item)
        elif obj_type == "query":
            self._open_saved_query(item)

    def _open_category(self, item: QTreeWidgetItem) -> None:
        """Double-click on a category folder (e.g. 查询/表) to open its management panel."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        cat_key = data.get("category", "")
        parent_data = item.parent().data(0, Qt.ItemDataRole.UserRole)
        conn_id = parent_data.get("connection_id") if parent_data else ""
        db_name = parent_data.get("name") if parent_data else ""
        mw = self.window()

        if "queries" in cat_key:
            from open_navicat.ui.widgets.query_manager import QueryManagerWidget
            if hasattr(mw, '_workspace'):
                qm = QueryManagerWidget(conn_id, db_name, parent=mw._workspace)
                idx = mw._workspace.addTab(qm, f"📂 查询 - {db_name}")
                mw._workspace.setCurrentIndex(idx)
        elif "tables" in cat_key:
            self._open_table_list(conn_id, db_name)

    def _open_table_list(self, conn_id: str, db_name: str) -> None:
        """Open a tab showing table list with metadata columns."""
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
        from PySide6.QtWidgets import QHeaderView
        from open_navicat.dal.connection_pool import _loop as pool_loop
        mw = self.window()
        if not hasattr(mw, '_workspace'):
            return

        connector = connection_pool.get(conn_id)
        if not connector:
            return

        try:
            tables = pool_loop.run_until_complete(connector.list_tables_with_info(db_name))
        except Exception as e:
            logger.warning("_open_table_list failed: %s", e)
            tables = []

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel(f"📋 {db_name} — 表列表"))
        toolbar.addStretch()
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(lambda: self._reload_table_list(conn_id, db_name, table_widget))
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        # Table widget
        table_widget = QTableWidget(container)
        table_widget.setColumnCount(5)
        table_widget.setHorizontalHeaderLabels(["名称", "自动递增", "修改日期", "数据长度", "引擎"])
        table_widget.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table_widget.setAlternatingRowColors(True)
        table_widget.doubleClicked.connect(lambda idx: self._open_table_from_list(table_widget, idx, conn_id, db_name))

        self._populate_table_list(table_widget, tables)
        layout.addWidget(table_widget)

        idx = mw._workspace.addTab(container, f"📋 表 - {db_name}")
        mw._workspace.setCurrentIndex(idx)

    def _populate_table_list(self, table_widget: QTableWidget, tables: list[dict]) -> None:
        """Fill table widget with metadata rows."""
        table_widget.setRowCount(len(tables))
        for row, info in enumerate(tables):
            table_widget.setItem(row, 0, QTableWidgetItem(info["name"]))
            ai = info.get("auto_increment")
            table_widget.setItem(row, 1, QTableWidgetItem(str(ai) if ai else ""))
            table_widget.setItem(row, 2, QTableWidgetItem(info.get("update_time", "")))
            dl = info.get("data_length", 0)
            table_widget.setItem(row, 3, QTableWidgetItem(_fmt_bytes(dl) if dl else ""))
            table_widget.setItem(row, 4, QTableWidgetItem(info.get("engine", "")))

    def _reload_table_list(self, conn_id: str, db_name: str, table_widget: QTableWidget) -> None:
        from open_navicat.dal.connection_pool import _loop as pool_loop
        connector = connection_pool.get(conn_id)
        if not connector:
            return
        try:
            tables = pool_loop.run_until_complete(connector.list_tables_with_info(db_name))
            self._populate_table_list(table_widget, tables)
        except Exception as e:
            logger.warning("_reload_table_list failed: %s", e)

    def _open_table_from_list(self, table_widget: QTableWidget, idx, conn_id: str, db_name: str) -> None:
        """Double-click a row in table list to open the table data view."""
        name_item = table_widget.item(idx.row(), 0)
        if name_item:
            mw = self.window()
            if hasattr(mw, 'open_table_tab'):
                mw.open_table_tab(conn_id, db_name, name_item.text())

    def _expand_connection(self, item: QTreeWidgetItem) -> None:
        """Fetch and display databases under a connection."""
        logger.info(">>> _expand_connection called")
        item.takeChildren()  # remove placeholder
        data = item.data(0, Qt.ItemDataRole.UserRole)
        conn_id = data["id"]
        logger.info("_expand_connection: conn_id=%s", conn_id)
        connector = connection_pool.get(conn_id)
        logger.info("_expand_connection: connector=%s", connector)
        if not connector:
            # 尝试用保存的连接信息重新连接
            saved_info = data.get("info")
            if saved_info:
                logger.info("_expand_connection: attempting reconnect with saved info id=%s host=%s",
                            saved_info.id, saved_info.host)
                ok = connection_pool.open(saved_info)
                logger.info("_expand_connection: reconnect result=%s", ok)
                if ok:
                    connector = connection_pool.get(conn_id)
                else:
                    item.setText(0, item.text(0) + " " + t("browser.disconnected"))
                    return
            else:
                item.setText(0, item.text(0) + " " + t("browser.disconnected"))
                logger.warning("_expand_connection: no saved info in tree data, keys=%s",
                               list(connection_pool._connectors.keys()) if hasattr(connection_pool, '_connectors') else 'N/A')
                return

        import asyncio
        # 复用 connection_pool 的事件循环，否则 aiomysql 报 "attached to a different loop"
        from open_navicat.dal.connection_pool import _loop as pool_loop
        try:
            dbs = pool_loop.run_until_complete(connector.list_databases())
        except Exception as e:
            logger.error("_expand_connection: list_databases failed: %s", e, exc_info=True)
            item.setText(0, item.text(0) + " " + t("browser.error"))
            return

        logger.info("_expand_connection: found %d databases", len(dbs))
        for db in dbs:
            db_item = QTreeWidgetItem(item)
            db_item.setText(0, db.name)
            db_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "database",
                "name": db.name,
                "connection_id": conn_id,
            })
            # Add sub-items placeholders
            for category_key in ("browser.category_tables", "browser.category_views", "browser.category_routines", "browser.category_queries"):
                cat_item = QTreeWidgetItem(db_item)
                cat_item.setText(0, t(category_key))
                cat_item.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": "category",
                    "category": category_key,
                    "connection_id": conn_id,
                    "database": db.name,
                })

    def _expand_database(self, item: QTreeWidgetItem) -> None:
        """Expand database to show tables/views/routines."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        conn_id = data["connection_id"]
        db_name = data["name"]
        connector = connection_pool.get(conn_id)
        if not connector:
            return

        import asyncio
        from open_navicat.dal.connection_pool import _loop as pool_loop

        for i in range(item.childCount()):
            cat_item = item.child(i)
            cat_data = cat_item.data(0, Qt.ItemDataRole.UserRole)
            cat_key = cat_data["category"]  # e.g. "browser.category_tables"
            cat_item.takeChildren()  # Clear before re-adding

            objects: list[str] = []
            try:
                if "tables" in cat_key:
                    objects = pool_loop.run_until_complete(connector.list_tables(db_name))
                elif "views" in cat_key:
                    objects = pool_loop.run_until_complete(connector.list_views(db_name))
                elif "routines" in cat_key:
                    routines = pool_loop.run_until_complete(connector.list_routines(db_name))
                    objects = [f"{name} ({rtype})" for name, rtype in routines]
                elif "queries" in cat_key:
                    saved = local_db.list_queries(conn_id, db_name)
                    for q in saved:
                        child = QTreeWidgetItem(cat_item)
                        child.setText(0, q["name"])
                        child.setData(0, Qt.ItemDataRole.UserRole, {
                            "type": "query",
                            "id": q["id"],
                            "name": q["name"],
                            "sql_text": q["sql_text"],
                            "database": db_name,
                            "connection_id": conn_id,
                        })
                    continue
            except Exception as e:
                logger.warning("_expand_database: failed to list %s: %s", cat_key, e)
                objects = []

            for obj_name in objects:
                child = QTreeWidgetItem(cat_item)
                child.setText(0, obj_name)
                obj_type = "table" if "tables" in cat_key else ("routine" if "routines" in cat_key else "view")
                child.setData(0, Qt.ItemDataRole.UserRole, {
                    "type": obj_type,
                    "name": obj_name,
                    "database": db_name,
                    "connection_id": conn_id,
                })

    def _refresh_connection(self, item: QTreeWidgetItem) -> None:
        item.takeChildren()
        loading = QTreeWidgetItem(item)
        loading.setText(0, "Loading…")
        self._expand_connection(item)

    def _refresh_database(self, item: QTreeWidgetItem) -> None:
        item.takeChildren()
        for cat_key in ("browser.category_tables", "browser.category_views", "browser.category_routines", "browser.category_queries"):
            cat_item = QTreeWidgetItem(item)
            cat_item.setText(0, t(cat_key))
            cat_item.setData(0, Qt.ItemDataRole.UserRole, {
                "type": "category",
                "category": cat_key,
                "connection_id": item.data(0, Qt.ItemDataRole.UserRole).get("connection_id", ""),
                "database": item.data(0, Qt.ItemDataRole.UserRole).get("name", ""),
            })
        # Reload contents
        self._expand_database(item)

    def _remove_connection(self, item: QTreeWidgetItem) -> None:
        """Delete connection: close pool, delete from DB, remove from tree."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and "id" in data:
            connection_pool.close(data["id"])
            local_db.delete_connection(data["id"])
        root = self.invisibleRootItem()
        root.removeChild(item)

    def _disconnect_connection(self, item: QTreeWidgetItem) -> None:
        """Just disconnect from the server, keep the saved connection record."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and "id" in data:
            connection_pool.close(data["id"])
        # Update tree item to show disconnected state
        item.setText(0, item.text(0) + " " + t("browser.disconnected"))
        item.setExpanded(False)

    def _new_connection(self, _item: QTreeWidgetItem) -> None:
        """Open the new connection dialog from the context menu."""
        dialog = ConnectionDialog(self.window())
        if dialog.exec() == ConnectionDialog.DialogCode.Accepted:
            info = dialog.connection_info()
            ok = connection_pool.open(info)
            if ok:
                local_db.save_connection(info)
                self._load_saved_connections()
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self.window(), "连接失败",
                                    f"无法连接到 {info.host}:{info.port}")

    def _copy_connection(self, item: QTreeWidgetItem) -> None:
        """Duplicate an existing connection with a new name."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        saved_info = data.get("info") or local_db.get_connection(data.get("id", ""))
        if not saved_info:
            return
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            self.window(), "复制连接", "新连接名称:",
            text=f"{saved_info.name} (copy)",
        )
        if not ok or not new_name:
            return
        import uuid
        new_info = saved_info
        new_info.id = str(uuid.uuid4().hex[:8])
        new_info.name = new_name
        ok = connection_pool.open(new_info)
        if ok:
            local_db.save_connection(new_info)
            self._load_saved_connections()
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.window(), "连接失败",
                                f"无法连接到 {new_info.host}:{new_info.port}")

    def _run_sql_file(self, item: QTreeWidgetItem) -> None:
        """Execute a .sql file against the selected connection/database."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        conn_id = data.get("connection_id") or data.get("id")
        database = data.get("name", "")
        if not conn_id:
            return
        from PySide6.QtWidgets import QFileDialog, QProgressDialog
        path, _ = QFileDialog.getOpenFileName(
            self.window(), "选择 SQL 文件", "",
            "SQL 文件 (*.sql);;所有文件 (*)",
        )
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return
        from open_navicat.dal.connection_pool import _loop as pool_loop
        connector = connection_pool.get(conn_id)
        if not connector:
            return
        statements = [s.strip() for s in content.split(";") if s.strip()]
        progress = QProgressDialog(f"执行 {len(statements)} 条语句...", "取消", 0, len(statements), self.window())
        progress.setWindowTitle("运行 SQL 文件")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        errors = []
        for i, stmt in enumerate(statements):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            try:
                if database:
                    pool_loop.run_until_complete(connector.execute(f"USE `{database}`"))
                pool_loop.run_until_complete(connector.execute(stmt))
            except Exception as e:
                errors.append(f"第 {i+1} 条: {e}")
        progress.setValue(len(statements))
        progress.close()
        if errors:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.window(), "部分执行失败",
                                f"{len(errors)} 条语句失败:\n" + "\n".join(errors[:5]))
        else:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self.window(), "完成",
                                    f"成功执行 {len(statements)} 条语句。")

    def _toggle_favorite(self, item: QTreeWidgetItem) -> None:
        """Toggle the favorite (star) status of a connection."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        conn_id = data.get("id", data.get("connection_id", ""))
        db_name = data.get("name", data.get("database", ""))
        obj_type = data.get("type", "connection")
        obj_name = data.get("name", "")

        if local_db.is_favorite(conn_id, db_name, obj_type, obj_name):
            local_db.remove_favorite(conn_id, db_name, obj_type, obj_name)
            text = item.text(0)
            if text.startswith("⭐ "):
                item.setText(0, text[2:])
        else:
            local_db.add_favorite(conn_id, db_name, obj_type, obj_name)
            if not item.text(0).startswith("⭐ "):
                item.setText(0, "⭐ " + item.text(0))

    def _edit_connection(self, item: QTreeWidgetItem) -> None:
        """Open ConnectionDialog pre-filled with saved info, then update."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        saved_info = data.get("info") or local_db.get_connection(data.get("id", ""))
        if not saved_info:
            logger.warning("_edit_connection: no saved info for this connection")
            return

        dialog = ConnectionDialog(self.window(), info=saved_info)
        if dialog.exec() != ConnectionDialog.DialogCode.Accepted:
            return

        new_info = dialog.connection_info()
        logger.info("_edit_connection: updating id=%s name=%s", new_info.id, new_info.name)

        # Disconnect old (if connected), then (re)connect with new settings
        connection_pool.close(new_info.id)
        ok = connection_pool.open(new_info)
        if not ok:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.window(), "连接失败", f"无法使用新配置连接到 {new_info.host}")

        # Update tree item
        item.setText(0, new_info.display_name)
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "type": "connection",
            "id": new_info.id,
            "info": new_info,
        })
        item.setToolTip(0, new_info.dsn)

        # Persist
        local_db.save_connection(new_info)

        # Re-expand if was expanded
        if item.childCount() > 0:
            item.takeChildren()
            loading = QTreeWidgetItem(item)
            loading.setText(0, "Loading…")
            item.setExpanded(True)

    def _open_table(self, item: QTreeWidgetItem) -> None:
        """Signal to open table in workspace — handled by MainWindow."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            mw = self.window()
            if hasattr(mw, 'open_table_tab'):
                mw.open_table_tab(
                    data["connection_id"], data["database"], data["name"]
                )

    def _open_query_tab(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            mw = self.window()
            if hasattr(mw, 'open_query_tab'):
                mw.open_query_tab(
                    data["connection_id"], data.get("name", "")
                )

    def _design_table(self, item: QTreeWidgetItem) -> None:
        """Open table designer for the selected table."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        mw = self.window()
        from open_navicat.ui.widgets.table_designer import TableDesignerWidget
        designer = TableDesignerWidget(data["connection_id"], data["database"], data["name"], parent=mw._workspace)
        idx = mw._workspace.addTab(designer, f"📐 {data['name']}")
        mw._workspace.setCurrentIndex(idx)

    def _truncate_table(self, item: QTreeWidgetItem) -> None:
        """Truncate the selected table with confirmation."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        from PySide6.QtWidgets import QMessageBox, QCheckBox
        from PySide6.QtCore import Qt as QtConst

        dlg = QMessageBox(self.window())
        dlg.setWindowTitle(t("browser.truncate_table"))
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setText(f'你确定要清空 "{data["name"]}" 吗？')

        layout = dlg.layout()
        confirm_cb = QCheckBox("我了解此操作是永久性的且无法撤销")
        layout.addWidget(confirm_cb)

        btn_truncate = dlg.addButton("清空", QMessageBox.ButtonRole.AcceptRole)
        btn_cancel = dlg.addButton("取消", QMessageBox.ButtonRole.RejectRole)  # noqa: F841
        btn_truncate.setEnabled(False)
        confirm_cb.stateChanged.connect(lambda state: btn_truncate.setEnabled(state == QtConst.CheckState.Checked.value))

        dlg.exec()
        if dlg.clickedButton() != btn_truncate:
            return

        from open_navicat.dal.connection_pool import connection_pool, _loop as pool_loop
        connector = connection_pool.get(data["connection_id"])
        if connector:
            pool_loop.run_until_complete(
                connector.execute(f"TRUNCATE TABLE `{data['database']}`.`{data['name']}`")
            )

    def _drop_table(self, item: QTreeWidgetItem) -> None:
        """Drop the selected table with FK check and confirmation."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        from PySide6.QtWidgets import QMessageBox, QComboBox, QCheckBox, QLabel
        from PySide6.QtCore import Qt as QtConst

        dlg = QMessageBox(self.window())
        dlg.setWindowTitle(t("browser.drop_table"))
        dlg.setIcon(QMessageBox.Icon.Warning)
        dlg.setText(f'你确定要删除 "{data["name"]}" 吗？')

        layout = dlg.layout()
        fk_combo = QComboBox()
        fk_combo.addItems(["默认", "启用外键检查", "禁用外键检查"])
        fk_label = QLabel("外键检查:")
        confirm_cb = QCheckBox("我了解此操作是永久性的且无法撤销")
        layout.addWidget(fk_label)
        layout.addWidget(fk_combo)
        layout.addWidget(confirm_cb)

        btn_delete = dlg.addButton("删除", QMessageBox.ButtonRole.AcceptRole)
        btn_cancel = dlg.addButton("取消", QMessageBox.ButtonRole.RejectRole)  # noqa: F841
        btn_delete.setEnabled(False)
        confirm_cb.stateChanged.connect(lambda state: btn_delete.setEnabled(state == QtConst.CheckState.Checked.value))

        dlg.exec()
        if dlg.clickedButton() != btn_delete:
            return

        fk_mode = fk_combo.currentIndex()
        from open_navicat.dal.connection_pool import connection_pool, _loop as pool_loop
        connector = connection_pool.get(data["connection_id"])
        if connector:
            if fk_mode == 2:
                pool_loop.run_until_complete(connector.execute("SET FOREIGN_KEY_CHECKS = 0"))
            pool_loop.run_until_complete(
                connector.execute(f"DROP TABLE `{data['database']}`.`{data['name']}`")
            )
            if fk_mode == 2:
                pool_loop.run_until_complete(connector.execute("SET FOREIGN_KEY_CHECKS = 1"))
            parent = item.parent()
            if parent:
                parent.removeChild(item)

    # ---- saved queries ----

    def _open_saved_query(self, item: QTreeWidgetItem) -> None:
        """Open a saved query in the SQL editor."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        mw = self.window()
        if hasattr(mw, 'open_query_tab'):
            mw.open_query_tab(
                data["connection_id"], data["database"],
                data.get("sql_text", ""),
                query_id=data.get("id", 0),
            )

    def _rename_query(self, item: QTreeWidgetItem) -> None:
        """Rename a saved query."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        name, ok = QInputDialog.getText(
            self.window(), t("browser.rename_query"), "新名称:", QLineEdit.EchoMode.Normal,
            data.get("name", ""),
        )
        if ok and name:
            name = name.strip()
            local_db.rename_query(data["id"], name)
            item.setText(0, name)
            data["name"] = name
            item.setData(0, Qt.ItemDataRole.UserRole, data)

    def _delete_query(self, item: QTreeWidgetItem) -> None:
        """Delete a saved query."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self.window(), t("browser.delete_query"),
            f"确定要删除查询 '{data.get('name', '')}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            local_db.delete_query(data["id"])
            parent = item.parent()
            if parent:
                parent.removeChild(item)

    # ---- new context menu actions ----

    def _wizard_import(self, item: QTreeWidgetItem) -> None:
        """Import connection config from JSON file."""
        import json
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "导入连接", "", "JSON 文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                configs = json.load(f)
            if not isinstance(configs, list):
                configs = [configs]
            from open_navicat.dal.local_config import local_db
            from open_navicat.models.connection_info import ConnectionInfo
            count = 0
            for cfg in configs:
                info = ConnectionInfo(
                    name=cfg.get("name", "Imported"),
                    host=cfg.get("host", "localhost"),
                    port=int(cfg.get("port", 3306)),
                    user=cfg.get("user", "root"),
                    password=cfg.get("password", ""),
                    database=cfg.get("database", ""),
                    charset=cfg.get("charset", "utf8mb4"),
                    use_ssh=cfg.get("use_ssh", False),
                    ssh_host=cfg.get("ssh_host", ""),
                    ssh_port=int(cfg.get("ssh_port", 22)),
                    ssh_user=cfg.get("ssh_user", ""),
                    ssh_password=cfg.get("ssh_password", ""),
                    ssh_key_file=cfg.get("ssh_key_file", ""),
                    use_ssl=cfg.get("use_ssl", False),
                    ssl_ca=cfg.get("ssl_ca", ""),
                    ssl_cert=cfg.get("ssl_cert", ""),
                    ssl_key=cfg.get("ssl_key", ""),
                    color=cfg.get("color", ""),
                )
                local_db.save_connection(info)
                count += 1
            self._refresh_all()
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "导入成功", f"已导入 {count} 个连接配置。")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "导入失败", str(e))

    def _wizard_export(self, item: QTreeWidgetItem) -> None:
        """Export connection config to JSON file."""
        import json
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("obj_type") != "connection":
            return
        from open_navicat.dal.local_config import local_db
        info = local_db.get_connection(data["connection_id"])
        if not info:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出连接", f"{info.name}.json", "JSON 文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return
        try:
            cfg = {
                "name": info.name,
                "host": info.host,
                "port": info.port,
                "user": info.user,
                "password": info.password,
                "database": info.database,
                "charset": info.charset,
                "use_ssh": info.use_ssh,
                "ssh_host": info.ssh_host,
                "ssh_port": info.ssh_port,
                "ssh_user": info.ssh_user,
                "ssh_password": info.ssh_password,
                "ssh_key_file": info.ssh_key_file,
                "use_ssl": info.use_ssl,
                "ssl_ca": info.ssl_ca,
                "ssl_cert": info.ssl_cert,
                "ssl_key": info.ssl_key,
                "color": info.color,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "导出成功", f"连接配置已保存到:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    def _new_database(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self.window(), t("browser.new_database"), "数据库名称:")
        if ok and name:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            connector = connection_pool.get(data["connection_id"])
            if connector:
                from open_navicat.dal.connection_pool import _loop as pool_loop
                pool_loop.run_until_complete(connector.execute(f"CREATE DATABASE `{name.strip()}`"))
                self._refresh_connection(item.parent() if item.parent() else item)

    def _drop_database(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QMessageBox
        data = item.data(0, Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self.window(), t("browser.drop_database"),
            f"确定要删除数据库 `{data['name']}` 吗？\n此操作不可恢复！",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            connector = connection_pool.get(data["connection_id"])
            if connector:
                from open_navicat.dal.connection_pool import _loop as pool_loop
                pool_loop.run_until_complete(connector.execute(f"DROP DATABASE `{data['name']}`"))
                parent = item.parent()
                if parent:
                    parent.removeChild(item)

    def _new_table(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        mw = self.window()
        if hasattr(mw, '_workspace') and data:
            from open_navicat.ui.widgets.table_designer import TableDesignerWidget
            designer = TableDesignerWidget(data["connection_id"], data["database"], "", parent=mw._workspace)
            idx = mw._workspace.addTab(designer, t("browser.new_table"))
            mw._workspace.setCurrentIndex(idx)

    def _copy_table(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        data = item.data(0, Qt.ItemDataRole.UserRole)
        name, ok = QInputDialog.getText(self.window(), t("browser.copy_table"), "新表名称:", text=f"{data['name']}_copy")
        if ok and name:
            connector = connection_pool.get(data["connection_id"])
            if connector:
                from open_navicat.dal.connection_pool import _loop as pool_loop
                try:
                    pool_loop.run_until_complete(
                        connector.execute(f"CREATE TABLE `{data['database']}`.`{name.strip()}` LIKE `{data['database']}`.`{data['name']}`")
                    )
                except Exception as e:
                    QMessageBox.warning(self.window(), "错误", str(e))

    def _rename_table(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        data = item.data(0, Qt.ItemDataRole.UserRole)
        new_name, ok = QInputDialog.getText(self.window(), "重命名表", "新名称:", text=data["name"])
        if ok and new_name and new_name != data["name"]:
            connector = connection_pool.get(data["connection_id"])
            if connector:
                from open_navicat.dal.connection_pool import _loop as pool_loop
                try:
                    pool_loop.run_until_complete(
                        connector.execute(f"RENAME TABLE `{data['database']}`.`{data['name']}` TO `{data['database']}`.`{new_name.strip()}`")
                    )
                    item.setText(0, new_name.strip())
                except Exception as e:
                    QMessageBox.warning(self.window(), "错误", str(e))

    def _dump_table_sql(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QFileDialog
        data = item.data(0, Qt.ItemDataRole.UserRole)
        path, _ = QFileDialog.getSaveFileName(self.window(), "转储 SQL 文件", f"{data['name']}.sql", "SQL 文件 (*.sql)")
        if not path:
            return
        connector = connection_pool.get(data["connection_id"])
        if connector:
            from open_navicat.dal.connection_pool import _loop as pool_loop
            try:
                result = pool_loop.run_until_complete(
                    connector.execute(f"SHOW CREATE TABLE `{data['database']}`.`{data['name']}`")
                )
                if result.rows:
                    ddl = str(result.rows[0][1]) if len(result.rows[0]) > 1 else ""
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(f"-- Dump table `{data['name']}`\n{ddl};\n")
            except Exception as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self.window(), "错误", str(e))

    def _set_table_permissions(self, item: QTreeWidgetItem) -> None:
        pass  # ponytail: permissions UI not yet implemented

    def _reverse_to_model(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        mw = self.window()
        if hasattr(mw, '_show_model_designer') and data:
            mw._show_model_designer()

    def _create_bi_workspace(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        mw = self.window()
        if hasattr(mw, '_show_bi_dashboard') and data:
            mw._show_bi_dashboard()

    def open_table_tab(self, conn_id: str, database: str, table: str) -> None:
        """Open a data viewer tab for a table."""
        mw = self.window()
        if hasattr(mw, 'open_table_tab'):
            mw.open_table_tab(conn_id, database, table)

    def _open_view(self, item: QTreeWidgetItem) -> None:
        """Open view data — reuse open_table_tab since it's read-only."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            mw = self.window()
            if hasattr(mw, 'open_table_tab'):
                mw.open_table_tab(data["connection_id"], data["database"], data["name"])

    def _design_view(self, item: QTreeWidgetItem) -> None:
        """Open view designer — reuses table designer for now."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        mw = self.window()
        if hasattr(mw, '_workspace') and data:
            from open_navicat.ui.widgets.table_designer import TableDesignerWidget
            designer = TableDesignerWidget(data["connection_id"], data["database"], data["name"], parent=mw._workspace)
            idx = mw._workspace.addTab(designer, f"📐 {data['name']}")
            mw._workspace.setCurrentIndex(idx)

    def _drop_view(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QMessageBox
        data = item.data(0, Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self.window(), t("browser.drop_view"),
            f"确定要删除视图 `{data['name']}` 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            connector = connection_pool.get(data["connection_id"])
            if connector:
                from open_navicat.dal.connection_pool import _loop as pool_loop
                pool_loop.run_until_complete(
                    connector.execute(f"DROP VIEW IF EXISTS `{data['database']}`.`{data['name']}`")
                )
                parent = item.parent()
                if parent:
                    parent.removeChild(item)

    def _open_function(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        mw = self.window()
        if hasattr(mw, 'open_query_tab'):
            # Show function definition as a query
            conn_id = data["connection_id"]
            database = data["database"]
            func_name = data["name"]
            mw.open_query_tab(conn_id, database, f"SHOW CREATE FUNCTION `{database}`.`{func_name}`;\n")

    def _drop_function(self, item: QTreeWidgetItem) -> None:
        from PySide6.QtWidgets import QMessageBox
        data = item.data(0, Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self.window(), t("browser.drop_function"),
            f"确定要删除函数/存储过程 `{data['name']}` 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            connector = connection_pool.get(data["connection_id"])
            if connector:
                from open_navicat.dal.connection_pool import _loop as pool_loop
                name = data["name"].split(" (")[0]  # strip type suffix
                pool_loop.run_until_complete(
                    connector.execute(f"DROP PROCEDURE IF EXISTS `{data['database']}`.`{name}`")
                )
                parent = item.parent()
                if parent:
                    parent.removeChild(item)

    def _run_maintenance_sql(self, item: QTreeWidgetItem, operation: str) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        connector = connection_pool.get(data["connection_id"])
        if connector:
            from open_navicat.dal.connection_pool import _loop as pool_loop
            sql = f"{operation} TABLE `{data['database']}`.`{data['name']}`"
            pool_loop.run_until_complete(connector.execute(sql))

    def _check_table(self, item: QTreeWidgetItem) -> None:
        self._run_maintenance_sql(item, "CHECK")

    def _optimize_table(self, item: QTreeWidgetItem) -> None:
        self._run_maintenance_sql(item, "OPTIMIZE")

    def _repair_table(self, item: QTreeWidgetItem) -> None:
        self._run_maintenance_sql(item, "REPAIR")

    def _analyze_table(self, item: QTreeWidgetItem) -> None:
        self._run_maintenance_sql(item, "ANALYZE")

    def _copy_object_to(self, item: QTreeWidgetItem) -> None:
        """Copy table/view to another database on the same connection."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        name = data.get("name", "")
        database = data.get("database", "")
        obj_type = data.get("type", "table")
        conn_id = data.get("connection_id", "")

        if not name or not database or not conn_id:
            QMessageBox.warning(self.window(), "错误", "缺少对象信息。")
            return

        from PySide6.QtWidgets import QInputDialog
        target_db, ok = QInputDialog.getItem(
            self.window(), "复制到数据库",
            f"选择目标数据库 ({name}):",
            self._get_databases(conn_id), 0, False,
        )
        if not ok or not target_db:
            return

        from open_navicat.dal.connection_pool import connection_pool, _loop as pool_loop
        connector = connection_pool.get(conn_id)
        if not connector:
            return

        try:
            if obj_type == "table":
                sql = f"CREATE TABLE `{target_db}`.`{name}` LIKE `{database}`.`{name}`"
                pool_loop.run_until_complete(connector.execute(sql))
                QMessageBox.information(self.window(), "成功",
                    f"表 `{name}` 已复制到 `{target_db}`。")
            elif obj_type == "view":
                sql = f"CREATE VIEW `{target_db}`.`{name}` AS SELECT * FROM `{database}`.`{name}`"
                pool_loop.run_until_complete(connector.execute(sql))
                QMessageBox.information(self.window(), "成功",
                    f"视图 `{name}` 已复制到 `{target_db}`。")
            else:
                QMessageBox.information(self.window(), "提示", f"暂不支持复制 {obj_type} 类型。")
        except Exception as e:
            QMessageBox.warning(self.window(), "复制失败", str(e))

    def _get_databases(self, conn_id: str) -> list[str]:
        from open_navicat.dal.connection_pool import connection_pool, _loop as pool_loop
        connector = connection_pool.get(conn_id)
        if not connector:
            return []
        try:
            dbs = pool_loop.run_until_complete(connector.list_databases())
            return [d.name for d in dbs]
        except Exception as e:
            _log.warning("Failed to list databases: %s", e)
            return []

    def _show_properties(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        from PySide6.QtWidgets import QMessageBox
        info_lines = [f"{k}: {v}" for k, v in data.items() if k != "info"]
        QMessageBox.information(self.window(), t("browser.properties"), "\n".join(info_lines))
