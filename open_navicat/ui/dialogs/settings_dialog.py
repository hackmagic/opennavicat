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

        tabs.addTab(self._build_general_tab(), "常规")
        tabs.addTab(self._build_tabs_tab(), "选项卡")
        tabs.addTab(self._build_code_completion_tab(), "代码补全")
        tabs.addTab(self._build_editor_tab(), "编辑器")
        tabs.addTab(self._build_records_tab(), "记录")
        tabs.addTab(self._build_ai_tab(), "AI")
        tabs.addTab(self._build_advanced_tab(), "高级")

        layout.addWidget(tabs)

        # Bottom buttons: Default + OK/Cancel
        bottom = QHBoxLayout()
        btn_default = QPushButton("默认")
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
        form.addRow("布景主题:", self._combo_theme)

        # Language
        self._combo_lang = QComboBox()
        self._combo_lang.addItem("简体中文", "zh_CN")
        self._combo_lang.addItem("English", "en_US")
        self._combo_lang.currentIndexChanged.connect(self._on_language_changed)
        form.addRow("语言:", self._combo_lang)

        # Checkboxes
        self._chk_allow_duplicate = QCheckBox("允许重复打开相同的对象")
        form.addRow("", self._chk_allow_duplicate)
        self._chk_show_toolbar_titles = QCheckBox("显示工具栏标题")
        form.addRow("", self._chk_show_toolbar_titles)
        self._chk_prompt_save_query = QCheckBox("在关闭前提示保存新建的查询或配置文件")
        form.addRow("", self._chk_prompt_save_query)
        self._chk_prompt_save_table = QCheckBox("在关闭前提示保存新建的表配置文件")
        form.addRow("", self._chk_prompt_save_table)
        self._chk_safe_confirm = QCheckBox("使用安全确认对话框 (主窗口)")
        form.addRow("", self._chk_safe_confirm)
        self._chk_auto_update = QCheckBox("在启动时自动检查更新")
        form.addRow("", self._chk_auto_update)

        return tab

    # ---- Tabs behavior ----

    def _build_tabs_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        grp1 = QGroupBox("打开新选项卡于")
        r1 = QVBoxLayout(grp1)
        self._radio_tab_main = QRadioButton("主窗口")
        self._radio_tab_last = QRadioButton("最后打开选项卡的窗口")
        self._radio_tab_new = QRadioButton("新窗口")
        self._radio_tab_main.setChecked(True)
        for rb in [self._radio_tab_main, self._radio_tab_last, self._radio_tab_new]:
            r1.addWidget(rb)
        layout.addWidget(grp1)

        grp2 = QGroupBox("启动画面")
        r2 = QVBoxLayout(grp2)
        self._radio_start_object = QRadioButton("仅打开对象选项卡")
        self._radio_start_restore = QRadioButton("从上次离开的画面继续")
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

        self._chk_code_complete = QCheckBox("使用代码补全")
        form.addRow("", self._chk_code_complete)
        self._chk_auto_update_cc = QCheckBox("自动更新代码补全的信息")
        form.addRow("", self._chk_auto_update_cc)
        self._chk_include_sys = QCheckBox("更新代码补全的信息时包括系统对象")
        form.addRow("", self._chk_include_sys)
        self._chk_auto_select_first = QCheckBox("自动选择第一个建议项目")
        form.addRow("", self._chk_auto_select_first)

        return tab

    # ---- Editor ----

    def _build_editor_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # General settings
        grp_general = QGroupBox("常规")
        form1 = QFormLayout(grp_general)
        self._chk_line_numbers = QCheckBox("显示行号")
        form1.addRow("", self._chk_line_numbers)
        self._chk_bracket_highlight = QCheckBox("使用括号高亮显示")
        form1.addRow("", self._chk_bracket_highlight)
        self._chk_syntax_highlight = QCheckBox("使用语法高亮显示")
        form1.addRow("", self._chk_syntax_highlight)

        row_wrap = QHBoxLayout()
        self._chk_word_wrap = QCheckBox("使用自动换行")
        row_wrap.addWidget(self._chk_word_wrap)
        row_wrap.addStretch()
        form1.addRow("", self._chk_word_wrap)

        self._spin_tab_size = QSpinBox()
        self._spin_tab_size.setRange(1, 16)
        row_tab = QHBoxLayout()
        row_tab.addWidget(self._spin_tab_size)
        row_tab.addWidget(QLabel("制表符宽度"))
        row_tab.addStretch()
        form1.addRow("", row_tab)

        self._chk_insert_spaces = QCheckBox("按下 Tab 键时插入空格")
        form1.addRow("", self._chk_insert_spaces)
        layout.addWidget(grp_general)

        # Font and colors
        grp_font = QGroupBox("字体和颜色")
        form2 = QFormLayout(grp_font)
        font_row = QHBoxLayout()
        self._edit_font_family = QLineEdit()
        self._edit_font_family.setMaximumWidth(160)
        font_row.addWidget(self._edit_font_family)
        self._spin_font_size = QSpinBox()
        self._spin_font_size.setRange(6, 36)
        font_row.addWidget(self._spin_font_size)
        font_row.addStretch()
        form2.addRow("编辑器字体:", font_row)

        colors = [
            ("color_normal", "常规:", "#333333"),
            ("color_keyword", "关键字:", "#0000FF"),
            ("color_string", "字符串:", "#FF0000"),
            ("color_number", "数字:", "#00AA00"),
            ("color_comment", "注释:", "#808080"),
            ("color_background", "背景:", "#FFFFFF"),
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

        grp1 = QGroupBox("记录")
        form1 = QFormLayout(grp1)
        self._chk_limit_records = QCheckBox("限制记录:")
        self._spin_limit = QSpinBox()
        self._spin_limit.setRange(1, 1000000)
        self._spin_limit.setValue(1000)
        row_limit = QHBoxLayout()
        row_limit.addWidget(self._chk_limit_records)
        row_limit.addWidget(self._spin_limit)
        row_limit.addWidget(QLabel("条记录 (每页)"))
        row_limit.addStretch()
        form1.addRow("", row_limit)
        layout.addWidget(grp1)

        grp2 = QGroupBox("网格")
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
        form2.addRow("网格字体:", font_row)

        self._combo_row_stripe = QComboBox()
        self._combo_row_stripe.addItems(["无", "每行", "每二行", "每三行"])
        self._combo_row_stripe.setCurrentIndex(3)
        form2.addRow("行底纹:", self._combo_row_stripe)
        layout.addWidget(grp2)

        grp3 = QGroupBox("显示格式")
        form3 = QFormLayout(grp3)
        self._edit_date_fmt = QLineEdit()
        self._edit_date_fmt.setPlaceholderText("yyyy-MM-dd")
        form3.addRow("日期:", self._edit_date_fmt)
        self._edit_time_fmt = QLineEdit()
        self._edit_time_fmt.setPlaceholderText("HH:mm:ss")
        form3.addRow("时间:", self._edit_time_fmt)
        self._edit_datetime_fmt = QLineEdit()
        self._edit_datetime_fmt.setPlaceholderText("yyyy-MM-dd HH:mm:ss")
        form3.addRow("日期时间:", self._edit_datetime_fmt)
        self._chk_thousand_sep = QCheckBox("显示千位分隔符")
        form3.addRow("", self._chk_thousand_sep)
        self._chk_use_locale = QCheckBox("使用系统区域设置小数点和千位分隔符")
        form3.addRow("", self._chk_use_locale)
        layout.addWidget(grp3)

        layout.addStretch()
        return tab

    # ---- AI ----

    def _build_ai_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self._chk_ai_enabled = QCheckBox("启用 AI 助手")
        self._chk_ai_enabled.toggled.connect(self._on_ai_toggled)
        layout.addWidget(self._chk_ai_enabled)

        grp = QGroupBox("AI 助手")
        self._ai_group = grp
        form = QFormLayout(grp)

        self._combo_ai_provider = QComboBox()
        for pid, pname in [("openai", "OpenAI"), ("deepseek", "DeepSeek"), ("ollama", "Ollama"), ("custom", "自定义")]:
            self._combo_ai_provider.addItem(pname, pid)
        self._combo_ai_provider.currentIndexChanged.connect(self._on_ai_provider_changed)
        form.addRow("AI 提供商:", self._combo_ai_provider)

        self._edit_ai_base = QLineEdit()
        form.addRow("API 主机:", self._edit_ai_base)

        self._edit_ai_key = QLineEdit()
        self._edit_ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("API 密钥:", self._edit_ai_key)

        self._edit_ai_model = QLineEdit()
        model_row = QHBoxLayout()
        model_row.addWidget(self._edit_ai_model)
        btn_browse = QPushButton("...")
        btn_browse.setMaximumWidth(30)
        model_row.addWidget(btn_browse)
        form.addRow("模型:", model_row)

        # Temperature slider
        temp_row = QHBoxLayout()
        self._slider_temp = QSlider(Qt.Orientation.Horizontal)
        self._slider_temp.setRange(0, 20)
        self._slider_temp.setValue(10)
        self._lbl_temp = QLabel("1.0 - 平衡的")
        self._slider_temp.valueChanged.connect(self._on_temp_changed)
        temp_row.addWidget(self._slider_temp)
        temp_row.addWidget(self._lbl_temp)
        temp_row.addStretch()
        form.addRow("温度:", temp_row)

        self._edit_ai_desc = QLineEdit()
        form.addRow("说明:", self._edit_ai_desc)

        # Test connection
        btn_test = QPushButton("测试连接")
        btn_test.clicked.connect(self._test_ai_connection)
        form.addRow("", btn_test)

        self._ai_status = QLabel("")
        self._ai_status.setStyleSheet("color: #888; font-size: 11px;")
        form.addRow("", self._ai_status)

        layout.addWidget(grp)

        # UI behavior
        grp_ui = QGroupBox("AI 助手 UI")
        form_ui = QFormLayout(grp_ui)
        self._combo_enter = QComboBox()
        self._combo_enter.addItems(["发送消息", "换行"])
        form_ui.addRow("按下回车键时执行的操作:", self._combo_enter)
        layout.addWidget(grp_ui)

        layout.addStretch()
        return tab

    # ---- Advanced ----

    def _build_advanced_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self._chk_diag_log = QCheckBox("启用诊断日志")
        form.addRow("", self._chk_diag_log)
        self._chk_allow_multi = QCheckBox("允许重复运行 Navicat")
        form.addRow("", self._chk_allow_multi)

        note = QLabel("* 更改将于重新启动后生效")
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
        labels = {0.0: "精确的", 0.5: "创造性的", 1.0: "平衡的", 1.5: "更随机", 2.0: "最随机"}
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

        if lang_changed:
            QMessageBox.information(self.window(), t("menu.file.settings"), t("prompt.language_changed"))

        if theme_changed:
            app = QApplication.instance()
            window = self.window()
            if app and window:
                from open_navicat.ui.themes import apply_theme
                apply_theme(cfg["theme"], app, window)
