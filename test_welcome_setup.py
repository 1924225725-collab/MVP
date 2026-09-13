"""P1 五步首次使用体验与状态落盘测试。"""

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
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from desktop import theme
from desktop.services.initialization import (
    InitializationItem, InitializationReport,
)
from desktop.services.setup_state import SetupStateStore
from desktop.ui.main_window import MainWindow
from desktop.ui.welcome_setup import WelcomeSetupPage


APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(theme.QSS)


def make_report(api_status="warn"):
    items = []
    for key in ("ffmpeg", "python", "local_asr", "model", "api", "video"):
        status = api_status if key == "api" else "ok"
        items.append(InitializationItem(
            key=key,
            title=key,
            activity="正在确认",
            status=status,
            summary="准备完成" if status == "ok" else "稍后配置",
            blocking=False,
        ))
    return InitializationReport(tuple(items), "2026-09-13T00:00:00")


def runner_for(report):
    def run(model_id="", on_item=None):
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


class TestSetupStateCompletion(unittest.TestCase):
    def test_completed_state_keeps_only_safe_summary(self):
        with tempfile.TemporaryDirectory(prefix="lc_setup_state_") as temp:
            path = Path(temp) / "setup_state.json"
            store = SetupStateStore(path)
            store.mark_completed("cloud", {
                "status": "attention",
                "total": 6,
                "ok": 5,
                "warn": 1,
                "fail": 0,
                "blocking": False,
                "checked_at": "2026-09-13T00:00:00",
                "api_key": "secret-value",
                "password": "never-save-this",
                "detail": "technical detail",
            })
            state = store.load()
            self.assertTrue(state["completed"])
            self.assertEqual(state["completion"], "finished")
            self.assertEqual(state["work_mode"], "cloud")
            self.assertTrue(state["completed_at"])
            self.assertEqual(set(state["last_initialization"]), {
                "status", "total", "ok", "warn", "fail", "blocking",
                "checked_at",
            })
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("secret-value", raw)
            self.assertNotIn("never-save-this", raw)

    def test_skipped_state_is_terminal(self):
        with tempfile.TemporaryDirectory(prefix="lc_setup_skip_") as temp:
            store = SetupStateStore(Path(temp) / "setup_state.json")
            store.mark_skipped("local", make_report().summarize())
            state = store.load()
            self.assertTrue(state["completed"])
            self.assertEqual(state["completion"], "skipped")
            self.assertEqual(state["work_mode"], "local")


class TestWelcomeSetupPage(unittest.TestCase):
    def tearDown(self):
        for widget in APP.topLevelWidgets():
            if isinstance(widget, WelcomeSetupPage):
                widget.close()
        APP.processEvents()

    def test_local_mode_is_selected_by_default_and_back_preserves_choice(self):
        page = WelcomeSetupPage()
        page.resize(1180, 720)
        page.start(make_report())
        page.advance()
        self.assertEqual(page.current_step, 1)
        self.assertEqual(page.work_mode, "local")
        self.assertTrue(bool(page.local_choice.property("selected")))

        page.cloud_choice.chosen.emit("cloud")
        page.advance()
        self.assertEqual(page.current_step, 2)
        page.go_back()
        self.assertEqual(page.current_step, 1)
        self.assertEqual(page.work_mode, "cloud")
        self.assertTrue(bool(page.cloud_choice.property("selected")))
        page.close()

    def test_advanced_ai_configuration_is_collapsed(self):
        page = WelcomeSetupPage()
        page.resize(1180, 720)
        page.start(make_report())
        page.advance()
        page.advance()
        self.assertEqual(page.current_step, 2)
        self.assertFalse(page.advanced_panel.isVisible())
        self.assertEqual(page.cloud_ai_row.status_label.text(), "稍后配置")
        page.advanced_toggle.click()
        self.assertTrue(page.advanced_panel.isVisible())
        page.close()


class TestWelcomeStartupFlow(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="lc_welcome_flow_")
        self.previous_home = os.environ.get("LIVE_CLIPPER_HOME")
        os.environ["LIVE_CLIPPER_HOME"] = self.home.name

    def tearDown(self):
        for widget in APP.topLevelWidgets():
            if isinstance(widget, MainWindow):
                widget.close()
        if self.previous_home is None:
            os.environ.pop("LIVE_CLIPPER_HOME", None)
        else:
            os.environ["LIVE_CLIPPER_HOME"] = self.previous_home
        self.home.cleanup()
        APP.processEvents()

    def _new_window_at_welcome(self):
        report = make_report()
        window = MainWindow()
        window.initialization_page._runner = runner_for(report)
        window.resize(1180, 720)
        window.show()
        window.start_startup_flow()
        self.assertTrue(wait_until(lambda: not window.initialization_page.running))
        window.initialization_page.continue_button.click()
        APP.processEvents()
        self.assertTrue(window.welcome_setup.isVisible())
        return window

    def test_new_user_completes_full_flow(self):
        window = self._new_window_at_welcome()
        page = window.welcome_setup
        for expected in (1, 2, 3, 4):
            page.primary_button.click()
            APP.processEvents()
            self.assertEqual(page.current_step, expected)
        page.primary_button.click()
        APP.processEvents()

        state = SetupStateStore(
            Path(self.home.name) / "setup_state.json").load()
        self.assertEqual(state["completion"], "finished")
        self.assertEqual(state["work_mode"], "local")
        self.assertEqual(state["last_initialization"]["total"], 6)
        self.assertFalse(page.isVisible())
        projects = Path(self.home.name) / "projects"
        self.assertFalse(any(projects.glob("*.json")))

    def test_skip_saves_state_and_next_launch_bypasses_setup(self):
        first = self._new_window_at_welcome()
        first.welcome_setup.skip_button.click()
        APP.processEvents()
        state = SetupStateStore(
            Path(self.home.name) / "setup_state.json").load()
        self.assertEqual(state["completion"], "skipped")
        self.assertFalse(first.welcome_setup.isVisible())
        first.close()

        second = MainWindow()
        second.show()
        second.run_selfcheck = lambda **_kwargs: None
        second.start_startup_flow()
        QTest.qWait(380)
        self.assertFalse(second.startup_decision.needs_setup)
        self.assertFalse(second.initialization_page.isVisible())
        self.assertFalse(second.welcome_setup.isVisible())
        second.close()

    def test_state_write_failure_keeps_setup_open_with_friendly_message(self):
        window = self._new_window_at_welcome()
        page = window.welcome_setup
        for _step in range(4):
            page.primary_button.click()
            APP.processEvents()

        def deny_write(*_args, **_kwargs):
            raise PermissionError("simulated read-only user directory")

        window.setup_state.mark_completed = deny_write
        page.primary_button.click()
        APP.processEvents()

        self.assertTrue(page.isVisible())
        self.assertTrue(page.primary_button.isEnabled())
        self.assertIn("无法保存", page.finish_note.text())
        self.assertFalse(
            (Path(self.home.name) / "setup_state.json").exists())
        window.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
