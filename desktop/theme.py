# ============================================================
# desktop/theme.py —— 界面样式表（Qt Style Sheet）
#
# P0 黑白品牌视觉系统：
#   - 深黑空间 + 低透明边界，避免传统 Windows 工具感
#   - 卡片只用材质层级，不用大面积渐变或高饱和色
#   - 不显示 S/A/B/C/D 字母（D-044），只显示 config.GRADE_UI 的模糊档位
# ============================================================

# 主色
ACCENT = "#f5f5f7"
SIDEBAR_BG = "#08090b"
SIDEBAR_BG_HOVER = "#14161a"
SIDEBAR_BG_SEL = "#1b1e23"
CONTENT_BG = "#050506"
CARD_BG = "#111317"
CARD_BORDER = "#292c32"
TEXT_MAIN = "#f5f5f7"
TEXT_SUB = "#a6a8ad"
OK_COLOR = "#8fb7a2"
WARN_COLOR = "#c7ad82"
ERR_COLOR = "#c88b8b"

# 等级色条（内部 grade；展示上不出现字母）
GRADE_COLORS = {
    "S": "#f5f5f7",
    "A": "#d8d9dc",
    "B": "#aeb1b7",
    "C": "#7b7f87",
    "D": "#555961",
}


def grade_color(grade: str) -> str:
    return GRADE_COLORS.get(str(grade or "").upper(), "#696c73")


QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
    color: {TEXT_MAIN};
}}

QMainWindow, QDialog, #ContentArea {{
    background: {CONTENT_BG};
}}

QMainWindow, #WindowRoot {{
    background: transparent;
}}
#WindowSurface {{
    background: #08090b;
    border: 1px solid rgba(255, 255, 255, 24);
    border-radius: 17px;
}}
#ShellBody {{ background: #08090b; }}

/* ---------- 自定义窗口栏 ---------- */
#WindowChrome {{
    background: #08090b;
    border-bottom: 1px solid rgba(255, 255, 255, 18);
}}
#ChromeProduct {{
    color: #f5f5f7;
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 1px;
}}
#WindowMinimize, #WindowMaximize, #WindowClose {{
    color: #a6a8ad;
    background: transparent;
    border: none;
    border-radius: 9px;
    font-family: "Segoe UI Symbol";
    font-size: 16px;
    padding: 0;
}}
#WindowMinimize:hover, #WindowMaximize:hover {{
    color: #f5f5f7;
    background: rgba(255, 255, 255, 13);
}}
#WindowClose:hover {{
    color: #f5f5f7;
    background: rgba(200, 139, 139, 52);
}}

/* ---------- P0 外壳 ---------- */
#InspectorPanel {{
    background: #0b0c0e;
    border-left: 1px solid rgba(255, 255, 255, 17);
}}
#InspectorEyebrow {{
    color: #696c73;
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 9px;
    letter-spacing: 2px;
}}
#InspectorTitle {{ color: #f5f5f7; font-size: 17px; font-weight: 600; }}
#InspectorCopy {{ color: #81848b; font-size: 12px; line-height: 1.5; }}
#InspectorRule {{ background: rgba(255, 255, 255, 18); }}
#InspectorQuiet {{ color: #50535a; font-size: 9px; letter-spacing: 1px; }}
#StatusStrip {{
    background: #08090b;
    border-top: 1px solid rgba(255, 255, 255, 15);
}}
#StatusDot {{ color: #8fb7a2; font-size: 10px; }}
#StatusMessage {{ color: #898c92; font-size: 10px; }}
#StatusMode {{ color: #50535a; font-size: 9px; letter-spacing: 1px; }}
#DeveloperCredit {{
    color: #4b4e55;
    font-family: "Segoe UI Variable Text", "Microsoft YaHei UI";
    font-size: 9px;
    letter-spacing: 0.7px;
}}

/* ---------- P1 System Initialization ---------- */
#SystemInitializationPage {{
    background: #050506;
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 17px;
}}
#InitializationCardHost {{ background: transparent; }}
#InitializationBrand {{
    color: #5f6269;
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 2.4px;
}}
#InitializationEyebrow {{
    color: #777a82;
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 3px;
}}
#InitializationTitle {{
    color: #f5f5f7;
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 30px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
#InitializationSubtitle {{
    color: #8d9097;
    font-family: "Segoe UI Variable Text", "Microsoft YaHei UI";
    font-size: 12px;
    letter-spacing: 0.6px;
}}
#InitializationCard {{
    background: #0b0c0e;
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 14px;
}}
#InitializationCard[state="ok"] {{
    border-color: rgba(143, 183, 162, 62);
}}
#InitializationCard[state="warn"] {{
    border-color: rgba(199, 173, 130, 72);
}}
#InitializationCard[state="attention"],
#InitializationCard[state="blocked"] {{
    border-color: rgba(200, 139, 139, 76);
}}
#InitializationIndicator {{
    color: #7d8087;
    font-size: 9px;
}}
#InitializationIndicator[state="ok"] {{ color: #8fb7a2; }}
#InitializationIndicator[state="warn"] {{ color: #c7ad82; }}
#InitializationIndicator[state="attention"],
#InitializationIndicator[state="blocked"] {{ color: #c88b8b; }}
#InitializationCardTitle {{
    color: #d9dade;
    font-family: "Segoe UI Variable Text", "Microsoft YaHei UI";
    font-size: 12px;
    font-weight: 600;
}}
#InitializationCardStatus {{
    color: #f5f5f7;
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 17px;
    font-weight: 600;
}}
#InitializationCardSummary {{
    color: #74777e;
    font-family: "Segoe UI Variable Text", "Microsoft YaHei UI";
    font-size: 10px;
}}
#InitializationFooterNote {{
    color: #686b72;
    font-size: 10px;
}}
#InitializationContinue {{
    color: #090a0c;
    background: #f5f5f7;
    border: none;
    border-radius: 12px;
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 12px;
    font-weight: 600;
    padding: 0 24px;
}}
#InitializationContinue:hover {{ background: #ffffff; }}
#InitializationContinue:pressed {{ background: #d9dadd; }}
#InitializationContinue:disabled {{
    color: #6b6e75;
    background: #17191d;
    border: 1px solid #292c32;
}}

/* ---------- P1 Welcome Setup ---------- */
#WelcomeSetupPage {{
    background: #050506;
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 17px;
}}
#SetupPages, #SetupExperiencePage {{ background: transparent; }}
#SetupHeaderBrand {{
    color: #74777e;
    font-family: "Microsoft YaHei UI";
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 2px;
}}
#SetupHeaderProduct {{
    color: #555860;
    font-family: "Segoe UI Variable Text", "Segoe UI";
    font-size: 10px;
    letter-spacing: 1.7px;
}}
#SetupStepDot {{ color: #292c32; font-size: 7px; }}
#SetupStepDot[active="true"] {{ color: #d8d9dc; }}
#SetupEyebrow {{
    color: #777a82;
    font-family: "Microsoft YaHei UI";
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 2.6px;
}}
#SetupTitle {{
    color: #f5f5f7;
    font-family: "Microsoft YaHei UI";
    font-size: 29px;
    font-weight: 600;
}}
#SetupDescription {{
    color: #8d9097;
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
}}
#SetupWelcomeProduct, #SetupFinishProduct {{
    color: #c8c9cd;
    font-family: "Segoe UI Variable Display", "Segoe UI";
    font-size: 18px;
    font-weight: 600;
    letter-spacing: 2.2px;
}}
#SetupWelcomeTitle, #SetupFinishTitle {{
    color: #f5f5f7;
    font-family: "Microsoft YaHei UI";
    font-size: 30px;
    font-weight: 600;
}}
#SetupWelcomeCopy, #SetupFinishCopy {{
    color: #8d9097;
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
}}
#SetupFinishCopy[error="true"] {{ color: #c88b8b; }}
#SetupModeChoice {{
    background: #0b0c0e;
    border: 1px solid rgba(255, 255, 255, 22);
    border-radius: 16px;
}}
#SetupModeChoice:hover {{
    background: #0e1013;
    border-color: rgba(255, 255, 255, 42);
}}
#SetupModeChoice[selected="true"] {{
    background: #111317;
    border-color: rgba(245, 245, 247, 105);
}}
#SetupModeTitle {{
    color: #f5f5f7;
    font-family: "Microsoft YaHei UI";
    font-size: 18px;
    font-weight: 600;
}}
#SetupModeMark {{ color: #7d8087; font-size: 13px; }}
#SetupModeChoice[selected="true"] #SetupModeMark {{ color: #f5f5f7; }}
#SetupModeDescription {{
    color: #85888f;
    font-family: "Microsoft YaHei UI";
    font-size: 12px;
}}
#SetupCapabilityRow {{
    background: #0b0c0e;
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 13px;
}}
#SetupCapabilityRow[state="config"] {{
    border-color: rgba(199, 173, 130, 58);
}}
#SetupCapabilityRow[state="attention"] {{
    border-color: rgba(200, 139, 139, 68);
}}
#SetupCapabilityTitle {{
    color: #e1e2e5;
    font-family: "Microsoft YaHei UI";
    font-size: 13px;
    font-weight: 600;
}}
#SetupCapabilityDescription {{
    color: #696c73;
    font-family: "Microsoft YaHei UI";
    font-size: 10px;
}}
#SetupCapabilityStatus {{
    color: #8fb7a2;
    font-family: "Microsoft YaHei UI";
    font-size: 11px;
}}
#SetupCapabilityStatus[state="config"] {{ color: #c7ad82; }}
#SetupCapabilityStatus[state="attention"] {{ color: #c88b8b; }}
#SetupAdvancedToggle, #SetupSkipButton {{
    color: #676a71;
    background: transparent;
    border: none;
    padding: 7px 3px;
    font-family: "Microsoft YaHei UI";
    font-size: 10px;
}}
#SetupAdvancedToggle:hover, #SetupSkipButton:hover {{
    color: #a6a8ad;
    background: transparent;
}}
#SetupAdvancedPanel {{
    background: #090a0c;
    border: 1px solid #24272d;
    border-radius: 10px;
}}
#SetupAdvancedCopy {{ color: #74777e; font-size: 10px; }}
#SetupQuietButton {{
    color: #a6a8ad;
    background: #111317;
    border: 1px solid #2a2d33;
    border-radius: 11px;
    padding: 9px 17px;
    font-family: "Microsoft YaHei UI";
    font-size: 11px;
}}
#SetupQuietButton:hover {{
    color: #f5f5f7;
    background: #17191d;
    border-color: #3b3f47;
}}
#SetupPrimaryButton {{
    color: #090a0c;
    background: #f5f5f7;
    border: none;
    border-radius: 12px;
    padding: 0 25px;
    font-family: "Microsoft YaHei UI";
    font-size: 12px;
    font-weight: 600;
}}
#SetupPrimaryButton:hover {{ background: #ffffff; }}
#SetupPrimaryButton:pressed {{ background: #d9dadd; }}
#SetupPrimaryButton:disabled {{
    color: #6b6e75;
    background: #17191d;
    border: 1px solid #292c32;
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
    color: #696c73;
    font-size: 11px;
    padding: 0 16px 14px 16px;
}}
#SidebarHint {{
    color: #696c73;
    font-size: 11px;
    padding: 2px 16px 8px 16px;
}}

#PrimaryButton {{
    background: {ACCENT};
    color: #090a0c;
    border: none;
    border-radius: 7px;
    padding: 10px 14px;
    font-size: 14px;
    font-weight: 600;
}}
#PrimaryButton:hover {{ background: #ffffff; }}
#PrimaryButton:pressed {{ background: #d9dadd; }}
#PrimaryButton:disabled {{ background: #303239; color: #777a82; }}

#SidebarButton {{
    background: transparent;
    color: #b9bbc0;
    border: 1px solid #292c32;
    border-radius: 6px;
    padding: 7px 10px;
    text-align: left;
}}
#SidebarButton:hover {{ background: {SIDEBAR_BG_HOVER}; }}
#SidebarButton:disabled {{ color: #555860; border-color: #1b1d21; }}

#ProjectList {{
    background: transparent;
    border: none;
    outline: none;
    padding: 4px 8px;
}}
#ProjectList::item {{
    color: #b9bbc0;
    padding: 8px 10px;
    margin: 2px 0;
    border-radius: 6px;
}}
#ProjectList::item:hover {{ background: {SIDEBAR_BG_HOVER}; }}
#ProjectList::item:selected {{ background: {SIDEBAR_BG_SEL}; color: #ffffff; border: 1px solid #2c2f35; }}

/* ---------- 顶部信息条 ---------- */
#TopBar {{
    background: #0b0c0e;
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
QScrollBar::handle:vertical {{ background: #34373e; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #4a4e57; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #34373e; border-radius: 5px; min-width: 30px; }}

/* ---------- 表单控件 ---------- */
QComboBox, QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {CARD_BG};
    color: {TEXT_MAIN};
    border: 1px solid #30333a;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
    selection-color: #ffffff;
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD_BG};
    border: 1px solid #30333a;
    selection-background-color: #2a2d33;
    selection-color: {TEXT_MAIN};
    outline: none;
}}
QPushButton {{
    background: #17191e;
    border: 1px solid #30333a;
    border-radius: 6px;
    padding: 7px 14px;
}}
QPushButton:hover {{ background: #202329; border-color: #42464f; }}
QPushButton:pressed {{ background: #111317; }}
QPushButton:disabled {{ color: #5d6067; background: #101115; border-color: #202228; }}
#AccentButton {{
    background: {ACCENT}; color: #090a0c; border: none; font-weight: 600;
}}
#AccentButton:hover {{ background: #ffffff; }}
#AccentButton:disabled {{ background: #303239; color: #777a82; }}

QProgressBar {{
    border: none;
    background: #24272d;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: {TEXT_SUB};
    font-size: 11px;
}}
QProgressBar::chunk {{ background: #d8d9dc; border-radius: 5px; }}

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
    background: #202329;
    color: #ffffff;
    border: none;
    padding: 5px 8px;
    border-radius: 4px;
}}
"""
