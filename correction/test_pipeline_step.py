# -*- coding: utf-8 -*-
"""
test_pipeline_step.py —— correction **接入 pipeline 测试流程**的离线测试。

全部离线、不烧 API：分析函数用假函数注入（`analyze_fn`），
只验证「接线对不对 + 产物对不对」。

运行：
    cd live_clipper
    python correction/test_pipeline_step.py
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIVE_CLIPPER = HERE.parent
if str(LIVE_CLIPPER) not in sys.path:
    sys.path.insert(0, str(LIVE_CLIPPER))

from correction.pipeline_step import run_correction_step          # noqa: E402
from correction.run_pipeline_test import compare_highlights, run_full_test  # noqa: E402

#: 测试用稿：三处典型情形（2 处该改 + 1 处灰区）
SAMPLE = (
    "[00:00 - 00:05] 这个主播叫陈则，粉丝很多\n"
    "[00:05 - 00:10] 昨天去电影院看了猫妖传\n"
    "[00:10 - 00:15] 我跟大叔说什么\n"
)

TS_RE = re.compile(r"^\[[^\]]*\]")


def _timestamps(text: str) -> list[str]:
    return [TS_RE.match(ln).group(0) for ln in text.splitlines() if TS_RE.match(ln)]


class TestCorrectionStep(unittest.TestCase):
    """新增步骤本身：保留原稿、产出 corrected、记录修改位置与置信度。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="corr_step_"))
        cls.src = cls.tmp / "sample.txt"
        cls.src.write_text(SAMPLE, encoding="utf-8")
        cls.orig_bytes = cls.src.read_bytes()
        cls.step = run_correction_step(cls.src, out_dir=cls.tmp / "out")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_original_transcript_preserved(self):
        """原始 transcript 一个字节都不能变。"""
        self.assertEqual(self.src.read_bytes(), self.orig_bytes)

    def test_corrected_transcript_generated(self):
        """必须生成独立的 corrected 稿，且路径与原始稿不同。"""
        self.assertTrue(self.step.corrected_path.exists())
        self.assertNotEqual(self.step.corrected_path.resolve(), self.src.resolve())
        self.assertTrue(self.step.corrected_path.name.endswith(".corrected.txt"))

    def test_expected_corrections_applied(self):
        """语境明确的错字被替换。"""
        got = {c["original"]: c["corrected"] for c in self.step.applied}
        self.assertEqual(got.get("陈则"), "陈泽")
        self.assertEqual(got.get("猫妖传"), "妖猫传")
        self.assertIn("陈泽", self.step.corrected_text)
        self.assertIn("妖猫传", self.step.corrected_text)

    def test_timestamps_never_touched(self):
        """时间戳必须与原始稿逐行一致。"""
        self.assertEqual(_timestamps(self.step.corrected_text), _timestamps(SAMPLE))

    def test_gray_zone_kept_and_recorded(self):
        """灰区候选：原文保留，但记进 suggestions（不进 changes）。"""
        self.assertIn("我跟大叔说什么", self.step.corrected_text)
        self.assertNotIn("大叔", [c["original"] for c in self.step.applied])
        self.assertIn("大叔", [s["original"] for s in self.step.suggestions])

    def test_report_has_all_required_records(self):
        """报告必须包含：原文本 / 修正文本 / 修改位置 / 置信度。"""
        report = json.loads(self.step.report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["original_text"], SAMPLE)      # 原文本
        self.assertEqual(report["corrected_text"], self.step.corrected_text)  # 修正文本
        for c in report["changes"]:
            for key in ("line", "char_start", "char_end", "original",
                        "corrected", "score", "confidence", "reasons"):
                self.assertIn(key, c, f"修改记录缺字段 {key}")
            self.assertIsInstance(c["line"], int)
            self.assertGreaterEqual(c["score"], 0.0)
            self.assertIn("context", c["confidence"])          # 置信度四维拆解

    def test_report_line_numbers_point_to_right_line(self):
        """修改位置的行号要真能对上。"""
        report = json.loads(self.step.report_path.read_text(encoding="utf-8"))
        lines = SAMPLE.splitlines()
        for c in report["changes"]:
            self.assertIn(c["original"], lines[c["line"] - 1])

    def test_stats(self):
        self.assertEqual(self.step.stats["applied"], 2)
        self.assertEqual(self.step.stats["suggestions"], 1)
        self.assertTrue(self.step.stats["changed"])


class TestRunnerWiring(unittest.TestCase):
    """runner 的接线：DeepSeek 分析默认读 corrected 稿。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="corr_run_"))
        self.src = self.tmp / "sample.txt"
        self.src.write_text(SAMPLE, encoding="utf-8")
        self.seen: list[Path] = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_analyze(self, path, token_mode=None, quantity_mode=None, verbose=True):
        self.seen.append(Path(path))
        return {"highlights": [], "rejected": [], "cost": {}, "meta": {}}

    def test_analysis_reads_corrected_first(self):
        """第 3 步拿到的必须是 corrected 稿，不是原始稿。"""
        out = run_full_test(
            self.src, do_api=True, do_compare=True,
            analyze_fn=self._fake_analyze, verbose=False,
            out_dir=self.tmp / "out",
        )
        self.assertEqual(len(self.seen), 2)
        self.assertTrue(str(self.seen[0]).endswith(".corrected.txt"),
                        f"第一次分析应读 corrected 稿，实际：{self.seen[0]}")
        self.assertEqual(self.seen[1].resolve(), self.src.resolve(),
                         "第二次是对照，读原始稿")

    def test_offline_mode_skips_api(self):
        """--no-api 不调用分析。"""
        out = run_full_test(self.src, do_api=False, analyze_fn=self._fake_analyze,
                            verbose=False, out_dir=self.tmp / "out")
        self.assertEqual(self.seen, [])
        self.assertIsNone(out["analysis"])

    def test_comparison_json_written(self):
        out_dir = self.tmp / "out"
        run_full_test(self.src, do_api=True, do_compare=True,
                      analyze_fn=self._fake_analyze, verbose=False,
                      out_dir=out_dir)
        files = list(out_dir.glob("*.comparison.json"))
        self.assertEqual(len(files), 1, f"产物目录：{list(out_dir.glob('*'))}")
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertIn("highlights_before", payload)
        self.assertIn("highlights_after", payload)

    def test_demo_injection_does_not_touch_original(self):
        """演示注入只作用于副本，原稿不动。"""
        before = self.src.read_bytes()
        run_full_test(self.src, do_api=False, demo_errors=True, verbose=False,
                      out_dir=self.tmp / "demo_out")
        self.assertEqual(self.src.read_bytes(), before)


class TestCompareHighlights(unittest.TestCase):
    """前后高光对比逻辑。"""

    def test_identical(self):
        hs = [{"start": "00:10", "end": "00:40", "score": 70, "grade": "B",
               "recommended": True, "title": "同一个片段"}]
        cmp = compare_highlights(hs, hs)
        self.assertTrue(cmp["identical"])
        self.assertEqual(cmp["count_before"], cmp["count_after"])

    def test_score_delta(self):
        before = [{"start": "00:10", "end": "00:40", "score": 70, "grade": "B",
                   "recommended": False, "title": "旧标题"}]
        after = [{"start": "00:10", "end": "00:40", "score": 85, "grade": "A",
                  "recommended": True, "title": "新标题"}]
        cmp = compare_highlights(before, after)
        self.assertFalse(cmp["identical"])
        self.assertEqual(cmp["matched"][0]["score_delta"], 15.0)
        self.assertEqual(cmp["recommended_after"], 1)

    def test_new_and_missing(self):
        before = [{"start": "05:00", "end": "05:30", "score": 60, "grade": "B",
                   "recommended": False, "title": "消失的"}]
        after = [{"start": "09:00", "end": "09:30", "score": 80, "grade": "A",
                  "recommended": True, "title": "新增的"}]
        cmp = compare_highlights(before, after)
        self.assertEqual(len(cmp["only_before"]), 1)
        self.assertEqual(len(cmp["only_after"]), 1)
        self.assertEqual(cmp["matched"], [])


def _main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestCorrectionStep, TestRunnerWiring, TestCompareHighlights):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    ok = unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())
