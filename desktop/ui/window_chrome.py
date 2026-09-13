"""P0 无边框窗口控制：保留 Windows 原生移动、缩放与窗口状态。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QWidget,
)


_ASSET_DIR = Path(__file__).resolve().parent / "assets"


class WindowChrome(QWidget):
    """自定义标题栏；空白区域支持系统拖动与双击最大化。"""

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setObjectName("WindowChrome")
        self.setFixedHeight(58)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 7, 8, 7)
        layout.setSpacing(10)

        self.logo = QLabel()
        self.logo.setObjectName("ChromeLogo")
        self.logo.setFixedSize(78, 38)
        pixmap = QPixmap(str(_ASSET_DIR / "dkn_mark.svg"))
        self.logo.setPixmap(pixmap.scaled(
            self.logo.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(self.logo)

        product = QLabel("AI Live Clipper")
        product.setObjectName("ChromeProduct")
        layout.addWidget(product)
        layout.addStretch(1)

        self.minimize_button = self._button("—", "最小化", "WindowMinimize")
        self.maximize_button = self._button("□", "最大化", "WindowMaximize")
        self.close_button = self._button("×", "关闭", "WindowClose")
        self.minimize_button.clicked.connect(host.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximized)
        self.close_button.clicked.connect(host.close)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(self.close_button)

    def _button(self, text: str, tooltip: str, name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.setToolTip(tooltip)
        button.setFixedSize(QSize(42, 36))
        button.setFocusPolicy(Qt.NoFocus)
        return button

    def toggle_maximized(self):
        if self.host.isMaximized():
            self.host.showNormal()
        else:
            self.host.showMaximized()
        self.sync_state()

    def sync_state(self):
        maximized = self.host.isMaximized()
        self.maximize_button.setText("❐" if maximized else "□")
        self.maximize_button.setToolTip("还原" if maximized else "最大化")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            handle = self.host.windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ResizeHandle(QWidget):
    """透明边缘热区，调用 Qt 的系统级窗口缩放。"""

    def __init__(self, host, edges: Qt.Edges, cursor, parent=None):
        super().__init__(parent)
        self.host = host
        self.edges = edges
        self.setCursor(cursor)
        self.setObjectName("ResizeHandle")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and not self.host.isMaximized():
            handle = self.host.windowHandle()
            if handle is not None and handle.startSystemResize(self.edges):
                event.accept()
                return
        super().mousePressEvent(event)
