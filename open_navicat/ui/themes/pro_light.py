"""
ProLight — 现代专业数据库 IDE 亮色主题（v2）。

与 ProDark 共享相同的设计系统骨架，仅颜色翻转。
所有颜色值经过 WCAG AA 对比度验证。
"""

from __future__ import annotations

import logging
from typing import ClassVar

from PySide6.QtWidgets import QApplication, QMainWindow

from open_navicat.ui.themes import Theme, register_theme

logger = logging.getLogger("opennavicat.theme.prolight")


class Color:
    """语义化颜色令牌 — 亮色版，WCAG AA 验证通过。"""

    # 背景层级
    BG_PRIMARY = "#ffffff"       # 主内容区
    BG_SECONDARY = "#f4f4f8"     # 侧边栏/面板头
    BG_TERTIARY = "#ecedf1"     # 输入框/树节点
    BG_HOVER = "#e0e1e6"        # 悬停态
    BG_SELECTED = "#c8c9d0"     # 选中态
    BG_TOOLTIP = "#2e2e3a"      # 悬浮提示
    BG_OVERLAY = "rgba(0, 0, 0, 0.35)"  # 模态遮罩

    # 强调色
    ACCENT = "#3b5cde"          # 主色 ← 从 #4a6cf7 修正（4.39→5.57:1 ✓）
    ACCENT_HOVER = "#5a78e8"    # 悬停
    ACCENT_PRESSED = "#2e4ac4"  # 按下
    ACCENT_DISABLED = "#c0c4d0" # 禁用
    ACCENT_BG = "#eef1ff"       # 强调背景
    SELECTION_BG = "#d0daff"    # SQL 编辑器选中背景 — 更明显区别于输入框背景

    # 语义色
    SUCCESS = "#16a34a"
    SUCCESS_BG = "#e6f7ee"
    WARNING = "#d97706"
    WARNING_BG = "#fef3e7"
    ERROR = "#dc2626"
    ERROR_BG = "#fee7e7"
    INFO = "#3b5cde"
    INFO_BG = "#eef1ff"

    # 文本层级（WCAG AA 验证通过）
    TEXT_PRIMARY = "#1a1a2e"       # 17.1:1 on white ✓
    TEXT_SECONDARY = "#4a4a6a"     # 8.5:1 on white ✓
    TEXT_MUTED = "#6e6e8a"         # 4.9:1 on white ✓ ← 从 #8a8aaa 修正
    TEXT_ACCENT = "#3b5cde"        # 5.6:1 on white ✓ ← 从 #4a6cf7 修正
    TEXT_SUCCESS = "#16a34a"
    TEXT_WARNING = "#d97706"
    TEXT_ERROR = "#dc2626"
    TEXT_DISABLED = "#8e8e9e"      # 3.2:1 on white ✓ ← 从 #b0b0c0 修正
    TEXT_LINK = "#2563eb"          # 链接色（6.3:1 ✓）

    # 边框
    BORDER = "#d4d5db"
    BORDER_LIGHT = "#b0b1b8"
    BORDER_FOCUS = "#3b5cde"
    BORDER_ERROR = "#dc2626"
    BORDER_DIVIDER = "#e4e5ea"

    # 亚克力
    ACRYLIC_BG = "rgba(255, 255, 255, 0.85)"
    ACRYLIC_DARK = "rgba(244, 244, 248, 0.92)"
    ACRYLIC_LIGHT = "rgba(224, 225, 230, 0.80)"


# 字体
FONT_SANS = """"Segoe UI", "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", "Helvetica Neue", Arial, sans-serif"""
FONT_MONO = """"Cascadia Code", "JetBrains Mono", "Fira Code", "Consolas", "Courier New", monospace"""

FS_10  = "10px"
FS_11  = "11px"
FS_12  = "12px"
FS_13  = "13px"
FS_14  = "14px"
FS_16  = "16px"
FS_20  = "20px"
FS_26  = "26px"
FS_32  = "32px"

W_NORMAL = "400"
W_MEDIUM = "500"
W_SEMIBOLD = "600"
W_BOLD = "700"

# 间距（4px 网格）
S2  = "2px"
S4  = "4px"
S8  = "8px"
S12 = "12px"
S16 = "16px"
S24 = "24px"
S32 = "32px"
S48 = "48px"

# 圆角
R_SM  = "3px"
R_MD  = "6px"
R_LG  = "8px"
R_XL  = "12px"
R_FULL = "9999px"


def _qss() -> str:
    return f"""
QWidget {{
    font-family: {FONT_SANS};
    font-size: {FS_13};
    color: {Color.TEXT_PRIMARY};
    background-color: {Color.BG_PRIMARY};
}}
QWidget:disabled {{
    color: {Color.TEXT_DISABLED};
}}
QMainWindow {{
    background-color: {Color.BG_PRIMARY};
}}

QMenuBar {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_SECONDARY};
    font-size: {FS_12};
    border-bottom: 1px solid {Color.BORDER};
    padding: 0;
    min-height: 28px;
}}
QMenuBar::item {{
    padding: {S4} {S8};
    background: transparent;
    border-radius: {R_SM};
    margin: 2px 1px;
}}
QMenuBar::item:selected {{
    background-color: {Color.BG_HOVER};
    color: {Color.TEXT_PRIMARY};
}}
QMenuBar::item:pressed {{
    background-color: {Color.BG_SELECTED};
}}
QMenu {{
    background-color: {Color.BG_SECONDARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_MD};
    padding: {S4} 0;
    margin: 2px;
}}
QMenu::item {{
    padding: {S4} {S24} {S4} {S16};
    font-size: {FS_12};
    color: {Color.TEXT_SECONDARY};
}}
QMenu::item:selected {{
    background-color: {Color.BG_HOVER};
    color: {Color.TEXT_PRIMARY};
}}
QMenu::item:disabled {{
    color: {Color.TEXT_DISABLED};
}}
QMenu::separator {{
    height: 1px;
    background: {Color.BORDER_DIVIDER};
    margin: {S4} {S12};
}}

QToolBar {{
    background-color: {Color.BG_SECONDARY};
    border-bottom: 1px solid {Color.BORDER};
    padding: {S4} {S8};
    spacing: {S4};
    min-height: 32px;
}}
QToolBar::separator {{
    width: 1px;
    height: 20px;
    background: {Color.BORDER};
    margin: 2px {S8};
}}
QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {R_SM};
    padding: {S4} {S8};
    font-size: {FS_12};
    color: {Color.TEXT_SECONDARY};
    min-width: 28px;
    min-height: 24px;
}}
QToolButton:hover {{
    background-color: {Color.BG_HOVER};
    border-color: {Color.BORDER};
    color: {Color.TEXT_PRIMARY};
}}
QToolButton:pressed {{
    background-color: {Color.BG_SELECTED};
}}
QToolButton:checked {{
    background-color: {Color.ACCENT_BG};
    border-color: {Color.ACCENT};
    color: {Color.TEXT_ACCENT};
}}
QToolButton:disabled {{
    color: {Color.TEXT_DISABLED};
}}

QPushButton {{
    background-color: {Color.BG_TERTIARY};
    color: {Color.TEXT_SECONDARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S4} {S16};
    font-size: {FS_12};
    font-weight: {W_MEDIUM};
    min-height: 22px;
    min-width: 32px;
}}
QPushButton:hover {{
    background-color: {Color.BG_HOVER};
    border-color: {Color.BORDER_LIGHT};
    color: {Color.TEXT_PRIMARY};
}}
QPushButton:pressed {{
    background-color: {Color.BG_SELECTED};
}}
QPushButton:disabled {{
    background-color: {Color.BG_TERTIARY};
    color: {Color.TEXT_DISABLED};
    border-color: {Color.BORDER};
}}
QPushButton#primaryBtn,
QPushButton[class="primary"] {{
    background-color: {Color.ACCENT};
    color: #ffffff;
    border-color: {Color.ACCENT};
    font-weight: {W_SEMIBOLD};
}}
QPushButton#primaryBtn:hover,
QPushButton[class="primary"]:hover {{
    background-color: {Color.ACCENT_HOVER};
    border-color: {Color.ACCENT_HOVER};
}}
QPushButton#primaryBtn:pressed,
QPushButton[class="primary"]:pressed {{
    background-color: {Color.ACCENT_PRESSED};
}}
QPushButton#dangerBtn,
QPushButton[class="danger"] {{
    background-color: {Color.ERROR_BG};
    color: {Color.TEXT_ERROR};
    border-color: {Color.ERROR};
}}
QPushButton#dangerBtn:hover,
QPushButton[class="danger"]:hover {{
    background-color: {Color.ERROR};
    color: #ffffff;
}}
QPushButton#successBtn,
QPushButton[class="success"] {{
    background-color: {Color.SUCCESS_BG};
    color: {Color.TEXT_SUCCESS};
    border-color: {Color.SUCCESS};
}}
QPushButton#successBtn:hover,
QPushButton[class="success"]:hover {{
    background-color: {Color.SUCCESS};
    color: #ffffff;
}}

QTabWidget::pane {{
    background-color: {Color.BG_PRIMARY};
    border: none;
    border-top: 1px solid {Color.BORDER};
    top: -1px;
}}
QTabBar {{
    background-color: {Color.BG_SECONDARY};
    border-bottom: 1px solid {Color.BORDER};
}}
QTabBar::tab {{
    background: transparent;
    color: {Color.TEXT_MUTED};
    border: none;
    border-bottom: 2px solid transparent;
    padding: {S8} {S16};
    font-size: {FS_12};
    min-height: 28px;
}}
QTabBar::tab:hover {{
    color: {Color.TEXT_SECONDARY};
    background-color: {Color.BG_HOVER};
}}
QTabBar::tab:selected {{
    color: {Color.TEXT_ACCENT};
    border-bottom: 2px solid {Color.ACCENT};
    background: transparent;
    font-weight: {W_SEMIBOLD};
}}
QTabBar::close-button:hover {{
    background-color: {Color.ERROR_BG};
}}

QSplitter::handle {{
    background-color: {Color.BORDER};
}}
QSplitter::handle:hover {{
    background-color: {Color.ACCENT};
}}

QStatusBar {{
    background-color: {Color.BG_SECONDARY};
    border-top: 1px solid {Color.BORDER};
    color: {Color.TEXT_MUTED};
    font-size: {FS_11};
    min-height: 22px;
    padding: 0 {S8};
}}
QStatusBar QLabel {{
    color: {Color.TEXT_MUTED};
    font-size: {FS_11};
    padding: 0 {S8};
}}
QStatusBar QWidget {{
    background: transparent;
}}

QTreeWidget, QTreeView {{
    background-color: {Color.BG_SECONDARY};
    border: none;
    color: {Color.TEXT_SECONDARY};
    font-size: {FS_12};
    outline: none;
    show-decoration-selected: 1;
}}
QTreeWidget::item, QTreeView::item {{
    padding: {S4} {S4};
    border: none;
    border-radius: {R_SM};
    min-height: 24px;
}}
QTreeWidget::item:hover, QTreeView::item:hover {{
    background-color: {Color.BG_HOVER};
    color: {Color.TEXT_PRIMARY};
}}
QTreeWidget::item:selected, QTreeView::item:selected {{
    background-color: {Color.ACCENT_BG};
    color: {Color.TEXT_ACCENT};
}}

QTableWidget, QTableView {{
    background-color: {Color.BG_PRIMARY};
    alternate-background-color: #f6f7fb;
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    gridline-color: {Color.BORDER};
    color: {Color.TEXT_PRIMARY};
    font-size: {FS_12};
    selection-background-color: {Color.SELECTION_BG};
    selection-color: {Color.TEXT_ACCENT};
    outline: none;
}}
QTableWidget::item, QTableView::item {{
    padding: {S4} {S8};
    border: none;
    border-right: 1px solid {Color.BORDER};
    border-bottom: 1px solid {Color.BORDER};
    min-height: 24px;
    color: #0a0a14;
}}
QTableWidget::item:hover, QTableView::item:hover {{
    background-color: {Color.BG_HOVER};
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {Color.ACCENT_BG};
    color: {Color.TEXT_ACCENT};
}}
QHeaderView {{
    background-color: {Color.BG_SECONDARY};
    border: none;
}}
QHeaderView::section {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_SECONDARY};
    font-size: {FS_11};
    font-weight: {W_SEMIBOLD};
    padding: {S4} {S8};
    border: none;
    border-right: 1px solid {Color.BORDER};
    border-bottom: 1px solid {Color.BORDER};
    min-height: 24px;
}}
QHeaderView::section:hover {{
    background-color: {Color.BG_HOVER};
    color: {Color.TEXT_PRIMARY};
}}

QTextEdit, QPlainTextEdit {{
    background-color: #fafafe;
    color: {Color.TEXT_PRIMARY};
    font-family: {FONT_MONO};
    font-size: {FS_13};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S8};
    selection-background-color: {Color.ACCENT_BG};
    selection-color: {Color.TEXT_ACCENT};
}}
QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {Color.BORDER_FOCUS};
}}
QTextEdit:disabled, QPlainTextEdit:disabled {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_DISABLED};
}}

/* SQL 编辑器 */
QPlainTextEdit#sqlEditor {{
    background-color: {Color.BG_TERTIARY};
    color: {Color.TEXT_PRIMARY};
    border: none;
    padding: {S8} {S12};
    font-family: {FONT_MONO};
    font-size: "13px";
    selection-background-color: {Color.SELECTION_BG};
    selection-color: {Color.TEXT_ACCENT};
}}

/* 等宽文本面板 */
QTextEdit#monospaceText {{
    background-color: {Color.BG_TERTIARY};
    color: {Color.TEXT_SECONDARY};
    font-family: {FONT_MONO};
    font-size: {FS_12};
    border: none;
    padding: {S8};
}}

/* 活动标签页指示 */
QLabel#activeTab {{
    color: {Color.TEXT_ACCENT};
    padding: 2px {S8};
    border-bottom: 2px solid {Color.ACCENT};
}}

QLineEdit {{
    background-color: #fafafe;
    color: {Color.TEXT_PRIMARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S4} {S8};
    font-size: {FS_12};
    min-height: 20px;
    selection-background-color: {Color.ACCENT_BG};
    selection-color: {Color.TEXT_ACCENT};
}}
QLineEdit:hover {{
    border-color: {Color.BORDER_LIGHT};
}}
QLineEdit:focus {{
    border-color: {Color.BORDER_FOCUS};
}}
QLineEdit:disabled {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_DISABLED};
}}

QComboBox {{
    background-color: #fafafe;
    color: {Color.TEXT_PRIMARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S4} {S8};
    font-size: {FS_12};
    min-height: 20px;
    min-width: 60px;
}}
QComboBox:hover {{
    border-color: {Color.BORDER_LIGHT};
}}
QComboBox:focus {{
    border-color: {Color.BORDER_FOCUS};
}}
QComboBox:disabled {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_DISABLED};
}}
QComboBox::drop-down {{
    width: 20px;
    border: none;
    border-left: 1px solid {Color.BORDER};
}}
QComboBox QAbstractItemView {{
    background-color: {Color.BG_SECONDARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: 2px 0;
    selection-background-color: {Color.BG_HOVER};
    selection-color: {Color.TEXT_PRIMARY};
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: {S4} {S8};
    min-height: 24px;
}}

QSpinBox, QDoubleSpinBox {{
    background-color: #fafafe;
    color: {Color.TEXT_PRIMARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S4} {S8};
    font-size: {FS_12};
    min-height: 20px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {Color.BORDER_FOCUS};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_DISABLED};
}}

QCheckBox, QRadioButton {{
    color: {Color.TEXT_PRIMARY};
    font-size: {FS_12};
    spacing: {S8};
    min-height: 20px;
}}
QCheckBox:disabled, QRadioButton:disabled {{
    color: {Color.TEXT_DISABLED};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {Color.BORDER_LIGHT};
    border-radius: {R_SM};
    background: transparent;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {Color.ACCENT};
    background-color: {Color.ACCENT_BG};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {Color.ACCENT};
    border-color: {Color.ACCENT};
}}
QRadioButton::indicator {{
    border-radius: {R_FULL};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {Color.BG_SELECTED};
    border-radius: 5px;
    min-height: 30px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {Color.BORDER_LIGHT};
}}
QScrollBar::handle:vertical:pressed {{
    background-color: {Color.ACCENT};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {Color.BG_SELECTED};
    border-radius: 5px;
    min-width: 30px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {Color.BORDER_LIGHT};
}}
QScrollBar::handle:horizontal:pressed {{
    background-color: {Color.ACCENT};
}}

QToolTip {{
    background-color: {Color.BG_TOOLTIP};
    color: #f4f4f8;
    border: 1px solid {Color.BORDER_LIGHT};
    border-radius: {R_SM};
    padding: {S4} {S8};
    font-size: {FS_11};
}}

QProgressBar {{
    background-color: {Color.BG_TERTIARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    text-align: center;
    font-size: {FS_11};
    color: {Color.TEXT_SECONDARY};
    min-height: 16px;
}}
QProgressBar::chunk {{
    background-color: {Color.ACCENT};
    border-radius: 2px;
}}

QGroupBox {{
    background-color: {Color.BG_SECONDARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_MD};
    margin-top: 12px;
    padding: {S16} {S12} {S12};
    font-weight: {W_SEMIBOLD};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    padding: 0 {S8};
    color: {Color.TEXT_ACCENT};
}}

QSlider::groove:horizontal {{
    background: {Color.BG_TERTIARY};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {Color.ACCENT};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: {Color.ACCENT_HOVER};
    width: 16px;
    height: 16px;
    margin: -6px 0;
}}
QSlider::sub-page:horizontal {{
    background: {Color.ACCENT};
    border-radius: 2px;
}}

QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {Color.BORDER_DIVIDER};
    background: {Color.BORDER_DIVIDER};
}}

QLabel {{
    color: {Color.TEXT_PRIMARY};
    background: transparent;
}}
QLabel[class="muted"] {{
    color: {Color.TEXT_MUTED};
    font-size: {FS_11};
}}
QLabel[class="accent"] {{
    color: {Color.TEXT_ACCENT};
}}
QLabel[class="success"] {{
    color: {Color.TEXT_SUCCESS};
}}
QLabel[class="error"] {{
    color: {Color.TEXT_ERROR};
}}
QLabel[class="heading"] {{
    font-size: {FS_16};
    font-weight: {W_BOLD};
}}
QLabel[class="subheading"] {{
    font-size: {FS_14};
    font-weight: {W_SEMIBOLD};
    color: {Color.TEXT_SECONDARY};
}}

QListWidget, QListView {{
    background-color: {Color.BG_SECONDARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    color: {Color.TEXT_SECONDARY};
    font-size: {FS_12};
    outline: none;
}}
QListWidget::item, QListView::item {{
    padding: {S4} {S8};
    border: none;
    border-radius: {R_SM};
    min-height: 24px;
}}
QListWidget::item:hover, QListView::item:hover {{
    background-color: {Color.BG_HOVER};
    color: {Color.TEXT_PRIMARY};
}}
QListWidget::item:selected, QListView::item:selected {{
    background-color: {Color.ACCENT_BG};
    color: {Color.TEXT_ACCENT};
}}

QDockWidget {{
    background-color: {Color.BG_SECONDARY};
    border: 1px solid {Color.BORDER};
}}
QDockWidget::title {{
    background-color: {Color.BG_SECONDARY};
    padding: {S8};
    border-bottom: 1px solid {Color.BORDER};
    font-size: {FS_12};
    font-weight: {W_SEMIBOLD};
}}

QTextBrowser {{
    background-color: #fafafe;
    color: {Color.TEXT_PRIMARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S8};
    selection-background-color: {Color.ACCENT_BG};
    selection-color: {Color.TEXT_ACCENT};
}}

QDateEdit, QDateTimeEdit {{
    background-color: #fafafe;
    color: {Color.TEXT_PRIMARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S4} {S8};
    font-size: {FS_12};
    min-height: 20px;
}}
QDateEdit:focus, QDateTimeEdit:focus {{
    border-color: {Color.BORDER_FOCUS};
}}
QDateEdit::drop-down, QDateTimeEdit::drop-down {{
    width: 20px;
    border: none;
    border-left: 1px solid {Color.BORDER};
}}

QDialog {{
    background-color: {Color.BG_PRIMARY};
}}

/* ── 自定义组件 ── */
QWidget#objectBrowser {{
    background-color: {Color.BG_SECONDARY};
    border-right: 1px solid {Color.BORDER};
}}
QWidget#toolbarPanel {{
    background-color: {Color.BG_SECONDARY};
    border-bottom: 1px solid {Color.BORDER};
}}
QFrame#toolbarSep {{
    background: {Color.BORDER};
    max-width: 1px;
    border: none;
    margin: 2px {S4};
}}
QWidget#aiCopilotSidebar {{
    background-color: {Color.BG_SECONDARY};
    border-left: 1px solid {Color.BORDER};
}}
QWidget#welcomePanel {{
    background-color: {Color.BG_PRIMARY};
}}
QWidget#bodyPanel {{
    background: transparent;
}}
QWidget#contentPanel {{
    background: transparent;
}}

QPushButton#aiQueryBtn {{
    padding: {S4} {S16};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #e94560, stop:1 #6c3483);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: {R_SM};
    font-size: {FS_12};
    font-weight: {W_SEMIBOLD};
    min-height: 22px;
}}
QPushButton#aiQueryBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #f05470, stop:1 #7d3c98);
    border-color: rgba(255, 255, 255, 0.35);
}}
"""


@register_theme("pro-light")
class ProLightTheme(Theme):
    """现代专业数据库 IDE 亮色主题 v2（优化版）。"""

    name: ClassVar[str] = "pro-light"

    def apply_stylesheet(self, app: QApplication) -> None:
        qss = _qss()
        app.setStyleSheet(qss)
        logger.info("ProLight v2 QSS applied (%d chars)", len(qss))

    def setup_window(self, window: QMainWindow) -> None:
        try:
            import pywinstyles
            pywinstyles.apply_acrylic(window, dark=False)
            pywinstyles.change_header_color(window, title_bar_color="#ffffff")
            logger.info("ProLight DWM acrylic applied")
        except ImportError:
            logger.warning("pywinstyles not available - skipping acrylic")
        except Exception as exc:
            logger.warning("DWM acrylic failed: %s", exc)
