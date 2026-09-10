# ============================================================
# desktop/ui/recommended_panel.py —— ⭐ 推荐剪辑
#
# 【铁律】这一屏每条内容都来自当前项目自己的 analysis["highlights"]。
#   没有任何"默认样例 / 固定 51 分钟"的兜底。
#
# 【展示约定】不出现 S/A/B/C/D 字母（D-044）：
#   grade 只在卡片左侧用颜色条表示，文案统一过 soften()。
# ============================================================

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

import config
from desktop import theme
from desktop.ui import widgets as W

_FEEDBACK_REASONS = list(getattr(config, "FEEDBACK_REASONS",
                                 ["太普通", "很好笑", "缺上下文", "剪辑点不对", "标题不准", "其他"]))
# 内部英文键 → 中文短名（结果里通常已经是中文标签，这里只做兜底）
_DIMS_LABEL = {
    "hook": "三秒吸引力",
    "contrast": "反差/意外",
    "persona": "人物表现力",
    "personality": "人物表现力",
    "standalone": "独立成片",
    "completeness": "事件完整度",
}


class RecommendedPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._project_id = ""
        self._analysis = None
        self._show_rejected = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        bar = QHBoxLayout()
        self.summary = W.strong("", size=14)
        self.summary.setMinimumWidth(200)
        # 占满剩余宽度（否则长句会被压成窄条来回折行）
        bar.addWidget(self.summary, 1)
        self.filter_box = QComboBox()
        self.filter_box.addItems(["只看推荐", "全部候选", "只看被拒"])
        self.filter_box.currentTextChanged.connect(lambda _=None: self._render())
        self.filter_box.setFixedWidth(120)
        bar.addWidget(W.muted("显示"))
        bar.addWidget(self.filter_box)
        root.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.inner = QWidget()
        self.host = QVBoxLayout(self.inner)
        self.host.setContentsMargins(0, 0, 6, 0)
        self.host.setSpacing(10)
        self.host.addStretch(1)
        self.scroll.setWidget(self.inner)
        root.addWidget(self.scroll, 1)

        self._empty = W.muted("")
        root.addWidget(self._empty)

    # ---------------- 对外 ----------------

    def set_project(self, project: dict):
        self._project_id = (project or {}).get("project_id", "")
        self._analysis = (project or {}).get("analysis") or None
        self._render()

    # ---------------- 渲染 ----------------

    def _clear(self):
        while self.host.count() > 1:                       # 保留末尾的 stretch
            item = self.host.takeAt(0)
            w = item.widget()
            if w:
                # setParent(None) 立刻从窗口树里摘掉（否则 findChildren 还能找到旧控件，
                # 切项目时"上一个视频的内容"会短暂/永久留在界面上）
                w.setParent(None)
                w.deleteLater()

    def _render(self):
        self._clear()
        a = self._analysis
        if not a:
            self.summary.setText("")
            self._empty.setText("还没有分析结果。先在左侧选一个项目并完成分析。")
            return
        self._empty.setText("")

        highlights = list(a.get("highlights") or [])
        rejected = list(a.get("rejected") or [])
        recs = [h for h in highlights if h.get("recommended")]
        # 旧版结果可能还没有「推荐标记」这个字段（D-041 之前）。
        # 这时候不能假装"本场没有推荐"，要如实说清楚是数据旧了。
        has_flag = any("recommended" in h for h in highlights)

        mode = self.filter_box.currentText()
        if mode == "只看推荐":
            items = recs or highlights
            if not has_flag:
                self.summary.setText(
                    f"这份结果来自旧版本（还没有「推荐标记」），下方是全部候选 {len(highlights)} 条")
            elif not recs and highlights:
                self.summary.setText(
                    f"本场没有进入推荐名单的片段（下方列出的是全部候选，共 {len(highlights)} 条）")
            else:
                self.summary.setText(f"⭐ 推荐剪辑 {len(recs)} 条")
        elif mode == "全部候选":
            items = sorted(highlights, key=lambda h: -(h.get("score") or 0))
            self.summary.setText(f"全部候选 {len(highlights)} 条")
        else:
            items = sorted(rejected, key=lambda h: -(h.get("score") or 0))
            self.summary.setText(f"被拒候选 {len(rejected)} 条（供对照，看看 AI 的判断）")

        if not items:
            self._empty.setText("这里暂时没有内容。")
            return

        for rank, h in enumerate(items, 1):
            self.host.insertWidget(self.host.count() - 1,
                                   self._card(h, rank, show_rejected=(mode == "只看被拒")))

    # ---------------- 单张卡片 ----------------

    def _card(self, h: dict, rank: int, show_rejected: bool) -> QWidget:
        grade = str(h.get("grade") or "").upper()
        box, lay = W.card(theme.grade_color(grade))

        # --- 标题行 ---
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(W.strong(f"#{rank}", size=13))
        tier = W.tier_badge(h.get("recommend_tier"))
        if tier:
            top.addWidget(W.tagged_chip(tier, theme.ACCENT))
        badge = W.grade_badge(grade)
        if badge:
            top.addWidget(W.tagged_chip(badge, theme.grade_color(grade)))
        score = h.get("score")
        if score is not None:
            top.addWidget(W.chip(f"{float(score):.1f} 分", bg="#4a5568"))
        top.addStretch(1)
        top.addWidget(W.muted(W.soften(h.get("hit_reason") or "") or "", size=11))
        lay.addLayout(top)

        # --- 标题 ---
        lay.addWidget(W.strong(W.soften(h.get("title") or "（无标题）"), size=14))

        # --- 时间 / 时长 / 类型 ---
        bits = [_time_range(h)]
        dur = h.get("recommended_duration") or h.get("duration")
        if dur:
            bits.append(f"建议剪 {_fmt_dur(dur)}")
        if h.get("highlight_type"):
            bits.append(str(h["highlight_type"]))
        if h.get("event_id"):
            bits.append(f"事件 {h['event_id']}")
        lay.addWidget(W.muted("　·　".join(bits), size=12))

        # --- 摘要 ---
        summary = W.soften(h.get("summary") or h.get("reason") or "")
        if summary:
            lay.addWidget(W.soften_label(summary))

        # --- 为什么值得剪 / 风险 ---
        why = W.soften(h.get("why_cut") or "")
        risk = W.soften(h.get("risk") or "")
        if why:
            lay.addWidget(_kv("为什么值得剪", why, theme.OK_COLOR))
        if risk:
            lay.addWidget(_kv("可能需要留意", risk, theme.WARN_COLOR))

        if show_rejected:
            rr = h.get("reject_reason") or []
            if rr:
                lay.addWidget(_kv("被拒原因", "；".join(W.soften(x) for x in rr), theme.ERR_COLOR))

        # --- 五维判决书 ---
        dims = h.get("dims") or {}
        if dims:
            lay.addWidget(_dims_block(dims))

        # --- 所属 Chapter / Story ---
        ctx = self._locate(h)
        if ctx:
            lay.addWidget(W.muted(ctx, size=11, wrap=True))

        # --- 剪辑区间 + clip_id ---
        if h.get("duration_reason"):
            lay.addWidget(W.muted(f"时长依据：{W.soften(h['duration_reason'])}", size=11, wrap=True))
        lay.addWidget(W.selectable(f"clip_id: {h.get('clip_id', '')}", mono=True, wrap=False))

        # --- 反馈 ---
        lay.addLayout(self._feedback_row(h))
        return box

    def _locate(self, h: dict) -> str:
        """从当前项目的 structure 里找出这个片段属于哪个 Chapter / Story。"""
        a = self._analysis or {}
        sid = h.get("story_id") or ""
        eid = h.get("event_id") or ""
        chapters = ((a.get("structure") or {}).get("chapters") or [])
        for ch in chapters:
            for st in (ch.get("stories") or []):
                ids = {st.get("story_id"), st.get("raw_story_id")}
                ev_ids = {e.get("event_id") for e in (st.get("events") or [])}
                if (sid and sid in ids) or (eid and eid in ev_ids):
                    return (f"所属：{ch.get('title', '')}"
                            f"　→　{st.get('title', '')}")
        return ""

    def _feedback_row(self, h: dict) -> QHBoxLayout:
        row = QHBoxLayout()
        clip_id = h.get("clip_id")
        row.addWidget(W.muted("AI 判断对吗？", size=11))
        reason = QComboBox()
        reason.addItem("（可不选原因）", "")
        for r in _FEEDBACK_REASONS:
            reason.addItem(r, r)
        reason.setFixedWidth(140)

        like = QPushButton("👍 值得剪")
        dislike = QPushButton("👎 不推荐")

        def record(choice):
            try:
                from analysis import feedback
                from analysis.feedback import save_feedback
                snap = {
                    "title": h.get("title", ""),
                    "start_time": h.get("start_time", ""),
                    "end_time": h.get("end_time", ""),
                    "score": h.get("score"),
                    "grade": h.get("grade", ""),
                    "story_id": h.get("story_id", ""),
                    "project_id": self._project_id,
                }
                save_feedback(clip_id, choice, reason=reason.currentData() or "", snapshot=snap)
                note.setText(f"已记录：{choice}"
                             f"{'（' + reason.currentData() + '）' if reason.currentData() else ''}"
                             f"　{feedback.feedback_stats()}")
            except Exception as e:
                note.setText(f"记录失败：{e}")

        like.clicked.connect(lambda: record("喜欢"))
        dislike.clicked.connect(lambda: record("不喜欢"))

        row.addWidget(like)
        row.addWidget(dislike)
        row.addWidget(reason)
        note = W.muted("", size=11)
        row.addWidget(note, 1)
        return row


# ---------------- 小工具 ----------------

def _kv(key: str, value: str, color: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    k = QLabel(key)
    k.setStyleSheet(f"color:{color}; font-size:11px; font-weight:700;")
    lay.addWidget(k)
    lay.addWidget(W.soften_label(value))
    return w


def _wrap(text: str) -> QLabel:
    return W.selectable(text)


def _dims_block(dims: dict) -> QWidget:
    """五维评分构成。

    【为什么不做键名硬编码】真实结果里的 dims 键是**中文可读标签**，
    形如 `三秒吸引力（权重30%）`（见 analysis/_entry_dims），
    而内部键是 `hook / contrast / ...`。这里两种都吃，认不出来就照原样显示，
    绝不因为键名对不上就整块不显示（之前就是这个毛病：只剩标题、没有条）。
    """
    rows = []
    for key, val in (dims or {}).items():
        if isinstance(val, dict):
            val = val.get("score")
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        label = str(key)
        weight = ""
        m = re.search(r"（权重\s*(\d+)%）", label)
        if m:
            weight = f"{m.group(1)}%"
            label = label[:m.start()].strip()
        label = _DIMS_LABEL.get(str(key), _DIMS_LABEL.get(label, label))
        rows.append((label, v, weight))

    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 4, 0, 0)
    lay.setSpacing(2)
    if not rows:
        return w
    lay.addWidget(W.muted("评分构成", size=11))
    for label, v, weight in rows:
        row = QHBoxLayout()
        txt = QLabel(label + (f"　{weight}" if weight else ""))
        txt.setFixedWidth(148)
        txt.setStyleSheet(f"color:{theme.TEXT_SUB}; font-size:11px;")
        row.addWidget(txt)
        pb = QProgressBar()
        pb.setRange(0, 100)
        pb.setValue(int(max(0, min(100, v * 10 if v <= 10 else v))))
        pb.setTextVisible(False)
        pb.setFixedHeight(8)
        row.addWidget(pb, 1)
        row.addWidget(W.muted(f"{v:g}", size=11))
        lay.addLayout(row)
    return w


def _time_range(h: dict) -> str:
    start = h.get("recommended_start") or h.get("start_time") or ""
    end = h.get("recommended_end") or h.get("end_time") or ""
    if start and end:
        return f"{start} - {end}"
    return start or "时间未知"


def _fmt_dur(sec) -> str:
    try:
        sec = float(sec)
    except (TypeError, ValueError):
        return str(sec)
    if sec >= 60:
        return f"{int(sec // 60)} 分 {int(sec % 60)} 秒"
    return f"{int(sec)} 秒"
