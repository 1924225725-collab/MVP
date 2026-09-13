"""Regression tests for repair/upgrade installation layout."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from setup_app import flatten_if_wrapped


class TestUpgradeFlattening(unittest.TestCase):
    def test_existing_install_is_replaced_without_nested_copy(self):
        with tempfile.TemporaryDirectory(prefix="lc_setup_upgrade_") as temp:
            target = Path(temp)
            (target / "AILiveClipper.exe").write_text(
                "old", encoding="utf-8")
            (target / "keep.txt").write_text("keep", encoding="utf-8")
            wrapped = target / "AILiveClipper"
            (wrapped / "_internal" / "desktop").mkdir(parents=True)
            (wrapped / "AILiveClipper.exe").write_text(
                "new", encoding="utf-8")
            (wrapped / "_internal" / "desktop" / "asset.txt").write_text(
                "asset", encoding="utf-8")

            flatten_if_wrapped(str(target))

            self.assertEqual(
                (target / "AILiveClipper.exe").read_text(encoding="utf-8"),
                "new",
            )
            self.assertTrue(
                (target / "_internal" / "desktop" / "asset.txt").is_file())
            self.assertEqual(
                (target / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertFalse(wrapped.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
