# ============================================================
# desktop/theme.py —— 界面样式表（Qt Style Sheet）
#
# 一套浅色、干净、偏「工具型」的风格：
#   - 左边栏深色、内容区浅色，视觉分区清楚
#   - 卡片圆角 + 淡描边，等级色只用在左侧色条上（不刷满）
#   - 不显示 S/A/B/C/D 字母（D-044），只显示 config.GRADE_UI 的模糊档位
# ============================================================

# 主色
ACCENT = "#3b7ddd"
SIDEBAR_BG = "#1f2733"
SIDEBAR_BG_HOVER = "#2b3646"
SIDEBAR_BG_SEL = "#31405a"
CONTENT_BG = "#f4f6f9"
CARD_BG = "#ffffff"
CARD_BORDER = "#e3e8ef"
TEXT_MAIN = "#1f2733"
TEXT_SUB = "#6b7686"
OK_COLOR = "#2f9e63"
WARN_COLOR = "#d9822b"
ERR_COLOR = "#d9534f"

# 等级色条（内部 grade；展示上不出现字母）
GRADE_COLORS = {
    "S": "#e0245e",
    "A": "#f0663f",
    "B": "#3b7ddd",
    "C": "#8a94a6",
    "D": "#c2cad6",
}


def grade_color(grade: str) -> str:
    return GRADE_COLORS.get(str(grade or "").upper(), "#c2cad6")


QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {TEXT_MAIN};
}}

QMainWindow, QDialog, #ContentArea {{
    background: {CONTENT_BG};
}}

/* ---------- 左侧边栏 ---------- */
#Sidebar {{
    background: {SIDEBAR_BG};
    border: none;
}}
#Sidebar QLabel, #Sidebar QCheckBox {{
    color: #dbe2ec;
}}
#AppTitle {{
    color: #ffffff;
    font-size: 17px;
    font-weight: 700;
    padding: 18px 16px 4px 16px;
}}
#AppSubtitle {{
    color: #8c9aae;
    font-size: 11px;
    padding: 0 16px 14px 16px;
}}
#SidebarHint {{
    color: #7d8ba0;
    font-size: 11px;
    padding: 2px 16px 8px 16px;
}}

#PrimaryButton {{
    background: {ACCENT};
    color: #ffffff;
    border: none;
    border-radius: 7px;
    padding: 10px 14px;
    font-size: 14px;
    font-weight: 600;
}}
#PrimaryButton:hover {{ background: #4d8ce6; }}
#PrimaryButton:pressed {{ background: #316cbf; }}
#PrimaryButton:disabled {{ background: #4a5a72; color: #9aa7ba; }}

#SidebarButton {{
    background: transparent;
    color: #cfd8e4;
    border: 1px solid #3a465a;
    border-radius: 6px;
    padding: 7px 10px;
    text-align: left;
}}
#SidebarButton:hover {{ background: {SIDEBAR_BG_HOVER}; }}
#SidebarButton:disabled {{ color: #63708a; border-color: #2c3646; }}

#ProjectList {{
    background: transparent;
    border: none;
    outline: none;
    padding: 4px 8px;
}}
#ProjectList::item {{
    color: #cfd8e4;
    padding: 8px 10px;
    margin: 2px 0;
    border-radius: 6px;
}}
#ProjectList::item:hover {{ background: {SIDEBAR_BG_HOVER}; }}
#ProjectList::item:selected {{ background: {SIDEBAR_BG_SEL}; color: #ffffff; }}

/* ---------- 顶部信息条 ---------- */
#TopBar {{
    background: {CARD_BG};
    border-bottom: 1px solid {CARD_BORDER};
}}
#VideoTitle {{
    font-size: 16px;
    font-weight: 700;
}}
#VideoMeta {{
    color: {TEXT_SUB};
    font-size: 12px;
}}
#StateChip {{
    border-radius: 10px;
    padding: 3px 10px;
    font-size: 11px;
}}

/* ---------- 卡片 ---------- */
#Card {{
    background: {CARD_BG};
    border: 1px solid {CARD_BORDER};
    border-radius: 10px;
}}
#CardTitle {{
    font-size: 14px;
    font-weight: 700;
}}
#CardSub {{
    color: {TEXT_SUB};
    font-size: 12px;
}}
#SectionTitle {{
    font-size: 15px;
    font-weight: 700;
    padding: 2px 0 6px 0;
}}
#Muted {{ color: {TEXT_SUB}; }}
#Monospace {{
    font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
    font-size: 12px;
}}

/* ---------- 选项卡 ---------- */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_SUB};
    padding: 9px 16px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
    font-weight: 600;
}}
QTabBar::tab:hover {{ color: {TEXT_MAIN}; }}

/* ---------- 滚动区 ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #c8d0dc; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #aab5c5; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #c8d0dc; border-radius: 5px; min-width: 30px; }}

/* ---------- 表单控件 ---------- */
QComboBox, QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {CARD_BG};
    border: 1px solid #d5dce6;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD_BG};
    border: 1px solid #d5dce6;
    selection-background-color: #e8f0fc;
    selection-color: {TEXT_MAIN};
    outline: none;
}}
QPushButton {{
    background: #eef1f6;
    border: 1px solid #d5dce6;
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: #e4e9f1; }}
QPushButton:pressed {{ background: #d9dfe9; }}
QPushButton:disabled {{ color: #a8b1bf; background: #f2f4f7; }}
#AccentButton {{
    background: {ACCENT}; color: #ffffff; border: none; font-weight: 600;
}}
#AccentButton:hover {{ background: #4d8ce6; }}
#AccentButton:disabled {{ background: #b7c8e2; color: #ffffff; }}

QProgressBar {{
    border: none;
    background: #e6eaf1;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: {TEXT_SUB};
    font-size: 11px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QGroupBox {{
    border: 1px solid {CARD_BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding: 10px;
    background: {CARD_BG};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT_SUB};
    font-weight: 600;
}}

QToolTip {{
    background: #2b3646;
    color: #ffffff;
    border: none;
    padding: 5px 8px;
    border-radius: 4px;
}}
"""
