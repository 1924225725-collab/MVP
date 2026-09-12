# ============================================================
# desktop/services/ai_progress.py —— 把「AI 分析的日志」翻译成用户能看的进度
#
# 【为什么这么做】
#   AI 分析由 analysis/ 里的编排器完成，它每一步都会 print 一行日志
#   （[分区] / [海选] 区块 3/12 / [复审] 批次 2/3 / [结构] …）。
#   我们**不改 analysis 一行代码**（那里是冻结的算法），而是在外面把这
#   些日志行翻译成"处理到哪一步了"，喂给进度条。
#
# 【诚实原则】
#   能算出真百分比的就算真的（海选 / 复审都有"第几批、共几批"）；
#   算不出来的（质检、事件聚合、写报告）就推到一个**里程碑值**并如实
#   写出"正在做什么"——不装成精确进度，更不用定时器空转。
# ============================================================

import re

import stages

# 日志前缀 → (AI 阶段内的里程碑百分比, 给用户看的一句话)
_MILESTONES = (
    ("[分区]", 5, "正在把整场切成若干区块…"),
    ("[预算]", 8, "正在规划扫描范围…"),
    ("[降级", 8, "内容较多，正在调整扫描密度…"),
    ("[质检]", 60, "正在检查有没有漏掉的爆点…"),
    ("[Story层]", 62, "正在给候选片段标注所属段落…"),
    ("[事件聚合]", 68, "正在把候选片段合并成完整事件…"),
    ("[结构]", 90, "正在生成 Chapter / Story 内容结构…"),
    ("[报告]", 96, "正在写整场复盘…"),
    ("[成本]", 98, "正在汇总本次花费…"),
)

# [海选] 区块 3/12：00:00 - 04:00
_RE_SCREEN = re.compile(r"\[海选\]\s*区块\s*(\d+)\s*/\s*(\d+)")
# [复审] 批次 2/3（5 个事件）…
_RE_REVIEW = re.compile(r"\[复审\]\s*批次\s*(\d+)\s*/\s*(\d+)")

# AI 阶段内百分比分配（海选占大头，复审次之）
_SCREEN_FROM, _SCREEN_TO = 10.0, 58.0
_REVIEW_FROM, _REVIEW_TO = 72.0, 88.0


class AiProgressTracker:
    """吃日志行，吐进度事件。"""

    def __init__(self, report=None):
        self._report = report
        self.total_chunks = 0
        self.last_percent = None
        self.last_detail = ""

    # ---- 主入口 ----

    def feed(self, line: str):
        """喂一行日志（来自 analysis 的 print）。"""
        if not line or self._report is None:
            return
        line = line.strip()
        if not line:
            return

        # 1) 海选：有真实区块数 → 真百分比
        m = _RE_SCREEN.search(line)
        if m:
            idx, total = int(m.group(1)), max(1, int(m.group(2)))
            self.total_chunks = total
            pct = _SCREEN_FROM + (idx - 1) / total * (_SCREEN_TO - _SCREEN_FROM)
            self._emit(pct, f"正在扫描候选片段（区块 {idx}/{total}）")
            return

        # 2) 复审：有真实批次 → 真百分比
        m = _RE_REVIEW.search(line)
        if m:
            idx, total = int(m.group(1)), max(1, int(m.group(2)))
            pct = _REVIEW_FROM + (idx - 1) / total * (_REVIEW_TO - _REVIEW_FROM)
            self._emit(pct, f"正在复审与打分（第 {idx}/{total} 批）")
            return

        # 3) 其余里程碑
        for prefix, pct, text in _MILESTONES:
            if line.startswith(prefix):
                # 结构层有开始和完成两条，完成时往前推一点
                if prefix == "[结构]" and "生成完成" in line:
                    self._emit(94.0, "内容结构已生成…")
                    return
                self._emit(float(pct), text)
                return

    # ---- 收尾 ----

    def finish(self):
        """AI 分析结束。"""
        self._emit(100.0, "AI 分析完成", force=True)

    # ---- 内部 ----

    def _emit(self, pct, detail, force=False):
        # 只前进不后退：日志是乱序的（比如结构层可能先失败降级再继续），
        # 进度条往回跳会让用户以为出问题了。
        if not force and self.last_percent is not None and pct < self.last_percent:
            return
        self.last_percent = pct
        self.last_detail = detail
        self._report(stages.STAGE_AI, pct, detail, force=force)
