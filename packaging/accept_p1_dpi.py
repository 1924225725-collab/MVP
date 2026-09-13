"""P1.4 DPI and first-run UI acceptance screenshots.

This is a release validation helper, not an application entry point.  Run it
once per scale factor because Qt reads ``QT_SCALE_FACTOR`` before creating the
application object.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, required=True)
    return parser.parse_args()


ARGS = _arguments()
SCALE = ARGS.scale
PERCENT = int(round(SCALE * 100))

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["QT_SCALE_FACTOR"] = str(SCALE)
os.environ["LIVE_CLIPPER_SKIP_REVEAL"] = "1"

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "p1_4_release" / f"dpi_{PERCENT}"
DATA = OUT / "user_data"
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True, exist_ok=True)
os.environ["LIVE_CLIPPER_HOME"] = str(DATA)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from desktop import theme
from desktop.services.initialization import InitializationItem, InitializationReport
from desktop.services.setup_state import SetupStateStore
from desktop.ui.main_window import MainWindow


def _report():
    labels = {
        "ffmpeg": ("FFmpeg", "媒体引擎准备完成", "ok"),
        "python": ("应用运行环境", "桌面运行环境准备完成", "ok"),
        "local_asr": ("本地语音识别", "本地识别能力准备完成", "ok"),
        "model": ("本地模型", "可在首次创作时继续准备", "warn"),
        "api": ("AI 服务", "云端能力可以稍后连接", "warn"),
        "video": ("视频处理", "视频读取与处理能力准备完成", "ok"),
    }
    return InitializationReport(tuple(
        InitializationItem(
            key=key,
            title=title,
            activity="正在确认",
            status=status,
            summary=summary,
            blocking=False,
        )
        for key, (title, summary, status) in labels.items()
    ), "2026-09-14T00:00:00")


REPORT = _report()


def _runner(model_id="", on_item=None):
    for item in REPORT.items:
        if on_item:
            on_item(item)
    return REPORT


def _wait_until(predicate, timeout_ms=5000):
    elapsed = 0
    while not predicate() and elapsed < timeout_ms:
        QTest.qWait(25)
        elapsed += 25
    return bool(predicate())


def _save(window, name):
    QApplication.processEvents()
    QTest.qWait(80)
    image = window.grab()
    target = OUT / name
    if not image.save(str(target)):
        raise RuntimeError(f"无法保存截图：{target}")
    return {
        "file": str(target),
        "width": image.width(),
        "height": image.height(),
        "device_pixel_ratio": image.devicePixelRatio(),
    }


def _visible_text_issues(root):
    """Find obvious clipping/overflow for single-line labels and buttons."""
    issues = []
    for widget in root.findChildren(QWidget):
        if not isinstance(widget, (QLabel, QPushButton)):
            continue
        if not widget.isVisibleTo(root):
            continue
        text = widget.text().replace("&", "").strip()
        if not text or (isinstance(widget, QLabel) and widget.wordWrap()):
            continue
        available = max(0, widget.contentsRect().width())
        required = QFontMetrics(widget.font()).horizontalAdvance(text)
        if required > available + 8:
            issues.append({
                "type": type(widget).__name__,
                "object": widget.objectName(),
                "text": text,
                "required": required,
                "available": available,
            })
    return issues


def main():
    app = QApplication.instance() or QApplication([])
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(theme.QSS)

    window = MainWindow()
    window.resize(1440, 900)
    window.initialization_page._runner = _runner
    window.run_selfcheck = lambda **_kwargs: None
    window.show()
    app.processEvents()

    # The reveal is rendered even though the normal acceptance route skips it.
    window.brand_reveal.show()
    window.brand_reveal.raise_()
    window.brand_reveal.skip_to_gate()
    QTest.qWait(180)
    screenshots = [_save(window, "01_brand_reveal.png")]
    window.brand_reveal.hide()

    window.start_startup_flow()
    if not _wait_until(lambda: not window.initialization_page.running):
        raise RuntimeError("初始化页面未在时限内完成")
    screenshots.append(_save(window, "02_initialization.png"))
    initialization_issues = _visible_text_issues(window.initialization_page)

    window.initialization_page.continue_button.click()
    QTest.qWait(280)
    setup = window.welcome_setup
    if not setup.isVisible() or setup.current_step != 0:
        raise RuntimeError("初始化完成后未进入欢迎体验")
    screenshots.append(_save(window, "03_welcome.png"))

    setup.primary_button.click()
    QTest.qWait(280)
    if setup.current_step != 1 or setup.work_mode != "local":
        raise RuntimeError("工作模式默认值或页面切换不正确")
    screenshots.append(_save(window, "04_mode.png"))
    setup.cloud_choice.chosen.emit("cloud")
    setup.go_back()
    QTest.qWait(280)
    if setup.current_step != 0 or setup.work_mode != "cloud":
        raise RuntimeError("返回上一页时工作模式状态丢失")
    setup.advance()
    setup.local_choice.chosen.emit("local")

    setup.primary_button.click()
    QTest.qWait(280)
    setup.advanced_toggle.click()
    QTest.qWait(100)
    if not setup.advanced_panel.isVisible():
        raise RuntimeError("高级选项未展开")
    screenshots.append(_save(window, "05_ai_advanced.png"))

    dialog_result = {}

    def inspect_dialog():
        dialog = app.activeModalWidget()
        dialog_result["opened"] = dialog is not None
        dialog_result["parent_is_main_window"] = (
            dialog is not None and dialog.parent() is window)
        if dialog is not None:
            dialog_result["title"] = dialog.windowTitle()
            dialog_result["screenshot"] = _save(dialog, "06_advanced_settings.png")
            dialog.reject()

    QTimer.singleShot(180, inspect_dialog)
    setup.configure_ai_requested.emit()
    QTest.qWait(180)
    dialog_result["returned_to_setup"] = setup.isVisible() and setup.current_step == 2
    dialog_result["status_after_return"] = setup.cloud_ai_row.status_label.text()
    if not all((dialog_result.get("opened"),
                dialog_result.get("parent_is_main_window"),
                dialog_result.get("returned_to_setup"))):
        raise RuntimeError(f"高级设置层级或返回逻辑异常：{dialog_result}")

    setup.primary_button.click()
    QTest.qWait(280)
    screenshots.append(_save(window, "07_workspace.png"))
    setup.primary_button.click()
    QTest.qWait(280)
    screenshots.append(_save(window, "08_finish.png"))
    setup_issues = _visible_text_issues(setup)

    setup.primary_button.click()
    QTest.qWait(180)
    state_path = DATA / "setup_state.json"
    state = SetupStateStore(state_path).load()
    if state.get("completion") != "finished" or state.get("work_mode") != "local":
        raise RuntimeError(f"首次完成状态异常：{state}")
    if setup.isVisible():
        raise RuntimeError("完成后欢迎页面仍然可见")
    screenshots.append(_save(window, "09_main_window.png"))
    main_issues = _visible_text_issues(window.window_surface)
    window.close()
    app.processEvents()

    second = MainWindow()
    second.run_selfcheck = lambda **_kwargs: None
    second.show()
    second.start_startup_flow()
    QTest.qWait(450)
    second_launch = {
        "needs_setup": second.startup_decision.needs_setup,
        "initialization_visible": second.initialization_page.isVisible(),
        "welcome_visible": second.welcome_setup.isVisible(),
    }
    if any(second_launch.values()):
        raise RuntimeError(f"二次启动错误地进入首次引导：{second_launch}")
    second.close()
    app.processEvents()

    projects = list((DATA / "projects").glob("*.json"))
    result = {
        "result": "PASS",
        "scale": SCALE,
        "percent": PERCENT,
        "screenshots": screenshots,
        "text_clipping": {
            "initialization": initialization_issues,
            "setup": setup_issues,
            "main": main_issues,
        },
        "advanced_settings": dialog_result,
        "setup_state": state,
        "second_launch": second_launch,
        "generated_projects": [str(path) for path in projects],
    }
    (OUT / "acceptance.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
