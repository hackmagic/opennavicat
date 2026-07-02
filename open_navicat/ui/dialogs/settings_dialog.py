"""Settings dialog — Navicat-style multi-tab settings with full feature parity."""

from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
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
    QRadioButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from open_navicat.config import config
from open_navicat.i18n import set_language, t
from open_navicat.ui.themes import list_themes


def _color_button(color_hex: str) -> QPushButton:
    btn = QPushButton()
    btn.setFixedSize(24, 24)
    btn.setStyleSheet(f"background-color: {color_hex}; border: 1px solid #888;")
    return btn


class SettingsDialog(QDialog):
    """Modal multi-tab settings dialog matching Navicat Options layout."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("menu.file.settings"))
        self.setMinimumSize(640, 520)
        self._color_buttons: dict[str, QPushButton] = {}
        self._setup_ui()
        self._load_config()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)

        tabs.addTab(self._build_general_tab(), t("settings.general"))
        tabs.addTab(self._build_tabs_tab(), t("settings.tabs"))
        tabs.addTab(self._build_code_completion_tab(), t("settings.code_completion"))
        tabs.addTab(self._build_editor_tab(), t("settings.editor"))
        tabs.addTab(self._build_records_tab(), t("settings.records"))
        tabs.addTab(self._build_ai_tab(), t("settings.ai"))
        tabs.addTab(self._build_advanced_tab(), t("settings.advanced"))

        layout.addWidget(tabs)

        # Bottom buttons: Default + OK/Cancel
        bottom = QHBoxLayout()
        btn_default = QPushButton(t("settings.reset"))
        btn_default.clicked.connect(self._reset_defaults)
        bottom.addStretch()
        bottom.addWidget(btn_default)
        layout.addLayout(bottom)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        btn_box.accepted.connect(self._save_and_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ---- General ----

    def _build_general_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        # Theme
        self._combo_theme = QComboBox()
        for name in list_themes():
            self._combo_theme.addItem(name.capitalize(), name)
        form.addRow(t("settings.theme") + ":", self._combo_theme)

        # Language
        self._combo_lang = QComboBox()
        self._combo_lang.addItem(t("lang.zh_CN"), "zh_CN")
        self._combo_lang.addItem(t("lang.en_US"), "en_US")
        self._combo_lang.currentIndexChanged.connect(self._on_language_changed)
        form.addRow(t("settings.language") + ":", self._combo_lang)

        # Checkboxes
        self._chk_allow_duplicate = QCheckBox(t("settings.allow_duplicate"))
        form.addRow("", self._chk_allow_duplicate)
        self._chk_show_toolbar_titles = QCheckBox(t("settings.show_toolbar_titles"))
        form.addRow("", self._chk_show_toolbar_titles)
        self._chk_prompt_save_query = QCheckBox(t("settings.prompt_save_query"))
        form.addRow("", self._chk_prompt_save_query)
        self._chk_prompt_save_table = QCheckBox(t("settings.prompt_save_table"))
        form.addRow("", self._chk_prompt_save_table)
        self._chk_safe_confirm = QCheckBox(t("settings.safe_confirm"))
        form.addRow("", self._chk_safe_confirm)
        self._chk_auto_update = QCheckBox(t("settings.auto_update"))
        form.addRow("", self._chk_auto_update)

        return tab

    # ---- Tabs behavior ----

    def _build_tabs_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        grp1 = QGroupBox(t("settings.tab_open_in"))
        r1 = QVBoxLayout(grp1)
        self._radio_tab_main = QRadioButton(t("settings.tab_main_window"))
        self._radio_tab_last = QRadioButton(t("settings.tab_last_window"))
        self._radio_tab_new = QRadioButton(t("settings.tab_new_window"))
        self._radio_tab_main.setChecked(True)
        for rb in [self._radio_tab_main, self._radio_tab_last, self._radio_tab_new]:
            r1.addWidget(rb)
        layout.addWidget(grp1)

        grp2 = QGroupBox(t("settings.startup_screen"))
        r2 = QVBoxLayout(grp2)
        self._radio_start_object = QRadioButton(t("settings.startup_object_only"))
        self._radio_start_restore = QRadioButton(t("settings.startup_restore"))
        self._radio_start_object.setChecked(True)
        for rb in [self._radio_start_object, self._radio_start_restore]:
            r2.addWidget(rb)
        layout.addWidget(grp2)

        layout.addStretch()
        return tab

    # ---- Code Completion ----

    def _build_code_completion_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self._chk_code_complete = QCheckBox(t("settings.use_code_completion"))
        form.addRow("", self._chk_code_complete)
        self._chk_auto_update_cc = QCheckBox(t("settings.auto_update_completion"))
        form.addRow("", self._chk_auto_update_cc)
        self._chk_include_sys = QCheckBox(t("settings.include_system_objects"))
        form.addRow("", self._chk_include_sys)
        self._chk_auto_select_first = QCheckBox(t("settings.auto_select_first"))
        form.addRow("", self._chk_auto_select_first)

        return tab

    # ---- Editor ----

    def _build_editor_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # General settings
        grp_general = QGroupBox(t("settings.general"))
        form1 = QFormLayout(grp_general)
        self._chk_line_numbers = QCheckBox(t("settings.show_line_numbers"))
        form1.addRow("", self._chk_line_numbers)
        self._chk_bracket_highlight = QCheckBox(t("settings.use_bracket_highlight"))
        form1.addRow("", self._chk_bracket_highlight)
        self._chk_syntax_highlight = QCheckBox(t("settings.use_syntax_highlight"))
        form1.addRow("", self._chk_syntax_highlight)

        row_wrap = QHBoxLayout()
        self._chk_word_wrap = QCheckBox(t("settings.use_word_wrap"))
        row_wrap.addWidget(self._chk_word_wrap)
        row_wrap.addStretch()
        form1.addRow("", self._chk_word_wrap)

        self._spin_tab_size = QSpinBox()
        self._spin_tab_size.setRange(1, 16)
        row_tab = QHBoxLayout()
        row_tab.addWidget(self._spin_tab_size)
        row_tab.addWidget(QLabel(t("settings.tab_size")))
        row_tab.addStretch()
        form1.addRow("", row_tab)

        self._chk_insert_spaces = QCheckBox(t("settings.insert_spaces_on_tab"))
        form1.addRow("", self._chk_insert_spaces)
        layout.addWidget(grp_general)

        # Font and colors
        grp_font = QGroupBox(t("settings.font_and_colors"))
        form2 = QFormLayout(grp_font)
        font_row = QHBoxLayout()
        self._edit_font_family = QLineEdit()
        self._edit_font_family.setMaximumWidth(160)
        font_row.addWidget(self._edit_font_family)
        self._spin_font_size = QSpinBox()
        self._spin_font_size.setRange(6, 36)
        font_row.addWidget(self._spin_font_size)
        font_row.addStretch()
        form2.addRow(t("settings.editor_font"), font_row)

        colors = [
            ("color_normal", t("settings.color_normal"), "#333333"),
            ("color_keyword", t("settings.color_keyword"), "#0000FF"),
            ("color_string", t("settings.color_string"), "#FF0000"),
            ("color_number", t("settings.color_number"), "#00AA00"),
            ("color_comment", t("settings.color_comment"), "#808080"),
            ("color_background", t("settings.color_background"), "#FFFFFF"),
        ]
        for key, label, default in colors:
            btn = _color_button(default)
            btn.clicked.connect(lambda checked=False, k=key, b=btn: self._pick_color(k, b))
            self._color_buttons[key] = btn
            form2.addRow(label, btn)

        layout.addWidget(grp_font)
        layout.addStretch()
        return tab

    # ---- Records ----

    def _build_records_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        grp1 = QGroupBox(t("settings.records"))
        form1 = QFormLayout(grp1)
        self._chk_limit_records = QCheckBox(t("settings.limit_records"))
        self._spin_limit = QSpinBox()
        self._spin_limit.setRange(1, 1000000)
        self._spin_limit.setValue(1000)
        row_limit = QHBoxLayout()
        row_limit.addWidget(self._chk_limit_records)
        row_limit.addWidget(self._spin_limit)
        row_limit.addWidget(QLabel(t("settings.records_per_page")))
        row_limit.addStretch()
        form1.addRow("", row_limit)
        layout.addWidget(grp1)

        grp2 = QGroupBox(t("settings.grid"))
        form2 = QFormLayout(grp2)
        font_row = QHBoxLayout()
        self._edit_grid_font = QLineEdit("Microsoft YaHei UI")
        self._edit_grid_font.setMaximumWidth(160)
        font_row.addWidget(self._edit_grid_font)
        self._spin_grid_size = QSpinBox()
        self._spin_grid_size.setRange(6, 24)
        self._spin_grid_size.setValue(9)
        font_row.addWidget(self._spin_grid_size)
        font_row.addStretch()
        form2.addRow(t("settings.grid_font"), font_row)

        self._combo_row_stripe = QComboBox()
        self._combo_row_stripe.addItems(["无", "每行", "每二行", "每三行"])
        self._combo_row_stripe.setCurrentIndex(3)
        form2.addRow(t("settings.row_stripe"), self._combo_row_stripe)
        layout.addWidget(grp2)

        grp3 = QGroupBox(t("settings.display_format"))
        form3 = QFormLayout(grp3)
        self._edit_date_fmt = QLineEdit()
        self._edit_date_fmt.setPlaceholderText("yyyy-MM-dd")
        form3.addRow(t("settings.date"), self._edit_date_fmt)
        self._edit_time_fmt = QLineEdit()
        self._edit_time_fmt.setPlaceholderText("HH:mm:ss")
        form3.addRow(t("settings.time"), self._edit_time_fmt)
        self._edit_datetime_fmt = QLineEdit()
        self._edit_datetime_fmt.setPlaceholderText("yyyy-MM-dd HH:mm:ss")
        form3.addRow(t("settings.datetime"), self._edit_datetime_fmt)
        self._chk_thousand_sep = QCheckBox(t("settings.thousand_separator"))
        form3.addRow("", self._chk_thousand_sep)
        self._chk_use_locale = QCheckBox(t("settings.use_locale_separator"))
        form3.addRow("", self._chk_use_locale)
        layout.addWidget(grp3)

        layout.addStretch()
        return tab

    # ---- AI ----

    def _build_ai_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self._chk_ai_enabled = QCheckBox(t("settings.enable_ai_assistant"))
        self._chk_ai_enabled.toggled.connect(self._on_ai_toggled)
        layout.addWidget(self._chk_ai_enabled)

        grp = QGroupBox(t("settings.ai_assistant"))
        self._ai_group = grp
        form = QFormLayout(grp)

        self._combo_ai_provider = QComboBox()
        for pid, pname in [("openai", "OpenAI"), ("deepseek", "DeepSeek"), ("ollama", "Ollama"), ("custom", t("ai.provider.custom"))]:
            self._combo_ai_provider.addItem(pname, pid)
        self._combo_ai_provider.currentIndexChanged.connect(self._on_ai_provider_changed)
        form.addRow(t("settings.ai_provider"), self._combo_ai_provider)

        self._edit_ai_base = QLineEdit()
        form.addRow(t("settings.api_host"), self._edit_ai_base)

        self._edit_ai_key = QLineEdit()
        self._edit_ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(t("settings.api_key"), self._edit_ai_key)

        self._edit_ai_model = QLineEdit()
        model_row = QHBoxLayout()
        model_row.addWidget(self._edit_ai_model)
        btn_browse = QPushButton("...")
        btn_browse.setMaximumWidth(30)
        model_row.addWidget(btn_browse)
        form.addRow(t("settings.model"), model_row)

        # Temperature slider
        temp_row = QHBoxLayout()
        self._slider_temp = QSlider(Qt.Orientation.Horizontal)
        self._slider_temp.setRange(0, 20)
        self._slider_temp.setValue(10)
        self._lbl_temp = QLabel("1.0 - " + t("settings.temp_balanced"))
        self._slider_temp.valueChanged.connect(self._on_temp_changed)
        temp_row.addWidget(self._slider_temp)
        temp_row.addWidget(self._lbl_temp)
        temp_row.addStretch()
        form.addRow(t("settings.temperature"), temp_row)

        self._edit_ai_desc = QLineEdit()
        form.addRow(t("settings.description"), self._edit_ai_desc)

        # Test connection
        btn_test = QPushButton(t("ai.config.test"))
        btn_test.clicked.connect(self._test_ai_connection)
        form.addRow("", btn_test)

        self._ai_status = QLabel("")
        self._ai_status.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow("", self._ai_status)

        layout.addWidget(grp)

        # UI behavior
        grp_ui = QGroupBox(t("settings.ai_ui"))
        form_ui = QFormLayout(grp_ui)
        self._combo_enter = QComboBox()
        self._combo_enter.addItems([t("settings.send_message"), t("settings.newline")])
        form_ui.addRow(t("settings.enter_action"), self._combo_enter)
        layout.addWidget(grp_ui)

        layout.addStretch()
        return tab

    # ---- Advanced ----

    def _build_advanced_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self._chk_diag_log = QCheckBox(t("settings.enable_diag_log"))
        form.addRow("", self._chk_diag_log)
        self._chk_allow_multi = QCheckBox(t("settings.allow_multi_instance"))
        form.addRow("", self._chk_allow_multi)

        note = QLabel(t("settings.restart_required"))
        note.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow("", note)

        return tab

    # ---- helpers ----

    def _pick_color(self, key: str, btn: QPushButton) -> None:
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            btn.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")

    def _on_temp_changed(self, val: int) -> None:
        v = val / 10.0
        labels = {
            0.0: t("settings.temp_precise"),
            0.5: t("settings.temp_creative"),
            1.0: t("settings.temp_balanced"),
            1.5: t("settings.temp_random"),
            2.0: t("settings.temp_max_random"),
        }
        closest = min(labels.keys(), key=lambda x: abs(x - v))
        self._lbl_temp.setText(f"{v:.1f} - {labels[closest]}")

    def _on_ai_toggled(self, checked: bool) -> None:
        self._ai_group.setVisible(checked)

    def _on_ai_provider_changed(self, index: int) -> None:
        provider = self._combo_ai_provider.itemData(index)
        hints = {
            "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
            "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
            "ollama": ("http://localhost:11434", "llama3"),
            "custom": ("http://localhost:8000/v1", ""),
        }
        base, model = hints.get(provider, ("", ""))
        if not self._edit_ai_base.text().strip():
            self._edit_ai_base.setText(base)
        if not self._edit_ai_model.text().strip():
            self._edit_ai_model.setText(model)

    def _test_ai_connection(self) -> None:
        from open_navicat.services.ai_service import ai_service
        cfg = {
            "provider": self._combo_ai_provider.currentData(),
            "api_key": self._edit_ai_key.text().strip(),
            "api_base": self._edit_ai_base.text().strip(),
            "model": self._edit_ai_model.text().strip(),
        }
        ok, msg = ai_service.test_config(cfg)
        if ok:
            self._ai_status.setText(f"✓ {msg}")
            self._ai_status.setStyleSheet("color: #4ec9b0; font-size: 11px;")
        else:
            self._ai_status.setText(f"✗ {msg}")
            self._ai_status.setStyleSheet("color: #e06c75; font-size: 11px;")

    def _on_language_changed(self, index: int) -> None:
        lang = self._combo_lang.itemData(index)
        set_language(lang)

    def _reset_defaults(self) -> None:
        self._combo_theme.setCurrentIndex(0)
        self._combo_lang.setCurrentIndex(0)
        self._chk_allow_duplicate.setChecked(False)
        self._chk_show_toolbar_titles.setChecked(True)
        self._chk_prompt_save_query.setChecked(True)
        self._chk_prompt_save_table.setChecked(True)
        self._chk_safe_confirm.setChecked(True)
        self._chk_auto_update.setChecked(True)
        self._radio_tab_main.setChecked(True)
        self._radio_start_object.setChecked(True)
        self._chk_code_complete.setChecked(True)
        self._chk_auto_update_cc.setChecked(True)
        self._chk_include_sys.setChecked(True)
        self._chk_auto_select_first.setChecked(True)
        self._chk_line_numbers.setChecked(True)
        self._chk_bracket_highlight.setChecked(True)
        self._chk_syntax_highlight.setChecked(True)
        self._chk_word_wrap.setChecked(True)
        self._spin_tab_size.setValue(2)
        self._chk_insert_spaces.setChecked(True)
        self._spin_font_size.setValue(10)
        self._edit_font_family.setText("Consolas")
        self._chk_limit_records.setChecked(True)
        self._spin_limit.setValue(1000)
        self._combo_row_stripe.setCurrentIndex(3)
        self._chk_thousand_sep.setChecked(False)
        self._chk_use_locale.setChecked(True)
        self._chk_ai_enabled.setChecked(False)
        self._slider_temp.setValue(10)
        self._combo_enter.setCurrentIndex(0)
        self._chk_diag_log.setChecked(False)
        self._chk_allow_multi.setChecked(False)

    # ---- load / save ----

    def _load_config(self) -> None:
        lang = config.get("language", "zh_CN")
        for i in range(self._combo_lang.count()):
            if self._combo_lang.itemData(i) == lang:
                self._combo_lang.setCurrentIndex(i)
                break

        theme = config.get("theme", "acrylic")
        for i in range(self._combo_theme.count()):
            if self._combo_theme.itemData(i) == theme:
                self._combo_theme.setCurrentIndex(i)
                break

        self._chk_allow_duplicate.setChecked(config.get("general.allow_duplicate", False))
        self._chk_show_toolbar_titles.setChecked(config.get("general.show_toolbar_titles", True))
        self._chk_prompt_save_query.setChecked(config.get("general.prompt_save_query", True))
        self._chk_prompt_save_table.setChecked(config.get("general.prompt_save_table", True))
        self._chk_safe_confirm.setChecked(config.get("general.safe_confirm", True))
        self._chk_auto_update.setChecked(config.get("general.auto_update", True))

        self._chk_code_complete.setChecked(config.get("code_completion.enabled", True))
        self._chk_auto_update_cc.setChecked(config.get("code_completion.auto_update", True))
        self._chk_include_sys.setChecked(config.get("code_completion.include_system", True))
        self._chk_auto_select_first.setChecked(config.get("code_completion.auto_select", True))

        self._chk_line_numbers.setChecked(config.get("editor.line_numbers", True))
        self._chk_bracket_highlight.setChecked(config.get("editor.bracket_highlight", True))
        self._chk_syntax_highlight.setChecked(config.get("editor.syntax_highlight", True))
        self._chk_word_wrap.setChecked(config.get("editor.word_wrap", True))
        self._spin_tab_size.setValue(config.get("editor.tab_size", 2))
        self._chk_insert_spaces.setChecked(config.get("editor.insert_spaces", True))
        self._edit_font_family.setText(config.get("editor.font_family", "Consolas"))
        self._spin_font_size.setValue(config.get("editor.font_size", 10))

        for key, default in [("color_normal", "#333333"), ("color_keyword", "#0000FF"), ("color_string", "#FF0000"), ("color_number", "#00AA00"), ("color_comment", "#808080"), ("color_background", "#FFFFFF")]:
            c = config.get(f"editor.{key}", default)
            if key in self._color_buttons:
                self._color_buttons[key].setStyleSheet(f"background-color: {c}; border: 1px solid #888;")

        self._chk_limit_records.setChecked(config.get("records.limit_enabled", True))
        self._spin_limit.setValue(config.get("records.limit", 1000))
        stripe = config.get("records.row_stripe", "每三行")
        idx = self._combo_row_stripe.findText(stripe)
        if idx >= 0:
            self._combo_row_stripe.setCurrentIndex(idx)
        self._chk_thousand_sep.setChecked(config.get("records.thousand_sep", False))
        self._chk_use_locale.setChecked(config.get("records.use_locale", True))

        self._chk_ai_enabled.setChecked(config.get("ai.enabled", False))
        self._ai_group.setVisible(config.get("ai.enabled", False))
        provider = config.get("ai.provider", "openai")
        for i in range(self._combo_ai_provider.count()):
            if self._combo_ai_provider.itemData(i) == provider:
                self._combo_ai_provider.setCurrentIndex(i)
                break
        self._edit_ai_base.setText(config.get("ai.api_base", ""))
        self._edit_ai_key.setText(config.get("ai.api_key", ""))
        self._edit_ai_model.setText(config.get("ai.model", "gpt-4o-mini"))
        self._slider_temp.setValue(int(config.get("ai.temperature", 1.0) * 10))

        self._chk_diag_log.setChecked(config.get("advanced.diag_log", False))
        self._chk_allow_multi.setChecked(config.get("advanced.allow_multi", False))

    def _collect_config(self) -> dict:
        cfg = {
            "language": self._combo_lang.currentData(),
            "theme": self._combo_theme.currentData(),
            "general.allow_duplicate": self._chk_allow_duplicate.isChecked(),
            "general.show_toolbar_titles": self._chk_show_toolbar_titles.isChecked(),
            "general.prompt_save_query": self._chk_prompt_save_query.isChecked(),
            "general.prompt_save_table": self._chk_prompt_save_table.isChecked(),
            "general.safe_confirm": self._chk_safe_confirm.isChecked(),
            "general.auto_update": self._chk_auto_update.isChecked(),
            "code_completion.enabled": self._chk_code_complete.isChecked(),
            "code_completion.auto_update": self._chk_auto_update_cc.isChecked(),
            "code_completion.include_system": self._chk_include_sys.isChecked(),
            "code_completion.auto_select": self._chk_auto_select_first.isChecked(),
            "editor.line_numbers": self._chk_line_numbers.isChecked(),
            "editor.bracket_highlight": self._chk_bracket_highlight.isChecked(),
            "editor.syntax_highlight": self._chk_syntax_highlight.isChecked(),
            "editor.word_wrap": self._chk_word_wrap.isChecked(),
            "editor.tab_size": self._spin_tab_size.value(),
            "editor.insert_spaces": self._chk_insert_spaces.isChecked(),
            "editor.font_family": self._edit_font_family.text().strip(),
            "editor.font_size": self._spin_font_size.value(),
            "records.limit_enabled": self._chk_limit_records.isChecked(),
            "records.limit": self._spin_limit.value(),
            "records.row_stripe": self._combo_row_stripe.currentText(),
            "records.thousand_sep": self._chk_thousand_sep.isChecked(),
            "records.use_locale": self._chk_use_locale.isChecked(),
            "ai.enabled": self._chk_ai_enabled.isChecked(),
            "ai.provider": self._combo_ai_provider.currentData(),
            "ai.api_key": self._edit_ai_key.text().strip(),
            "ai.api_base": self._edit_ai_base.text().strip(),
            "ai.model": self._edit_ai_model.text().strip(),
            "ai.temperature": self._slider_temp.value() / 10.0,
            "advanced.diag_log": self._chk_diag_log.isChecked(),
            "advanced.allow_multi": self._chk_allow_multi.isChecked(),
        }
        # Color settings
        for key, btn in self._color_buttons.items():
            style = btn.styleSheet()
            if "background-color:" in style:
                color = style.split("background-color:")[1].split(";")[0].strip()
                cfg[f"editor.{key}"] = color
        return cfg

    @Slot()
    def _save_and_accept(self) -> None:
        cfg = self._collect_config()
        old_lang = config.get("language", "zh_CN")
        lang_changed = cfg["language"] != old_lang
        theme_changed = cfg["theme"] != config.get("theme")
        ai_enabled_changed = cfg["ai.enabled"] != config.get("ai.enabled", False)

        for key, val in cfg.items():
            config.set(key, val)

        set_language(cfg["language"])

        from open_navicat.services.ai_service import ai_service
        ai_service.update_config({
            "provider": cfg["ai.provider"],
            "api_key": cfg["ai.api_key"],
            "api_base": cfg["ai.api_base"],
            "model": cfg["ai.model"],
        })

        self.accept()

        if ai_enabled_changed:
            mw = self.window()
            if hasattr(mw, '_refresh_ui'):
                mw._refresh_ui()

        if lang_changed:
            QMessageBox.information(self.window(), t("menu.file.settings"), t("prompt.language_changed"))

        if theme_changed:
            app = QApplication.instance()
            window = self.window()
            if app and window:
                from open_navicat.ui.themes import apply_theme
                apply_theme(cfg["theme"], app, window)
