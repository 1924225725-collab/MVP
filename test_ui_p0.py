"""P0 品牌启动层与主窗口外壳的离线回归测试。"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LIVE_CLIPPER_SKIP_REVEAL", "1")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel

from desktop import theme
from desktop.ui.brand_reveal import BrandReveal
from desktop.ui.main_window import MainWindow


APP = QApplication.instance() or QApplication([])
ROOT = Path(__file__).resolve().parent
HTML_REFERENCE = Path(os.environ.get(
    "DKN_HTML_REFERENCE",
    ROOT / "_external" / "DKN动画.html",
))


class TestBrandAssets(unittest.TestCase):
    def test_brand_assets_are_local_and_vector(self):
        asset_dir = ROOT / "desktop" / "ui" / "assets"
        for name in ("dkn_mark.svg", "night_rain_signature.svg"):
            path = asset_dir / name
            self.assertTrue(path.is_file(), name)
            self.assertIn("<svg", path.read_text(encoding="utf-8"))

    def test_signature_has_dedicated_treatment(self):
        text = (ROOT / "desktop" / "ui" / "assets" /
                "night_rain_signature.svg").read_text(encoding="utf-8")
        self.assertIn("夜雨声烦", text)
        self.assertIn("STXingkai", text)
        self.assertIn("rotate", text)

    def test_blueprint_tokens(self):
        self.assertEqual(theme.CONTENT_BG, "#050506")
        self.assertEqual(theme.CARD_BG, "#111317")
        self.assertEqual(theme.TEXT_MAIN, "#f5f5f7")
        self.assertEqual(theme.TEXT_SUB, "#a6a8ad")


class TestBrandReveal(unittest.TestCase):
    def test_new_qml_keeps_legacy_and_original_timing(self):
        reveal = BrandReveal()
        self.assertEqual(reveal.qml_path.name, "BrandRevealDKN.qml")
        self.assertTrue(reveal.legacy_qml_path.is_file())
        qml = reveal.qml_path.read_text(encoding="utf-8")
        metadata = re.findall(
            r'name:\s*"p(\d)",\s*width:\s*([\d.]+),\s*'
            r'start:\s*([\d.]+),\s*end:\s*([\d.]+)',
            qml,
        )
        self.assertEqual(metadata, [
            ("1", "10.2", "0.039", "0.334"),
            ("2", "11.1", "0.334", "0.462"),
            ("3", "15.5", "0.462", "0.603"),
            ("4", "11.6", "0.603", "0.783"),
            ("5", "12.7", "0.783", "1.011"),
        ])
        reveal.close()

    @unittest.skipUnless(HTML_REFERENCE.is_file(), "未提供 HTML 视觉基准")
    def test_qml_paths_match_html_reference_exactly(self):
        html = HTML_REFERENCE.read_text(encoding="utf-8")
        qml = (ROOT / "desktop" / "ui" / "qml" /
               "BrandRevealDKN.qml").read_text(encoding="utf-8")

        html_paths = {}
        for match in re.finditer(
            r'<path id="p(\d)" class="hp" d="([^"]+)"'
            r' data-w="([^"]+)" data-a="([^"]+)" data-b="([^"]+)"',
            html,
        ):
            html_paths.setdefault(match.group(1), match.groups()[1:])

        qml_paths = {
            match.group(1): (
                match.group(5), match.group(2), match.group(3), match.group(4)
            )
            for match in re.finditer(
                r'name:\s*"p(\d)",\s*width:\s*([\d.]+),\s*'
                r'start:\s*([\d.]+),\s*end:\s*([\d.]+),\s*'
                r'path:\s*"([^"]+)"',
                qml,
            )
        }
        self.assertEqual(qml_paths, html_paths)

    def test_qml_loads(self):
        reveal = BrandReveal()
        reveal.resize(1280, 800)
        reveal.show()
        APP.processEvents()
        self.assertEqual(reveal.rootObject().objectName(), "BrandRevealRoot")
        self.assertTrue(reveal.qml_path.is_file())
        reveal.close()

    def test_skip_reaches_gate(self):
        reveal = BrandReveal()
        reveal.skip_to_gate()
        APP.processEvents()
        self.assertTrue(reveal.rootObject().property("introComplete"))
        self.assertEqual(
            float(reveal.rootObject().property("timelineSeconds")), 1.5)
        self.assertTrue(reveal.rootObject().property("terminalReady"))
        reveal.close()

    def test_natural_sequence_holds_then_opens_terminal_gate(self):
        reveal = BrandReveal()
        reveal.resize(960, 640)
        reveal.show()
        QTest.qWait(3050)
        root = reveal.rootObject()
        self.assertAlmostEqual(
            float(root.property("timelineSeconds")), 1.5, places=2)
        self.assertTrue(root.property("introComplete"))
        self.assertTrue(root.property("terminalReady"))
        self.assertAlmostEqual(float(root.property("signatureOpacity")), 1.0)
        self.assertAlmostEqual(float(root.property("productOpacity")), 1.0)
        self.assertAlmostEqual(float(root.property("promptOpacity")), 1.0)
        reveal.close()

    def test_any_key_enters_only_after_terminal_is_ready(self):
        reveal = BrandReveal()
        reveal.resize(960, 640)
        reveal.show()
        reveal.setFocus()
        APP.processEvents()
        spy = QSignalSpy(reveal.entered)
        QTest.keyClick(reveal, Qt.Key_A)
        APP.processEvents()
        self.assertFalse(reveal.rootObject().property("introComplete"))
        self.assertEqual(spy.count(), 0)

        reveal.skip_to_gate()
        QTest.keyClick(reveal, Qt.Key_A)
        QTest.qWait(600)
        self.assertEqual(spy.count(), 1)
        reveal.close()

    def test_pointer_enters_from_terminal(self):
        reveal = BrandReveal()
        reveal.resize(960, 640)
        reveal.show()
        reveal.skip_to_gate()
        APP.processEvents()
        spy = QSignalSpy(reveal.entered)
        QTest.mouseClick(reveal, Qt.LeftButton, pos=reveal.rect().center())
        QTest.qWait(600)
        self.assertEqual(spy.count(), 1)
        reveal.close()


class TestWindowShell(unittest.TestCase):
    def setUp(self):
        APP.setStyleSheet(theme.QSS)
        self.window = MainWindow()
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        self.window.close()
        APP.processEvents()

    def test_frameless_shell(self):
        self.assertTrue(self.window.windowFlags() & Qt.FramelessWindowHint)
        self.assertEqual(self.window.chrome.objectName(), "WindowChrome")
        self.assertEqual(self.window.inspector.objectName(), "InspectorPanel")
        self.assertEqual(self.window.status_strip.objectName(), "StatusStrip")

    def test_developer_credit_is_quiet_and_in_status_strip(self):
        credit = self.window.status_strip.findChild(QLabel, "DeveloperCredit")
        self.assertIsNotNone(credit)
        self.assertEqual(credit.text(), "Developed by 夜雨声烦")
        self.assertIsNone(self.window.chrome.findChild(QLabel, "ChromeCreator"))

    def test_existing_ui_contract_is_preserved(self):
        self.assertEqual(self.window.tabs.count(), 4)
        self.assertIsNotNone(self.window.panel_recommended)
        self.assertIsNotNone(self.window.panel_structure)
        self.assertIsNotNone(self.window.panel_project)
        self.assertIsNotNone(self.window.panel_developer)

    def test_brand_reveal_is_single_overlay(self):
        self.assertIsInstance(self.window.brand_reveal, BrandReveal)
        self.assertTrue(self.window._brand_ready)
        self.assertFalse(self.window.brand_reveal.isVisible())
        self.assertEqual(self.window.brand_reveal.size(),
                         self.window.centralWidget().size())


if __name__ == "__main__":
    unittest.main(verbosity=2)
