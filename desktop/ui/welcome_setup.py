"""AI Live Clipper 首次使用体验。

该组件只管理五步展示与用户选择，通过信号把完成、跳过和高级配置请求
交给主窗口；它不直接写状态文件，也不接触 API 密钥。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation,
    Qt, Signal,
)
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from desktop.services.initialization import InitializationItem


_ASSET_DIR = Path(__file__).resolve().parent / "assets"


class ModeChoice(QFrame):
    """可用鼠标和键盘选择的工作模式卡片。"""

    chosen = Signal(str)

    def __init__(self, mode: str, title: str, description: str, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setObjectName("SetupModeChoice")
        self.setProperty("selected", False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(156)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(12)
        top = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SetupModeTitle")
        self.mark = QLabel("○")
        self.mark.setObjectName("SetupModeMark")
        top.addWidget(self.title_label)
        top.addStretch(1)
        top.addWidget(self.mark)
        self.description_label = QLabel(description)
        self.description_label.setObjectName("SetupModeDescription")
        self.description_label.setWordWrap(True)
        root.addLayout(top)
        root.addStretch(1)
        root.addWidget(self.description_label)

        for child in (self.title_label, self.mark, self.description_label):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_selected(self, selected: bool):
        self.setProperty("selected", bool(selected))
        self.mark.setText("●" if selected else "○")
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.chosen.emit(self.mode)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.chosen.emit(self.mode)
            event.accept()
            return
        super().keyPressEvent(event)


class CapabilityRow(QFrame):
    """工作空间和 AI 能力的简洁状态行。"""

    def __init__(self, title: str, description: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("SetupCapabilityRow")
        self.setProperty("state", "ready")
        self.setMinimumHeight(76)
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("SetupCapabilityTitle")
        description_label = QLabel(description)
        description_label.setObjectName("SetupCapabilityDescription")
        description_label.setWordWrap(True)
        text.addWidget(title_label)
        if description:
            text.addWidget(description_label)
        self.status_label = QLabel("准备完成")
        self.status_label.setObjectName("SetupCapabilityStatus")
        root.addLayout(text, 1)
        root.addWidget(self.status_label)

    def set_status(self, text: str, state: str = "ready"):
        self.status_label.setText(text)
        self.setProperty("state", state)
        self.status_label.setProperty("state", state)
        for widget in (self, self.status_label):
            style = widget.style()
            style.unpolish(widget)
            style.polish(widget)
            widget.update()


class WelcomeSetupPage(QWidget):
    """五步首次使用体验；所有普通用户文案均为简体中文。"""

    completed = Signal(str, object)
    skipped = Signal(str, object)
    configure_ai_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WelcomeSetupPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.work_mode = "local"
        self._report = None
        self._items = {}
        self._transition = None
        self._advanced_visible = False

        root = QVBoxLayout(self)
        root.setContentsMargins(70, 42, 70, 38)
        root.setSpacing(0)

        header = QHBoxLayout()
        brand = QLabel("DKN  ·  夜雨声烦")
        brand.setObjectName("SetupHeaderBrand")
        product = QLabel("AI Live Clipper")
        product.setObjectName("SetupHeaderProduct")
        header.addWidget(brand)
        header.addStretch(1)
        header.addWidget(product)
        root.addLayout(header)

        self.step_dots = []
        progress = QHBoxLayout()
        progress.setSpacing(8)
        progress.addStretch(1)
        for _ in range(5):
            dot = QLabel("●")
            dot.setObjectName("SetupStepDot")
            dot.setProperty("active", False)
            progress.addWidget(dot)
            self.step_dots.append(dot)
        progress.addStretch(1)
        root.addSpacing(22)
        root.addLayout(progress)
        root.addSpacing(20)

        self.pages = QStackedWidget()
        self.pages.setObjectName("SetupPages")
        self.pages.addWidget(self._build_welcome_page())
        self.pages.addWidget(self._build_mode_page())
        self.pages.addWidget(self._build_ai_page())
        self.pages.addWidget(self._build_workspace_page())
        self.pages.addWidget(self._build_finish_page())
        root.addWidget(self.pages, 1)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        self.back_button = QPushButton("返回")
        self.back_button.setObjectName("SetupQuietButton")
        self.back_button.clicked.connect(self.go_back)
        self.skip_button = QPushButton("暂时跳过设置")
        self.skip_button.setObjectName("SetupSkipButton")
        self.skip_button.clicked.connect(self._skip)
        self.primary_button = QPushButton("开始设置")
        self.primary_button.setObjectName("SetupPrimaryButton")
        self.primary_button.setFixedHeight(46)
        self.primary_button.clicked.connect(self.advance)
        footer.addWidget(self.back_button)
        footer.addWidget(self.skip_button)
        footer.addStretch(1)
        footer.addWidget(self.primary_button)
        root.addLayout(footer)

        self._select_mode("local")
        self._set_step(0, animate=False)

    @property
    def current_step(self) -> int:
        return self.pages.currentIndex()

    def start(self, report):
        self._report = report
        self._items = {
            item.key: item for item in getattr(report, "items", ())
        }
        self._advanced_visible = False
        self.advanced_panel.hide()
        self._select_mode("local")
        self._refresh_capabilities()
        self.finish_note.setText("现在可以开始创建你的第一个 AI 视频项目。")
        self.finish_note.setProperty("error", False)
        self.primary_button.setEnabled(True)
        self.skip_button.setEnabled(True)
        self._set_step(0, animate=False)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)

    def advance(self):
        step = self.current_step
        if step < 4:
            self._set_step(step + 1)
            return
        self.primary_button.setEnabled(False)
        self.completed.emit(self.work_mode, self._summary())

    def go_back(self):
        if self.current_step > 0:
            self._set_step(self.current_step - 1, direction=-1)

    def show_save_error(self):
        self.finish_note.setText("暂时无法保存设置，请检查创作空间后重试。")
        self.finish_note.setProperty("error", True)
        style = self.finish_note.style()
        style.unpolish(self.finish_note)
        style.polish(self.finish_note)
        self.primary_button.setEnabled(True)
        self.skip_button.setEnabled(True)

    def refresh_ai_service(self, item: InitializationItem):
        self._items["api"] = item
        self._refresh_capabilities()

    def _build_page(self):
        page = QWidget()
        page.setObjectName("SetupExperiencePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        return page, layout

    def _page_heading(self, layout, eyebrow: str, title: str, copy: str):
        mark = QLabel(eyebrow)
        mark.setObjectName("SetupEyebrow")
        heading = QLabel(title)
        heading.setObjectName("SetupTitle")
        heading.setWordWrap(True)
        description = QLabel(copy)
        description.setObjectName("SetupDescription")
        description.setWordWrap(True)
        layout.addWidget(mark)
        layout.addSpacing(5)
        layout.addWidget(heading)
        layout.addWidget(description)

    def _build_welcome_page(self):
        page, layout = self._build_page()
        layout.addStretch(1)
        logo = QSvgWidget(str(_ASSET_DIR / "dkn_mark.svg"))
        logo.setObjectName("SetupDknMark")
        logo.setFixedSize(250, 98)
        line = QHBoxLayout()
        line.addStretch(1)
        line.addWidget(logo)
        line.addStretch(1)
        layout.addLayout(line)
        signature = QSvgWidget(str(_ASSET_DIR / "night_rain_signature.svg"))
        signature.setFixedSize(190, 54)
        signature_line = QHBoxLayout()
        signature_line.addStretch(1)
        signature_line.addWidget(signature)
        signature_line.addStretch(1)
        layout.addLayout(signature_line)
        name = QLabel("AI Live Clipper")
        name.setObjectName("SetupWelcomeProduct")
        name.setAlignment(Qt.AlignCenter)
        title = QLabel("欢迎使用 AI Live Clipper")
        title.setObjectName("SetupWelcomeTitle")
        title.setAlignment(Qt.AlignCenter)
        copy = QLabel("让 AI 帮你发现视频中的精彩瞬间。")
        copy.setObjectName("SetupWelcomeCopy")
        copy.setAlignment(Qt.AlignCenter)
        layout.addWidget(name)
        layout.addSpacing(12)
        layout.addWidget(title)
        layout.addWidget(copy)
        layout.addStretch(2)
        return page

    def _build_mode_page(self):
        page, layout = self._build_page()
        self._page_heading(
            layout,
            "你的创作方式",
            "选择更适合你的工作模式",
            "从本地开始，之后随时可以启用更强的 AI 能力。",
        )
        layout.addSpacing(28)
        choices = QHBoxLayout()
        choices.setSpacing(18)
        self.local_choice = ModeChoice(
            "local", "本地模式",
            "数据主要在本机处理，适合注重隐私和本地运行。")
        self.cloud_choice = ModeChoice(
            "cloud", "AI 增强模式",
            "结合云端 AI 能力，获得更强的视频理解和分析效果。")
        self.local_choice.chosen.connect(self._select_mode)
        self.cloud_choice.chosen.connect(self._select_mode)
        choices.addWidget(self.local_choice)
        choices.addWidget(self.cloud_choice)
        layout.addLayout(choices)
        layout.addStretch(1)
        return page

    def _build_ai_page(self):
        page, layout = self._build_page()
        self._page_heading(
            layout,
            "AI 创作能力",
            "了解你的 AI 创作伙伴",
            "本地能力负责理解声音与素材，云端能力可以在需要时再开启。",
        )
        layout.addSpacing(24)
        self.local_ai_row = CapabilityRow(
            "本地 AI", "语音识别与基础处理在你的设备上完成")
        self.cloud_ai_row = CapabilityRow(
            "云端 AI", "用于更深入地理解内容与发现传播价值")
        layout.addWidget(self.local_ai_row)
        layout.addWidget(self.cloud_ai_row)
        layout.addSpacing(8)
        self.advanced_toggle = QPushButton("高级选项")
        self.advanced_toggle.setObjectName("SetupAdvancedToggle")
        self.advanced_toggle.clicked.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_toggle, 0, Qt.AlignLeft)
        self.advanced_panel = QFrame()
        self.advanced_panel.setObjectName("SetupAdvancedPanel")
        advanced_layout = QHBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(16, 12, 16, 12)
        advanced_copy = QLabel(
            "云端服务可稍后在设置中连接，不影响本地模式使用。")
        advanced_copy.setObjectName("SetupAdvancedCopy")
        advanced_copy.setWordWrap(True)
        configure = QPushButton("打开设置")
        configure.setObjectName("SetupQuietButton")
        configure.clicked.connect(self.configure_ai_requested)
        advanced_layout.addWidget(advanced_copy, 1)
        advanced_layout.addWidget(configure)
        self.advanced_panel.hide()
        layout.addWidget(self.advanced_panel)
        layout.addStretch(1)
        return page

    def _build_workspace_page(self):
        page, layout = self._build_page()
        self._page_heading(
            layout,
            "创作空间",
            "你的 AI 创作空间已经准备好了",
            "从视频与声音出发，AI Live Clipper 会陪你找到值得传播的内容。",
        )
        layout.addSpacing(22)
        self.workspace_rows = {
            "video": CapabilityRow("视频处理"),
            "speech": CapabilityRow("语音识别"),
            "analysis": CapabilityRow("AI 分析"),
            "workspace": CapabilityRow("项目空间"),
        }
        first = QHBoxLayout()
        first.setSpacing(14)
        first.addWidget(self.workspace_rows["video"])
        first.addWidget(self.workspace_rows["speech"])
        second = QHBoxLayout()
        second.setSpacing(14)
        second.addWidget(self.workspace_rows["analysis"])
        second.addWidget(self.workspace_rows["workspace"])
        layout.addLayout(first)
        layout.addLayout(second)
        layout.addStretch(1)
        return page

    def _build_finish_page(self):
        page, layout = self._build_page()
        layout.addStretch(1)
        logo = QSvgWidget(str(_ASSET_DIR / "dkn_mark.svg"))
        logo.setFixedSize(210, 82)
        logo_line = QHBoxLayout()
        logo_line.addStretch(1)
        logo_line.addWidget(logo)
        logo_line.addStretch(1)
        layout.addLayout(logo_line)
        signature = QSvgWidget(str(_ASSET_DIR / "night_rain_signature.svg"))
        signature.setFixedSize(230, 66)
        signature_line = QHBoxLayout()
        signature_line.addStretch(1)
        signature_line.addWidget(signature)
        signature_line.addStretch(1)
        layout.addLayout(signature_line)
        product = QLabel("AI Live Clipper")
        product.setObjectName("SetupFinishProduct")
        product.setAlignment(Qt.AlignCenter)
        title = QLabel("一切准备就绪")
        title.setObjectName("SetupFinishTitle")
        title.setAlignment(Qt.AlignCenter)
        self.finish_note = QLabel("现在可以开始创建你的第一个 AI 视频项目。")
        self.finish_note.setObjectName("SetupFinishCopy")
        self.finish_note.setAlignment(Qt.AlignCenter)
        layout.addWidget(product)
        layout.addSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self.finish_note)
        layout.addStretch(2)
        return page

    def _select_mode(self, mode: str):
        self.work_mode = "cloud" if mode == "cloud" else "local"
        self.local_choice.set_selected(self.work_mode == "local")
        self.cloud_choice.set_selected(self.work_mode == "cloud")

    def _toggle_advanced(self):
        self._advanced_visible = not self._advanced_visible
        self.advanced_panel.setVisible(self._advanced_visible)
        self.advanced_toggle.setText(
            "收起高级选项" if self._advanced_visible else "高级选项")

    def _skip(self):
        self.primary_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.skipped.emit(self.work_mode, self._summary())

    def _summary(self) -> dict:
        if self._report is None:
            return {}
        summarize = getattr(self._report, "summarize", None)
        return dict(summarize()) if callable(summarize) else {}

    def _item_state(self, *keys: str) -> tuple[str, str]:
        items = [self._items.get(key) for key in keys]
        items = [item for item in items if item is not None]
        if not items:
            return "稍后确认", "config"
        if any(item.blocking for item in items):
            return "需要注意", "attention"
        if any(item.status == "fail" for item in items):
            return "需要注意", "attention"
        if any(item.status == "warn" for item in items):
            return "稍后配置", "config"
        return "准备完成", "ready"

    def _refresh_capabilities(self):
        self.local_ai_row.set_status(
            *self._item_state("local_asr", "model"))
        self.cloud_ai_row.set_status(*self._item_state("api"))
        self.workspace_rows["video"].set_status(
            *self._item_state("ffmpeg", "video"))
        self.workspace_rows["speech"].set_status(
            *self._item_state("local_asr", "model"))
        self.workspace_rows["analysis"].set_status(
            *self._item_state("api"))
        self.workspace_rows["workspace"].set_status(
            *self._item_state("python", "video"))

    def _set_step(self, index: int, direction: int = 1,
                  animate: bool = True):
        index = max(0, min(4, int(index)))
        self.pages.setCurrentIndex(index)
        self._update_navigation(index)
        self._update_progress(index)
        if animate:
            page = self.pages.currentWidget()
            base = page.pos()
            page.move(base + QPoint(0, 12 * direction))
            effect = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(effect)
            fade = QPropertyAnimation(effect, b"opacity", self)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setDuration(240)
            fade.setEasingCurve(QEasingCurve.OutCubic)
            slide = QPropertyAnimation(page, b"pos", self)
            slide.setStartValue(page.pos())
            slide.setEndValue(base)
            slide.setDuration(240)
            slide.setEasingCurve(QEasingCurve.OutCubic)
            group = QParallelAnimationGroup(self)
            group.addAnimation(fade)
            group.addAnimation(slide)
            group.finished.connect(lambda: page.setGraphicsEffect(None))
            self._transition = group
            group.start()
        self.setFocus(Qt.OtherFocusReason)

    def _update_navigation(self, step: int):
        self.back_button.setVisible(step > 0)
        self.skip_button.setVisible(step < 4)
        ai_action = (
            "继续" if self._item_state("api")[1] == "ready" else "稍后配置")
        labels = (
            "开始设置", "确认此模式", ai_action, "看看完成状态", "开始创作")
        self.primary_button.setText(labels[step])
        self.primary_button.setMinimumWidth(150)

    def _update_progress(self, step: int):
        for index, dot in enumerate(self.step_dots):
            dot.setProperty("active", index <= step)
            style = dot.style()
            style.unpolish(dot)
            style.polish(dot)
            dot.update()

    def _skip(self):
        self.skipped.emit(self.work_mode, self._summary())

    def _summary(self) -> dict:
        if self._report is None:
            return {}
        summarize = getattr(self._report, "summarize", None)
        return summarize() if callable(summarize) else {}

    def _status_for(self, keys, optional: bool = False):
        items = [self._items.get(key) for key in keys]
        items = [item for item in items if item is not None]
        if not items:
            return ("稍后确认" if optional else "需要注意", "optional")
        if any(item.blocking for item in items):
            return "需要注意", "attention"
        if all(item.status == "ok" for item in items):
            return "准备完成", "ready"
        return ("稍后配置" if optional else "需要注意",
                "optional" if optional else "attention")

    def _refresh_capabilities(self):
        local_text, local_state = self._status_for(
            ("local_asr", "model"), optional=True)
        cloud_text, cloud_state = self._status_for(("api",), optional=True)
        self.local_ai_row.set_status(local_text, local_state)
        self.cloud_ai_row.set_status(cloud_text, cloud_state)

        video = self._status_for(("ffmpeg", "video"))
        speech = self._status_for(("local_asr", "model"), optional=True)
        analysis = self._status_for(("api",), optional=True)
        workspace = self._status_for(("python", "video"))
        for key, value in (
            ("video", video), ("speech", speech),
            ("analysis", analysis), ("workspace", workspace),
        ):
            self.workspace_rows[key].set_status(*value)
