"""P0 品牌启动层：Qt Quick 负责视觉，Widgets 主窗口保持不变。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtQuickWidgets import QQuickWidget


_HERE = Path(__file__).resolve().parent
_QML = _HERE / "qml" / "BrandRevealDKN.qml"
_LEGACY_QML = _HERE / "qml" / "BrandReveal.qml"


class BrandReveal(QQuickWidget):
    """覆盖主窗口的单次 Brand Reveal，结束后发出 ``entered``。"""

    entered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BrandReveal")
        self.setResizeMode(QQuickWidget.SizeRootObjectToView)
        # 透明清屏色允许退出阶段与已经就绪的主窗口平滑交叠。
        self.setClearColor(Qt.transparent)
        self.setSource(QUrl.fromLocalFile(str(_QML)))

        errors = self.errors()
        if errors:
            detail = "\n".join(error.toString() for error in errors)
            raise RuntimeError(f"Brand Reveal QML 加载失败：\n{detail}")

        root = self.rootObject()
        if root is None:
            raise RuntimeError("Brand Reveal QML 未创建根对象")
        root.enterRequested.connect(self._finish)

    @property
    def qml_path(self) -> Path:
        return _QML

    @property
    def legacy_qml_path(self) -> Path:
        """P0 初版保留路径；完成新动画验收前不删除。"""
        return _LEGACY_QML

    def skip_to_gate(self):
        """测试与辅助功能入口：跳到等待用户进入的最终画面。"""
        root = self.rootObject()
        if root is not None:
            root.finishIntro()

    def enter(self):
        """终态就绪后触发进入；书写阶段的输入不会改变原始节奏。"""
        root = self.rootObject()
        if root is not None:
            root.activate()

    def seek_reference(self, seconds: float):
        """固定在 HTML 基准时间点，仅用于逐帧验收。"""
        root = self.rootObject()
        if root is not None:
            root.seekReference(float(seconds))

    def _finish(self):
        self.hide()
        self.entered.emit()
