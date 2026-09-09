# ============================================================
# budget —— Token 预算估算（v0.3 阶段 2）
#
# 职责：在真正调 AI 之前，先估算「这一场分析大约要烧多少 token」。
# 估算超过所选模式的预算 → 编排器触发三级降级：
#   降级 1：普通区合并粗切（区块更少、单块更大）
#   降级 2：每个区块最多 1 个候选
#   降级 3：仍超预算 → 提示用户换精细模式，但继续执行
#           （覆盖铁律优先：不能因为省钱就跳过区块）
#
# 注意：这只是「出发前的估算」，真实花费以 CostTracker 事后报账为准。
# ============================================================

import config

# 中文约 0.6 token / 字（和 deepseek_client 里的估算口径一致）

# 海选提示词的固定开销（模板本身约 700 字，不含区块原文）
_SCREENING_TEMPLATE_CHARS = 700

# 每个候选的估算开销（token）：
# 海选输出一个候选约 230 token（v0.3.1 加了 highlight_type 字段）；
# 复审时每个候选要再喂一次原文节选 + 出一份分级结论
_CANDIDATE_OUTPUT_TOKENS = 230
_CANDIDATE_REVIEW_TOKENS = 350

# 复审环节的固定开销（模板 + 分析报告的输出）
_REVIEW_FIXED_TOKENS = 800

# 漏检质检环节（v0.3.1）：
#   质检输入 = 每个区块一行摘要（约 150 字）+ 候选简表
#   重扫 = 最坏情况重扫 MISS_CHECK_MAX_CHUNKS 个区块（按平均区块大小算）
_MISS_CHECK_SUMMARY_CHARS = 150
_MISS_CHECK_OUTPUT_TOKENS = 300


def estimate_tokens(text_chars: int) -> int:
    """字数 → token 数的粗略换算。"""
    return int(text_chars * 0.6)


def estimate_total(chunks: list, max_candidates: int) -> int:
    """估算「一场分析」的总 token 用量。

    chunks         —— chunker 吐出来的区块列表（用 chunk['char_count']）
    max_candidates —— 每个区块的候选上限

    组成：
      海选输入 = 所有区块原文 + 每块一份模板开销
      海选输出 = 候选数 × 每个候选的输出
      复审输入 = 候选数 × 每个候选的原文节选 + 结论
      复审输出 = 候选数 × 每个候选的结论 + 报告固定开销
    """
    if not chunks:
        return 0

    total_chars = sum(c["char_count"] for c in chunks)
    chunk_count = len(chunks)

    # 海选：输入
    screening_input = estimate_tokens(
        total_chars + _SCREENING_TEMPLATE_CHARS * chunk_count
    )
    # 海选：输出（按上限估，实际往往更少——估算偏保守是好事）
    est_candidates = chunk_count * max_candidates
    screening_output = est_candidates * _CANDIDATE_OUTPUT_TOKENS

    # 复审：输入（每个候选要再喂一次原文节选）+ 输出（每个候选一份结论 + 报告）
    review_input = est_candidates * _CANDIDATE_REVIEW_TOKENS
    review_output = est_candidates * 100 + _REVIEW_FIXED_TOKENS

    # 漏检质检（v0.3.1）：一次质检调用 + 最坏情况重扫几个区块
    avg_chunk_chars = total_chars / chunk_count
    miss_check_input = estimate_tokens(
        (_MISS_CHECK_SUMMARY_CHARS + 30) * chunk_count   # 摘要 + 候选简表行
    )
    rescreen_input = estimate_tokens(
        (avg_chunk_chars + _SCREENING_TEMPLATE_CHARS) * config.MISS_CHECK_MAX_CHUNKS
    )
    miss_check_total = miss_check_input + _MISS_CHECK_OUTPUT_TOKENS + rescreen_input

    return (screening_input + screening_output + review_input + review_output
            + miss_check_total)
