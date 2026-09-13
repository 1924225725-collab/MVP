"""P1 System Initialization 覆盖页。

页面只展示 ``desktop.services.initialization`` 的结构化结果；检测逻辑、
错误分类与能力探测均留在 services 层。
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from desktop.services.initialization import (
    InitializationItem, InitializationReport, run_initialization,
)
from desktop.workers import TaskWorker


CARD_ORDER = (
    ("ffmpeg", "FFmpeg", "正在确认媒体引擎"),
    ("python", "应用运行环境", "正在确认应用运行环境"),
    ("local_asr", "本地语音识别", "正在确认本地语音能力"),
    ("model", "本地模型", "正在确认模型资源"),
    ("api", "AI 服务", "正在确认 AI 服务状态"),
    ("video", "视频处理", "正在准备视频处理能力"),
)


class InitializationCard(QFrame):
    """单个检测卡片；永远不展示异常堆栈。"""

    STATUS_TEXT = {
        "checking": "正在确认",
        "ok": "准备完成",
        "warn": "需要设置",
        "attention": "需要注意",
        "blocked": "暂无法继续",
    }

    def __init__(self, key: str, title: str, activity: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.activity = activity
        self.setObjectName("InitializationCard")
        self.setProperty("state", "checking")
        self.setMinimumSize(250, 146)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(9)

        heading = QHBoxLayout()
        heading.setSpacing(9)
        self.indicator = QLabel("●")
        self.indicator.setObjectName("InitializationIndicator")
        self.title_label = QLabel(title)
        self.title_label.setObjectName("InitializationCardTitle")
        heading.addWidget(self.indicator)
        heading.addWidget(self.title_label)
        heading.addStretch(1)

        self.status_label = QLabel("正在确认")
        self.status_label.setObjectName("InitializationCardStatus")
        self.summary_label = QLabel(activity)
        self.summary_label.setObjectName("InitializationCardSummary")
        self.summary_label.setWordWrap(True)

        root.addLayout(heading)
        root.addStretch(1)
        root.addWidget(self.status_label)
        root.addWidget(self.summary_label)

        self._indicator_effect = QGraphicsOpacityEffect(self.indicator)
        self.indicator.setGraphicsEffect(self._indicator_effect)
        self._pulse = QPropertyAnimation(
            self._indicator_effect, b"opacity", self)
        self._pulse.setStartValue(0.28)
        self._pulse.setEndValue(1.0)
        self._pulse.setDuration(920)
        self._pulse.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse.setLoopCount(-1)
        self._pulse.start()

    @property
    def state(self) -> str:
        return str(self.property("state") or "checking")

    def reset(self):
        self._set_state("checking")
        self.status_label.setText(self.STATUS_TEXT["checking"])
        self.summary_label.setText(self.activity)
        self._indicator_effect.setOpacity(1.0)
        self._pulse.start()

    def apply_result(self, item: InitializationItem):
        if item.status == "ok":
            state = "ok"
        elif item.status == "warn":
            state = "warn"
        elif item.blocking:
            state = "blocked"
        else:
            state = "attention"
        self._pulse.stop()
        self._indicator_effect.setOpacity(1.0)
        self._set_state(state)
        self.status_label.setText(self.STATUS_TEXT[state])
        self.summary_label.setText(item.summary)
        self.setToolTip(item.fix or item.summary)

    def show_unavailable(self, blocking: bool = True):
        self._pulse.stop()
        self._indicator_effect.setOpacity(1.0)
        state = "blocked" if blocking else "attention"
        self._set_state(state)
        self.status_label.setText(self.STATUS_TEXT[state])
        self.summary_label.setText("暂时无法完成这项确认")

    def _set_state(self, state: str):
        self.setProperty("state", state)
        self.indicator.setProperty("state", state)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        indicator_style = self.indicator.style()
        indicator_style.unpolish(self.indicator)
        indicator_style.polish(self.indicator)
        self.update()


class SystemInitializationPage(QWidget):
    """首次启动初始化页面，完成后只发出下一阶段信号。"""

    continue_requested = Signal(object)

    def __init__(self, parent=None, runner=run_initialization):
        super().__init__(parent)
        self.setObjectName("SystemInitializationPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._runner = runner
        self._worker = None
        self._report = None
        self._running = False

        root = QVBoxLayout(self)
        root.setContentsMargins(70, 54, 70, 42)
        root.setSpacing(0)

        brand = QLabel("DKN  ·  AI Live Clipper")
        brand.setObjectName("InitializationBrand")
        brand.setAlignment(Qt.AlignCenter)
        eyebrow = QLabel("准备创作空间")
        eyebrow.setObjectName("InitializationEyebrow")
        eyebrow.setAlignment(Qt.AlignCenter)
        title = QLabel("系统初始化")
        title.setObjectName("InitializationTitle")
        title.setAlignment(Qt.AlignCenter)
        self.subtitle = QLabel("正在为你准备 AI 创作环境")
        self.subtitle.setObjectName("InitializationSubtitle")
        self.subtitle.setAlignment(Qt.AlignCenter)

        root.addWidget(brand)
        root.addSpacing(24)
        root.addWidget(eyebrow)
        root.addSpacing(9)
        root.addWidget(title)
        root.addSpacing(10)
        root.addWidget(self.subtitle)
        root.addSpacing(38)

        card_host = QWidget()
        card_host.setObjectName("InitializationCardHost")
        grid = QGridLayout(card_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        self.cards = {}
        for index, (key, card_title, activity) in enumerate(CARD_ORDER):
            card = InitializationCard(key, card_title, activity)
            self.cards[key] = card
            grid.addWidget(card, index // 3, index % 3)
        for column in range(3):
            grid.setColumnStretch(column, 1)
        self._content_effect = QGraphicsOpacityEffect(card_host)
        card_host.setGraphicsEffect(self._content_effect)
        root.addWidget(card_host)
        root.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(14)
        self.footer_note = QLabel("正在确认系统能力…")
        self.footer_note.setObjectName("InitializationFooterNote")
        self.continue_button = QPushButton("正在确认…")
        self.continue_button.setObjectName("InitializationContinue")
        self.continue_button.setFixedSize(190, 46)
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self._continue)
        footer.addWidget(self.footer_note)
        footer.addStretch(1)
        footer.addWidget(self.continue_button)
        root.addLayout(footer)

        self._entrance = QPropertyAnimation(
            self._content_effect, b"opacity", self)
        self._entrance.setStartValue(0.0)
        self._entrance.setEndValue(1.0)
        self._entrance.setDuration(420)
        self._entrance.setEasingCurve(QEasingCurve.OutCubic)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def report(self):
        return self._report

    def start(self, model_id: str = ""):
        if self._running:
            return
        self._report = None
        self._running = True
        for card in self.cards.values():
            card.reset()
        self.subtitle.setText("正在为你准备 AI 创作环境")
        self.footer_note.setText("正在确认系统能力…")
        self.continue_button.setText("正在确认…")
        self.continue_button.setEnabled(False)

        self.show()
        self.raise_()
        self.force_focus()
        self._content_effect.setOpacity(0.0)
        self._entrance.start()

        def job(progress=None):
            return self._runner(model_id=model_id, on_item=progress)

        worker = TaskWorker(job, self)
        worker.progressChanged.connect(self._on_item)
        worker.succeeded.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()

    def force_focus(self):
        self.setFocus(Qt.OtherFocusReason)

    def _on_item(self, item):
        card = self.cards.get(getattr(item, "key", ""))
        if card is not None:
            card.apply_result(item)

    def _on_finished(self, report):
        self._worker = None
        self._running = False
        self._report = report
        summary = report.summarize()
        if summary["blocking"]:
            self.subtitle.setText("有些能力需要你的关注")
            self.footer_note.setText(
                "请先处理暂时无法继续的项目")
            self.continue_button.setText("需要处理")
            self.continue_button.setEnabled(False)
        elif summary["warn"] or summary["fail"]:
            self.subtitle.setText("创作空间已就绪，还有少量选项可以完善")
            self.footer_note.setText(
                "你可以在接下来的体验中继续设置")
            self.continue_button.setText("继续体验")
            self.continue_button.setEnabled(True)
        else:
            self.subtitle.setText("你的 AI 创作环境已经准备好了")
            self.footer_note.setText("核心能力均可使用")
            self.continue_button.setText("继续体验")
            self.continue_button.setEnabled(True)
        self.force_focus()

    def _on_failed(self, _exc):
        self._worker = None
        self._running = False
        for card in self.cards.values():
            if card.state == "checking":
                card.show_unavailable(blocking=True)
        self.subtitle.setText("初始化过程需要你的关注")
        self.footer_note.setText("请重新启动应用后再次确认")
        self.continue_button.setText("需要处理")
        self.continue_button.setEnabled(False)

    def _continue(self):
        if self._running or self._report is None:
            return
        if self._report.summarize().get("blocking"):
            return
        self.continue_requested.emit(self._report)

    def shutdown(self, timeout_ms: int = 6000):
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(timeout_ms)
