# -*- coding: utf-8 -*-
"""
pipeline_step.py —— 新增的独立步骤：**ASR 输出 → correction 纠错 → corrected_transcript**

定位
----
这是 correction 模块与主流程之间的**桥接层**。
它**不修改** `pipeline.py` 任何一个字，也不碰 ASR / DeepSeek 提示词 / UI，
必须被显式 import 才生效（`from correction.pipeline_step import run_correction_step`）。

数据流
------
    ASR 输出  transcripts/<name>.txt            ← 原样保留，一个字不动
        ↓ run_correction_step()
    transcripts/corrected/<name>.corrected.txt          ← DeepSeek 分析默认读这个
    transcripts/corrected/<name>.correction_report.json ← 原文本/修正文本/修改位置/置信度

输出记录（需求第四条）每条修改都带：
    行号 / 字符偏移 / 原文 / 修正后 / 标准词 / 分类 / 置信度总分与四维拆解 / 判断理由 / 所在句
灰区候选（保留原文但值得人工看）单独列在 `suggestions` 里，不进 `changes`。

用法
----
    from correction.pipeline_step import run_correction_step
    step = run_correction_step("transcripts/测试视频.txt")
    print(step.corrected_path, step.stats)
    print(step.report_path)          # 完整审计 JSON
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .corrector import AsrCorrector, Entry

UPDATED_AT = "2026-09-13"


def default_output_dir(transcript_path: Path) -> Path:
    """纠错产物目录：优先用 app_paths 解析的 transcripts/corrected，取不到就在原稿旁边建。"""
    try:
        import app_paths
        return Path(app_paths.transcripts_dir()) / "corrected"
    except Exception:
        return Path(transcript_path).resolve().parent / "corrected"


@dataclass
class CorrectionStepResult:
    """一次纠错步骤的全部产物。"""

    original_path: Path
    corrected_path: Path
    report_path: Path
    original_text: str
    corrected_text: str
    applied: list[dict] = field(default_factory=list)
    suggestions: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return self.corrected_text != self.original_text

    def summary(self) -> str:
        s = self.stats
        return (f"纠错 {s.get('applied', 0)} 处 / 灰区候选 {s.get('suggestions', 0)} 处 "
                f"（共 {s.get('lines', 0)} 行，{s.get('chars', 0)} 字）")


def _line_of(offsets: list[int], pos: int) -> int:
    """把字符偏移换算成 1 起始的行号。"""
    lo, hi = 0, len(offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if offsets[mid] <= pos:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def run_correction_step(
    transcript_path,
    out_dir=None,
    corrector: AsrCorrector | None = None,
    extra_entries: list[Entry] | None = None,
) -> CorrectionStepResult:
    """
    对一份 ASR 文字稿执行纠错，产出 corrected 稿 + 审计 JSON。

    参数：
        transcript_path —— 原始文字稿路径（**只读，绝不改写**）
        out_dir         —— 产物目录，默认 transcripts/corrected/
        corrector       —— 复用已有纠错器（不传就新建一个）
        extra_entries   —— 临时追加的词条（只进内存，不写进词库文件）

    返回 CorrectionStepResult。
    """
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        raise FileNotFoundError(f"文字稿不存在：{transcript_path}")

    original_text = transcript_path.read_text(encoding="utf-8")

    if corrector is None:
        corrector = AsrCorrector.from_dictionary_dir()
    for entry in extra_entries or []:
        corrector.index.add_entry(entry)

    # 整篇一起纠错（不是逐行）：这样「全文领域倾向」才看得见，
    # 时间戳保护也是全局生效的（见 corrector.PROTECT_RE）。
    result = corrector.correct(original_text)

    out_dir = Path(out_dir) if out_dir else default_output_dir(transcript_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    corrected_path = out_dir / f"{transcript_path.stem}.corrected.txt"
    report_path = out_dir / f"{transcript_path.stem}.correction_report.json"

    corrected_path.write_text(result.text, encoding="utf-8")

    # 行号换算
    starts = _line_starts(original_text)

    def _record(idx, d: object, decision: str) -> dict:
        return {
            "index": idx,
            "line": _line_of(starts, d.start),
            "char_start": d.start,
            "char_end": d.end,
            "original": d.matched,          # 原文本（被改掉的那一段）
            "corrected": d.canonical,       # 修正文本
            "canonical": d.canonical,
            "category": d.category,
            "score": round(d.score, 4),     # 置信度
            "decision": decision,
            "confidence": d.breakdown,      # 四维拆解：prior/similarity/context/fluency/ambiguity
            "reasons": list(d.reasons),
            "sentence": d.sentence,
            "source": d.source,
        }

    applied = [_record(i, d, "replace") for i, d in enumerate(result.applied, 1)]
    suggestions = [_record(i, d, "keep_suggest")
                   for i, d in enumerate(result.suggestions, 1)]

    stats = {
        "lines": original_text.count("\n") + 1,
        "chars": len(original_text),
        "applied": len(applied),
        "suggestions": len(suggestions),
        "candidates_total": len(result.decisions),
        "dictionary_entries": corrector.index.stats.get("entries", 0),
        "dictionary_aliases": corrector.index.stats.get("aliases", 0),
        "changed": result.changed,
    }

    report = {
        "meta": {
            "step": "correction",
            "source_transcript": str(transcript_path),
            "corrected_transcript": str(corrected_path),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dictionary_updated_at": UPDATED_AT,
            "note": "原始文字稿未做任何修改；corrected 稿为新增产物。",
        },
        "stats": stats,
        "original_text": original_text,        # 原文本
        "corrected_text": result.text,         # 修正文本
        "changes": applied,                    # 修改位置 + 置信度
        "suggestions": suggestions,            # 保留原文但值得人工确认的候选
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return CorrectionStepResult(
        original_path=transcript_path,
        corrected_path=corrected_path,
        report_path=report_path,
        original_text=original_text,
        corrected_text=result.text,
        applied=applied,
        suggestions=suggestions,
        stats=stats,
    )
