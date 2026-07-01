"""User Manager — list, create, drop MySQL users and manage privileges."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.connection_pool import _loop as pool_loop
from open_navicat.dal.connection_pool import connection_pool


class UserManagerWidget(QWidget):
    """Panel for managing MySQL users."""

    COMMON_PRIVILEGES = [
        "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP",
        "ALTER", "INDEX", "REFERENCES", "CREATE VIEW", "SHOW VIEW",
        "CREATE ROUTINE", "ALTER ROUTINE", "EXECUTE", "TRIGGER",
        "EVENT", "CREATE TEMPORARY TABLES", "LOCK TABLES",
    ]

    def __init__(self, connection_id: str, parent=None) -> None:
        super().__init__(parent)
        self._connection_id = connection_id
        self._setup_ui()
        self._load_users()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QWidget(self)
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(8, 4, 8, 4)
        t_layout.addWidget(QLabel("👤 用户管理", toolbar))
        t_layout.addStretch()

        for text, cb, obj_name in [
            ("➕ 新建用户", self._new_user, "primaryBtn"),
            ("🗑️ 删除用户", self._drop_user, "dangerBtn"),
            ("🔑 权限管理", self._manage_privileges, "successBtn"),
        ]:
            btn = QPushButton(text, toolbar)
            btn.setObjectName(obj_name)
            btn.clicked.connect(cb)
            t_layout.addWidget(btn)

        layout.addWidget(toolbar)

        self._table = QTableWidget(self)
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(["User", "Host", "Auth Plugin", "Global Privs", "Max Conns", ""])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget { background: #1e1e1e; color: #ccc; border: none; }
            QTableWidget::item:selected { background: #094771; }
            QHeaderView::section { background: #2d2d30; color: #888; border: 1px solid #3c3c3c; padding: 4px; }
        """)
        layout.addWidget(self._table)

        self._status = QLabel("", self)
        self._status.setStyleSheet("color: #888; font-size: 11px; padding: 2px 8px;")
        layout.addWidget(self._status)

    def _load_users(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            rows = pool_loop.run_until_complete(
                connector._fetch_all("SELECT User, Host, plugin FROM mysql.user ORDER BY User")
            )
            self._table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                self._table.setItem(i, 0, QTableWidgetItem(str(r[0])))
                self._table.setItem(i, 1, QTableWidgetItem(str(r[1])))
                self._table.setItem(i, 2, QTableWidgetItem(str(r[2]) if len(r) > 2 else ""))
            self._status.setText(f"共 {len(rows)} 个用户")
        except Exception as e:
            self._status.setText(f"加载失败: {e}")

    def _new_user(self) -> None:
        dlg = QDialog(self.window())
        dlg.setWindowTitle("新建用户")
        form = QFormLayout(dlg)
        user_edit = QLineEdit(dlg)
        host_edit = QLineEdit("%", dlg)
        pass_edit = QLineEdit(dlg)
        pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("用户名:", user_edit)
        form.addRow("Host:", host_edit)
        form.addRow("密码:", pass_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        user, host, pwd = user_edit.text().strip(), host_edit.text().strip(), pass_edit.text().strip()
        if not user:
            return
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            pool_loop.run_until_complete(connector.execute(f"CREATE USER '{user}'@'{host}' IDENTIFIED BY '{pwd}'"))
            QMessageBox.information(self, "成功", f"用户 '{user}'@'{host}' 已创建")
            self._load_users()
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def _drop_user(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        user = self._table.item(row, 0).text()
        host = self._table.item(row, 1).text()
        if QMessageBox.question(self, "确认", f"删除用户 '{user}'@'{host}'？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            pool_loop.run_until_complete(connector.execute(f"DROP USER '{user}'@'{host}'"))
            self._load_users()
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    def _manage_privileges(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        user = self._table.item(row, 0).text()
        host = self._table.item(row, 1).text()
        dlg = QDialog(self.window())
        dlg.setWindowTitle(f"权限管理 - '{user}'@'{host}'")
        dlg.resize(450, 400)
        layout = QVBoxLayout(dlg)
        db_edit = QLineEdit("*.*", dlg)
        layout.addWidget(QLabel("数据库模式 (db.table):", dlg))
        layout.addWidget(db_edit)
        layout.addWidget(QLabel("全局权限:", dlg))
        checks = {}
        for priv in self.COMMON_PRIVILEGES:
            cb = QCheckBox(priv, dlg)
            checks[priv] = cb
            layout.addWidget(cb)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        db_pattern = db_edit.text().strip() or "*.*"
        selected = [p for p, cb in checks.items() if cb.isChecked()]
        if not selected:
            return
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            priv_str = ", ".join(selected)
            pool_loop.run_until_complete(connector.execute(f"GRANT {priv_str} ON {db_pattern} TO '{user}'@'{host}'"))
            pool_loop.run_until_complete(connector.execute("FLUSH PRIVILEGES"))
            QMessageBox.information(self, "成功", "权限已更新")
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))
