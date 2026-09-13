"""P1 System Initialization 页面与启动分流回归测试。"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("LIVE_CLIPPER_SKIP_REVEAL", "1")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from desktop import theme
from desktop.services.initialization import (
    InitializationItem, InitializationReport,
)
from desktop.services.setup_state import SetupStateStore
from desktop.ui.main_window import MainWindow
from desktop.ui.system_initialization import SystemInitializationPage


APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(theme.QSS)


def make_item(key: str, status: str = "ok", blocking: bool = False):
    return InitializationItem(
        key=key,
        title=key,
        activity=f"Checking {key}",
        status=status,
        summary={
            "ok": "Capability ready",
            "warn": "Optional setup needed",
            "fail": "Capability unavailable",
        }[status],
        blocking=blocking,
    )


def make_report(problem_key: str = "", status: str = "ok",
                blocking: bool = False):
    keys = ("ffmpeg", "python", "local_asr", "model", "api", "video")
    items = tuple(
        make_item(key, status if key == problem_key else "ok",
                  blocking if key == problem_key else False)
        for key in keys
    )
    return InitializationReport(items, "2026-09-13T00:00:00")


def runner_for(report, delay: float = 0.0):
    def run(model_id="", on_item=None):
        if delay:
            time.sleep(delay)
        for item in report.items:
            if on_item:
                on_item(item)
        return report
    return run


def wait_until(predicate, timeout_ms=3000):
    elapsed = 0
    while not predicate() and elapsed < timeout_ms:
        QTest.qWait(20)
        elapsed += 20
    return predicate()


class TestInitializationCards(unittest.TestCase):
    def tearDown(self):
        for widget in APP.topLevelWidgets():
            if isinstance(widget, SystemInitializationPage):
                widget.shutdown()
                widget.close()
        APP.processEvents()

    def test_nonblocking_problem_allows_continue_setup(self):
        report = make_report("api", "warn", False)
        page = SystemInitializationPage(runner=runner_for(report))
        page.resize(1180, 720)
        page.start()
        self.assertTrue(wait_until(lambda: not page.running))
        self.assertEqual(page.cards["api"].state, "warn")
        self.assertEqual(page.cards["api"].status_label.text(),
                         "需要设置")
        self.assertEqual(page.continue_button.text(), "继续体验")
        self.assertTrue(page.continue_button.isEnabled())
        page.close()

    def test_blocking_problem_disables_continue(self):
        report = make_report("ffmpeg", "fail", True)
        page = SystemInitializationPage(runner=runner_for(report))
        page.resize(1180, 720)
        page.start()
        self.assertTrue(wait_until(lambda: not page.running))
        self.assertEqual(page.cards["ffmpeg"].state, "blocked")
        self.assertEqual(page.cards["ffmpeg"].status_label.text(), "暂无法继续")
        self.assertEqual(page.continue_button.text(), "需要处理")
        self.assertFalse(page.continue_button.isEnabled())
        page.close()

    def test_nonblocking_failure_shows_attention_required(self):
        report = make_report("api", "fail", False)
        page = SystemInitializationPage(runner=runner_for(report))
        page.resize(1180, 720)
        page.start()
        self.assertTrue(wait_until(lambda: not page.running))
        self.assertEqual(page.cards["api"].state, "attention")
        self.assertEqual(page.cards["api"].status_label.text(),
                         "需要注意")
        self.assertEqual(page.continue_button.text(), "继续体验")
        self.assertTrue(page.continue_button.isEnabled())
        page.close()

    def test_detection_cannot_be_skipped_while_running(self):
        report = make_report()
        page = SystemInitializationPage(
            runner=runner_for(report, delay=0.25))
        page.resize(1180, 720)
        spy = QSignalSpy(page.continue_requested)
        page.start()
        self.assertTrue(page.running)
        self.assertFalse(page.continue_button.isEnabled())
        QTest.mouseClick(page.continue_button, Qt.LeftButton)
        self.assertEqual(spy.count(), 0)
        self.assertTrue(wait_until(lambda: not page.running))
        self.assertEqual(page.continue_button.text(), "继续体验")
        page.close()


class TestStartupRouting(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="lc_p1_route_")
        self.previous_home = os.environ.get("LIVE_CLIPPER_HOME")
        os.environ["LIVE_CLIPPER_HOME"] = self.home.name

    def tearDown(self):
        if self.previous_home is None:
            os.environ.pop("LIVE_CLIPPER_HOME", None)
        else:
            os.environ["LIVE_CLIPPER_HOME"] = self.previous_home
        self.home.cleanup()
        APP.processEvents()

    def _window(self):
        window = MainWindow()
        window.show()
        APP.processEvents()
        return window

    def test_new_user_enters_initialization(self):
        window = self._window()
        report = make_report("api", "warn", False)
        window.initialization_page._runner = runner_for(report)
        window.start_startup_flow()

        self.assertTrue(window.startup_decision.needs_setup)
        self.assertTrue(window.initialization_page.isVisible())
        self.assertTrue(wait_until(lambda: not window.initialization_page.running))
        self.assertEqual(window.initialization_page.continue_button.text(),
                         "继续体验")
        self.assertFalse((Path(self.home.name) / "setup_state.json").exists())

        QTest.mouseClick(
            window.initialization_page.continue_button, Qt.LeftButton)
        APP.processEvents()
        self.assertFalse(window.initialization_page.isVisible())
        self.assertTrue(window.welcome_setup.isVisible())
        window.close()

    def test_completed_user_skips_initialization(self):
        SetupStateStore(Path(self.home.name) / "setup_state.json").mark_completed()
        window = self._window()
        calls = []
        window.run_selfcheck = lambda **kwargs: calls.append(kwargs)
        window.start_startup_flow()
        QTest.qWait(420)

        self.assertFalse(window.startup_decision.needs_setup)
        self.assertFalse(window.initialization_page.isVisible())
        self.assertEqual(calls, [{"startup": True}])
        window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
