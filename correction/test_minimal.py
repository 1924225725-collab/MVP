# -*- coding: utf-8 -*-
"""
test_minimal.py —— correction 模块的最小测试（纯标准库，离线可跑）。

覆盖需求里的三类验收，外加四条安全闸门：

    A 明确错误   → replace        应该替换
    B 正确文本   → 不改变         不能误伤
    C 模糊情况   → keep_suggest   保留原文 + 输出候选
    D 时间戳保护 / 标准词保护区 / 多义折价 / 词库结构 / 独立可运行
    E 文档级一致性（同一名字不两种写法）+ 它的安全阀

运行：
    cd live_clipper
    python correction/test_minimal.py
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

from correction import (  # noqa: E402
    AsrCorrector,
    DictionaryIndex,
    Entry,
    THRESHOLD_REPLACE,
    THRESHOLD_SUGGEST,
)


def build_corrector() -> AsrCorrector:
    """加载真实词库 + 一个**演示词条**（仅内存，不写入任何词库文件）。"""
    corrector = AsrCorrector.from_dictionary_dir(HERE / "dictionary")
    corrector.index.add_entry(
        Entry(
            canonical="永劫无间",
            aliases=["永久无间", "永劫无兼", "永杰无间"],
            category="movie",
            priority=2,
            context_tags=["game"],
            description="需求示例词条：只在游戏语境下才应替换",
            source="demo(不落盘)",
            updated_at="2026-09-13",
        )
    )
    return corrector


class TestA_ShouldReplace(unittest.TestCase):
    """A. 明确错误 + 语境匹配 → 替换。"""

    @classmethod
    def setUpClass(cls):
        cls.c = build_corrector()

    def test_game_context_hotword(self):
        """需求原例：『今天玩永久无间』→ 永劫无间（游戏语境命中）。"""
        r = self.c.correct("今天玩永久无间")
        self.assertEqual(r.text, "今天玩永劫无间", r.to_dict())
        self.assertEqual(len(r.applied), 1)
        self.assertGreaterEqual(r.applied[0].score, THRESHOLD_REPLACE)

    def test_movie_context(self):
        """影视语境：『电影院』强证据 → 猫妖传 换成 妖猫传。"""
        r = self.c.correct("昨天去电影院看了猫妖传，特效真不错")
        self.assertEqual(r.text, "昨天去电影院看了妖猫传，特效真不错")
        self.assertEqual(r.applied[0].category, "movie")

    def test_person_context(self):
        """人物语境：『主播 / 粉丝』→ 小杨哥 换成 疯狂小杨哥。"""
        r = self.c.correct("这个主播叫小杨哥，粉丝很多")
        self.assertEqual(r.text, "这个主播叫疯狂小杨哥，粉丝很多")
        self.assertEqual(r.applied[0].category, "person")

    def test_reason_is_explainable(self):
        """每次替换都必须留下可读理由（可审计，不能是黑箱）。"""
        r = self.c.correct("今天玩永久无间")
        self.assertTrue(r.applied[0].reasons)
        self.assertIn("context", r.applied[0].breakdown)


class TestB_ShouldNotReplace(unittest.TestCase):
    """B. 正确文本不能被改坏。"""

    @classmethod
    def setUpClass(cls):
        cls.c = build_corrector()

    def test_no_context_no_replace(self):
        """需求原例：『永久无间的等待』是普通表达，不是游戏名。"""
        r = self.c.correct("永久无间的等待")
        self.assertEqual(r.text, "永久无间的等待")
        self.assertEqual(r.applied, [])

    def test_common_word_alias_not_replaced(self):
        """『摩天轮』确实是『摩天大楼』的错写候选，但这里它是游乐设施本义。"""
        r = self.c.correct("周末带孩子去坐摩天轮")
        self.assertEqual(r.text, "周末带孩子去坐摩天轮")
        self.assertEqual(r.applied, [])

    def test_candidate_cannot_vouch_for_itself(self):
        """
        回归：候选自己的字不能拿来当语境证据。

        『王博主测评』里候选是『王博』，它右侧的『主测评』拼出了『博主』——
        而『博主』正是人物类的强语境词。早期版本让候选自己给自己作证，
        把博主王博改成了唐代诗人王勃。这条测试把这个坑永久钉住。
        """
        r = self.c.correct("王博主测评了一下这款手机")
        self.assertEqual(r.text, "王博主测评了一下这款手机")
        self.assertEqual(r.applied, [])

    def test_keyword_hits_exclude_candidate_span(self):
        """候选区间内的关键词命中必须被剔除（scorer._keyword_hits 的直接验证）。"""
        from correction.scorer import _keyword_hits

        # 『博主』横跨候选『王博』的右半边 → 不算证据
        self.assertEqual(_keyword_hits("王博主测评", ("博主",), (0, 2)), [])
        # 同一句话里候选之外的『博主』照常算证据
        self.assertEqual(_keyword_hits("博主王博主测评", ("博主",), (2, 4)), ["博主"])
        # 不传 span 时保持旧行为
        self.assertEqual(_keyword_hits("王博主测评", ("博主",)), ["博主"])

    def test_canonical_itself_untouched(self):
        """原文已经是标准词 → 一个候选都不该产生。"""
        r = self.c.correct("我昨天在楼下买了三斤苹果")
        self.assertEqual(r.text, "我昨天在楼下买了三斤苹果")
        self.assertEqual(r.decisions, [])

    def test_standard_word_inside_longer_canonical(self):
        """
        标准词保护区：『陈翔六点半』整体是正确词，
        不能把它里面的『陈翔六点』当成错词去替换。
        """
        r = self.c.correct("陈翔六点半的视频真好看")
        self.assertEqual(r.text, "陈翔六点半的视频真好看")
        self.assertEqual(r.applied, [])

    def test_timestamp_never_modified(self):
        """文字稿行的时间戳一个字都不能动。"""
        line = "[00:12:34] 这个主播叫小杨哥，粉丝很多"
        out, r = self.c.correct_transcript_line(line)
        self.assertTrue(out.startswith("[00:12:34] "), out)
        self.assertIn("疯狂小杨哥", out)

    def test_timestamp_content_not_matched(self):
        """时间戳内部即使长得像别名也不参与匹配。"""
        line = "[00:12:34] 正常台词"
        out, _ = self.c.correct_transcript_line(line)
        self.assertEqual(out, line)


class TestC_FuzzyKeepsOriginal(unittest.TestCase):
    """C. 模糊情况：保留原文，只把候选抛给上层。"""

    @classmethod
    def setUpClass(cls):
        self_c = build_corrector()
        cls.c = self_c

    def test_weak_context_becomes_suggestion(self):
        """有影视弱线索（『看』）但没有强语境 → 灰区：留原文 + 提示候选。"""
        text = "昨天看了猫妖传 真的不错"
        r = self.c.correct(text)
        self.assertEqual(r.text, text, "灰区必须保留原文")
        self.assertEqual(r.applied, [])
        self.assertEqual(len(r.suggestions), 1)
        self.assertEqual(r.suggestions[0].matched, "猫妖传")
        self.assertEqual(r.suggestions[0].canonical, "妖猫传")
        self.assertGreaterEqual(r.suggestions[0].score, THRESHOLD_SUGGEST)
        self.assertLess(r.suggestions[0].score, THRESHOLD_REPLACE)

    def test_suggestion_carries_position_and_sentence(self):
        """候选要带位置与原句，上层才能定位与人工复核。"""
        r = self.c.correct("昨天看了猫妖传 真的不错")
        s = r.suggestions[0]
        self.assertEqual(r.original[s.start:s.end], "猫妖传")
        self.assertIn("猫妖传", s.sentence)

    def test_overlap_conflict_keeps_best_only(self):
        """同一位置多个候选打架时，只保留分数最高的那个。"""
        r = self.c.correct("今天玩永久无间")
        spans = [(d.start, d.end) for d in r.decisions if d.decision != "keep"]
        self.assertEqual(len(spans), len(set(spans)))


class TestD_ModuleIntegrity(unittest.TestCase):
    """D. 词库结构、安全闸门与独立可运行性。"""

    def test_dictionary_files_exist_and_shaped(self):
        for name in ("converted_hot_words.json", "converted_people.json",
                     "converted_books.json", "converted_movies.json"):
            path = HERE / "dictionary" / name
            self.assertTrue(path.exists(), f"缺少 {name}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("meta", payload)
            self.assertIn("entries", payload)
            for e in payload["entries"]:
                for key in ("canonical", "aliases", "category", "priority",
                            "context_tags", "description", "source", "updated_at"):
                    self.assertIn(key, e, f"{name} 条目缺字段 {key}")
                self.assertIn(e["category"], ("hotword", "person", "book", "movie"))
                self.assertNotIn(e["canonical"], e["aliases"], "别名不能等于标准词")

    def test_raw_sources_preserved(self):
        """原始词库快照必须在，且热词/人物/影视三份非空（书本源本就为空）。"""
        raw = HERE / "dictionary" / "raw"
        for name in ("热词库.txt", "人物库.txt", "影视作品名.txt"):
            self.assertTrue((raw / name).exists(), f"原始词库缺失：{name}")
            self.assertGreater((raw / name).stat().st_size, 0)
        self.assertTrue((raw / "书本.txt").exists())

    def test_index_stats(self):
        idx = DictionaryIndex.from_dir(HERE / "dictionary")
        self.assertGreater(idx.stats["entries"], 500)
        self.assertGreater(idx.stats["aliases"], 1000)

    def test_pattern_entry_not_matched_literally(self):
        """含 ×× 占位符的模板词条（如『拼好×』）不做字面匹配。"""
        c = AsrCorrector.from_dictionary_dir(HERE / "dictionary")
        self.assertNotIn("拼好×", c.index.alias_map)

    def test_module_is_standalone(self):
        """本模块不得把生产模块拖进来（不接主流程的硬保证）。"""
        forbidden = {"pipeline", "analysis", "asr", "ui", "desktop", "config"}
        loaded = forbidden & set(sys.modules)
        self.assertEqual(loaded, set(), f"correction 不应依赖生产模块：{loaded}")


class TestE_DocumentConsistency(unittest.TestCase):
    """
    E. 文档级一致性：同一篇稿子里，同一个名字不该有两种写法。

    ASR 最常见的毛病就是一个人名前后写成两样（峰哥 / 风哥）。
    逐句独立打分只看得见单句，看不见「这篇稿子整体在说什么」，
    所以会改一半留一半——那比不改更糟。
    """

    @staticmethod
    def _with_temp_entry(*entries: Entry) -> AsrCorrector:
        c = AsrCorrector.from_dictionary_dir(HERE / "dictionary")
        for e in entries:
            c.index.add_entry(e)
        return c

    def test_same_alias_resolved_consistently(self):
        """
        标准词在文中原样出现过 → 别处的同音写法应当统一。

        第一句有『直播间』强语境，本来就能改；后两句很平淡，单看只能进灰区。
        一致性让它们跟上，而不是一半改一半留。
        """
        c = self._with_temp_entry(
            Entry(canonical="峰哥", aliases=["风哥"], category="person",
                  priority=2, context_tags=["livestream"], source="test")
        )
        r = c.correct("直播间里风哥讲得真好。\n风哥还说了别的。\n风哥最后总结了一下。")
        self.assertEqual(r.text.count("峰哥"), 3)
        self.assertNotIn("风哥", r.text)

    def test_consistency_reason_is_explainable(self):
        """被一致性提升的候选，理由里必须写明是文档级证据（不能黑箱加buff）。"""
        c = self._with_temp_entry(
            Entry(canonical="峰哥", aliases=["风哥"], category="person",
                  priority=2, context_tags=["livestream"], source="test")
        )
        r = c.correct("直播间里风哥讲得真好。\n风哥还说了别的。")
        boosted = [d for d in r.applied if "文档级一致性" in "".join(d.reasons)]
        self.assertEqual(len(boosted), 1, "应当有一处是靠文档级一致性提升的")

    def test_safety_valve_below_gray_zone_not_promoted(self):
        """
        安全阀：一致性只能推『差一点』的过线，不能凭空造判断。

        『王勃』确实在文中出现过（witness 成立），但『王博主测评』
        单句证据不足（0.39 < 0.40）。若此时被提升，一处误判就会顺着
        一致性扩散到全文——那比漏改危险得多。
        """
        r = AsrCorrector.from_dictionary_dir(HERE / "dictionary").correct(
            "王勃的诗写得很有气势。\n王博主测评了一下这款手机。"
        )
        self.assertIn("王博主测评", r.text)
        self.assertEqual(r.applied, [])

    def test_ambiguous_alias_not_extrapolated(self):
        """同一个写法对应多个标准词时，不做一致性外推（多义风险太高）。"""
        c = self._with_temp_entry(
            Entry(canonical="张三峰", aliases=["风哥"], category="person", source="test"),
            Entry(canonical="李吹风", aliases=["风哥"], category="person", source="test"),
        )
        r = c.correct("直播间里张三峰讲得真好。\n风哥还说了别的。")
        self.assertIn("风哥", r.text)
        self.assertEqual(r.applied, [])


def _main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (TestA_ShouldReplace, TestB_ShouldNotReplace,
                TestC_FuzzyKeepsOriginal, TestD_ModuleIntegrity,
                TestE_DocumentConsistency):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    runner = unittest.TextTestRunner(verbosity=2)
    return 0 if runner.run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(_main())
