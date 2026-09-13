# -*- coding: utf-8 -*-
"""
correction —— ASR 后处理纠错模块（**独立模块，当前未接入主流程**）。

边界（明确写死，改动前先看 docs/DECISIONS.md）：
- 不改生产 ASR（asr/）
- 不改评分系统（analysis/ 与 config 的评分权重）
- 不改 UI
- 不接入 pipeline，不写回文字稿

对外接口：
    from correction import AsrCorrector, Entry
    c = AsrCorrector.from_dictionary_dir()
    result = c.correct("昨天去电影院看了猫妖传")   # → replace
    line, result = c.correct_transcript_line("[00:12:34] 台词")
"""

from .corrector import (
    AsrCorrector,
    Candidate,
    CorrectionResult,
    Decision,
    DictionaryIndex,
    Entry,
    detect,
)
from .scorer import (
    CATEGORY_PRIOR,
    DocumentProfile,
    ScoreBreakdown,
    THRESHOLD_REPLACE,
    THRESHOLD_SUGGEST,
    form_similarity,
    score_candidate,
)

__all__ = [
    "AsrCorrector",
    "Candidate",
    "CorrectionResult",
    "Decision",
    "DictionaryIndex",
    "Entry",
    "detect",
    "CATEGORY_PRIOR",
    "DocumentProfile",
    "ScoreBreakdown",
    "THRESHOLD_REPLACE",
    "THRESHOLD_SUGGEST",
    "form_similarity",
    "score_candidate",
]

__version__ = "0.1.0"
