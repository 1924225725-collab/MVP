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

from . import transcript_parser, event_scanner, chunker, budget, event_cluster
from . import story_context as _sc
from .prompt_builder import (
    build_screening_prompt,
    build_review_prompt,
    build_miss_check_prompt,
    build_event_judge_prompt,
    build_report_prompt,
    build_batch_review_prompt,
    SCREENING_SYSTEM,
    REVIEW_SYSTEM,
    MISS_CHECK_SYSTEM,
    EVENT_JUDGE_SYSTEM,
    REPORT_SYSTEM,
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
        # v0.4 Step3.1-A1：质检补的候选 vs 已有候选的去重，从「exact 时间匹配」改为
        # 「时间重叠 > 50%」。原 exact 匹配会漏掉「同一瞬间被海选/质检各报一次、时间差几秒」
        # 的重复候选（如 49:41-49:53 与 49:38-49:53），它们带着重复进同一簇 → AI 困惑判 split
        # → 各自孤零零判 D（微波炉案例）。用重叠系数能精确去掉这类重复，又不误删真正
        # 时间错开/仅少量重叠的补漏候选（本函数只在质检单向去重用，不碰事件级 _dedupe_events）。
        # 先把已有候选时间换算成秒（算不出来就保留原样，走 old exact 兜底）
        existing_sec = []
        for c in candidates:
            s = _parse_time(c["start_time"])
            e = _parse_time(c["end_time"])
            if s is not None and e is not None:
                existing_sec.append((s, e))
        added = 0
        for c in found:
            if (c["start_time"], c["end_time"]) in existing:
                continue   # 和已有候选完全同时间，跳过（防重复）
            # 时间高度重叠也算重复（同一爆点被两次扫描发现，不是真的漏检）
            cs = _parse_time(c["start_time"])
            ce = _parse_time(c["end_time"])
            if cs is not None and ce is not None:
                if any(event_cluster._overlap_score(cs, ce, es, ee) > 0.5
                       for es, ee in existing_sec):
                    continue
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

    # ---------- 第 5.6 层：事件聚合（v0.4 步骤 2）----------
    # 先把碎片还原成完整事件，再交给复审评分——**先聚合，再评分**（需求第七条）。
    # 这一层不做任何取舍：本地只提分组，AI 才判断是不是同一件事。
    events, event_stats = _run_event_aggregation(
        client, tracker, segments, candidates, duration, say
    )

    # ---------- 第 6 层：AI 复审（分批 + 事件级评分 + 动态时长 + 全局排序） ----------
    # v0.3.2：复审只打「五维子分」，总分和等级全由本地定级引擎算——
    # 可解释、可审计，AI 也不能靠一句漂亮理由把普通失误捧成爆款。
    # v0.4 步骤 3：评审对象是「完整事件」（step 2 事件聚合产物），不是爆点碎片：
    #   · 复审从「一次调用审完所有事件」改成分批（_review_in_batches）——每批控制
    #     事件数与上下文，防止单次 prompt 过大、后半段被忽略、前半段偏置。
    #   · 上下文用时间窗口（事件边界 ± 缓冲），与最终剪辑时长完全分离。
    #   · AI 输出 recommended_start/end/duration + duration_reason（动态时长，不固定 20/30/60）。
    #   · 评分仍只打五维子分（1-10），本地加权 ×10 得 100 分制总分，再按四档定级。
    #   · 各 batch 独立复审，最后统一按 final_score 做 Global Ranking（批次无优劣）。
    say(f"[复审] 共 {len(events)} 个事件，分批复审…")
    # review_map: {event_id: 复审结论 dict}，按 event_id 对号入座（禁止依赖返回顺序）
    review_map = _review_in_batches(client, tracker, segments, events, say)
    say(tracker.report())

    # 合并复审结论：按 event_id 对号入座（AI 可能漏条），对不上用海选分兜底
    for cand in events:
        r = review_map.get(cand["event_id"])
        if r:
            cand["dims"] = r["dims"]                 # 五维子分（判决书零件）
            cand["final_score"] = r["final_score"]   # 本地加权 100 分制总分
            cand["grade"] = r["grade"]
            cand["negative_flags"] = r["negative_flags"]
            cand["why_cut"] = r["why_cut"]
            cand["risk"] = r["risk"]
            if r["confidence"] is not None:
                cand["confidence"] = r["confidence"]
            # v0.4 A3：保留 AI 声明的「不值得剪」原因类型 + 是否被 D 门控降 C（供审计）
            cand["reject_reason_kind"] = r.get("reject_reason_kind", "")
            if cand["grade"] == "C" and r.get("reject_reason_kind") and \
                    r["reject_reason_kind"] != "truly_low_value":
                cand["d_guarded"] = True   # 本会判 D，因「AI 不确定/不完整/上下文不够」降 C
            # v0.4 步骤 3：动态剪辑范围（recommended_*），与上下文窗口分离。
            # 时间统一成标准 mm:ss（AI 可能回 HH:MM:SS 或 MM:SS 混用）；越界钳回事件范围。
            ev_start = cand.get("start")
            ev_end = cand.get("end")
            rstart, rstart_sec = _norm_rec_ts(
                r.get("recommended_start"), ev_start or 0, duration)
            rend, rend_sec = _norm_rec_ts(
                r.get("recommended_end"), ev_end or 0, duration)
            if rstart_sec is not None and rend_sec is not None and rend_sec < rstart_sec:
                rstart_sec, rend_sec = rend_sec, rstart_sec   # 起止写反就纠正
                rstart, rend = rend, rstart
            cand["recommended_start"] = rstart
            cand["recommended_end"] = rend
            rdur = r.get("recommended_duration")
            try:
                rdur = int(rdur)
            except (TypeError, ValueError):
                rdur = None
            if rdur is None and rstart_sec is not None and rend_sec is not None:
                rdur = int(round(rend_sec - rstart_sec))   # AI 没给时长 → 用起止差兜底
            cand["recommended_duration"] = max(0, rdur) if rdur is not None else None
            if r.get("duration_reason"):
                cand["duration_reason"] = r["duration_reason"]
            # 合理性校验：recommended 起止若严重偏离事件边界（AI 偶发把推荐点写成
            # 全场末尾/其他事件时间），按事件边界兜底——不能把剪辑点指向错误的位置。
            if (rstart_sec is not None and rend_sec is not None
                    and ev_start is not None and ev_end is not None):
                drift = max(abs(rstart_sec - ev_start), abs(rend_sec - ev_end))
                if drift > config.RECOMMEND_MAX_DRIFT:
                    say(f"[复审·警示] {cand['event_id']} recommended 偏离事件边界 "
                        f"{int(drift)}s，按事件边界兜底")
                    cand["recommended_start"] = cand["start_time"]
                    cand["recommended_end"] = cand["end_time"]
                    if cand.get("recommended_duration") is None:
                        cand["recommended_duration"] = cand.get("duration")
                    cand["duration_reason"] = "（推荐点偏离事件过远，按事件边界）"
        else:
            # 复审漏了这条（AI 回复条目数不足）：用海选分兜底定级。
            # 海选分是 1-10，兜底成 100 分制要 ×10，否则和阈值（90/80/60/50）对不上。
            cand["dims"] = {k: int(_clamp(cand["score"], 1, 10, 5))
                            for k in config.SCORE_V3_WEIGHTS}
            cand["final_score"] = round(_clamp(cand["score"], 0, 10, 5) * 10.0, 1)
            cand["grade"] = _grade_from_score(cand["final_score"])
            cand["negative_flags"] = []
            cand["why_cut"] = ""
            cand["risk"] = ""
            # 复审漏条（未覆盖到）：动态剪辑范围回退到事件边界本身
            cand["recommended_start"] = cand.get("start_time", "")
            cand["recommended_end"] = cand.get("end_time", "")
            cand["recommended_duration"] = cand.get("duration")
            cand["duration_reason"] = "（复审未覆盖，按事件边界）"
        # 负面清单硬约束：命中「不值得剪」规则 → 封顶 B 级（进不了 S/A）
        _apply_negative_cap(cand)

    # 淘汰理由由本地组装（grade D 时给个交代，不用 AI 写套话）
    for cand in events:
        if cand["grade"] == "D":
            cand["reject_reason"] = cand.get("risk") or (
                cand["negative_flags"] and "命中「不值得剪」规则" or "五维加权未达质量线"
            )
            cand["reject_reason"] = [cand["reject_reason"]]
        else:
            cand["reject_reason"] = []

    # 零输出禁令（v0.3.1）：全灭时只要最佳候选够底线，强制保留一个 C 级
    _enforce_no_zero(events)

    # Global Ranking：分批复审完成后，跨 batch 统一按最终分排序（需求十二）——
    # 各 batch 用同一评分标准（config 权重 + 本地定级），这里只做全量排序，
    # 不因 batch 先后给任何事件额外优势（天然消除前半段偏置）。
    events.sort(key=lambda c: c["final_score"], reverse=True)

    # 独立生成整场 AI 分析报告（基于各事件精华，一次小调用，成本低）
    report = _build_ai_report(client, tracker, events, say)

    # ---------- 第 7 层：数量模式选择 ----------
    highlights, rejected = _select_quantity(
        events, quantity_mode, custom_count
    )

    return {
        "meta": _build_meta(transcript_path, live_type, token_mode, quantity_mode,
                            custom_count, duration, len(chunks), len(candidates),
                            degrade_level, miss_check_chunks, event_stats),
        "highlights": highlights,
        "rejected": rejected,
        "report": report,
        "cost": tracker.to_dict(),
    }


# ---------------- 编排器的内部工具函数 ----------------

def _build_meta(path, live_type, token_mode, quantity_mode, custom_count,
                duration, chunk_count, candidate_count, degrade_level,
                miss_check_chunks=None, event_stats=None):
    """结果里的 meta 段：这场分析的基本盘。"""
    meta = {
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
    if event_stats:
        # v0.4 事件聚合审计数据：开发者模式靠它检查 AI 有没有错合并/漏合并
        meta["event_stats"] = event_stats
    return meta


def _grab_context(segments: list, start_time, end_time, char_limit=None) -> str:
    """按候选的起止时间，从整场台词里捞出原文节选（复审时要再喂给 AI 一遍）。

    AI 海选返回的时间是字符串（如 "29:12"），先换算成秒再匹配；
    换算失败就返回空串（复审少点上下文，但不崩）。

    char_limit：字符上限，不传就用 _CONTEXT_CHAR_LIMIT。
    v0.4 起事件级候选比单句长，复审需要看更长的原文，所以这个参数可调。
    """
    limit = char_limit or _CONTEXT_CHAR_LIMIT
    start = _parse_time(str(start_time))
    end = _parse_time(str(end_time))
    if start is None or end is None:
        return ""

    lines = []
    used = 0
    for seg in segments:
        if seg["start"] < end and seg["end"] > start:
            line = f"[{chunker.format_time(seg['start'])} - {chunker.format_time(seg['end'])}] {seg['text']}"
            if used + len(line) > limit:
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


def _format_events_for_review(events: list) -> str:
    """把事件池拼成复审需求单里的清单文本。

    v0.4 起复审审的是「完整事件」，不是爆点碎片——
    所以清单里要有故事结构（铺垫/发展/结果）和最强爆点，
    让 AI 判断的是「这件事值不值得剪」，而不是「这句话好不好笑」。
    """
    blocks = []
    for i, ev in enumerate(events, 1):
        st = ev.get("structure") or {}
        src = ", ".join(ev.get("source_candidates", [])) or "无"
        blocks.append(
            f"### 事件 {i}（{ev['event_id']}）\n"
            f"时间：{ev['start_time']} - {ev['end_time']}"
            f"（时长 {ev.get('duration', 0)} 秒）\n"
            f"事件摘要：{ev.get('summary') or '（无）'}\n"
            f"事件类型：{ev.get('event_type') or '未分类'}\n"
            f"故事结构：铺垫——{st.get('setup') or '无'}；"
            f"发展——{st.get('development') or '无'}；"
            f"结果——{st.get('payoff') or '无'}\n"
            f"最强爆点：{ev.get('strongest_moment') or '（无）'}\n"
            f"由 {ev.get('source_count', 1)} 个原始候选聚合而成（{src}）\n"
            f"原文节选：\n{ev.get('context') or '（无）'}"
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
            "reason": str(item.get("reason", "")).strip()[:150],
            "category": str(item.get("category", "其他")).strip(),
            "viral_probability": str(item.get("viral_probability", "中")).strip(),
            "editing_advice": str(item.get("editing_advice", "")).strip()[:80],
            "confidence": _clamp(item.get("confidence", 0.5), 0, 1, 0.5),
            # v0.4 Step 3.2-B1: 事件种子信息——让聚合/复审知道这个候选是不是某个完整事件的一部分
            "event_context": str(item.get("event_context", "")).strip()[:200],
            "event_boundary_note": str(item.get("event_boundary_note", "")).strip()[:200],
        })
    return clean


# 五维子分允许的「等价键名」：内部统一用 config.SCORE_V3_WEIGHTS 的键（persona），
# 但 AI 输出协议可能用 personality 等写法——都认，取先命中的那个。
_DIM_KEY_ALIASES = {
    "persona": ("persona", "personality", "personality_score", "persona_score"),
}
# AI 没给满的维度键（schema 校验用）：记录 warning，不用静默默认 5 分掩盖。
_schema_warnings = []   # 模块级收集本场所有 schema warning


def _norm_reject_kind(value):
    """规范化 AI 填的「不值得剪」原因类型：只认 config.REJECT_KINDS 四类，否则返回空串。"""
    if not value:
        return ""
    v = str(value).strip()
    return v if v in config.REJECT_KINDS else ""


def _extract_dim_scores(item: dict, warnings: list) -> dict:
    """从单条复审结果里提取五维子分，兼容嵌套 scores 或平铺 _score。

    返回 {config键: 1-10 整数}。AI 没给的维度：
      · 有记录在案 → 走 warnings，用 5 兜底（不能静默，要给用户交代）；
      · 没记录 → 也走 warnings，用 5 兜底。
    绝不「无提示默认 5」——需求第十节：字段缺失必须记录 warning + 明确 fallback。
    """
    # 先看有没有嵌套的 scores:{hook:...}
    scores_block = item.get("scores")
    if not isinstance(scores_block, dict):
        scores_block = item

    dims = {}
    for key in config.SCORE_V3_WEIGHTS:
        val = None
        aliases = _DIM_KEY_ALIASES.get(key, (key,))
        # 兼容三种写法（取先命中的）：
        #   ① 嵌套 scores:{hook:...}  ② 平铺 hook  ③ 平铺 hook_score / personality_score
        for name in aliases:
            for cand in (scores_block.get(name),
                         scores_block.get(f"{name}_score"),
                         item.get(name),
                         item.get(f"{name}_score")):
                if cand is not None:
                    val = cand
                    break
            if val is not None:
                break
        if val is None:
            # schema 校验失败：明确记 warning + 用默认 5 兜底（不是静默）
            warnings.append(f"事件缺五维子分「{key}」，已按 5 分兜底")
            val = 5
        try:
            val = int(val)
        except (TypeError, ValueError):
            warnings.append(f"事件五维子分「{key}」不是数字（{val!r}），已按 5 分兜底")
            val = 5
        dims[key] = int(_clamp(val, 1, 10, 5))
    return dims


def _parse_review_reply(reply_text: str) -> dict:
    """清洗一条分批复审的回复 → {"results": [...], "warnings": [...]}。

    v0.3.2 起复审只输出五维子分，不输出 final_score/grade：
    AI 打的是「零件」，本地按权重组装成总分再定级（可解释、可审计）。
    v0.4 步骤 3：每条多带动态剪辑范围（recommended_*）+ duration_reason；
    缺字段一律记 warning，不静默用 5 分掩盖（需求第十节 schema 校验）。

    注意：分批复审时不再返回整场 report（report 由 _build_ai_report 单独生成）。
    返回 {"results": [...], "warnings": [...]}；坏 JSON 返回空 results（调用方兜底）。
    """
    try:
        data = json.loads(reply_text)
    except (json.JSONDecodeError, TypeError):
        return {"results": [], "warnings": [f"分批复审回复不是合法 JSON：{reply_text[:100]}"]}

    if not isinstance(data, dict):
        return {"results": [], "warnings": ["分批复审回复格式不对"]}

    warnings = []
    results = []
    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue
        eid = str(item.get("event_id", "")).strip()
        if not eid:
            warnings.append("分批复审有条目没带 event_id，已跳过（无法对号入座）")
            continue

        dims = _extract_dim_scores(item, warnings)
        # schema 校验事件级字段：事件 ID / 五维子分 / 推荐剪辑范围是硬性字段
        rstart = str(item.get("recommended_start", "")).strip()
        rend = str(item.get("recommended_end", "")).strip()
        rdur_raw = item.get("recommended_duration")
        try:
            rdur = int(rdur_raw)
        except (TypeError, ValueError):
            rdur = None
        if not rstart or not rend:
            warnings.append(f"{eid} 缺 recommended_start/end（动态剪辑范围），按事件边界兜底")
        if rdur is None:
            warnings.append(f"{eid} 缺 recommended_duration，按事件实际时长兜底")

        # AI 若认为它看到的上下文不足以判断 setup/payoff → 标记扩窗重审
        need_expand = bool(item.get("context_incomplete", False))

        # 负面清单标记：只认 config.NEGATIVE_RULES 里的规则名，别的扔掉
        flags_raw = item.get("negative_flags", [])
        if not isinstance(flags_raw, list):
            flags_raw = [flags_raw] if flags_raw else []
        negative_flags = [str(f).strip() for f in flags_raw
                          if str(f).strip() in config.NEGATIVE_RULES]

        results.append({
            "event_id": eid,
            "title": str(item.get("title", "")).strip(),
            "dims": dims,
            "negative_flags": negative_flags,
            "why_cut": str(item.get("why_cut", "")).strip(),
            "risk": str(item.get("risk", "")).strip(),
            "confidence": None if item.get("confidence") is None
            else _clamp(item.get("confidence"), 0, 1, 0.5),
            "recommended_start": rstart,
            "recommended_end": rend,
            "recommended_duration": rdur,
            "duration_reason": str(item.get("duration_reason", "")).strip(),
            "_need_expand": need_expand,
            # v0.4 A3：AI 判「不值得剪」时声明原因类型（只认四类合法值，别的不认）
            "reject_reason_kind": _norm_reject_kind(item.get("reject_reason_kind")),
        })

    return {"results": results, "warnings": warnings}


# ============================================================
# v0.4 步骤 3：分批复审 + 动态剪辑时长 + 上下文时间窗口
#
# 为什么分批（需求八）：一次把所有事件交给 AI，会导致单次 prompt 过大、
# 后面的事件被忽略、前半段事件占便宜（前半段偏置）、预算难控、失败难重试。
# 分批后：每批独立审 → 结果按 event_id 对号 → 全局排序。
#
# 两条不可混淆的量（需求三）：
#   Context Window —— AI 为了理解事件而阅读的原文范围（事件边界 ± 缓冲）
#   Clip Duration —— 最终推荐剪多长（recommended_duration），由 AI 单独判断
#   AI 读 5 分钟上下文，不代表要剪 5 分钟——两者完全分离。
# ============================================================

def _norm_rec_ts(value, fallback_sec, duration=None):
    """把 AI 回的 recommended 时间字符串统一成标准 mm:ss（>1h 用 h:mm:ss）。

    真实 API 实测发现 AI 会回 HH:MM:SS（00:48:20）或 MM:SS（05:17）混用，
    必须统一否则 UI / 后续切视频的时间解析会乱。规范化失败/越界 → 用 fallback。
    返回 (标准字符串, 秒)。
    """
    sec = _parse_time(str(value)) if value else None
    if sec is None:
        sec = fallback_sec
    if duration and sec is not None:
        sec = min(float(duration), max(0.0, sec))
    if sec is None:
        return str(value) if value else "", None
    sec = float(sec)
    # 统一输出格式（>1h → h:mm:ss；否则 mm:ss）
    if sec >= 3600:
        h = int(sec // 3600); m = int((sec % 3600) // 60); s = int(sec % 60)
        ts = f"{h:02d}:{m:02d}:{s:02d}"
    else:
        ts = chunker.format_time(sec)
    return ts, sec


def _event_seconds(ev: dict) -> tuple:
    """事件对象里已有的起止秒（_make_event 已算好 start/end）。算不出返回 (None, None)。"""
    return ev.get("start"), ev.get("end")


def _event_review_context(segments, ev: dict, expand_level=0, char_cap=None) -> str:
    """取一个事件复审要用的上下文原文：事件边界 ± 缓冲。

    expand_level：
        0 → 事件 start-before 到 end+after（默认 ±60s，config.REVIEW_CONTEXT）
        1 → ±180s；2 → ±300s（事件 setup/payoff 不完整需要更多铺垫时）
    以事件边界为锚整段捞取——**长事件天然完整进入**（不会被 ±60 窗口切掉本体），
    缓冲只是给 AI 判断「从哪起剪、在哪收」的额外铺垫，与 recommended_duration 无关。

    受 char_cap 约束：超了就优先保留贴近事件中心的部分（宁缺前后铺垫，不切事件本体）。
    """
    start, end = _event_seconds(ev)
    if start is None or end is None:
        return ev.get("context", "")

    ctx_cfg = config.REVIEW_CONTEXT
    default_before = ctx_cfg.get("default_before", 60)
    default_after = ctx_cfg.get("default_after", 60)
    levels = ctx_cfg.get("expand_levels", [180, 300])

    before = default_before
    after = default_after
    if expand_level > 0:
        pad = levels[min(expand_level - 1, len(levels) - 1)]
        before = after = pad

    cap = char_cap or ctx_cfg.get("char_budget", 4000)
    lo, hi = start - before, end + after

    # 捞整段落在 (lo, hi) 的台词
    picked = []
    for seg in segments:
        if seg["start"] < hi and seg["end"] > lo:
            picked.append(seg)

    # 超字符预算：从最贴近事件中心的两侧优先保留，逐段外扩丢弃，直到装得下。
    if sum(len(s["text"]) + 12 for s in picked) > cap:
        center = (start + end) / 2.0
        picked.sort(key=lambda s: (abs((s["start"] + s["end"]) / 2.0 - center), s["start"]))
        kept, used = [], 0
        for seg in picked:
            line = (f"[{chunker.format_time(seg['start'])} - "
                    f"{chunker.format_time(seg['end'])}] {seg['text']}")
            if used + len(line) > cap:
                break
            kept.append(seg)
            used += len(line)
        picked = sorted(kept, key=lambda s: s["start"])

    return "\n".join(
        f"[{chunker.format_time(s['start'])} - {chunker.format_time(s['end'])}] {s['text']}"
        for s in sorted(picked, key=lambda x: x["start"])
    )


def _review_in_batches(client, tracker, segments, events, say,
                       expand_level=0, depth=0):
    """把事件分批复审，返回 {event_id: 复审结论 dict}。

    分批策略（config.REVIEW_BATCH）：
      每批最多 max_events_per_batch 个事件；一批一个 prompt（每个事件带各自上下文），
      AI 按 event_id 逐个回评审 JSON（禁依赖顺序，靠 event_id 对号）。
    批内预算控制：REVIEW_CONTEXT.char_budget 约束单批总上下文字符，
      超了从「上下文最不需要的」事件上扣（按 final 前的 score 预估优先级）。
    自适应扩窗：若某批 AI 返回的事件标 context_incomplete（setup/payoff 在窗口外），
      该事件单独用更大 expand_level 重审一次（最多 depth+1 层，防无限扩）。

    返回 {event_id: {dims, final_score, grade, negative_flags, why_cut, risk,
                     confidence, recommended_start/end/duration, duration_reason}}
    """
    cfg = config.REVIEW_BATCH
    batch_size = cfg.get("max_events_per_batch", 3)
    char_budget = config.REVIEW_CONTEXT.get("char_budget", 4000)

    # 先粗排：把「海选分 ×10」当预估优先级，批内预算不足时从低优先级事件上扣上下文
    for ev in events:
        ev.setdefault("_est_score", _clamp(ev.get("score", 5), 1, 10, 5) * 10.0)

    review_map = {}
    # 需要更大上下文的单事件（扩窗重审队列）
    needs_expand = []

    batches = [events[i:i + batch_size] for i in range(0, len(events), batch_size)]
    for bi, batch in enumerate(batches, 1):
        say(f"[复审] 批次 {bi}/{len(batches)}（{len(batch)} 个事件）…")

        # 用带上下文的清单文本（每个事件给独立上下文，但整批共享 char_budget）
        prompt = _build_batch_review_prompt(batch, segments, expand_level, char_budget)
        reply, usage = client(prompt, system=REVIEW_SYSTEM,
                              max_tokens=config.REVIEW_MAX_OUTPUT_TOKENS)
        tracker.add(usage)
        parsed = _parse_review_reply(reply)

        for w in parsed["warnings"]:
            say(f"[复审·警示] {w}")
        _schema_warnings.extend(parsed["warnings"])

        got_ids = set()
        for r in parsed["results"]:
            eid = r["event_id"]
            got_ids.add(eid)
            final_score = _weighted_final(r["dims"])
            grade = _grade_from_score(final_score)
            reject_kind = r.get("reject_reason_kind", "")
            # v0.4 A3：D 级原因门控——只有当 AI 明确说「内容本身低价值」(truly_low_value)，
            # 低分才算真淘汰；若是「上下文不够/事件不完整/AI 不确定」，不能把 AI 的困惑
            # 当成内容差直接判 D——降为 C 档供人工复核（召回优先）。
            if grade == "D" and reject_kind and reject_kind != "truly_low_value":
                grade = "C"
                say(f"[复审] {eid} 本会判 D，但 AI 理由是「{reject_kind}」，保留为 C 供人工复核")
            review_map[eid] = {
                "dims": r["dims"],
                "final_score": final_score,
                "grade": grade,
                "negative_flags": r["negative_flags"],
                "why_cut": r["why_cut"],
                "risk": r["risk"],
                "confidence": r["confidence"],
                "recommended_start": r["recommended_start"],
                "recommended_end": r["recommended_end"],
                "recommended_duration": r["recommended_duration"],
                "duration_reason": r["duration_reason"],
                "reject_reason_kind": reject_kind,   # 原始原因类型（供审计/UI）
            }
            # AI 说该事件上下文不够 → 排队扩窗重审
            if r.get("_need_expand"):
                needs_expand.append(eid)

        # 该批里没被 AI 覆盖到的事件（漏条）也记下来（主流程有海选兜底，这里不崩）
        missing = [e for e in batch if e["event_id"] not in got_ids]
        if missing:
            say(f"[复审·警示] 批次 {bi} 漏了 {len(missing)} 个事件"
                f"（{', '.join(e['event_id'] for e in missing)}），用海选分兜底")

    # 扩窗重审：AI 反馈上下文不够的事件，用更大窗口单独再审一次（最多 1 层深扩）
    if needs_expand and depth == 0:
        for eid in set(needs_expand):
            ev = next((e for e in events if e["event_id"] == eid), None)
            if not ev:
                continue
            say(f"[复审] {eid} 上下文不足，扩大窗口重审…")
            sub_map = _review_in_batches(client, tracker, segments, [ev], say,
                                         expand_level=1, depth=1)
            if eid in sub_map:
                review_map[eid] = sub_map[eid]

    return review_map


def _build_batch_review_prompt(batch: list, segments, expand_level=0, char_budget=4000):
    """把一个 batch 的事件 + 各自上下文拼成分批复审需求单（供 AI 一次审完这批）。

    每个事件给独立上下文（_event_review_context），但整批叠加可能超 char_budget，
    所以按预算做一次「上下文配给」：低优先级事件的上下文先被压缩。
    """
    from .prompt_builder import build_batch_review_prompt as _pb_build
    # 按预估分排，预算不足时先压缩低分事件的上下文
    order = sorted(batch, key=lambda ev: -ev.get("_est_score", 50.0))
    per_event_cap = max(400, int(char_budget / max(1, len(batch))))
    blocks = []
    for ev in batch:   # 清单仍按原序（event_id 对号，顺序不重要）
        ctx = _event_review_context(segments, ev, expand_level,
                                    char_cap=per_event_cap)
        blocks.append(_format_single_event_for_review(ev, ctx))
    return _pb_build(blocks)


def _format_single_event_for_review(ev: dict, context_text: str) -> str:
    """把单个事件拼成复审清单条目（含结构 + 上下文原文）。"""
    st = ev.get("structure") or {}
    src = ", ".join(ev.get("source_candidates", [])) or "无"
    return (
        f"### 事件（{ev['event_id']}）\n"
        f"时间：{ev['start_time']} - {ev['end_time']}"
        f"（时长 {ev.get('duration', 0)} 秒）\n"
        f"事件摘要：{ev.get('summary') or '（无）'}\n"
        f"事件类型：{ev.get('event_type') or '未分类'}\n"
        f"故事结构：铺垫——{st.get('setup') or '无'}；"
        f"发展——{st.get('development') or '无'}；"
        f"结果——{st.get('payoff') or '无'}\n"
        f"最强爆点：{ev.get('strongest_moment') or '（无）'}\n"
        f"由 {ev.get('source_count', 1)} 个原始候选聚合而成（{src}）\n"
        f"上下文原文：\n{context_text or '（无）'}"
    )


def _parse_ai_report_reply(reply_text: str) -> dict:
    """解析整场分析报告（_build_ai_report 用）。坏 JSON 返回空报告（不崩）。"""
    try:
        data = json.loads(reply_text)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "summary": str(data.get("summary", "")).strip(),
        "best_spread_point": str(data.get("best_spread_point", "")).strip(),
        "overall": str(data.get("overall", "")).strip(),
        "why_not_more": str(data.get("why_not_more", "")).strip(),
    }


def _build_ai_report(client, tracker, events, say) -> dict:
    """整场 AI 分析报告（独立一次小调用，成本低）。

    报告基于各事件的「精华卡」（event_id + 标题 + 100 分 + 等级 + 为什么值得剪），
    不用大段原文——让 AI 俯瞰整场，给用户解释「本场最强传播点 / 为什么没推荐更多」。
    坏 JSON 返回空报告字段（不崩，UI 能容忍空 report）。
    """
    from .prompt_builder import build_report_prompt
    if not events:
        return {"summary": "", "best_spread_point": "",
                "overall": "本场没有找到值得剪辑的事件",
                "why_not_more": "海选 + 质检 + 事件聚合后仍无候选，本场可能确实平淡。"}

    cards = []
    for ev in events:
        cards.append(
            f"- {ev['event_id']}｜{ev['grade']}｜{ev.get('final_score', 0)}分｜"
            f"{ev.get('title', '')}｜{ev.get('why_cut', '') or ev.get('reason', '')}"
        )
    prompt = build_report_prompt("\n".join(cards))
    reply, usage = client(prompt, system=REPORT_SYSTEM,
                          max_tokens=config.REPORT_OUTPUT_TOKENS)
    tracker.add(usage)
    report = _parse_ai_report_reply(reply)
    say(f"[报告] 整场分析报告已生成")
    return report


# ---------------- v0.3.2 定级引擎：五维子分 → 加权总分 → 等级 ----------------

_DIM_LABELS = {
    "hook": "三秒吸引力",
    "contrast": "反差/意外",
    "persona": "人物表现力",
    "standalone": "独立成片",
    "completeness": "事件完整度",
}


def _weighted_final(dims: dict) -> float:
    """把 AI 打的五维子分按 config 权重算成总分（0-100 的小数，如 83.5）。

    v0.4 步骤 3：复审只打子分（1-10），本地加权后 ×10 得 100 分制总分。
    对外 UI 按 0-100 理解，阈值 S90/A80/B60/C50 与 config.GRADE_*_SCORE 对齐。
    """
    weights = config.SCORE_V3_WEIGHTS
    total = 0.0
    for key, weight in weights.items():
        total += int(dims.get(key, 5)) * weight
    return round(total / 100.0 * 10.0, 1)   # 子分加权(0-10) ×10 → 0-100


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
    # v0.4：事件在聚合时就已经领了 event_id（clip_id 与之一致），不要覆盖，
    # 否则反馈闭环里记的 id 对不上原始候选，审计链会断
    for n, c in enumerate(candidates, 1):
        if not c.get("clip_id"):
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
        # v0.4：事件级字段——高光现在以「完整事件」为单位，不再是爆点句子。
        # 带上这些，界面才能显示「由几个候选聚合而成」「AI 为什么认为是一件事」
        # V0.4.1：加入 story_id（同 Story 内候选强连续先验）
        for key in ("event_id", "cluster_id", "story_id", "summary", "structure",
                    "strongest_moment", "source_candidates", "source_count",
                    "duration", "event_type", "judge_reason", "judge_confidence",
                    "merged_from", "split_by_ai", "reject_reason_kind"):
            if key in c:
                entry[key] = c[key]
        # v0.4 步骤 3：动态剪辑范围（AI 推荐起止 + 时长 + 理由），与事件边界分开——
        # 事件边界是「这段发生了什么」，recommended_* 是「这段剪出来发多长」
        for key in ("recommended_start", "recommended_end",
                    "recommended_duration", "duration_reason"):
            if key in c:
                entry[key] = c[key]
        if c.get("forced_keep"):
            entry["forced_keep"] = True
        if c.get("d_guarded"):
            entry["d_guarded"] = True   # v0.4 A3：本会判 D，因「AI 不确定/不完整/上下文不够」降 C
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


# ============================================================
# 第 5.6 层：事件聚合（v0.4 步骤 2）
#
# 为什么要有这一层：v0.3 的 AI 在评价「一句话」，而剪辑师在评价「一件事」。
# 一个完整的试吃事件（拆包装 → 掉出来 → 尝一口 → 难吃 → 吐掉）
# 会被拆成 5 个各自都不怎么样的片段，结果全被判成低价值——
# 而它们合起来才是一个爆款。
#
# 分工边界（需求原文，不可越界）：
#   1. 本地规则**只负责提出**「可能属于同一事件」的候选分组
#   2. **AI 才负责**最终判断是不是同一件事
#   3. 本地规则**不能**因时间距离、关键词不同而删除候选
#   4. **不允许**「超过 X 秒就必须拆分」这类硬规则
#
# 跑完这一层，候选池从「爆点句子」变成「完整事件」，
# 后面的复审评分与负面过滤全部作用在事件上——**先聚合，再评分**。
# ============================================================

def _clamp_time(value, duration):
    """把秒数夹回 [0, 时长]，不是数字就返回 None。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return 0.0
    if duration and v > duration:
        return float(duration)
    return v


def _format_cluster_candidates(members: list, cluster: dict) -> str:
    """把一簇候选拼成给事件判断 AI 看的文本（含时间、标题、理由）。"""
    lines = []
    for m in members:
        lines.append(
            f"- {m.get('clip_id', '?')}｜{m['start_time']} - {m['end_time']}｜"
            f"{m.get('title', '（无标题）')}｜{m.get('reason', '')}"
        )
    span = ""
    if cluster.get("start") is not None and cluster.get("end") is not None:
        span = (f"（整簇时间范围：{chunker.format_time(cluster['start'])} - "
                f"{chunker.format_time(cluster['end'])}）")
    return f"共 {len(members)} 个候选 {span}\n" + "\n".join(lines)


def _parse_event_judge_reply(reply_text: str):
    """清洗事件判断回复 → 标准化 dict。坏 JSON 返回 None（调用方兜底，不崩）。"""
    try:
        data = json.loads(reply_text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    structure = data.get("structure") or {}
    if not isinstance(structure, dict):
        structure = {}

    return {
        "same_event": bool(data.get("same_event", True)),
        "event_summary": str(data.get("event_summary", "")).strip(),
        "event_type": str(data.get("event_type", "")).strip(),
        "event_start": str(data.get("event_start", "")).strip(),
        "event_end": str(data.get("event_end", "")).strip(),
        "structure": {
            "setup": str(structure.get("setup", "")).strip(),
            "development": str(structure.get("development", "")).strip(),
            "payoff": str(structure.get("payoff", "")).strip(),
        },
        "strongest_moment": str(data.get("strongest_moment", "")).strip(),
        "reason": str(data.get("reason", "")).strip(),
        "confidence": _clamp(data.get("confidence", 0.5), 0, 1, 0.5),
        "need_more_context": bool(data.get("need_more_context", False)),
        "expand_direction": str(data.get("expand_direction", "")).strip().lower(),
    }


def _make_event(members: list, cluster: dict, judge, segments, duration,
                event_no: int, split: bool = False) -> dict:
    """生成一个事件级候选（Event Candidate）。

    members —— 组成这个事件的原始候选（审计用，一个都不丢）
    judge   —— AI 判断结果（None 表示 AI 翻车了，用候选自己的时间兜底）
    split   —— True 表示 AI 判定这些候选**不是**同一件事，每个候选自成一个事件。
              此时 judge 的 event_start/end/summary 描述的是整簇的否定判断，
              不适用于单个候选——若照用，拆出来的多个事件会因边界/摘要相同
              被去重层误合并成一个（v0.4 步骤 2 自测抓出的真 bug）。
    """
    # 事件边界：拆分时用候选自己的时间；否则优先用 AI 给的，兜底用整簇时间
    if split:
        start = _parse_time(str(members[0].get("start_time", "0")))
        end = _parse_time(str(members[0].get("end_time", "0")))
    else:
        start = _parse_time(judge["event_start"]) if judge else None
        end = _parse_time(judge["event_end"]) if judge else None
    if start is None or end is None:
        start = cluster.get("start")
        end = cluster.get("end")
        if start is None:   # 簇也没算出来（AI 时间格式异常）→ 用第一个候选
            start = _parse_time(str(members[0].get("start_time", "0")))
            end = _parse_time(str(members[0].get("end_time", "0")))

    start = _clamp_time(start, duration)
    end = _clamp_time(end, duration)
    if start is not None and end is not None and end < start:
        start, end = end, start          # AI 把起止写反了，就地纠正

    event_id = f"ev-{event_no:03d}"
    # 标题：拆分时直接用候选自己的标题；否则优先用最强爆点/事件摘要兜底
    title = ""
    if judge and not split:
        title = judge["strongest_moment"] or judge["event_summary"] or ""
    if not title:
        title = members[0].get("title", "")
    title = title[:40]
    # V0.4.1：从首个候选继承 story_id（同一 cluster 内候选 Story 相同）
    story_id = members[0].get("story_id", "__unknown__") if members else "__unknown__"

    return {
        "event_id": event_id,
        "clip_id": event_id,              # 兼容反馈接口（feedback.json 记的就是它）
        "cluster_id": cluster["cluster_id"],
        "story_id": story_id,             # V0.4.1：继承候选的 Story 归属
        "start_time": chunker.format_time(start) if start is not None else members[0]["start_time"],
        "end_time": chunker.format_time(end) if end is not None else members[0]["end_time"],
        "start": start,
        "end": end,
        "duration": int(end - start) if (start is not None and end is not None) else 0,
        "title": title,
        # split=True 时，judge 的 event_summary/structure/strongest_moment 描述的是整簇的
        # 否定判断，不能共享（否则拆出的事件因摘要/结构相同被去重层误并回一个，D-035）。
        # 但也不能让拆出的每个事件只剩时间戳、复审无任何故事锚点（A2）。
        # 安全兜底：用**该候选自己**的海选信息（reason / highlight_type / category），
        # 这些属于候选、不共享、不互相冲突，可作为「这个片段讲什么」的轻量摘要/类型，
        # 让复审至少知道片段主题，而不是面对光秃秃时间戳 + 无锚点原文。
        "summary": judge["event_summary"] if (judge and not split)
                   else (members[0].get("reason", "") or ""),
        "event_type": judge["event_type"] if (judge and not split)
                      else (members[0].get("highlight_type", "")
                            or members[0].get("category", "") or ""),
        "structure": judge["structure"] if (judge and not split) else {},
        "strongest_moment": judge["strongest_moment"] if (judge and not split) else "",
        "source_candidates": [m.get("clip_id", "") for m in members],
        "source_count": len(members),
        "judge_reason": judge["reason"] if judge else "（AI 判断失败，按原始候选处理）",
        "judge_confidence": judge["confidence"] if judge else 0.0,
        "judge_same_event": judge["same_event"] if judge else None,
        "split_by_ai": split,             # True = AI 认为这些候选不是同一件事，被拆开了
        # 复审评分要用的原始信息
        "score": max(int(m.get("score", 5)) for m in members),
        "highlight_type": members[0].get("highlight_type", "事件型"),
        "category": members[0].get("category", "其他"),
        # 复审评分/UI 展示要用的字段，从最强候选继承（事件是「由候选聚合而成」）
        "reason": members[0].get("reason", ""),
        "viral_probability": members[0].get("viral_probability", "中"),
        "editing_advice": members[0].get("editing_advice", ""),
        "confidence": (judge["confidence"] if judge and not split
                       else members[0].get("confidence", 0.5)),
        "context": "",
    }


def _same_event_identity(a: dict, b: dict) -> bool:
    """事件级去重判断：时间范围高度重叠 + 主题相同 → 视为同一个事件。

    对应需求「事件去重」：现在的 exact start/end 去重不够，
    主题相同、对象相同、因果链重叠、时间高度重叠的应视为同一事件
    （同一个事件被不同扫描路径发现时，最终只保留一个）。
    """
    if None in (a.get("start"), a.get("end"), b.get("start"), b.get("end")):
        return False

    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
    if overlap <= 0:
        return False
    shorter = min(a["end"] - a["start"], b["end"] - b["start"])
    if shorter <= 0:
        return False
    overlap_ratio = overlap / shorter

    # 主题相似度：拿摘要比；摘要为空就退回标题比
    topic = event_cluster._topic_score(
        a.get("summary") or a.get("title", ""),
        b.get("summary") or b.get("title", ""),
    )
    # 阈值用 > 而非 >=（严格大于）：
    # 若放宽到 >=，会让"标题很像 + 时间重叠恰 ≥50%"的两个**被 AI split 出的真不同事件**
    # 被 dedupe 误并回去（短标题的 topic 区分力弱，实测相关与无关事件 topic 都 ~0.14，
    # 恰 =0.5 只代表标题几乎逐字重复，不代表内容同主题）。保持 > 更安全。
    return overlap_ratio > 0.5 and topic > 0.5


def _merge_two_events(keep: dict, drop: dict) -> dict:
    """把 drop 并进 keep（保留信息更全的那份，source_candidates 累加）。"""
    # 时间取并集（事件边界以覆盖更全的为准）
    if None not in (keep.get("start"), drop.get("start")):
        keep["start"] = min(keep["start"], drop["start"])
    if None not in (keep.get("end"), drop.get("end")):
        keep["end"] = max(keep["end"], drop["end"])
    if keep.get("start") is not None and keep.get("end") is not None:
        keep["duration"] = int(keep["end"] - keep["start"])
        keep["start_time"] = chunker.format_time(keep["start"])
        keep["end_time"] = chunker.format_time(keep["end"])

    # 来源候选合并去重（审计链条不能断）
    seen = list(keep.get("source_candidates", []))
    for cid in drop.get("source_candidates", []):
        if cid and cid not in seen:
            seen.append(cid)
    keep["source_candidates"] = seen
    keep["source_count"] = len(seen)

    # 摘要/爆点取更长的那份，结构缺哪块补哪块
    if len(drop.get("summary", "")) > len(keep.get("summary", "")):
        keep["summary"] = drop["summary"]
    if len(drop.get("strongest_moment", "")) > len(keep.get("strongest_moment", "")):
        keep["strongest_moment"] = drop["strongest_moment"]
    for k in ("setup", "development", "payoff"):
        if not keep.get("structure", {}).get(k) and drop.get("structure", {}).get(k):
            keep["structure"][k] = drop["structure"][k]

    keep["score"] = max(keep.get("score", 0), drop.get("score", 0))
    keep["merged_from"] = keep.get("merged_from", []) + [drop.get("event_id", "")]
    return keep


def _dedupe_events(events: list) -> list:
    """事件级去重：同一个事件被不同路径发现时，只保留一个。"""
    if len(events) <= 1:
        return events

    used = [False] * len(events)
    result = []
    for i, ev in enumerate(events):
        if used[i]:
            continue
        for j in range(i + 1, len(events)):
            if used[j]:
                continue
            if _same_event_identity(ev, events[j]):
                ev = _merge_two_events(ev, events[j])
                used[j] = True
        result.append(ev)
    return result


def _run_event_aggregation(client, tracker, segments, candidates, duration, say):
    """事件聚合主流程：本地粗聚类 → AI 事件判断（自适应上下文）→ 事件级去重。

    返回 (events, stats)。
    stats 记录聚类数、AI 合并次数、拆分次数、上下文扩展次数、去重掉几个——
    全部写进结果的 meta，方便开发者模式审计「AI 有没有错合并」。
    """
    cfg = config.EVENT_JUDGE_CONTEXT

    # 提前给候选发身份证（需求九：审计要能看到 clip-001 → cluster → event 的链条）
    for n, c in enumerate(candidates, 1):
        c.setdefault("clip_id", f"clip-{n:03d}")

    # v0.4 步骤 4：Story 前置层 — 给候选打故事标注，构建 story_groups
    # 软边界：找不到 Story 文件或失败时静默降级，不影响主流程
    story_groups_cfg = getattr(config, "STORY_CONTEXT", None) or {}
    story_file = story_groups_cfg.get("story_file") if story_groups_cfg else None
    story_groups = _sc.load_story_groups(story_file)
    if story_groups:
        _sc.annotate_candidates(candidates, story_groups)
        story_groups = _sc.build_story_groups(candidates, story_groups)
        say(f"[Story层] 加载 {len(story_groups)} 个 Story，已给候选打标注")
        unknown = sum(1 for c in candidates if c.get("story_id") == "__unknown__")
        say(f"[Story层] 未匹配 Story 的候选：{unknown}/{len(candidates)}")
    else:
        say("[Story层] 未找到 Story 文件（poc/story_segmentation_result.json），跳过")

    clusters = event_cluster.build_clusters(candidates, story_groups=story_groups)
    say(f"[事件聚合] 本地粗聚类：{event_cluster.cluster_stats(clusters)}")

    events = []
    stats = {"clusters": len(clusters), "merged": 0, "split": 0,
             "expanded": 0, "judge_calls": 0, "judge_failed": 0}

    for cluster in clusters:
        members = [candidates[i] for i in cluster["members"]]
        cand_text = _format_cluster_candidates(members, cluster)

        # 第一轮：较小上下文
        ctx = event_cluster.build_cluster_context(
            segments, cluster, cfg["first_before"], cfg["first_after"], cfg["char_limit"]
        )
        prompt = build_event_judge_prompt(cand_text, ctx)
        reply, usage = client(prompt, system=EVENT_JUDGE_SYSTEM,
                              max_tokens=config.EVENT_JUDGE_MAX_OUTPUT_TOKENS)
        tracker.add(usage)
        stats["judge_calls"] += 1
        judge = _parse_event_judge_reply(reply)

        # 自适应上下文：AI 说故事不完整（setup/payoff 在窗口外）→ 扩大后重判一次
        if judge and judge["need_more_context"] and cfg["max_expand_rounds"] > 0:
            direction = judge["expand_direction"] or "both"
            before = cfg["expand_before"] if direction in ("before", "both") else cfg["first_before"]
            after = cfg["expand_after"] if direction in ("after", "both") else cfg["first_after"]
            ctx2 = event_cluster.build_cluster_context(
                segments, cluster, before, after, cfg["char_limit"]
            )
            if ctx2 and ctx2 != ctx:
                prompt2 = build_event_judge_prompt(cand_text, ctx2)
                reply2, usage2 = client(prompt2, system=EVENT_JUDGE_SYSTEM,
                                        max_tokens=config.EVENT_JUDGE_MAX_OUTPUT_TOKENS)
                tracker.add(usage2)
                stats["judge_calls"] += 1
                stats["expanded"] += 1
                judge2 = _parse_event_judge_reply(reply2)
                if judge2:
                    judge = judge2
                say(f"[事件聚合] {cluster['cluster_id']} 上下文不足，已扩大重判")

        if judge is None:
            # AI 翻车：不合并也不丢弃，簇内候选各自成事件（最保守的兜底）
            stats["judge_failed"] += 1
            for m in members:
                events.append(_make_event([m], cluster, None, segments, duration,
                                          len(events) + 1))
            continue

        if judge["same_event"] or len(members) == 1:
            events.append(_make_event(members, cluster, judge, segments, duration,
                                      len(events) + 1))
            stats["merged"] += max(0, len(members) - 1)
        else:
            # AI 认为这几个候选不是同一件事 → 拆开各自成事件
            for m in members:
                events.append(_make_event([m], cluster, judge, segments, duration,
                                          len(events) + 1, split=True))
            stats["split"] += max(0, len(members) - 1)

    # 事件级去重（不同扫描路径可能撞到同一件事）
    before = len(events)
    events = _dedupe_events(events)
    stats["deduped"] = before - len(events)
    stats["events"] = len(events)

    # 给每个事件补上复审要用的原文（事件比单句长，按配置放宽字符上限）
    limit = config.EVENT_REVIEW_CONTEXT_LIMIT
    for ev in events:
        ev["context"] = _grab_context(segments, ev["start_time"], ev["end_time"],
                                      char_limit=limit)

    say(f"[事件聚合] {len(candidates)} 个候选 → {len(events)} 个事件"
        f"（AI 合并 {stats['merged']} 次、拆分 {stats['split']} 次、"
        f"去重 {stats['deduped']} 个）")
    return events, stats
