"""
ProDark — 现代专业数据库 IDE 深色主题（优化版 v2）。

设计理念：
  - 深色背景降低视觉疲劳，适合长时间数据库开发工作
  - 语义化颜色令牌系统 + WCAG AA 对比度合规（正文 ≥4.5:1）
  - 4px/8px 严格间距网格系统，所有 padding/margin 必须被 4 整除
  - 字体层级体系：400 Regular / 500 Medium / 600 Semibold / 700 Bold
  - 亚克力/毛玻璃效果保留，但作为点缀而非主背景

配色系统（基于 Catppuccin Mocha 调优）：
  - 背景层：#1e1e2e → #181825 → #11111b
  - 强调色：#89b4fa 蓝色系（数据库工具行业约定色）
  - 语义色：success #a6e3a1 | warning #f9e2af | error #f38ba8
  - 文本层对比度：primary 11.3:1 / secondary 7.4:1 / muted 5.1:1 ✓
"""

from __future__ import annotations

import logging
from typing import ClassVar

from PySide6.QtWidgets import QApplication, QMainWindow

from open_navicat.ui.themes import Theme, register_theme

logger = logging.getLogger("opennavicat.theme.prodark")


# ═══════════════════════════════════════════════════════════════════════════
# 颜色令牌 — 所有值经过 WCAG AA 对比度验证
# ═══════════════════════════════════════════════════════════════════════════

class Color:
    """语义化颜色令牌 — 所有组件统一引用。"""

    # ── 背景层级（从深到浅） ──
    BG_PRIMARY = "#1e1e2e"       # 主内容区
    BG_SECONDARY = "#181825"     # 侧边栏/面板头
    BG_TERTIARY = "#11111b"     # 输入框/树节点
    BG_HOVER = "#313244"        # 悬停态：比基础亮 ~60%
    BG_SELECTED = "#45475a"     # 选中态
    BG_TOOLTIP = "#313244"      # 悬浮提示
    BG_OVERLAY = "rgba(0, 0, 0, 0.55)"  # 模态遮罩

    # ── 强调色（主蓝色） ──
    ACCENT = "#89b4fa"          # 主色
    ACCENT_HOVER = "#b4d0fb"    # 悬停：更亮
    ACCENT_PRESSED = "#6a94e0"  # 按下：略暗
    ACCENT_DISABLED = "#45475a" # 禁用：低对比
    ACCENT_BG = "#1e2a4a"       # 强调背景（按钮/标签/选中行）
    SELECTION_BG = "#2b4d7a"    # SQL 编辑器选中背景 — 更饱和，明显区分于输入框背景

    # ── 语义色 ──
    SUCCESS = "#a6e3a1"
    SUCCESS_BG = "#1a3a1a"
    WARNING = "#f9e2af"
    WARNING_BG = "#3a3a1a"
    ERROR = "#f38ba8"
    ERROR_BG = "#3a1a2a"
    INFO = "#89b4fa"
    INFO_BG = "#1a2a4a"

    # ── 文本层级（WCAG AA 验证通过） ──
    TEXT_PRIMARY = "#cdd6f4"       # 11.3:1 on BG_PRIMARY  — 主文本
    TEXT_SECONDARY = "#a6adc8"     # 7.4:1 on BG_PRIMARY   — 次要文本
    TEXT_MUTED = "#8a8fa8"         # 5.1:1 on BG_PRIMARY   — 辅助信息 ← 从 #585b70 修正
    TEXT_ACCENT = "#89b4fa"        # 7.8:1 on BG_PRIMARY   — 强调文本
    TEXT_SUCCESS = "#a6e3a1"
    TEXT_WARNING = "#f9e2af"
    TEXT_ERROR = "#f38ba8"
    TEXT_DISABLED = "#686c84"      # 3.2:1 on BG_PRIMARY   — 禁用文本 ← 从 #45475a 修正
    TEXT_LINK = "#74c7ec"          # 链接色

    # ── 边框 ──
    BORDER = "#313244"             # 默认边框（装饰性 ~1.3:1，无需 AA）
    BORDER_LIGHT = "#45475a"       # 高亮边框
    BORDER_FOCUS = "#89b4fa"       # 焦点环
    BORDER_ERROR = "#f38ba8"       # 错误边框
    BORDER_DIVIDER = "#252536"     # 分割线（极淡）

    # ── 亚克力 ──
    ACRYLIC_BG = "rgba(30, 30, 46, 0.85)"
    ACRYLIC_DARK = "rgba(24, 24, 37, 0.92)"
    ACRYLIC_LIGHT = "rgba(49, 50, 68, 0.80)"


# ═══════════════════════════════════════════════════════════════════════════
# 字体系统
# ═══════════════════════════════════════════════════════════════════════════

FONT_SANS = """"Segoe UI", "Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", "Helvetica Neue", Arial, sans-serif"""
FONT_MONO = """"Cascadia Code", "JetBrains Mono", "Fira Code", "Consolas", "Courier New", monospace"""

# 字号层级（px）
FS_10  = "10px"   #  微小标签
FS_11  = "11px"   #  状态栏/辅助文字
FS_12  = "12px"   #  次要界面文字
FS_13  = "13px"   #  正文/默认字号
FS_14  = "14px"   #  强调正文
FS_16  = "16px"   #  小标题
FS_20  = "20px"   #  标题
FS_26  = "26px"   #  大标题
FS_32  = "32px"   #  展示字

# 字重
W_NORMAL = "400"    # 正文
W_MEDIUM = "500"    # 中等强调
W_SEMIBOLD = "600"  # 强强调
W_BOLD = "700"      # 标题

# ═══════════════════════════════════════════════════════════════════════════
# 间距系统（严格 4px 网格，所有值必须被 4 整除）
# ═══════════════════════════════════════════════════════════════════════════

S2  = "2px"    #  微间距
S4  = "4px"    #  最小间距单位
S8  = "8px"    #  紧凑间距
S12 = "12px"   #  常规间距
S16 = "16px"   #  宽松间距
S20 = "20px"   #  段间距
S24 = "24px"   #  区块间距
S32 = "32px"   #  大区块间距
S48 = "48px"   #  章节间距

# ═══════════════════════════════════════════════════════════════════════════
# 圆角
# ═══════════════════════════════════════════════════════════════════════════

R_SM  = "3px"
R_MD  = "6px"
R_LG  = "8px"
R_XL  = "12px"
R_FULL = "9999px"

# ═══════════════════════════════════════════════════════════════════════════
# 阴影
# ═══════════════════════════════════════════════════════════════════════════

SHADOW_SM = "0 1px 2px rgba(0,0,0,0.35)"
SHADOW_MD = "0 4px 12px rgba(0,0,0,0.45)"
SHADOW_LG = "0 8px 24px rgba(0,0,0,0.55)"

# 焦点环
FOCUS_RING = f"0 0 0 2px {Color.ACCENT_BG}, 0 0 0 3px {Color.ACCENT}"


# ═══════════════════════════════════════════════════════════════════════════
# QSS 样式表
# ═══════════════════════════════════════════════════════════════════════════

def _qss() -> str:
    """生成完整的全局 QSS 样式表。"""

    # ── 基础重置 ──
    parts = [f"""
/* ===========================================================
   QSS: OpenNavicat ProDark v2
   4px grid | WCAG AA compliant | Semantic tokens
   =========================================================== */

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
QMainWindow::separator {{
    width: {S4};
    height: {S4};
    background-color: {Color.BORDER};
}}

/* ===========================================================
   QMenuBar / QMenu
   =========================================================== */
QMenuBar {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_SECONDARY};
    font-size: {FS_12};
    font-weight: {W_NORMAL};
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
QMenu::right-arrow {{
    width: 12px;
    height: 12px;
}}

/* ===========================================================
   QToolBar / QToolButton
   =========================================================== */
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
    border-color: {Color.BORDER_LIGHT};
}}
QToolButton:checked {{
    background-color: {Color.ACCENT_BG};
    border-color: {Color.ACCENT};
    color: {Color.TEXT_ACCENT};
}}
QToolButton:disabled {{
    color: {Color.TEXT_DISABLED};
}}
QToolButton[popupMode="1"] {{
    padding-right: {S24};
}}

/* ===========================================================
   QPushButton
   =========================================================== */
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
    border-color: {Color.BORDER_LIGHT};
}}
QPushButton:disabled {{
    background-color: {Color.BG_TERTIARY};
    color: {Color.TEXT_DISABLED};
    border-color: {Color.BORDER};
}}

QPushButton#primaryBtn,
QPushButton[class="primary"] {{
    background-color: {Color.ACCENT_BG};
    color: {Color.TEXT_ACCENT};
    border: 1px solid {Color.ACCENT};
    font-weight: {W_SEMIBOLD};
}}
QPushButton#primaryBtn:hover,
QPushButton[class="primary"]:hover {{
    background-color: {Color.ACCENT_HOVER};
    color: {Color.BG_PRIMARY};
    border-color: {Color.ACCENT_HOVER};
}}
QPushButton#primaryBtn:pressed,
QPushButton[class="primary"]:pressed {{
    background-color: {Color.ACCENT_PRESSED};
    color: {Color.BG_PRIMARY};
}}
QPushButton#primaryBtn:disabled,
QPushButton[class="primary"]:disabled {{
    background-color: {Color.ACCENT_DISABLED};
    color: {Color.TEXT_DISABLED};
    border-color: {Color.ACCENT_DISABLED};
}}

QPushButton#dangerBtn,
QPushButton[class="danger"] {{
    background-color: {Color.ERROR_BG};
    color: {Color.TEXT_ERROR};
    border-color: {Color.ERROR};
    font-weight: {W_SEMIBOLD};
}}
QPushButton#dangerBtn:hover,
QPushButton[class="danger"]:hover {{
    background-color: {Color.ERROR};
    color: {Color.BG_PRIMARY};
}}
QPushButton#dangerBtn:pressed,
QPushButton[class="danger"]:pressed {{
    background-color: {Color.ERROR};
}}

QPushButton#successBtn,
QPushButton[class="success"] {{
    background-color: {Color.SUCCESS_BG};
    color: {Color.TEXT_SUCCESS};
    border-color: {Color.SUCCESS};
    font-weight: {W_SEMIBOLD};
}}
QPushButton#successBtn:hover,
QPushButton[class="success"]:hover {{
    background-color: {Color.SUCCESS};
    color: {Color.BG_PRIMARY};
}}

/* ===========================================================
   QTabWidget / QTabBar
   =========================================================== */
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
    font-weight: {W_NORMAL};
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
QTabBar::close-button {{
    image: none;
    width: 16px;
    height: 16px;
    margin-left: {S4};
    border-radius: {R_SM};
    padding: 2px;
}}
QTabBar::close-button:hover {{
    background-color: {Color.ERROR_BG};
}}
QTabBar::tear {{
    width: 2px;
    background-color: {Color.ACCENT};
}}

/* ===========================================================
   QSplitter
   =========================================================== */
QSplitter::handle {{
    background-color: {Color.BORDER};
}}
QSplitter::handle:horizontal {{
    width: 3px;
    margin: 1px 0;
}}
QSplitter::handle:vertical {{
    height: 3px;
    margin: 0 1px;
}}
QSplitter::handle:hover {{
    background-color: {Color.ACCENT};
}}

/* ===========================================================
   QStatusBar
   =========================================================== */
QStatusBar {{
    background-color: {Color.BG_SECONDARY};
    border-top: 1px solid {Color.BORDER};
    color: {Color.TEXT_MUTED};
    font-size: {FS_11};
    min-height: 22px;
    padding: 0 {S8};
}}
QStatusBar::item {{
    border: none;
}}
QStatusBar QLabel {{
    color: {Color.TEXT_MUTED};
    font-size: {FS_11};
    padding: 0 {S8};
}}
QStatusBar QWidget {{
    background: transparent;
}}

/* ===========================================================
   QTreeWidget / QTreeView（对象浏览器）
   =========================================================== */
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
    border: none;
}}
QTreeWidget::branch, QTreeView::branch {{
    background: transparent;
}}

/* ===========================================================
   QTableWidget / QTableView（数据网格）
   =========================================================== */
QTableWidget, QTableView {{
    background-color: {Color.BG_PRIMARY};
    alternate-background-color: #25253e;
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    gridline-color: {Color.BORDER_LIGHT};
    color: {Color.TEXT_PRIMARY};
    font-size: {FS_12};
    font-family: {FONT_SANS};
    selection-background-color: {Color.ACCENT_BG};
    selection-color: {Color.TEXT_ACCENT};
    outline: none;
}}
QTableWidget::item, QTableView::item {{
    padding: {S4} {S8};
    border: none;
    border-right: 1px solid {Color.BORDER};
    border-bottom: 1px solid {Color.BORDER};
    min-height: 24px;
}}
QTableWidget::item:hover, QTableView::item:hover {{
    background-color: {Color.BG_HOVER};
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {Color.ACCENT_BG};
    color: {Color.TEXT_ACCENT};
}}
QTableWidget::item:focus, QTableView::item:focus {{
    border: 1px solid {Color.BORDER_FOCUS};
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
QHeaderView::section:checked {{
    background-color: {Color.ACCENT_BG};
}}
QHeaderView::down-arrow {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 8px;
    height: 8px;
    padding-right: {S4};
}}
QHeaderView::up-arrow {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 8px;
    height: 8px;
    padding-right: {S4};
}}

/* ===========================================================
   QTextEdit / QPlainTextEdit（SQL 编辑器）
   =========================================================== */
QTextEdit, QPlainTextEdit {{
    background-color: {Color.BG_TERTIARY};
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
    background-color: {Color.BG_TERTIARY};
}}
QTextEdit:disabled, QPlainTextEdit:disabled {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_DISABLED};
}}

/* SQL 编辑器 — 去掉边框，专注编码 */
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

/* 等宽文本面板（执行计划/消息） */
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

/* ===========================================================
   QLineEdit
   =========================================================== */
QLineEdit {{
    background-color: {Color.BG_TERTIARY};
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
    background-color: {Color.BG_TERTIARY};
}}
QLineEdit:disabled {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_DISABLED};
    border-color: {Color.BORDER};
}}
QLineEdit[echoMode="2"] {{
    lineedit-password-character: 9679;
}}

/* ===========================================================
   QComboBox
   =========================================================== */
QComboBox {{
    background-color: {Color.BG_TERTIARY};
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
    border-color: {Color.BORDER};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border: none;
    border-left: 1px solid {Color.BORDER};
    border-top-right-radius: {R_SM};
    border-bottom-right-radius: {R_SM};
}}
QComboBox::down-arrow {{
    width: 8px;
    height: 8px;
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
QComboBox QAbstractItemView::item:hover {{
    background-color: {Color.BG_HOVER};
}}

/* ===========================================================
   QSpinBox / QDoubleSpinBox
   =========================================================== */
QSpinBox, QDoubleSpinBox {{
    background-color: {Color.BG_TERTIARY};
    color: {Color.TEXT_PRIMARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S4} {S8};
    font-size: {FS_12};
    min-height: 20px;
}}
QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {Color.BORDER_LIGHT};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {Color.BORDER_FOCUS};
}}
QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_DISABLED};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 16px;
    border: none;
    background: transparent;
    subcontrol-origin: padding;
    border-radius: {R_SM};
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {Color.BG_HOVER};
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background-color: {Color.BG_SELECTED};
}}

/* ===========================================================
   QCheckBox / QRadioButton
   =========================================================== */
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
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {Color.BORDER};
    background-color: transparent;
}}
QRadioButton::indicator {{
    border-radius: {R_FULL};
}}
QRadioButton::indicator:checked {{
    background-color: {Color.ACCENT};
}}

/* ===========================================================
   QScrollBar（极细优雅滚动条）
   =========================================================== */
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
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
    border: none;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
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
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
    background: none;
    border: none;
}}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* ===========================================================
   QToolTip
   =========================================================== */
QToolTip {{
    background-color: {Color.BG_TOOLTIP};
    color: {Color.TEXT_PRIMARY};
    border: 1px solid {Color.BORDER_LIGHT};
    border-radius: {R_SM};
    padding: {S4} {S8};
    font-size: {FS_11};
}}

/* ===========================================================
   QProgressBar
   =========================================================== */
QProgressBar {{
    background-color: {Color.BG_TERTIARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    text-align: center;
    font-size: {FS_11};
    color: {Color.TEXT_SECONDARY};
    font-weight: {W_MEDIUM};
    min-height: 16px;
}}
QProgressBar::chunk {{
    background-color: {Color.ACCENT};
    border-radius: 2px;
}}

/* ===========================================================
   QGroupBox
   =========================================================== */
QGroupBox {{
    background-color: {Color.BG_SECONDARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_MD};
    margin-top: 12px;
    padding: {S16} {S12} {S12};
    font-size: {FS_12};
    font-weight: {W_SEMIBOLD};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 {S8};
    color: {Color.TEXT_ACCENT};
    font-weight: {W_SEMIBOLD};
}}

/* ===========================================================
   QDialog
   =========================================================== */
QDialog {{
    background-color: {Color.BG_PRIMARY};
}}

/* ===========================================================
   QFrame（分割线）
   =========================================================== */
QFrame[frameShape="4"],  /* HLine */
QFrame[frameShape="5"]   /* VLine */
{{
    color: {Color.BORDER_DIVIDER};
    background: {Color.BORDER_DIVIDER};
}}

/* ===========================================================
   QLabel
   =========================================================== */
QLabel {{
    color: {Color.TEXT_PRIMARY};
    background: transparent;
    font-size: {FS_13};
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
QLabel[class="warning"] {{
    color: {Color.TEXT_WARNING};
}}
QLabel[class="heading"] {{
    font-size: {FS_16};
    font-weight: {W_BOLD};
    color: {Color.TEXT_PRIMARY};
}}
QLabel[class="subheading"] {{
    font-size: {FS_14};
    font-weight: {W_SEMIBOLD};
    color: {Color.TEXT_SECONDARY};
}}

/* ===========================================================
   QListWidget / QListView
   =========================================================== */
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

/* ===========================================================
   QDockWidget
   =========================================================== */
QDockWidget {{
    background-color: {Color.BG_SECONDARY};
    border: 1px solid {Color.BORDER};
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background-color: {Color.BG_SECONDARY};
    padding: {S8};
    border-bottom: 1px solid {Color.BORDER};
    font-size: {FS_12};
    font-weight: {W_SEMIBOLD};
    text-align: left;
}}

/* ===========================================================
   QTextBrowser
   =========================================================== */
QTextBrowser {{
    background-color: {Color.BG_TERTIARY};
    color: {Color.TEXT_PRIMARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S8};
    selection-background-color: {Color.ACCENT_BG};
    selection-color: {Color.TEXT_ACCENT};
}}

/* ===========================================================
   QSlider
   =========================================================== */
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

/* ===========================================================
   QDateEdit / QDateTimeEdit
   =========================================================== */
QDateEdit, QDateTimeEdit {{
    background-color: {Color.BG_TERTIARY};
    color: {Color.TEXT_PRIMARY};
    border: 1px solid {Color.BORDER};
    border-radius: {R_SM};
    padding: {S4} {S8};
    font-size: {FS_12};
    min-height: 20px;
}}
QDateEdit:hover, QDateTimeEdit:hover {{
    border-color: {Color.BORDER_LIGHT};
}}
QDateEdit:focus, QDateTimeEdit:focus {{
    border-color: {Color.BORDER_FOCUS};
}}
QDateEdit:disabled, QDateTimeEdit:disabled {{
    background-color: {Color.BG_SECONDARY};
    color: {Color.TEXT_DISABLED};
}}
QDateEdit::drop-down, QDateTimeEdit::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border: none;
    border-left: 1px solid {Color.BORDER};
}}
QDateEdit::drop-down:hover, QDateTimeEdit::drop-down:hover {{
    background-color: {Color.BG_HOVER};
}}

/* ===========================================================
   自定义组件（通过 objectName 匹配）
   =========================================================== */
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
QWidget#aiCopilotHeader {{
    background-color: {Color.BG_SECONDARY};
    border-bottom: 1px solid {Color.BORDER};
    padding: {S8} {S12};
}}
QWidget#aiCopilotMessages {{
    background-color: {Color.BG_SECONDARY};
}}
QWidget#aiCopilotInput {{
    background-color: {Color.BG_SECONDARY};
    border-top: 1px solid {Color.BORDER};
    padding: {S8};
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

/* ── AI 查询按钮（渐变专业风格） ── */
QPushButton#aiQueryBtn {{
    padding: {S4} {S16};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #e94560, stop:1 #6c3483);
    color: #ffffff;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: {R_SM};
    font-size: {FS_12};
    font-weight: {W_SEMIBOLD};
    min-height: 22px;
}}
QPushButton#aiQueryBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #f05470, stop:1 #7d3c98);
    border-color: rgba(255, 255, 255, 0.3);
}}
QPushButton#aiQueryBtn:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #c0392b, stop:1 #5b2c6f);
}}
QPushButton#aiQueryBtn:disabled {{
    background: {Color.BG_TERTIARY};
    color: {Color.TEXT_DISABLED};
    border-color: {Color.BORDER};
}}
"""]

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# 主题类
# ═══════════════════════════════════════════════════════════════════════════

@register_theme("pro-dark")
class ProDarkTheme(Theme):
    """现代专业数据库 IDE 深色主题 v2（优化版）。"""

    name: ClassVar[str] = "pro-dark"

    def apply_stylesheet(self, app: QApplication) -> None:
        qss = _qss()
        app.setStyleSheet(qss)
        logger.info("ProDark v2 QSS applied (%d chars)", len(qss))

    def setup_window(self, window: QMainWindow) -> None:
        try:
            import pywinstyles
            pywinstyles.apply_acrylic(window, dark=True)
            pywinstyles.change_header_color(window, title_bar_color="#1e1e2e")
            logger.info("ProDark DWM acrylic applied")
        except ImportError:
            logger.warning("pywinstyles not available - skipping acrylic")
        except Exception as exc:
            logger.warning("DWM acrylic failed: %s", exc)
