"""生成 P0 启动页与主窗口外壳截图；只写入 outputs/ui_p0。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from desktop import theme
from desktop.ui.main_window import MainWindow


def main() -> int:
    out = ROOT / "outputs" / "ui_p0"
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(theme.QSS)

    os.environ.pop("LIVE_CLIPPER_SKIP_REVEAL", None)
    window = MainWindow()
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    window.brand_reveal.skip_to_gate()
    app.processEvents()
    window.brand_reveal.grabFramebuffer().save(
        str(out / "01_brand_reveal.png"))

    window.brand_reveal.hide()
    window._on_brand_entered()
    app.processEvents()
    window.grab().save(str(out / "02_workspace_shell.png"))

    QTimer.singleShot(0, app.quit)
    app.exec()
    window.close()
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
