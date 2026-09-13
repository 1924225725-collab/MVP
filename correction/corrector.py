# -*- coding: utf-8 -*-
"""
corrector.py —— ASR 后处理纠错的**独立模块**（当前不接入主流程）。

流程（严格按需求，不做暴力替换）：

    ASR 原文 → 候选检测 → 上下文判断 → 置信度评分 → 三选一决策
                                                    ├─ replace      替换
                                                    ├─ keep_suggest 保留原文 + 提示候选
                                                    └─ keep         保留原文

四条安全闸门（任一条不满足就不会被替换）：
1. **只匹配别名，不匹配标准词**——原文已经是标准词就不需要动。
2. **标准词保护区**——候选若落在原文里某个标准词的内部（例：「陈翔六点半」里的
   「陈翔六点」），直接跳过，绝不把一个正确的长词咬掉一半。
3. **占位符条目跳过**——标准词含 ×× / XX（如「拼好×」）的是模板，不做字面匹配。
4. **时间戳保护**——`[00:12:34]` 这类内容永不参与匹配与替换。

用法（独立运行，不依赖项目其余部分）：

    from correction.corrector import AsrCorrector
    c = AsrCorrector.from_dictionary_dir()
    result = c.correct("昨天去电影院看了猫妖传")
    print(result.text)              # 已替换的文本
    print(result.suggestions)       # 灰区候选（供人工/上层决策）
    print(result.to_dict())         # 全量审计信息

也可命令行体检：
    python corrector.py --text "今天玩永久无间"
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

try:  # 既支持 `from correction import corrector`，也支持直接跑脚本
    from . import scorer
    from .scorer import (
        THRESHOLD_REPLACE,
        THRESHOLD_SUGGEST,
        DocumentProfile,
        score_candidate,
    )
except ImportError:  # pragma: no cover
    import scorer
    from scorer import (
        THRESHOLD_REPLACE,
        THRESHOLD_SUGGEST,
        DocumentProfile,
        score_candidate,
    )

HERE = Path(__file__).resolve().parent
DICT_DIR = HERE / "dictionary"

DICT_FILES = {
    "hot_words": "converted_hot_words.json",
    "people": "converted_people.json",
    "books": "converted_books.json",
    "movies": "converted_movies.json",
}

#: 时间戳 / 方括号内容保护区（跟生产文字稿格式一致：`[00:12:34] 台词`）
PROTECT_RE = re.compile(r"\[[^\]\n]{1,24}\]")
#: 句子边界
SENT_BOUNDARY_RE = re.compile(r"[。！？!？；;\n]")


# ---------------------------------------------------------------- 数据结构

@dataclass
class Entry:
    """一条词库条目（与 converted_*.json 的条目一一对应）。"""

    canonical: str
    aliases: list[str]
    category: str
    priority: int = 0
    context_tags: list[str] = field(default_factory=list)
    description: str = ""
    source: str = ""
    updated_at: str = ""
    is_pattern: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Entry":
        return cls(
            canonical=d.get("canonical", ""),
            aliases=list(d.get("aliases", [])),
            category=d.get("category", ""),
            priority=int(d.get("priority", 0)),
            context_tags=list(d.get("context_tags", [])),
            description=d.get("description", ""),
            source=d.get("source", ""),
            updated_at=d.get("updated_at", ""),
            is_pattern=bool(d.get("is_pattern", False)),
        )


@dataclass
class Candidate:
    """一个候选错误词在原文中的一次出现。"""

    start: int
    end: int
    alias: str
    entry: Entry
    sentence: str = ""
    left: str = ""
    right: str = ""


@dataclass
class Decision:
    """对一个候选的最终处置决定（含全部中间量，可审计）。"""

    start: int
    end: int
    matched: str
    canonical: str
    category: str
    decision: str                 # replace / keep_suggest / keep
    score: float
    sentence: str
    source: str
    reasons: list[str] = field(default_factory=list)
    breakdown: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "matched": self.matched,
            "canonical": self.canonical,
            "category": self.category,
            "decision": self.decision,
            "score": round(self.score, 4),
            "sentence": self.sentence,
            "source": self.source,
            "reasons": list(self.reasons),
            "breakdown": self.breakdown,
        }


@dataclass
class CorrectionResult:
    """纠错结果：改后的文本 + 全部决策 + 灰区候选。"""

    original: str
    text: str
    decisions: list[Decision] = field(default_factory=list)
    applied: list[Decision] = field(default_factory=list)
    suggestions: list[Decision] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.text != self.original

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "text": self.text,
            "changed": self.changed,
            "applied": [d.to_dict() for d in self.applied],
            "suggestions": [d.to_dict() for d in self.suggestions],
            "decisions": [d.to_dict() for d in self.decisions],
        }


# ---------------------------------------------------------------- 索引

class DictionaryIndex:
    """把四个 converted_*.json 摊平成「别名 → 条目」的检索结构。"""

    def __init__(self, entries: list[Entry]):
        self.entries = [e for e in entries if e.canonical]
        self.alias_map: dict[str, list[Entry]] = {}
        self.canonical_set: set[str] = set()
        self.canonical_lengths: set[int] = set()
        self.alias_lengths: list[int] = []

        for e in self.entries:
            self.canonical_set.add(e.canonical)
            self.canonical_lengths.add(len(e.canonical))
            if e.is_pattern:
                continue                       # 模板条目（含 ××）不参与字面匹配
            for a in e.aliases:
                if not a or a == e.canonical:
                    continue
                self.alias_map.setdefault(a, []).append(e)

        self.alias_lengths = sorted({len(a) for a in self.alias_map}, reverse=True)
        self._build_gates()

    def _build_gates(self) -> None:
        """首字 → 候选长度表：扫全文时先按首字过滤，省掉大量无谓切片。"""
        self._alias_gate: dict[str, list[int]] = {}
        for a in self.alias_map:
            self._alias_gate.setdefault(a[0], set()).add(len(a))
        self._canon_gate: dict[str, list[int]] = {}
        for c in self.canonical_set:
            if len(c) > 1:
                self._canon_gate.setdefault(c[0], set()).add(len(c))
        self._alias_gate = {k: sorted(v, reverse=True) for k, v in self._alias_gate.items()}
        self._canon_gate = {k: sorted(v, reverse=True) for k, v in self._canon_gate.items()}

    @classmethod
    def from_dir(cls, dictionary_dir: Path | str = DICT_DIR) -> "DictionaryIndex":
        directory = Path(dictionary_dir)
        entries: list[Entry] = []
        for filename in DICT_FILES.values():
            path = directory / filename
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries.extend(Entry.from_dict(d) for d in payload.get("entries", []))
        return cls(entries)

    def add_entry(self, entry: Entry) -> None:
        """运行时追加条目（测试/用户临时词条用，不落盘、不改词库文件）。"""
        self.entries.append(entry)
        self.canonical_set.add(entry.canonical)
        self.canonical_lengths.add(len(entry.canonical))
        if entry.is_pattern:
            return
        for a in entry.aliases:
            if not a or a == entry.canonical:
                continue
            self.alias_map.setdefault(a, []).append(entry)
        self.alias_lengths = sorted({len(a) for a in self.alias_map}, reverse=True)
        self._build_gates()

    @property
    def stats(self) -> dict:
        return {
            "entries": len(self.entries),
            "aliases": len(self.alias_map),
            "ambiguous_aliases": sum(1 for v in self.alias_map.values() if len(v) > 1),
        }


# ---------------------------------------------------------------- 检测

def _sentence_span_at(text: str, start: int, end: int) -> tuple[str, int]:
    """取出候选所在的句子 + 该句在全文里的起始下标。"""
    window_left = text[max(0, start - 120):start]
    idx = max(window_left.rfind(p) for p in ("。", "！", "？", "!", "?", "；", ";", "\n"))
    sent_start = start - len(window_left) + idx + 1 if idx != -1 else max(0, start - 120)

    window_right = text[end:end + 120]
    positions = [window_right.find(p) for p in ("。", "！", "？", "!", "?", "；", ";", "\n")]
    positions = [p for p in positions if p != -1]
    sent_end = end + min(positions) + 1 if positions else min(len(text), end + 120)
    return text[sent_start:sent_end], sent_start


def _sentence_at(text: str, start: int, end: int) -> str:
    """取出候选所在的句子（最多向两侧看 120 字）。"""
    return _sentence_span_at(text, start, end)[0]


def _protected_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in PROTECT_RE.finditer(text)]


def _protected_mask(text: str) -> bytearray:
    """
    保护区掩码（0/1 每个字符一个字节）。

    不能写成 `any(s <= pos < e for ...)`：文字稿里每句都有时间戳，
    那会退化成 O(字符数 × 时间戳数)，万字稿直接卡死。
    """
    mask = bytearray(len(text))
    for s, e in _protected_spans(text):
        for i in range(s, min(e, len(text))):
            mask[i] = 1
    return mask


def _in_spans(pos: int, spans: bytearray) -> bool:
    return bool(spans[pos]) if 0 <= pos < len(spans) else False


def detect(text: str, index: DictionaryIndex) -> list[Candidate]:
    """
    在原文里找出所有候选错误词。

    跳过：时间戳保护区、标准词保护区（候选落在某个正确长词内部）。
    """
    if not text or not index.alias_lengths:
        return []

    protect = _protected_mask(text)

    # 先找出原文里出现的所有标准词 → 这些区间是「正确区」，不容许被咬掉一半
    canonical_spans: list[tuple[int, int]] = []
    canon_gate = getattr(index, "_canon_gate", None)
    for i in range(len(text)):
        lengths = canon_gate.get(text[i]) if canon_gate else index.canonical_lengths
        if not lengths:
            continue
        for length in lengths:
            if text[i:i + length] in index.canonical_set:
                canonical_spans.append((i, i + length))
                break

    candidates: list[Candidate] = []
    alias_gate = getattr(index, "_alias_gate", None)
    i = 0
    n = len(text)
    while i < n:
        if _in_spans(i, protect):
            i += 1
            continue
        hit = None
        for length in (alias_gate.get(text[i]) if alias_gate else index.alias_lengths) or ():
            if i + length > n:
                continue
            frag = text[i:i + length]
            owners = index.alias_map.get(frag)
            if owners:
                hit = (length, frag, owners)
                break                      # 最长优先
        if hit:
            length, frag, owners = hit
            end = i + length
            if not _in_spans(end - 1, protect):
                for entry in owners:
                    candidates.append(
                        Candidate(start=i, end=end, alias=frag, entry=entry)
                    )
            i = end                        # 命中后整体跳过，避免子串重复候选
        else:
            i += 1

    # 剔除落在标准词内部的候选（标准词保护区）
    safe: list[Candidate] = []
    for c in candidates:
        covered = any(s <= c.start and c.end <= e for s, e in canonical_spans)
        if not covered:
            safe.append(c)
    return safe


# ---------------------------------------------------------------- 纠错器

class AsrCorrector:
    """对一段 ASR 文本做「检测 → 上下文判断 → 评分 → 决策」。"""

    def __init__(self, index: DictionaryIndex):
        self.index = index

    @classmethod
    def from_dictionary_dir(cls, dictionary_dir: Path | str = DICT_DIR) -> "AsrCorrector":
        return cls(DictionaryIndex.from_dir(dictionary_dir))

    # -- 单句/单段 -------------------------------------------------
    def detect(self, text: str) -> list[Candidate]:
        return detect(text, self.index)

    def correct(self, text: str) -> CorrectionResult:
        if not text:
            return CorrectionResult(original=text or "", text=text or "")

        doc_keys = set()
        for e in self.index.entries:
            doc_keys.update(e.context_tags)
            doc_keys.add(e.category)
        doc = DocumentProfile.from_text(text, doc_keys)

        # 文档级一致性证据之一：标准词在本篇里被原样写过（时间戳保护区内的不算）
        witness = self._canonical_witness(text)

        decisions: list[Decision] = []
        scored: list[tuple[Decision, dict]] = []
        for cand in self.detect(text):
            sentence, sent_start = _sentence_span_at(text, cand.start, cand.end)
            # 候选在**句子内**的相对区间：交给 scorer 剔除「用候选自己的字凑出来的语境词」
            rel_span = (cand.start - sent_start, cand.end - sent_start)
            left = text[max(0, cand.start - 8):cand.start]
            right = text[cand.end:cand.end + 6]
            owners = len(self.index.alias_map.get(cand.alias, []))
            is_canon = cand.alias in self.index.canonical_set

            kwargs = dict(
                alias=cand.alias,
                entry=cand.entry,
                sentence=sentence,
                left=left,
                right=right,
                doc=doc,
                alias_owners=owners,
                alias_is_canonical=is_canon,
                span=rel_span,
            )
            bd = score_candidate(**kwargs)
            d = Decision(
                start=cand.start,
                end=cand.end,
                matched=cand.alias,
                canonical=bd.canonical,
                category=bd.category,
                decision=bd.decision,
                score=bd.score,
                sentence=sentence,
                source=cand.entry.source,
                reasons=bd.reasons,
                breakdown=bd.to_dict()["breakdown"],
            )
            decisions.append(d)
            scored.append((d, kwargs))     # 一致性复评时要原样重打分，入参得留着

        self._apply_consistency(decisions, scored, witness)

        # 冲突消解：区间重叠时只留分数最高的（一个位置只能改一次）
        decisions.sort(key=lambda d: (-d.score, d.start))
        taken: list[Decision] = []
        occupied: list[tuple[int, int]] = []
        for d in decisions:
            if any(d.start < e and s < d.end for s, e in occupied):
                d.decision = "keep"                     # 被更高分候选挡下
                d.reasons.append("与更高分候选区间重叠，本次不处理")
                continue
            occupied.append((d.start, d.end))
            taken.append(d)

        applied = [d for d in taken if d.decision == "replace"]
        suggestions = [d for d in taken if d.decision == "keep_suggest"]

        # 从后往前替换，保证前面的偏移不失效
        chars = list(text)
        for d in sorted(applied, key=lambda x: x.start, reverse=True):
            chars[d.start:d.end] = list(d.canonical)

        ordered = sorted(taken, key=lambda d: d.start)
        return CorrectionResult(
            original=text,
            text="".join(chars),
            decisions=ordered,
            applied=sorted(applied, key=lambda d: d.start),
            suggestions=sorted(suggestions, key=lambda d: d.start),
        )

    # -- 文档级一致性 ---------------------------------------------
    def _canonical_witness(self, text: str) -> set[str]:
        """
        本篇里**原样出现过**的标准词（时间戳保护区内的不算）。

        这是文稿能给出的最强证据：ASR 在同一场直播里把某个名字写对过，
        那别处写成同音的另一种样子，几乎可以肯定也是同一个人。
        """
        protect = _protected_mask(text)
        gate = getattr(self.index, "_canon_gate", None)
        found: set[str] = set()
        for i in range(len(text)):
            if _in_spans(i, protect):
                continue
            for length in (gate.get(text[i]) if gate else ()) or ():
                frag = text[i:i + length]
                if frag in self.index.canonical_set:
                    found.add(frag)
                    break
        return found

    @staticmethod
    def _apply_consistency(decisions: list[Decision], scored: list[tuple[Decision, dict]],
                           witness: set[str]) -> None:
        """
        文档级一致性裁决：同一篇稿子里，同一个名字不该有两种写法。

        触发条件（满足其一）：
          a) 标准词本身在本篇其他位置原样出现过 —— 稿子自己给了答案；
          b) 同一 (别名, 标准词) 组合里已有一处被高置信度判为听错 —— 语境最强的那处
             给其余相同写法背书。

        **安全阀（关键）**：只对**已进入灰区**（score ≥ THRESHOLD_SUGGEST）的候选生效。
        文档级证据只能把「差一点就过线」的推过去，绝不能凭空造出一个判断——
        否则一处误判会顺着一致性扩散到全文，那比漏改危险得多。
        多义别名（同一个写法对应多个标准词）也不做外推。
        """
        pairs: dict[tuple[str, str], list[int]] = {}
        for i, (d, _) in enumerate(scored):
            pairs.setdefault((d.matched, d.canonical), []).append(i)

        for (alias, canonical), idxs in pairs.items():
            if scored[idxs[0]][1]["alias_owners"] > 1:
                continue
            if not (canonical in witness
                    or any(decisions[i].decision == "replace" for i in idxs)):
                continue

            for i in idxs:
                d, kwargs = scored[i]
                if d.decision != "keep_suggest":
                    continue
                bd = score_candidate(**dict(kwargs, consistent=True))
                if bd.score >= THRESHOLD_REPLACE:
                    d.decision = bd.decision
                    d.score = bd.score
                    d.breakdown = bd.to_dict()["breakdown"]
                    d.reasons = bd.reasons

    # -- 文字稿行（保护时间戳，只改台词） ---------------------------
    def correct_transcript_line(self, line: str) -> tuple[str, CorrectionResult]:
        """
        处理一行文字稿：`[00:12:34] 台词`。
        时间戳一个字都不动，只对台词部分纠错。
        """
        m = PROTECT_RE.match(line or "")
        if not m:
            result = self.correct(line or "")
            return result.text, result
        prefix, body = line[:m.end()], line[m.end():]
        result = self.correct(body)

        # 候选在原行里的位置要加上前缀偏移，方便上层定位
        offset = len(prefix)
        for d in result.decisions:
            d.start += offset
            d.end += offset
        return prefix + result.text, result


# ---------------------------------------------------------------- CLI 体检

def _demo_entry() -> Entry:
    """
    演示用词条（**不写进任何词库文件**）。
    仅用于说明「游戏语境下才替换」这条规则，需求方给的例子是 永劫无间。
    """
    return Entry(
        canonical="永劫无间",
        aliases=["永久无间", "永劫无兼", "永杰无间"],
        category="movie",
        priority=2,
        context_tags=["game"],
        description="演示词条：仅在游戏语境下才应替换（不落盘）",
        source="demo",
        updated_at="2026-09-13",
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="ASR 纠错模块自检（独立运行）")
    ap.add_argument("--text", help="要纠错的文本")
    ap.add_argument("--with-demo", action="store_true",
                    help="额外加载演示词条「永劫无间」（不写入词库）")
    ap.add_argument("--stats", action="store_true", help="只打印词库统计")
    args = ap.parse_args(argv)

    corrector = AsrCorrector.from_dictionary_dir()
    if args.stats:
        print(json.dumps(corrector.index.stats, ensure_ascii=False))
        return 0
    if args.with_demo:
        corrector.index.add_entry(_demo_entry())
    if not args.text:
        ap.print_help()
        return 0

    result = corrector.correct(args.text)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
