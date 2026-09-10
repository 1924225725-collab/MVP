# ============================================================
# desktop/ui/structure_panel.py —— 🧭 直播内容结构（Video → Chapter → Story）
#
# 【数据来源铁律】一律读当前项目自己的 analysis["structure"]。
#   structure 为空时如实说"本场没生成结构"，**不拿任何固定样例兜底**。
# ============================================================

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from desktop import theme
from desktop.ui import widgets as W


class StructurePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.summary = W.strong("", size=14)
        root.addWidget(self.summary)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.inner = QWidget()
        self.host = QVBoxLayout(self.inner)
        self.host.setContentsMargins(0, 0, 6, 0)
        self.host.setSpacing(10)
        self.host.addStretch(1)
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll, 1)

        self.empty = W.muted("")
        root.addWidget(self.empty)

    # ---------------- 对外 ----------------

    def set_project(self, project: dict):
        self._render((project or {}).get("analysis") or None)

    # ---------------- 渲染 ----------------

    def _clear(self):
        while self.host.count() > 1:
            item = self.host.takeAt(0)
            w = item.widget()
            if w:
                # 必须 setParent(None)：只 deleteLater() 的话控件还在窗口树里，
                # 切项目时旧 Chapter/Story 会被 findChildren 找到（防串场检查会挂）
                w.setParent(None)
                w.deleteLater()

    def _render(self, analysis):
        self._clear()
        if not analysis:
            self.summary.setText("")
            self.empty.setText("还没有分析结果。")
            return
        structure = analysis.get("structure") or {}
        chapters = structure.get("chapters") or []
        stats = structure.get("stats") or {}
        meta = analysis.get("meta") or {}

        if not chapters:
            self.summary.setText("")
            self.empty.setText(
                "本场没有生成内容结构（AI 未产出有效 Chapter/Story，或分析未跑完）。"
                "这不影响推荐剪辑，可在「推荐剪辑」页查看结果。")
            return

        self.empty.setText("")
        best = stats.get("best_story_title") or ""
        txt = (f"共 {stats.get('chapter_count', len(chapters))} 个 Chapter"
               f"　·　{stats.get('story_count', '?')} 个 Story")
        if best:
            txt += f"　·　最精彩：{best}"
        self.summary.setText(txt)

        # 顶部：整场信息
        box, lay = W.card()
        lay.addWidget(W.strong(_video_title(meta, analysis), size=14))
        total = meta.get("duration") or "—"
        lay.addWidget(W.muted(
            f"整场时长 {total}　·　内容区块 {meta.get('chunk_count', '—')} 个"
            f"　·　候选 {len(analysis.get('highlights') or [])} 条", size=12))
        self.host.insertWidget(self.host.count() - 1, box)

        for i, ch in enumerate(chapters, 1):
            self.host.insertWidget(self.host.count() - 1, self._chapter(i, ch))

    # ---------------- Chapter ----------------

    def _chapter(self, idx: int, ch: dict) -> QWidget:
        grade = str(ch.get("grade") or "").upper()
        score = ch.get("score")

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(8)
        hl.addWidget(W.strong(f"Chapter {idx:02d}　{W.soften(ch.get('title') or '')}",
                              size=13, wrap=False))
        score_lb = W.muted(
            f"{ch.get('start_time', '')} - {ch.get('end_time', '')}", size=11)
        hl.addWidget(score_lb)
        hl.addStretch(1)
        if score is not None:
            hl.addWidget(W.chip(f"{float(score):.1f} 分", bg=theme.grade_color(grade)))
        badge = W.grade_badge(grade)
        if badge:
            hl.addWidget(W.tagged_chip(badge, theme.grade_color(grade)))
        hl.addWidget(W.muted(
            f"{ch.get('story_count', 0)} Story / {ch.get('event_count', 0)} 事件", size=11))

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(22, 4, 0, 6)
        bl.setSpacing(8)
        if ch.get("summary"):
            bl.addWidget(W.soften_label(ch["summary"]))
        if ch.get("boundary_reason"):
            bl.addWidget(W.muted(f"划分依据：{W.soften(ch['boundary_reason'])}", size=11, wrap=True))

        stories = ch.get("stories") or []
        if not stories:
            bl.addWidget(W.muted("这个 Chapter 下没有 Story。", size=11))
        for j, st in enumerate(stories, 1):
            bl.addWidget(self._story(f"{idx:02d}-{j:02d}", st))

        return W.Collapsible(head, body, expanded=False)

    # ---------------- Story ----------------

    def _story(self, tag: str, st: dict) -> QWidget:
        grade = str(st.get("grade") or "").upper()
        score = st.get("score")
        events = st.get("events") or []
        rec_count = sum(1 for e in events if e.get("recommended"))

        box, lay = W.card(theme.grade_color(grade) if score is not None else None)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(W.strong(f"Story {tag}　{W.soften(st.get('title') or '')}",
                               size=12, wrap=False))
        top.addStretch(1)
        if score is not None:
            top.addWidget(W.chip(f"{float(score):.1f} 分", bg=theme.grade_color(grade)))
        badge = W.grade_badge(grade) if score is not None else ""
        if badge:
            top.addWidget(W.tagged_chip(badge, theme.grade_color(grade)))
        if rec_count:
            top.addWidget(W.tagged_chip(f"⭐ 推荐 {rec_count}", theme.ACCENT))
        lay.addLayout(top)

        lay.addWidget(W.muted(
            f"{st.get('start_time', '')} - {st.get('end_time', '')}"
            f"　·　{st.get('event_count', len(events))} 个事件", size=11))
        if st.get("summary"):
            lay.addWidget(W.soften_label(st["summary"]))
        if st.get("reason"):
            lay.addWidget(W.muted(f"划分理由：{W.soften(st['reason'])}", size=11, wrap=True))

        for e in events:
            lay.addWidget(self._event(e))
        return box

    # ---------------- Event ----------------

    def _event(self, e: dict) -> QWidget:
        grade = str(e.get("grade") or "").upper()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 2, 0, 2)
        lay.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{theme.grade_color(grade)}; font-size:10px;")
        top.addWidget(dot)
        # 标题单独占一列并允许折行：分数/时间各自独立，别挤进标题文字里
        top.addWidget(W.strong(W.soften(e.get("title") or "（无标题）"), size=12), 1)
        score = e.get("score")
        if score is not None:
            top.addWidget(W.muted(f"{float(score):.1f} 分", size=11))
        if e.get("recommended"):
            top.addWidget(W.tagged_chip("⭐ 推荐", theme.ACCENT))
        top.addWidget(W.muted(_tr(e), size=11))
        lay.addLayout(top)

        if e.get("summary"):
            lay.addWidget(W.muted(W.soften(e["summary"]), size=11, wrap=True))
        return w


def _tr(e: dict) -> str:
    s, en = e.get("start_time", ""), e.get("end_time", "")
    return f"{s} - {en}" if s and en else ""


def _video_title(meta: dict, analysis: dict) -> str:
    return f"整场：{meta.get('live_type', '')}（{meta.get('duration', '')}）"
