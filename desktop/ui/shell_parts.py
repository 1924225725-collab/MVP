"""P0 主窗口外壳中的非业务占位组件。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class InspectorPlaceholder(QWidget):
    """P0 右侧上下文检查器占位，不读取任何业务数据。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self.setFixedWidth(316)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 26, 24, 24)
        layout.setSpacing(10)

        eyebrow = QLabel("CREATIVE CONTEXT")
        eyebrow.setObjectName("InspectorEyebrow")
        heading = QLabel("创作上下文")
        heading.setObjectName("InspectorTitle")
        copy = QLabel("这里将呈现当前片段、AI 判断与导出信息。")
        copy.setObjectName("InspectorCopy")
        copy.setWordWrap(True)

        rule = QWidget()
        rule.setObjectName("InspectorRule")
        rule.setFixedHeight(1)

        quiet = QLabel("P0 · WORKSPACE SHELL")
        quiet.setObjectName("InspectorQuiet")
        quiet.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        layout.addWidget(eyebrow)
        layout.addWidget(heading)
        layout.addWidget(copy)
        layout.addSpacing(8)
        layout.addWidget(rule)
        layout.addStretch(1)
        layout.addWidget(quiet)


class StatusStrip(QWidget):
    """底部低干扰状态区。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusStrip")
        self.setFixedHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)
        layout.setSpacing(8)

        dot = QLabel("●")
        dot.setObjectName("StatusDot")
        self.message = QLabel("创作环境已就绪")
        self.message.setObjectName("StatusMessage")
        mode = QLabel("LOCAL WORKSPACE")
        mode.setObjectName("StatusMode")
        creator = QLabel("Developed by 夜雨声烦")
        creator.setObjectName("DeveloperCredit")

        layout.addWidget(dot)
        layout.addWidget(self.message)
        layout.addStretch(1)
        layout.addWidget(mode)
        layout.addSpacing(14)
        layout.addWidget(creator)

    def set_message(self, text: str):
        self.message.setText(str(text or ""))
