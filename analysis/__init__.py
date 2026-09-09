"""analysis 模块对外入口 —— 别的文件只需要 import 这一个包。

流程：读文字稿 → 拼需求单 → 调 DeepSeek → 报成本 → 解析成高光列表
"""

import json
from pathlib import Path

from .deepseek_client import call_deepseek, print_cost_report
from .prompt_builder import build_prompt


def analyze_transcript(transcript_path) -> list:
    """分析一份文字稿，返回高光片段列表（字典的列表）。"""
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        raise SystemExit(f"[找不到文件] {transcript_path}")

    # ---- 1. 读文字稿 ----
    text = transcript_path.read_text(encoding="utf-8")

    # ---- 2. 拼需求单（超过字数上限会自动截断） ----
    prompt, used_chars, truncated = build_prompt(text)
    if truncated:
        print(f"[截断] 文字稿太长，只装了前 {used_chars} 字（上限在 config.py 里调）")

    # ---- 3. 调 DeepSeek（缺钥匙会在这里友好报错） ----
    reply_text, usage = call_deepseek(prompt)

    # ---- 4. 报账单 ----
    print_cost_report(len(prompt), usage)

    # ---- 5. 解析 AI 的回复 ----
    highlights = _parse_reply(reply_text)

    # 按分数从高到低排个序，最好的放最前面
    highlights.sort(key=lambda h: h["score"], reverse=True)
    return highlights


def _parse_reply(reply_text: str) -> list:
    """把 AI 回复的 JSON 文本，清洗成规规矩矩的高光列表。"""
    try:
        data = json.loads(reply_text)
    except json.JSONDecodeError:
        raise SystemExit(
            f"[解析失败] DeepSeek 回复的不是合法 JSON：\n{reply_text[:300]}"
        )

    # 兼容两种返回：{"highlights": [...]} 或直接 [...]
    items = data.get("highlights", []) if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise SystemExit(f"[空结果] AI 没有挑出任何片段，原始回复：\n{reply_text[:300]}")

    # 逐条体检：字段齐全、分数在 1-10 之间
    clean = []
    for item in items:
        try:
            score = int(item["score"])
        except (KeyError, ValueError, TypeError):
            continue  # 分数坏的条目直接丢弃，不让一颗老鼠屎坏一锅粥
        if not (1 <= score <= 10):
            score = min(10, max(1, score))  # 越界就拉回来
        clean.append(
            {
                "start_time": str(item.get("start_time", "")),
                "end_time": str(item.get("end_time", "")),
                "score": score,
                "reason": str(item.get("reason", "")),
                "suggested_title": str(item.get("suggested_title", "")),
            }
        )
    if not clean:
        raise SystemExit("[空结果] 所有片段都没通过体检，看看上面的原始回复。")
    return clean


# ============================================================
# v0.3 阶段 2：AI 海选 + AI 复审（新分析流程）
#
# 编排整条流水线：
#   解析 → 信号扫描 → 智能分区 → 预算降级 → AI 海选（逐区块）
#   → 候选池 → AI 复审（五维打分 + 分析报告）→ 数量模式 → 输出
#
# v0.3.2 定级引擎（DECISIONS.md D-022/D-023）：
#   复审 AI 只输出五个维度子分（hook/contrast/persona/standalone/completeness），
#   编排器按 config.SCORE_V3_WEIGHTS 加权算出 final_score，再按阈值定级
#   S/A/B/C/D；命中「不值得剪」负面清单的候选本地封顶为 B 级。
#   定级全程可解释：每个高光的 breakdown 就是它的「判决书」。
#
# 旧的 analyze_transcript（v0.2 单次分析）原样保留（analyze.py 在用）。
# ============================================================

import config

from . import transcript_parser, event_scanner, chunker, budget
from .prompt_builder import (
    build_screening_prompt,
    build_review_prompt,
    build_miss_check_prompt,
    SCREENING_SYSTEM,
    REVIEW_SYSTEM,
    MISS_CHECK_SYSTEM,
)
from .deepseek_client import CostTracker
from .transcript_parser import _time_to_seconds as _parse_time

# 每个候选在复审时带的原文节选上限（字符），太长会把复审 prompt 撑爆
_CONTEXT_CHAR_LIMIT = 600


def analyze_transcript_v2(
    transcript_path,
    live_type: str = None,
    token_mode: str = None,
    quantity_mode: str = None,
    custom_count: int = None,
    client=None,
    verbose: bool = True,
) -> dict:
    """v0.3 新流程：文字稿 → 分区 → AI 海选 → AI 复审 → 最终高光 + 分析报告。

    参数：
        transcript_path —— 文字稿路径（[mm:ss - mm:ss] 台词 格式）
        live_type      —— 直播类型（默认读 config，可选见 event_scanner.AVAILABLE_TYPES）
        token_mode     —— 分析模式：「快速 / 标准 / 精细」（默认读 config）
        quantity_mode  —— 数量模式：「自动精选 / 候选池 / 自定义数量」
        custom_count   —— 自定义数量模式的个数（quantity_mode 为「自定义数量」时生效）
        client         —— AI 调用函数（默认用 DeepSeek；测试时可以塞一个假客户端）
        verbose        —— 是否打印过程日志（网页版会把这些日志捕获到界面）

    返回 dict：
        {"meta": 元信息, "highlights": [...], "rejected": [...],
         "report": {...}, "cost": {...}}
    """
    live_type = live_type or config.LIVE_TYPE_DEFAULT
    token_mode = token_mode or config.TOKEN_MODE_DEFAULT
    quantity_mode = quantity_mode or config.QUANTITY_MODE_DEFAULT
    custom_count = custom_count or config.DEFAULT_CUSTOM_COUNT

    if token_mode not in config.TOKEN_MODES:
        raise SystemExit(f"[配置] 未知分析模式：{token_mode}（可选：{list(config.TOKEN_MODES)}）")
    if quantity_mode not in config.QUANTITY_MODES:
        raise SystemExit(f"[配置] 未知数量模式：{quantity_mode}（可选：{config.QUANTITY_MODES}）")

    if client is None:
        from .deepseek_client import call_deepseek as client

    def say(msg):
        if verbose:
            print(msg)

    # ---------- 第 1~3 层：解析 → 信号扫描 → 智能分区（Phase 1 的三层） ----------
    segments = transcript_parser.parse_transcript_file(transcript_path)
    if not segments:
        raise SystemExit(f"[空稿] {transcript_path} 里没有解析出任何台词")
    duration = transcript_parser.total_duration(segments)

    buckets = event_scanner.scan(segments, live_type)
    chunks = chunker.build_chunks(buckets, segments)
    problems = chunker.check_coverage(chunks, duration)
    if problems:
        raise SystemExit("[铁律] 分区没盖满时间轴：" + "；".join(problems))
    say(f"[分区] 时长 {chunker.format_time(duration)}，共 {len(chunks)} 个区块"
        f"（直播类型：{live_type}）")

    # ---------- 第 4 层：预算规划（Token 三模式 + 三级降级） ----------
    mode_cfg = config.TOKEN_MODES[token_mode]
    budget_total = mode_cfg["budget"]
    max_cand = mode_cfg["max_candidates_per_chunk"]

    degrade_level = 0
    est = budget.estimate_total(chunks, max_cand)
    if est > budget_total:
        # 降级 1：普通区合并粗切（区块更少）
        degrade_level = 1
        chunks = chunker.build_chunks(
            buckets, segments, normal_seconds=config.NORMAL_CHUNK_SECONDS * 2
        )
        problems = chunker.check_coverage(chunks, duration)
        if problems:
            raise SystemExit("[铁律] 降级粗切后没盖满时间轴：" + "；".join(problems))
        est = budget.estimate_total(chunks, max_cand)
        say(f"[降级 1] 超出「{token_mode}」预算，普通区已合并粗切（剩 {len(chunks)} 个区块）")
    if est > budget_total:
        # 降级 2：每区块候选上限压到 1
        degrade_level = 2
        max_cand = 1
        est = budget.estimate_total(chunks, max_cand)
        say("[降级 2] 仍超预算，每个区块最多 1 个候选")
    if est > budget_total:
        # 降级 3：提示用户，但必须继续（覆盖铁律优先，不能因为省钱跳过区块）
        degrade_level = 3
        say(f"[提示] 预计约 {est} token，仍超过「{token_mode}」预算 {budget_total}。"
            f"长直播建议用「精细」模式；本次继续执行（所有区块照常分析）。")
    else:
        say(f"[预算] 预计约 {est} token（{token_mode}模式预算 {budget_total}）")

    # ---------- 第 5 层：AI 海选（每个区块独立审判，v0.3.1：宁多勿少） ----------
    tracker = CostTracker()
    weights = config.LIVE_TYPE_WEIGHTS.get(live_type, "")
    candidates = []

    for i, chunk in enumerate(chunks, 1):
        say(f"[海选] 区块 {i}/{len(chunks)}："
            f"{chunker.format_time(chunk['start'])} - {chunker.format_time(chunk['end'])}")
        prompt = build_screening_prompt(chunk["text"], live_type, max_cand, weights)
        reply, usage = client(prompt, system=SCREENING_SYSTEM)
        tracker.add(usage)

        found = _parse_screening_reply(reply)
        for c in found:
            c["chunk_index"] = i
            c["context"] = _grab_context(segments, c["start_time"], c["end_time"])
            candidates.append(c)
        say(f"[海选] 区块 {i}：{len(found)} 个候选")

    say(tracker.report())

    # ---------- 第 5.5 层：漏检质检（v0.3.1） ----------
    # 独立角色：不找高光，专查「有没有区块明显有爆点却没进候选池」。
    # 查出可疑区块 → 用更宽的标准重扫一遍，新候选并入候选池（不判生死）。
    flagged = _run_miss_check(client, tracker, chunks, candidates, live_type, say)
    miss_check_chunks = []
    for idx, reason in flagged:
        if not (1 <= idx <= len(chunks)):
            continue   # AI 报了个不存在的区块编号，忽略
        miss_check_chunks.append(idx)
        chunk = chunks[idx - 1]
        say(f"[质检] 区块 {idx} 疑似漏检（{reason[:50]}），重扫…")
        prompt = build_screening_prompt(
            chunk["text"], live_type, max_cand, weights, second_pass=True
        )
        reply, usage = client(prompt, system=SCREENING_SYSTEM)
        tracker.add(usage)
        found = _parse_screening_reply(reply)

        existing = {(c["start_time"], c["end_time"]) for c in candidates}
        added = 0
        for c in found:
            if (c["start_time"], c["end_time"]) in existing:
                continue   # 和已有候选时间重叠，跳过（防重复）
            c["chunk_index"] = idx
            c["context"] = _grab_context(segments, c["start_time"], c["end_time"])
            candidates.append(c)
            added += 1
        say(f"[质检] 区块 {idx} 重扫新增 {added} 个候选")

    if miss_check_chunks:
        say(tracker.report())

    # 一个候选都没有 → 不用复审，直接给用户一个交代
    if not candidates:
        return {
            "meta": _build_meta(transcript_path, live_type, token_mode, quantity_mode,
                                custom_count, duration, len(chunks), 0, degrade_level,
                                miss_check_chunks),
            "highlights": [],
            "rejected": [],
            "report": {
                "summary": "",
                "best_spread_point": "",
                "overall": "本场没有找到值得剪辑的片段",
                "why_not_more": "AI 海选和质检重扫都认为所有区块缺少可剪点"
                                "（召回优先原则下仍无候选，本场可能确实平淡）。",
            },
            "cost": tracker.to_dict(),
        }

    # ---------- 第 6 层：AI 复审（五维打分 + 分析报告，一次调用） ----------
    # v0.3.2：复审只打「五维子分」，总分和等级全由本地定级引擎算——
    # 可解释、可审计，AI 也不能靠一句漂亮理由把普通失误捧成爆款。
    say(f"[复审] 共 {len(candidates)} 个候选进入终审…")
    review_prompt = build_review_prompt(_format_candidates_for_review(candidates))
    reply, usage = client(
        review_prompt, system=REVIEW_SYSTEM, max_tokens=config.REVIEW_MAX_OUTPUT_TOKENS
    )
    tracker.add(usage)
    review = _parse_review_reply(reply)
    say(tracker.report())

    # 合并复审结论（按顺序一一对应；复审少给的条目用海选分兜底）
    results = review["results"]
    for i, cand in enumerate(candidates):
        if i < len(results):
            r = results[i]
            cand["dims"] = r["dims"]                 # 五维子分（判决书零件）
            cand["final_score"] = _weighted_final(r["dims"])   # 本地加权总分
            cand["grade"] = _grade_from_score(cand["final_score"])
            cand["negative_flags"] = r["negative_flags"]
            cand["why_cut"] = r["why_cut"]
            cand["risk"] = r["risk"]
            if r["confidence"] is not None:
                cand["confidence"] = r["confidence"]
        else:
            # 复审漏了这条（AI 回复条目数不足）：用海选分兜底定级
            cand["dims"] = {k: int(_clamp(cand["score"], 1, 10, 5))
                            for k in config.SCORE_V3_WEIGHTS}
            cand["final_score"] = cand["score"]
            cand["grade"] = _grade_from_score(cand["score"])
            cand["negative_flags"] = []
            cand["why_cut"] = ""
            cand["risk"] = ""
        # 负面清单硬约束：命中「不值得剪」规则 → 封顶 B 级（进不了 S/A）
        _apply_negative_cap(cand)

    # 淘汰理由由本地组装（grade D 时给个交代，不用 AI 写套话）
    for cand in candidates:
        if cand["grade"] == "D":
            cand["reject_reason"] = cand.get("risk") or (
                cand["negative_flags"] and "命中「不值得剪」规则" or "五维加权未达质量线"
            )
            cand["reject_reason"] = [cand["reject_reason"]]
        else:
            cand["reject_reason"] = []

    # 零输出禁令（v0.3.1）：全灭时只要最佳候选够底线，强制保留一个 C 级
    _enforce_no_zero(candidates)

    # ---------- 第 7 层：数量模式选择 ----------
    highlights, rejected = _select_quantity(
        candidates, quantity_mode, custom_count
    )

    return {
        "meta": _build_meta(transcript_path, live_type, token_mode, quantity_mode,
                            custom_count, duration, len(chunks), len(candidates),
                            degrade_level, miss_check_chunks),
        "highlights": highlights,
        "rejected": rejected,
        "report": review["report"],
        "cost": tracker.to_dict(),
    }


# ---------------- 编排器的内部工具函数 ----------------

def _build_meta(path, live_type, token_mode, quantity_mode, custom_count,
                duration, chunk_count, candidate_count, degrade_level,
                miss_check_chunks=None):
    """结果里的 meta 段：这场分析的基本盘。"""
    return {
        "transcript": str(path),
        "live_type": live_type,
        "token_mode": token_mode,
        "quantity_mode": quantity_mode,
        "custom_count": custom_count if quantity_mode == "自定义数量" else None,
        "duration": chunker.format_time(duration),
        "chunk_count": chunk_count,
        "candidate_count": candidate_count,
        "degrade_level": degrade_level,   # 0=没降级 1=粗切 2=限候选 3=提示后继续
        "miss_check_chunks": miss_check_chunks or [],  # 质检判定疑似漏检并重扫的区块
    }


def _grab_context(segments: list, start_time, end_time) -> str:
    """按候选的起止时间，从整场台词里捞出原文节选（复审时要再喂给 AI 一遍）。

    AI 海选返回的时间是字符串（如 "29:12"），先换算成秒再匹配；
    换算失败就返回空串（复审少点上下文，但不崩）。
    """
    start = _parse_time(str(start_time))
    end = _parse_time(str(end_time))
    if start is None or end is None:
        return ""

    lines = []
    used = 0
    for seg in segments:
        if seg["start"] < end and seg["end"] > start:
            line = f"[{chunker.format_time(seg['start'])} - {chunker.format_time(seg['end'])}] {seg['text']}"
            if used + len(line) > _CONTEXT_CHAR_LIMIT:
                break
            lines.append(line)
            used += len(line)
    return "\n".join(lines)


def _format_candidates_for_review(candidates: list) -> str:
    """把候选池拼成复审需求单里的清单文本。"""
    blocks = []
    for i, c in enumerate(candidates, 1):
        blocks.append(
            f"### 候选 {i}\n"
            f"时间：{c['start_time']} - {c['end_time']}\n"
            f"标题：{c['title']}（{c.get('highlight_type', '未分类')}）\n"
            f"海选评分：{c['score']}（爆款概率 {c.get('viral_probability', '中')}）\n"
            f"海选理由：{c['reason']}\n"
            f"原文节选：\n{c['context'] or '（无）'}"
        )
    return "\n\n".join(blocks)


def _clamp(value, low, high, default):
    """把数字夹回 [low, high]；不是数字就用 default。"""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, value))


def _parse_screening_reply(reply_text: str) -> list:
    """清洗海选回复 → 规规矩矩的候选列表。

    坏回复（不是 JSON / 没有候选）返回空列表而不是崩——
    一个区块翻车不该连累整场分析。
    """
    try:
        data = json.loads(reply_text)
    except (json.JSONDecodeError, TypeError):
        return []

    items = data.get("candidates", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        return []

    clean = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start_time = str(item.get("start_time", "")).strip()
        end_time = str(item.get("end_time", "")).strip()
        if not start_time or not end_time:
            continue   # 没时间的候选没法定位到视频，等于废票
        try:
            score = int(item.get("score", 0))
        except (TypeError, ValueError):
            continue
        score = int(_clamp(score, 1, 10, 5))

        clean.append({
            "start_time": start_time,
            "end_time": end_time,
            "title": str(item.get("title", "")).strip(),
            "highlight_type": str(item.get("highlight_type", "事件型")).strip(),
            "score": score,
            "reason": str(item.get("reason", "")).strip(),
            "category": str(item.get("category", "其他")).strip(),
            "viral_probability": str(item.get("viral_probability", "中")).strip(),
            "editing_advice": str(item.get("editing_advice", "")).strip(),
            "confidence": _clamp(item.get("confidence", 0.5), 0, 1, 0.5),
        })
    return clean


def _parse_review_reply(reply_text: str) -> dict:
    """清洗复审回复 → {"results": [...], "report": {...}}。

    v0.3.2 起复审只输出五个维度子分，不输出 final_score/grade：
    AI 打的是「零件」，本地按权重组装成总分再定级（可解释、可审计）。
    同时清洗负面清单命中标记和正反理由。
    """
    try:
        data = json.loads(reply_text)
    except (json.JSONDecodeError, TypeError):
        raise SystemExit(f"[解析失败] 复审回复的不是合法 JSON：\n{reply_text[:300]}")

    if not isinstance(data, dict):
        raise SystemExit(f"[解析失败] 复审回复格式不对：\n{reply_text[:300]}")

    results = []
    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue

        dims = {}
        for key in config.SCORE_V3_WEIGHTS:
            try:
                val = int(item.get(key, 5))
            except (TypeError, ValueError):
                val = 5
            dims[key] = int(_clamp(val, 1, 10, 5))

        # 负面清单标记：只认 config.NEGATIVE_RULES 里的规则名，别的扔掉
        flags_raw = item.get("negative_flags", [])
        if not isinstance(flags_raw, list):
            flags_raw = [flags_raw] if flags_raw else []
        negative_flags = [str(f).strip() for f in flags_raw
                          if str(f).strip() in config.NEGATIVE_RULES]

        results.append({
            "title": str(item.get("title", "")).strip(),
            "dims": dims,
            "negative_flags": negative_flags,
            "why_cut": str(item.get("why_cut", "")).strip(),
            "risk": str(item.get("risk", "")).strip(),
            "confidence": None if item.get("confidence") is None
            else _clamp(item.get("confidence"), 0, 1, 0.5),
        })

    report = data.get("report") if isinstance(data.get("report"), dict) else {}
    report = {
        "summary": str(report.get("summary", "")).strip(),
        "best_spread_point": str(report.get("best_spread_point", "")).strip(),
        "overall": str(report.get("overall", "")).strip(),
        "why_not_more": str(report.get("why_not_more", "")).strip(),
    }
    return {"results": results, "report": report}


# ---------------- v0.3.2 定级引擎：五维子分 → 加权总分 → 等级 ----------------

_DIM_LABELS = {
    "hook": "三秒吸引力",
    "contrast": "反差/意外",
    "persona": "人物表现力",
    "standalone": "独立成片",
    "completeness": "事件完整度",
}


def _weighted_final(dims: dict) -> float:
    """把 AI 打的五维子分按 config 权重算成总分（1-10 的小数，如 8.3）。"""
    weights = config.SCORE_V3_WEIGHTS
    total = 0.0
    for key, weight in weights.items():
        total += int(dims.get(key, 5)) * weight
    return round(total / 100.0, 1)


def _grade_from_score(score) -> str:
    """按终审分数推等级（复审漏给 grade、或旧格式回复时兜底用）。"""
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = 0.0
    if score >= config.GRADE_S_SCORE:
        return "S"
    if score >= config.GRADE_A_SCORE:
        return "A"
    if score >= config.GRADE_B_SCORE:
        return "B"
    if score >= config.GRADE_C_SCORE:
        return "C"
    return "D"


_GRADE_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}


def _apply_negative_cap(candidate: dict):
    """负面清单硬约束（D-023）：命中「不值得剪」规则的候选封顶为 B 级，
    进不了 S/A——普通失误、单纯惊讶这类「假高光」不允许被 AI 捧上精品位。
    只降不升：原本就是 C/D 的低级候选不受影响（不会被意外"救活"）。
    """
    if not candidate.get("negative_flags"):
        return
    cap = config.NEGATIVE_RULE_CAP_GRADE
    if _GRADE_RANK.get(candidate["grade"], 9) < _GRADE_RANK.get(cap, 2):
        candidate["grade"] = cap


def _select_quantity(candidates: list, quantity_mode: str, custom_count: int):
    """按数量模式挑出最终展示的高光，剩下的进 rejected。

    v0.3.2 分级规则（S/A/B/C + D 淘汰）：
        S 爆款候选：三秒吸引力高 + 有传播结构 + 有明显记忆点
        A 强推荐：适合制作正式切片
        B 测试素材：有潜力，需人工判断（命中负面清单的最高档）
        C 备用素材：有内容，传播能力弱
        D 淘汰（进 rejected，带理由）
        自动精选 —— 只展示 S/A（AI 盖章值得剪的）
        候选池   —— 展示 S/A/B/C 全部（B/C 供用户自己权衡）
        自定义数量 —— 按终审分数取前 N 个，标注等级名

    返回 (highlights, rejected)：
        highlights —— 最终展示列表（按分数降序）
        rejected   —— 没进最终列表的候选（带原因，供用户翻案）
    """
    # 先给每个候选发身份证（未来 UI 的 👍/👎 反馈要靠 clip_id 记账）
    for n, c in enumerate(candidates, 1):
        c["clip_id"] = f"clip-{n:03d}"

    if quantity_mode == "自动精选":
        picked = [c for c in candidates if c["grade"] in ("S", "A")]

    elif quantity_mode == "候选池":
        picked = [c for c in candidates if c["grade"] in ("S", "A", "B", "C")]

    else:  # 自定义数量：按分数取前 N 个，标注质量分层
        picked = sorted(candidates, key=lambda c: c["final_score"], reverse=True)
        picked = picked[:max(1, custom_count)]
        quality_map = {"S": "爆款候选", "A": "强推荐", "B": "测试素材", "C": "备用素材"}
        for c in picked:
            c["quality"] = quality_map.get(c["grade"], "备用素材")

    picked_set = set(id(c) for c in picked)
    picked = sorted(picked, key=lambda c: c["final_score"], reverse=True)

    highlights, rejected = [], []
    for c in candidates:
        entry = {
            "clip_id": c["clip_id"],
            "start_time": c["start_time"],
            "end_time": c["end_time"],
            "title": c["title"],
            "highlight_type": c.get("highlight_type", "事件型"),
            "score": c["final_score"],          # v0.3.2：本地加权总分（1-10 小数）
            "first_round_score": c["score"],    # 海选原始分（仅供参考）
            "grade": c["grade"],
            "reason": c["reason"],              # 海选理由
            "why_cut": c.get("why_cut", ""),    # v0.3.2：复审「为什么值得剪」
            "risk": c.get("risk", ""),          # v0.3.2：复审「可能不值得剪」
            "negative_flags": c.get("negative_flags", []),  # 命中「不值得剪」规则
            "dims": _entry_dims(c.get("dims", {})),         # v0.3.2：五维子分判决书
            "category": c["category"],
            "viral_probability": c["viral_probability"],
            "editing_advice": c["editing_advice"],
            "confidence": c["confidence"],
            "ai_recommend": c["grade"] in ("S", "A"),   # 兼容旧字段：S/A 级 = AI 推荐
        }
        if c.get("forced_keep"):
            entry["forced_keep"] = True
        if id(c) in picked_set:
            if "quality" in c:
                entry["quality"] = c["quality"]
            highlights.append(entry)
        else:
            # 没进最终列表的：说明为什么
            if c["grade"] == "D" and c["reject_reason"]:
                entry["reject_reason"] = c["reject_reason"]
            elif c.get("forced_keep"):
                entry["reject_reason"] = ["召回优先保留的候选，未进入本模式展示范围"]
            else:
                entry["reject_reason"] = [
                    f"复审评级 {c['grade']}，未进入「{quantity_mode}」模式的展示范围"
                ]
            rejected.append(entry)

    return highlights, rejected


def _entry_dims(dims: dict) -> dict:
    """把内部维度键转成用户可读的中文标签（保留权重信息）。"""
    weights = config.SCORE_V3_WEIGHTS
    return {
        f"{_DIM_LABELS.get(k, k)}（权重{w}%）": int(dims.get(k, 0))
        for k, w in weights.items()
    }


# ---------------- v0.3.1 新增：零输出禁令 / 漏检质检 ----------------

def _enforce_no_zero(candidates: list):
    """零输出禁令（v0.3.1）：复审把候选全灭了时，强制捞回最好的一个。

    条件：最高 final_score >= FORCED_KEEP_MIN_SCORE（默认 4）。
    捞回来的标 grade=C + forced_keep=True，最终由用户人工复核——
    宁可让用户多看一个平庸候选，也不要漏掉一个可能爆的。
    """
    if not candidates:
        return
    best = max(candidates, key=lambda c: c["final_score"])
    if best["final_score"] >= config.GRADE_C_SCORE:
        return   # 有正常候选，不用捞
    if best["final_score"] < config.FORCED_KEEP_MIN_SCORE:
        return   # 连底线都没到，真垃圾，允许零输出
    best["grade"] = "C"
    best["forced_keep"] = True
    best["reject_reason"] = ["复审未达质量线，按召回优先原则保留最佳候选，请人工复核"]


def _run_miss_check(client, tracker, chunks, candidates, live_type, say):
    """漏检质检：把区块摘要 + 候选简表发给质检 AI，查出可疑区块。

    返回 [(区块编号, 原因), ...]，最多 config.MISS_CHECK_MAX_CHUNKS 个
    （防止 AI 一口气报十几个区块，成本失控）。
    质检回复坏 JSON 不崩——质检是保险丝，保险丝坏了不能连累主流程。
    """
    prompt = build_miss_check_prompt(
        live_type,
        _summarize_chunks(chunks, live_type, candidates),
        _short_candidates_text(candidates),
    )
    say(f"[质检] 检查 {len(chunks)} 个区块有没有漏掉的爆点…")
    reply, usage = client(
        prompt, system=MISS_CHECK_SYSTEM, max_tokens=config.MISS_CHECK_OUTPUT_TOKENS
    )
    tracker.add(usage)
    return _parse_miss_check_reply(reply)


def _summarize_chunks(chunks: list, live_type: str, candidates: list) -> str:
    """把每个区块压成一行摘要（纯本地计算，零成本）。

    摘要 = 编号 + 热/普 + 时间范围 + 信号分 + 已有候选数 + 关键句
    （含强信号词的台词，最多 3 句）。
    质检 AI 靠这个判断「这个区块看起来有爆点，怎么候选池里没有」。
    """
    lex = event_scanner.LEXICONS.get(live_type, {})
    strong_words = set(event_scanner.COMMON_STRONG) | set(lex.get("strong", []))
    strong_words.update(event_scanner.load_user_lexicon())

    # 每个区块已有几个候选（质检最关心的对比信息）
    cand_count = {}
    for c in candidates:
        idx = c.get("chunk_index")
        if idx:
            cand_count[idx] = cand_count.get(idx, 0) + 1

    lines = []
    for i, ch in enumerate(chunks, 1):
        kind = "热区" if ch["hot"] else "普通"
        key_lines = []
        for seg in ch["segments"]:
            if any(w in seg["text"] for w in strong_words):
                key_lines.append(seg["text"][:60])
            if len(key_lines) >= 3:
                break
        if not key_lines and ch["segments"]:
            key_lines = [ch["segments"][0]["text"][:60]]
        key_text = "；".join(key_lines) if key_lines else "（无台词）"
        lines.append(
            f"区块{i}（{kind}）{chunker.format_time(ch['start'])}-"
            f"{chunker.format_time(ch['end'])} 信号分{ch['score']} "
            f"已有候选{cand_count.get(i, 0)}个 关键句：{key_text}"
        )
    return "\n".join(lines)


def _short_candidates_text(candidates: list) -> str:
    """候选池简表（质检用）：一行一个，只留定位信息。"""
    if not candidates:
        return "（候选池为空——所有区块都没有产出候选）"
    lines = []
    for c in candidates:
        lines.append(
            f"区块{c.get('chunk_index', '?')} {c['start_time']}-{c['end_time']} "
            f"{c['score']}分 {c['title']}"
        )
    return "\n".join(lines)


def _parse_miss_check_reply(reply_text: str) -> list:
    """清洗质检回复 → [(区块编号, 原因), ...]。坏回复返回空列表（不崩）。"""
    try:
        data = json.loads(reply_text)
    except (json.JSONDecodeError, TypeError):
        return []

    checks = data.get("checks", []) if isinstance(data, dict) else []
    if not isinstance(checks, list):
        return []

    flagged = []
    for item in checks:
        if not isinstance(item, dict) or not item.get("miss_risk"):
            continue
        try:
            idx = int(item.get("chunk", 0))
        except (TypeError, ValueError):
            continue
        reason = str(item.get("reason", "")).strip()
        flagged.append((idx, reason))

    # 最多重扫 N 个区块（成本保险丝）
    return flagged[:config.MISS_CHECK_MAX_CHUNKS]
