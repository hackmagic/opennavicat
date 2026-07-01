"""Connection dialog — create and edit database connections."""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from open_navicat.dal.connection_pool import connection_pool
from open_navicat.i18n import t
from open_navicat.models.connection import ConnectionInfo


class ConnectionDialog(QDialog):
    """Modal dialog for creating or editing a database connection."""

    def __init__(self, parent=None, info: ConnectionInfo | None = None) -> None:
        super().__init__(parent)
        self._info = info or ConnectionInfo()
        self._setup_ui()
        self._load_info()

    def _setup_ui(self) -> None:
        self.setWindowTitle("New Connection" if not self._info.name else f"Edit {self._info.name}")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)

        # Tabs
        tabs = QTabWidget(self)

        # ---- General tab ----
        general = QWidget()
        general_layout = QFormLayout(general)

        self._edit_name = QLineEdit(self)
        self._edit_name.setPlaceholderText("My Database Server")
        general_layout.addRow(t("connection.name"), self._edit_name)

        self._combo_engine = QComboBox(self)
        self._combo_engine.addItem("MySQL", "mysql")
        self._combo_engine.addItem("PostgreSQL", "postgresql")
        self._combo_engine.addItem("SQLite", "sqlite")
        self._combo_engine.currentIndexChanged.connect(self._on_engine_changed)
        general_layout.addRow(t("connection.engine"), self._combo_engine)

        self._edit_host = QLineEdit("127.0.0.1", self)
        general_layout.addRow(t("connection.host"), self._edit_host)

        self._spin_port = QSpinBox(self)
        self._spin_port.setRange(1, 65535)
        self._spin_port.setValue(3306)
        general_layout.addRow(t("connection.port"), self._spin_port)

        self._edit_user = QLineEdit("root", self)
        general_layout.addRow(t("connection.user"), self._edit_user)

        self._edit_password = QLineEdit(self)
        self._edit_password.setEchoMode(QLineEdit.EchoMode.Password)
        general_layout.addRow(t("connection.password"), self._edit_password)

        self._edit_database = QLineEdit(self)
        self._edit_database.setPlaceholderText("(leave empty to browse)")
        general_layout.addRow(t("connection.default_db"), self._edit_database)

        self._edit_charset = QLineEdit("utf8mb4", self)
        general_layout.addRow(t("connection.charset"), self._edit_charset)

        # Color picker
        self._combo_color = QComboBox(self)
        colors = [("#4A90D9", "Blue"), ("#4ec9b0", "Green"), ("#dcdcaa", "Yellow"),
                  ("#f44747", "Red"), ("#c586c0", "Purple"), ("#ce9178", "Orange")]
        for code, name in colors:
            self._combo_color.addItem(name, code)
        self._combo_color.setStyleSheet(
            "QComboBox { background: #1e1e1e; color: #ccc; border: 1px solid #3c3c3c; "
            "padding: 4px 8px; }"
        )
        general_layout.addRow("Color:", self._combo_color)

        tabs.addTab(general, "General")

        # ---- SSH tab ----
        ssh_tab = QWidget()
        ssh_layout = QFormLayout(ssh_tab)

        self._chk_ssh = QCheckBox(t("connection.ssh"), self)
        self._chk_ssh.toggled.connect(self._toggle_ssh)
        ssh_layout.addRow(self._chk_ssh)

        self._edit_ssh_host = QLineEdit(self)
        self._edit_ssh_host.setEnabled(False)
        ssh_layout.addRow(t("connection.ssh.host"), self._edit_ssh_host)

        self._spin_ssh_port = QSpinBox(self)
        self._spin_ssh_port.setRange(1, 65535)
        self._spin_ssh_port.setValue(22)
        self._spin_ssh_port.setEnabled(False)
        ssh_layout.addRow(t("connection.ssh.port"), self._spin_ssh_port)

        self._edit_ssh_user = QLineEdit(self)
        self._edit_ssh_user.setEnabled(False)
        ssh_layout.addRow(t("connection.ssh.user"), self._edit_ssh_user)

        self._edit_ssh_pass = QLineEdit(self)
        self._edit_ssh_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_ssh_pass.setEnabled(False)
        ssh_layout.addRow(t("connection.ssh.password"), self._edit_ssh_pass)

        self._edit_ssh_key = QLineEdit(self)
        self._edit_ssh_key.setEnabled(False)
        self._edit_ssh_key.setPlaceholderText("Path to private key file")
        ssh_layout.addRow(t("connection.ssh.key_file"), self._edit_ssh_key)

        tabs.addTab(ssh_tab, "SSH")

        # ---- SSL tab ----
        ssl_tab = QWidget()
        ssl_layout = QFormLayout(ssl_tab)

        self._chk_ssl = QCheckBox(t("connection.ssl"), self)
        self._chk_ssl.toggled.connect(self._toggle_ssl)
        ssl_layout.addRow(self._chk_ssl)

        self._edit_ssl_ca = QLineEdit(self)
        self._edit_ssl_ca.setEnabled(False)
        ssl_layout.addRow(t("connection.ssl.ca"), self._edit_ssl_ca)

        self._edit_ssl_cert = QLineEdit(self)
        self._edit_ssl_cert.setEnabled(False)
        ssl_layout.addRow(t("connection.ssl.cert"), self._edit_ssl_cert)

        self._edit_ssl_key = QLineEdit(self)
        self._edit_ssl_key.setEnabled(False)
        ssl_layout.addRow(t("connection.ssl.key"), self._edit_ssl_key)

        tabs.addTab(ssl_tab, "SSL")

        # ---- Pool tab ----
        pool_tab = QWidget()
        pool_layout = QFormLayout(pool_tab)

        self._spin_pool_min = QSpinBox(pool_tab)
        self._spin_pool_min.setRange(0, 100)
        self._spin_pool_min.setValue(1)
        self._spin_pool_min.setToolTip("Minimum connections kept alive in the pool")
        pool_layout.addRow(t("connection.pool.min"), self._spin_pool_min)

        self._spin_pool_max = QSpinBox(pool_tab)
        self._spin_pool_max.setRange(1, 500)
        self._spin_pool_max.setValue(10)
        self._spin_pool_max.setToolTip("Maximum connections allowed in the pool")
        pool_layout.addRow(t("connection.pool.max"), self._spin_pool_max)

        self._spin_timeout = QSpinBox(pool_tab)
        self._spin_timeout.setRange(1, 300)
        self._spin_timeout.setValue(10)
        self._spin_timeout.setSuffix(" s")
        self._spin_timeout.setToolTip("Connection timeout in seconds")
        pool_layout.addRow(t("connection.pool.timeout"), self._spin_timeout)

        tabs.addTab(pool_tab, t("connection.pool"))

        layout.addWidget(tabs)

        # ---- Test & Save buttons ----
        btn_layout = QHBoxLayout()
        self._btn_test = QPushButton(t("connection.test"), self)
        self._btn_test.clicked.connect(self._test_connection)
        btn_layout.addWidget(self._btn_test)
        btn_layout.addStretch()

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        btn_layout.addWidget(button_box)

        layout.addLayout(btn_layout)

    def _load_info(self) -> None:
        self._edit_name.setText(self._info.name)
        idx = self._combo_engine.findData(self._info.engine)
        if idx >= 0:
            self._combo_engine.setCurrentIndex(idx)
        self._edit_host.setText(self._info.host)
        self._spin_port.setValue(self._info.port)
        self._edit_user.setText(self._info.user)
        self._edit_password.setText(self._info.password)
        self._edit_database.setText(self._info.database)
        self._edit_charset.setText(self._info.charset)

        # Color
        for i in range(self._combo_color.count()):
            if self._combo_color.itemData(i) == self._info.color:
                self._combo_color.setCurrentIndex(i)
                break

        if self._info.use_ssh:
            self._chk_ssh.setChecked(True)
            self._edit_ssh_host.setText(self._info.ssh_host)
            self._spin_ssh_port.setValue(self._info.ssh_port)
            self._edit_ssh_user.setText(self._info.ssh_user)
            self._edit_ssh_pass.setText(self._info.ssh_password)
            self._edit_ssh_key.setText(self._info.ssh_key_file)

        if self._info.use_ssl:
            self._chk_ssl.setChecked(True)
            self._edit_ssl_ca.setText(self._info.ssl_ca)
            self._edit_ssl_cert.setText(self._info.ssl_cert)
            self._edit_ssl_key.setText(self._info.ssl_key)

        # Pool
        self._spin_pool_min.setValue(self._info.pool_min)
        self._spin_pool_max.setValue(self._info.pool_max)
        self._spin_timeout.setValue(self._info.connect_timeout)

    # ---- public API ----

    def connection_info(self) -> ConnectionInfo:
        """Return the ConnectionInfo populated from the dialog fields."""
        return ConnectionInfo(
            id=self._info.id,
            name=self._edit_name.text().strip(),
            engine=self._combo_engine.currentData(),
            host=self._edit_host.text().strip(),
            port=self._spin_port.value(),
            user=self._edit_user.text().strip(),
            password=self._edit_password.text(),
            database=self._edit_database.text().strip(),
            charset=self._edit_charset.text().strip(),
            use_ssh=self._chk_ssh.isChecked(),
            ssh_host=self._edit_ssh_host.text().strip(),
            ssh_port=self._spin_ssh_port.value(),
            ssh_user=self._edit_ssh_user.text().strip(),
            ssh_password=self._edit_ssh_pass.text(),
            ssh_key_file=self._edit_ssh_key.text().strip(),
            use_ssl=self._chk_ssl.isChecked(),
            ssl_ca=self._edit_ssl_ca.text().strip(),
            ssl_cert=self._edit_ssl_cert.text().strip(),
            ssl_key=self._edit_ssl_key.text().strip(),
            color=self._combo_color.currentData(),
            pool_min=self._spin_pool_min.value(),
            pool_max=self._spin_pool_max.value(),
            connect_timeout=self._spin_timeout.value(),
        )

    # ---- slots ----

    @Slot(bool)
    def _toggle_ssh(self, enabled: bool) -> None:
        for widget in (self._edit_ssh_host, self._spin_ssh_port,
                       self._edit_ssh_user, self._edit_ssh_pass,
                       self._edit_ssh_key):
            widget.setEnabled(enabled)

    @Slot(bool)
    def _toggle_ssl(self, enabled: bool) -> None:
        for widget in (self._edit_ssl_ca, self._edit_ssl_cert, self._edit_ssl_key):
            widget.setEnabled(enabled)

    @Slot(int)
    def _on_engine_changed(self, _index: int) -> None:
        engine = self._combo_engine.currentData()
        is_sqlite = engine == "sqlite"
        is_pg = engine == "postgresql"

        # SQLite: host = file path, disable port/user/password
        self._edit_host.setPlaceholderText("Path to .db file" if is_sqlite else "")
        self._spin_port.setEnabled(not is_sqlite)
        self._edit_user.setEnabled(not is_sqlite)
        self._edit_password.setEnabled(not is_sqlite)
        self._edit_database.setEnabled(not is_sqlite)
        self._edit_charset.setEnabled(not is_sqlite)

        if not is_sqlite:
            self._spin_port.setValue(5432 if is_pg else 3306)

    @Slot()
    def _test_connection(self) -> None:
        info = self.connection_info()
        self._btn_test.setEnabled(False)
        self._btn_test.setText(t("connection.testing"))
        self._btn_test.repaint()

        success = connection_pool.open(info)
        if success:
            connection_pool.close(info.id)
            QMessageBox.information(self, "Success", t("connection.success"))
        else:
            QMessageBox.warning(self, "Failed", t("connection.failed"))

        self._btn_test.setText(t("connection.test"))
        self._btn_test.setEnabled(True)
