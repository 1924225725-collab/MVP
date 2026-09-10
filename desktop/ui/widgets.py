# ============================================================
# desktop/ui/widgets.py —— 共用小控件与文案工具
#
# 【一条硬规则】所有从 AI 来的文案在**展示前**都要过 soften()：
#   内部 grade 仍是 S/A/B/C/D（评分体系完全不动，D-044），
#   但界面上不能出现「B 级」「C 级」字样 —— 用户会以为不值得剪。
# ============================================================

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from desktop import theme

_GRADE_LETTER_RE = re.compile(r"[SABCD]\s*级(?:别)?")
_TIER_LETTER_RE = re.compile(r"\b[SABCD]\s*(?:档|类)\b")

try:
    import config
    GRADE_UI = dict(config.GRADE_UI)
    TIER_LABEL = dict(config.RECOMMEND_TIER_LABEL)
except Exception:
    GRADE_UI = {"S": "🌟 高光内容", "A": "🌟 高光内容", "B": "✨ 有看点",
                "C": "✨ 有看点", "D": ""}
    TIER_LABEL = {"S": "🚀 重点推荐", "A": "⭐ 推荐", "B_fill": "👌 值得一看",
                  "C_fallback": "📎 备选参考"}


# ---------------- 文案 ----------------

def soften(text):
    """抹掉文案里的等级字母（只改展示，不改数据）。"""
    if not text or not isinstance(text, str):
        return text or ""
    out = _GRADE_LETTER_RE.sub("", text)
    out = _TIER_LETTER_RE.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def grade_badge(grade: str) -> str:
    return GRADE_UI.get(str(grade or "").upper(), "")


def tier_badge(tier: str) -> str:
    return TIER_LABEL.get(str(tier or ""), "")


# ---------------- 基础控件 ----------------

def muted(text="", size=None, wrap=False) -> QLabel:
    lb = QLabel(str(text))
    lb.setObjectName("Muted")
    css = "color:%s;" % theme.TEXT_SUB
    if size:
        css += "font-size:%dpx;" % size
    lb.setStyleSheet(css)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def strong(text="", size=None, wrap=True) -> QLabel:
    lb = QLabel(str(text))
    css = "font-weight:600;"
    if size:
        css += "font-size:%dpx;" % size
    lb.setStyleSheet(css)
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def selectable(text="", mono=False, wrap=True) -> QLabel:
    lb = QLabel(str(text))
    if mono:
        lb.setObjectName("Monospace")
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def soften_label(text: str, wrap=True) -> QLabel:
    """会先做等级字母清洗的正文标签（AI 文案一律用它）。"""
    lb = QLabel(soften(text))
    lb.setWordWrap(wrap)
    lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def chip(text: str, fg: str = "#ffffff", bg: str = theme.ACCENT) -> QLabel:
    lb = QLabel(str(text))
    lb.setStyleSheet(
        f"background:{bg}; color:{fg}; border-radius:9px;"
        f"padding:2px 9px; font-size:11px; font-weight:600;"
    )
    lb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lb


def tagged_chip(text: str, color: str) -> QLabel:
    """浅底深字的标签（用于档位、类型）。"""
    lb = QLabel(str(text))
    lb.setStyleSheet(
        f"background:{color}22; color:{color}; border:1px solid {color}55;"
        f"border-radius:9px; padding:2px 9px; font-size:11px; font-weight:600;"
    )
    lb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lb


def hline() -> QFrame:
    ln = QFrame()
    ln.setFrameShape(QFrame.HLine)
    ln.setStyleSheet(f"color:{theme.CARD_BORDER}; background:{theme.CARD_BORDER}; max-height:1px;")
    return ln


def card(accent: str = None) -> tuple:
    """一张卡片：返回 (容器, 内容布局)。

    accent 给了就在左侧画一条色条（用于等级可视化，不写字母）。
    """
    outer = QFrame()
    outer.setObjectName("Card")
    row = QHBoxLayout(outer)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    if accent:
        bar = QFrame()
        bar.setFixedWidth(5)
        bar.setStyleSheet(f"background:{accent}; border-top-left-radius:10px;"
                          f"border-bottom-left-radius:10px;")
        row.addWidget(bar)
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(6)
    row.addWidget(body, 1)
    return outer, lay


class Collapsible(QWidget):
    """一个可折叠区块（Chapter 用它，默认折叠）。"""

    def __init__(self, header_widget: QWidget, body_widget: QWidget,
                 expanded: bool = False, parent=None):
        super().__init__(parent)
        self._btn = QToolButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(expanded)
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._btn.setStyleSheet("QToolButton{border:none;background:transparent;}")
        self._btn.toggled.connect(self._toggle)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)
        hl.addWidget(self._btn)
        hl.addWidget(header_widget, 1)

        self._body = body_widget
        self._body.setVisible(expanded)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(head)
        lay.addWidget(self._body)

    def _toggle(self, on: bool):
        self._btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self._body.setVisible(on)


def section_title(icon_text: str) -> QLabel:
    lb = QLabel(icon_text)
    lb.setObjectName("SectionTitle")
    return lb
