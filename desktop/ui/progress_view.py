# ============================================================
# desktop/ui/progress_view.py —— 顶栏里的处理进度区（V0.5.2）
#
# 【要解决的问题】
#   一场 51 分钟直播，本地识别要跑十几分钟。以前这里只有一个转圈的不定
#   进度条 + 一句"语音识别"，用户完全无法判断是在跑还是卡死了。
#
# 【显示什么】
#   第 1 行：六个阶段的路线图（走完的变绿、当前的高亮、没到的灰着）
#   第 2 行：正在做什么（左） + 真实百分比（右）
#   第 3 行：进度条（有真实百分比就是实心条，没有就是"进行中"的滚动条）
#   第 4 行：细节（"23:10 / 51:00　已识别 312 句"）
#
# 【一条原则】没有真实百分比时，进度条就走"不确定"模式，
#   绝不用定时器编一个假百分比糊弄用户。
# ============================================================

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget,
)

import stages
from desktop import theme

_DONE_COLOR = theme.OK_COLOR
_TODO_COLOR = "#aab4c2"
_RUN_COLOR = theme.ACCENT


class ProgressView(QWidget):
    """处理进度面板（默认隐藏，任务开始时出现）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stage_labels = {}
        self._current_stage = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 4)
        root.setSpacing(4)

        # ---- 第 1 行：阶段路线图 ----
        roadmap = QHBoxLayout()
        roadmap.setSpacing(6)
        for i, key in enumerate(stages.STAGE_ORDER):
            if i:
                sep = QLabel("·")
                sep.setStyleSheet(f"color:{_TODO_COLOR}; font-size:11px;")
                roadmap.addWidget(sep)
            lb = QLabel(stages.STAGE_TITLES[key])
            lb.setStyleSheet(f"color:{_TODO_COLOR}; font-size:11px;")
            self._stage_labels[key] = lb
            roadmap.addWidget(lb)
        roadmap.addStretch(1)
        root.addLayout(roadmap)

        # ---- 第 2 行：在做什么 + 百分比 ----
        line2 = QHBoxLayout()
        line2.setSpacing(8)
        self.title = QLabel("")
        self.title.setStyleSheet("font-size:13px; font-weight:600;")
        line2.addWidget(self.title)
        line2.addStretch(1)
        self.percent = QLabel("")
        self.percent.setStyleSheet(
            f"font-size:14px; font-weight:700; color:{_RUN_COLOR};")
        line2.addWidget(self.percent)
        root.addLayout(line2)

        # ---- 第 3 行：进度条 ----
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(9)
        self.bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        root.addWidget(self.bar)

        # ---- 第 4 行：细节 ----
        self.detail = QLabel("")
        self.detail.setStyleSheet(f"color:{theme.TEXT_SUB}; font-size:11px;")
        root.addWidget(self.detail)

        self.setVisible(False)

    # ---------------- 对外 ----------------

    def start(self):
        """任务开始：显示并把路线图清空。"""
        self._current_stage = ""
        for key, lb in self._stage_labels.items():
            lb.setStyleSheet(f"color:{_TODO_COLOR}; font-size:11px;")
        self.title.setText("准备中…")
        self.percent.setText("")
        self.detail.setText("")
        self.bar.setRange(0, 0)          # 不确定进度：先让用户看到"它在动"
        self.setVisible(True)

    def update_event(self, ev):
        """收到一个进度事件。"""
        if not isinstance(ev, dict):
            # 兼容万一收到纯字符串的老式事件
            self.title.setText(str(ev))
            self.bar.setRange(0, 0)
            self.setVisible(True)
            return
        stage = ev.get("stage", "")
        pct = ev.get("percent")
        detail = ev.get("detail", "") or ""

        if not self.isVisible():
            self.setVisible(True)
        if stage and stage != self._current_stage:
            self._mark_stage(stage)
            self._current_stage = stage

        running = ev.get("running_text") or ev.get("title") or ""
        self.title.setText(running)
        if pct is None:
            self.percent.setText("")
            self.bar.setRange(0, 0)                     # 不确定：滚动条动画
        else:
            self.percent.setText(f"{pct:.0f}%")
            self.bar.setRange(0, 100)
            self.bar.setValue(int(pct))
        self.detail.setText(detail)

    def finish(self, text="已完成"):
        """任务成功结束：六个阶段全部点亮，进度条满。"""
        self._current_stage = ""
        for key, lb in self._stage_labels.items():
            lb.setStyleSheet(f"color:{_DONE_COLOR}; font-size:11px;")
        self.title.setText(text)
        self.percent.setText("100%")
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.detail.setText("")

    def fail(self, text="已停止"):
        """任务失败/取消：保留当前位置，不假装完成。"""
        self.title.setText(text)
        self.percent.setText("")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)

    def reset(self):
        """回到隐藏状态。"""
        self.setVisible(False)
        self._current_stage = ""
        self.title.setText("")
        self.percent.setText("")
        self.detail.setText("")

    # ---------------- 内部 ----------------

    def _mark_stage(self, stage):
        """当前阶段高亮、它之前的阶段标成已完成。"""
        idx = stages.stage_index(stage)
        for i, key in enumerate(stages.STAGE_ORDER, 1):
            lb = self._stage_labels[key]
            if i < idx:
                lb.setStyleSheet(f"color:{_DONE_COLOR}; font-size:11px;")
            elif i == idx:
                lb.setStyleSheet(
                    f"color:{_RUN_COLOR}; font-size:11px; font-weight:700;")
            else:
                lb.setStyleSheet(f"color:{_TODO_COLOR}; font-size:11px;")
