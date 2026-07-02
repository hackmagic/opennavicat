"""AI 配置对话框 — 设置 LLM 提供商、API Key、模型等。"""

from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from open_navicat.config import config
from open_navicat.i18n import t
from open_navicat.services.ai_service import ai_service


class AIConfigDialog(QDialog):
    """Modal dialog for configuring AI provider, API key, model, etc."""

    PROVIDERS = [
        ("openai", "OpenAI"),
        ("deepseek", "DeepSeek"),
        ("ollama", t("ai.config.ollama")),
        ("custom", t("ai.config.custom")),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("ai.config.title"))
        self.setMinimumWidth(480)
        self._setup_ui()
        self._load_config()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ---- Provider ----
        provider_group = QGroupBox(t("ai.config.provider"), self)
        p_layout = QFormLayout(provider_group)

        self._combo_provider = QComboBox(self)
        for pid, pname in self.PROVIDERS:
            self._combo_provider.addItem(pname, pid)
        self._combo_provider.currentIndexChanged.connect(self._on_provider_changed)
        p_layout.addRow(t("ai.config.provider"), self._combo_provider)

        layout.addWidget(provider_group)

        # ---- API ----
        api_group = QGroupBox(t("ai.config.api_key").replace(":", ""), self)
        a_layout = QFormLayout(api_group)

        self._edit_api_key = QLineEdit(self)
        self._edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_api_key.setPlaceholderText("sk-...")
        a_layout.addRow(t("ai.config.api_key"), self._edit_api_key)

        self._edit_api_base = QLineEdit(self)
        self._edit_api_base.setPlaceholderText("https://api.openai.com/v1")
        a_layout.addRow(t("ai.config.api_base"), self._edit_api_base)

        self._edit_model = QLineEdit(self)
        self._edit_model.setPlaceholderText("gpt-4o-mini")
        a_layout.addRow(t("ai.config.model"), self._edit_model)

        # Show/hide password toggle
        self._btn_toggle_key = QPushButton(t("ai.config.show"), self)
        self._btn_toggle_key.setFixedWidth(80)
        self._btn_toggle_key.clicked.connect(self._toggle_api_key_visibility)
        a_layout.addRow("", self._btn_toggle_key)

        layout.addWidget(api_group)

        # ---- Status hint ----
        self._status_label = QLabel("", self)
        self._status_label.setStyleSheet("color: #888; font-size: 11px; padding: 4px;")
        layout.addWidget(self._status_label)

        layout.addStretch()

        # ---- Buttons ----
        btn_layout = QHBoxLayout()
        self._btn_test = QPushButton(t("ai.config.test"), self)
        self._btn_test.clicked.connect(self._test_config)
        btn_layout.addWidget(self._btn_test)
        btn_layout.addStretch()

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._save_and_accept)
        button_box.rejected.connect(self.reject)
        btn_layout.addWidget(button_box)

        layout.addLayout(btn_layout)

    def _load_config(self) -> None:
        """Load current AI settings from config into the form."""
        provider = config.get("ai.provider", "openai")
        for i in range(self._combo_provider.count()):
            if self._combo_provider.itemData(i) == provider:
                self._combo_provider.setCurrentIndex(i)
                break

        self._edit_api_key.setText(config.get("ai.api_key", ""))
        self._edit_api_base.setText(config.get("ai.api_base", ""))
        self._edit_model.setText(config.get("ai.model", "gpt-4o-mini"))
        self._update_status()

    def _collect_config(self) -> dict:
        return {
            "provider": self._combo_provider.currentData(),
            "api_key": self._edit_api_key.text().strip(),
            "api_base": self._edit_api_base.text().strip(),
            "model": self._edit_model.text().strip(),
        }

    def _update_status(self) -> None:
        cfg = self._collect_config()
        if cfg["api_key"]:
            masked = cfg["api_key"][:8] + "…" if len(cfg["api_key"]) > 8 else "***"
            self._status_label.setText(f"✅ {t('ai.config.key_set')}: {masked}")
            self._status_label.setStyleSheet("color: #4ec9b0; font-size: 11px; padding: 4px;")
        else:
            self._status_label.setText(f"⚠️ {t('ai.config.no_key_warning')}")
            self._status_label.setStyleSheet("color: #e06c75; font-size: 11px; padding: 4px;")

    # ---- slots ----

    @Slot(int)
    def _on_provider_changed(self, index: int) -> None:
        provider = self._combo_provider.itemData(index)
        hints = {
            "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
            "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
            "ollama": ("http://localhost:11434", "llama3"),
            "custom": ("http://localhost:8000/v1", ""),
        }
        base, model = hints.get(provider, ("", ""))
        if not self._edit_api_base.text().strip():
            self._edit_api_base.setText(base)
        if not self._edit_model.text().strip():
            self._edit_model.setText(model)
        self._update_status()

    @Slot()
    def _toggle_api_key_visibility(self) -> None:
        if self._edit_api_key.echoMode() == QLineEdit.EchoMode.Password:
            self._edit_api_key.setEchoMode(QLineEdit.EchoMode.Normal)
            self._btn_toggle_key.setText(t("ai.config.hide"))
        else:
            self._edit_api_key.setEchoMode(QLineEdit.EchoMode.Password)
            self._btn_toggle_key.setText(t("ai.config.show"))

    @Slot()
    def _test_config(self) -> None:
        """Test the current AI config by making a simple API call."""
        cfg = self._collect_config()
        if not cfg["api_key"] and cfg["provider"] != "ollama":
            QMessageBox.warning(self, t("common.notice"), t("ai.config.enter_key"))
            return

        self._btn_test.setEnabled(False)
        self._btn_test.setText(t("ai.config.testing"))
        self._btn_test.repaint()

        # Temporarily apply config and test
        ok, msg = ai_service.test_config(cfg)
        if ok:
            QMessageBox.information(self, t("common.ok"), f"{t('ai.config.test_success')}!\n{msg}")
        else:
            QMessageBox.warning(self, t("common.cancel"), f"{t('ai.config.test_failed')}:\n{msg}")

        self._btn_test.setText(t("ai.config.test"))
        self._btn_test.setEnabled(True)

    @Slot()
    def _save_and_accept(self) -> None:
        cfg = self._collect_config()
        # Validate
        if not cfg["api_key"] and cfg["provider"] != "ollama":
            ret = QMessageBox.question(
                self, t("common.ok"), f"{t('ai.config.no_key_warning')}。继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        # Save to config
        for key, val in cfg.items():
            config.set(f"ai.{key}", val)

        # Apply to ai_service at runtime
        ai_service.update_config(cfg)

        self.accept()
