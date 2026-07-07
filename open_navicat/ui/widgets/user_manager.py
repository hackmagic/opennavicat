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
from open_navicat.i18n import t


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
        t_layout.addWidget(QLabel(t("tab.user_manager"), toolbar))
        t_layout.addStretch()

        for text, cb, obj_name in [
            (t("user_manager.btn.create"), self._new_user, "primaryBtn"),
            (t("user_manager.btn.delete"), self._drop_user, "dangerBtn"),
            (t("user_manager.btn.privileges"), self._manage_privileges, "successBtn"),
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
        layout.addWidget(self._table)

        self._status = QLabel("", self)
        layout.addWidget(self._status)

    def _detect_engine(self) -> str:
        connector = connection_pool.get(self._connection_id)
        if connector:
            info = getattr(connector, "_info", None)
            return getattr(info, "engine", "mysql") if info else "mysql"
        return "mysql"

    def _load_users(self) -> None:
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        engine = self._detect_engine()
        try:
            if engine == "postgresql":
                result = pool_loop.run_until_complete(
                    connector.execute("SELECT rolname, rolsuper, rolcreatedb, rolcanlogin FROM pg_roles ORDER BY rolname")
                )
                rows = result.rows if result and result.rows else []
                self._table.setRowCount(len(rows))
                for i, r in enumerate(rows):
                    self._table.setItem(i, 0, QTableWidgetItem(str(r[0])))
                    self._table.setItem(i, 1, QTableWidgetItem("*"))
                    privs = []
                    if r[1]:
                        privs.append("SUPER")
                    if r[2]:
                        privs.append("CREATEDB")
                    if r[3]:
                        privs.append("LOGIN")
                    self._table.setItem(i, 2, QTableWidgetItem(",".join(privs)))
            else:
                result = pool_loop.run_until_complete(
                    connector.execute("SELECT User, Host, plugin FROM mysql.user ORDER BY User")
                )
                rows = result.rows if result and result.rows else []
                self._table.setRowCount(len(rows))
                for i, r in enumerate(rows):
                    self._table.setItem(i, 0, QTableWidgetItem(str(r[0])))
                    self._table.setItem(i, 1, QTableWidgetItem(str(r[1])))
                    self._table.setItem(i, 2, QTableWidgetItem(str(r[2]) if len(r) > 2 else ""))
            self._status.setText(t("user_manager.status.total_users", count=len(rows)))
        except Exception as e:
            self._status.setText(t("user_manager.status.load_failed", error=e))

    def _new_user(self) -> None:
        engine = self._detect_engine()
        dlg = QDialog(self.window())
        dlg.setWindowTitle(t("user_manager.dialog.new_user"))
        form = QFormLayout(dlg)
        user_edit = QLineEdit(dlg)
        host_edit = QLineEdit("%", dlg) if engine != "postgresql" else QLineEdit(dlg)
        pass_edit = QLineEdit(dlg)
        pass_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(t("user_manager.label.username"), user_edit)
        if engine != "postgresql":
            form.addRow(t("user_manager.label.host"), host_edit)
        form.addRow(t("user_manager.label.password"), pass_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("common.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("common.cancel"))
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        user, pwd = user_edit.text().strip(), pass_edit.text().strip()
        host = host_edit.text().strip() if engine != "postgresql" else ""
        if not user:
            return
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        try:
            if engine == "postgresql":
                pool_loop.run_until_complete(connector.execute(f"CREATE ROLE \"{user}\" WITH LOGIN PASSWORD '{pwd}'"))
            else:
                pool_loop.run_until_complete(connector.execute(f"CREATE USER '{user}'@'{host}' IDENTIFIED BY '{pwd}'"))
            QMessageBox.information(self, t("common.success"), t("user_manager.msg.created", user=user, host=host))
            self._load_users()
        except Exception as e:
            QMessageBox.warning(self, t("common.failed"), str(e))

    def _drop_user(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        user = self._table.item(row, 0).text()
        host = self._table.item(row, 1).text()
        if QMessageBox.question(self, t("common.confirm"), t("user_manager.msg.confirm_delete_user", user=user, host=host),
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        connector = connection_pool.get(self._connection_id)
        if not connector:
            return
        engine = self._detect_engine()
        try:
            if engine == "postgresql":
                pool_loop.run_until_complete(connector.execute(f"DROP ROLE \"{user}\""))
            else:
                pool_loop.run_until_complete(connector.execute(f"DROP USER '{user}'@'{host}'"))
            self._load_users()
        except Exception as e:
            QMessageBox.warning(self, t("common.failed"), str(e))

    def _manage_privileges(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        user = self._table.item(row, 0).text()
        host = self._table.item(row, 1).text()
        engine = self._detect_engine()
        dlg = QDialog(self.window())
        dlg.setWindowTitle(t("user_manager.dialog.privileges", user=user, host=host))
        dlg.resize(450, 400)
        layout = QVBoxLayout(dlg)
        db_edit = QLineEdit("*.*", dlg)
        layout.addWidget(QLabel(t("user_manager.label.db_table"), dlg))
        layout.addWidget(db_edit)
        layout.addWidget(QLabel(t("user_manager.label.global_privs"), dlg))
        checks = {}
        for priv in self.COMMON_PRIVILEGES:
            cb = QCheckBox(priv, dlg)
            checks[priv] = cb
            layout.addWidget(cb)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dlg)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(t("common.ok"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("common.cancel"))
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
            if engine == "postgresql":
                # PostgreSQL: GRANT role TO user
                priv_str = ", ".join(selected)
                pool_loop.run_until_complete(connector.execute(f"GRANT {priv_str} TO \"{user}\""))
            else:
                priv_str = ", ".join(selected)
                pool_loop.run_until_complete(connector.execute(f"GRANT {priv_str} ON {db_pattern} TO '{user}'@'{host}'"))
                pool_loop.run_until_complete(connector.execute("FLUSH PRIVILEGES"))
            QMessageBox.information(self, t("common.success"), t("user_manager.msg.privileges_updated"))
        except Exception as e:
            QMessageBox.warning(self, t("common.failed"), str(e))
