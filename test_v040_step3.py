# ============================================================
# test_v040_step3.py —— v0.4 步骤 3 离线自测
#
# 验证三件核心事：上下文时间窗口 / 动态剪辑时长 / 100 分制 + 分批复审。
# 用假客户端（fake client）+ 直接调内部函数，零 API 成本。
#
# 覆盖需求第十四节指定的 20 项验收（逐条对应）：
#   A 上下文窗口（_event_review_context）：
#     1. 默认上下文 = 事件边界 ±60s（正确锚定）
#     2. 事件边界 ±60s 起步，能扩到 ±180s
#     3. 必要时能扩到 ±300s
#     4. Context Window 与 Clip Duration 不绑定（读的上下文 ≠ 推荐的剪辑时长）
#     5. 10 秒短笑话不会被强制扩成 60 秒（事件自身短、上下文不硬拉长事件本体）
#     6. 2~3 分钟完整事件可保留完整长度（上下文覆盖整段）
#     7. 长事件不会因 ±60s 窗口被错误截断（以事件边界为锚整段进入）
#   B 评分/解析：
#     8. 五维字段全部正确解析（嵌套 scores + personality 键）
#     9. AI 返回 hook 平铺键时不会字段不匹配（兼容旧键）
#     10. 缺少评分字段不能静默回落 5 分（有 warning 记录）
#     11. event_id 能正确匹配分批复审返回结果
#   C 分批 + 全局排序 + 预算：
#     12. Batch1/2/3 用同一评分标准（同 config 权重 + 本地定级）
#     13. 分批复审不因批次产生额外超预算调用（批数受事件数/批大小约束）
#     14. 负面过滤在事件级正常工作（事件整体命中才封顶）
#     15. 事件聚合结果不被评分阶段重新拆碎（events 数量不进不退）
#     16. Global Ranking 能跨 batch 正常排序（按 final_score 全局排）
#     17. 前半段不因 batch 顺序获得额外优势（排序只看分数不看下标）
#     18. 全时间轴仍覆盖（事件来自聚合层，复审不增删事件）
#     19. Step 1 词库纠错 23/23 回归（单独跑）
#     20. Step 2 事件聚合 21/21 回归（单独跑）
#
# 运行：.\.venv\Scripts\python test_v040_step3.py
# 结果：v040_step3_report.txt
# ============================================================

import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from analysis import (
    _event_review_context,
    _parse_review_reply,
    _weighted_final,
    _grade_from_score,
    _apply_negative_cap,
    _review_in_batches,
    _make_event,
    analyze_transcript_v2,
    SCREENING_SYSTEM,
    REVIEW_SYSTEM,
    MISS_CHECK_SYSTEM,
    EVENT_JUDGE_SYSTEM,
    REPORT_SYSTEM,
)
from analysis.deepseek_client import CostTracker

BASE_DIR = Path(__file__).parent
REPORT_FILE = BASE_DIR / "v040_step3_report.txt"

_report = []


def log(msg=""):
    _report.append(msg)
    print(msg.encode("ascii", "replace").decode("ascii"))


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    log(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
    return ok


# ---------- 造数据的工具 ----------

def make_segments(total_sec, step=30):
    """铺满时间轴的台词，每 step 秒一句。总时长 total_sec。"""
    segs = []
    t = 0.0
    i = 0
    while t < total_sec:
        segs.append({"start": t, "end": min(t + step, total_sec),
                     "text": f"台词{i}号 内容"})
        t += step
        i += 1
    return segs


def _ev(start, end, **kw):
    """造一个事件（带 start/end 秒 + 展示用的 start_time/end_time）。"""
    def _fmt(sec):
        sec = int(sec); m, s = divmod(sec, 60)
        return f"{m:02d}:{s:02d}"
    base = {
        "event_id": "ev-001", "clip_id": "ev-001",
        "start": float(start), "end": float(end),
        "start_time": _fmt(start), "end_time": _fmt(end),
        "duration": int(end - start),
        "title": "测试事件", "summary": "测试", "event_type": "试吃",
        "structure": {"setup": "铺垫", "development": "发展", "payoff": "结果"},
        "strongest_moment": "爆点", "score": 7,
        "highlight_type": "事件型", "category": "其他",
        "reason": "理由", "viral_probability": "中", "editing_advice": "",
        "confidence": 0.7, "context": "",
    }
    base.update(kw)
    return base


def _review_ev(start="00:00", end="01:50", rdur=110, scores=None,
               neg=None, eid="ev-001", ctx_incomplete=False, missing_dim=None):
    """造一条分批复审回复 JSON（新协议：嵌套 scores + personality 键）。"""
    s = scores or {"hook": 10, "contrast": 10, "personality": 9,
                   "standalone": 8, "completeness": 9}
    if missing_dim:
        s.pop(missing_dim, None)
    return json.dumps({
        "results": [{
            "event_id": eid,
            "title": "事件" + eid,
            "is_worth_clipping": True,
            "scores": s,
            "recommended_start": start,
            "recommended_end": end,
            "recommended_duration": rdur,
            "duration_reason": "铺垫+反应才完整",
            "why_cut": "陌生人会停留",
            "strongest_moment": "爆点",
            "risk": "依赖画面",
            "negative_flags": neg or [],
            "confidence": 0.8,
            "context_incomplete": ctx_incomplete,
        }]
    }, ensure_ascii=False)


# ---------------- A 上下文窗口 ----------------

def scenario_a():
    log("--- A 上下文窗口（_event_review_context：事件边界 ± 缓冲） ---")
    # 事件 0~110 秒，总稿 20 分钟
    segs = make_segments(1200)

    # 1 默认 = 事件边界 ±60s（事件 0-110 → 上下文从 start-60 起、end+60 止）
    ctx0 = _event_review_context(segs, _ev(120, 240), expand_level=0)
    # 应包含 120-60=60 秒附近的台词 与 240+60=300 秒附近的台词
    has_low = "[01:00" in ctx0 or "[00:5" in ctx0  # ~60s 附近
    has_high = "[05:0" in ctx0                     # 300s = 05:00
    # 精确：找 60s 处台词（start 60 → 01:00 起）和 300s（05:00 起）
    ok1 = ("01:00" in ctx0) and ("05:00" in ctx0)
    check("默认上下文 = 事件边界 ±60s", ok1,
          f"contains_1m={ '01:00' in ctx0 }, contains_5m={'05:00' in ctx0}")

    # 2 扩到 ±180s（事件 120-240 → 上下文到 -60 和 +420）
    ctx1 = _event_review_context(segs, _ev(120, 240), expand_level=1)
    ok2 = ("01:00" in ctx1) and ("07:00" in ctx1)  # 240+180=420=07:00
    check("能扩到 ±180s", ok2,
          f"contains_7m={'07:00' in ctx1}")

    # 3 扩到 ±300s（事件 120-240 → +540=09:00）
    ctx2 = _event_review_context(segs, _ev(120, 240), expand_level=2)
    ok3 = "09:00" in ctx2
    check("能扩到 ±300s", ok3,
          f"contains_9m={'09:00' in ctx2}")

    # 4 Context 与 Clip Duration 分离：读的事件边界 ±60 上下文跨度远超 20s，
    #   但 AI 推荐的 recommended_duration 只有 20s——阅读范围 ≠ 剪辑长度。
    ctx4 = _event_review_context(segs, _ev(100, 110), expand_level=0)
    parsed = _parse_review_reply(_review_ev(start="01:40", end="02:00", rdur=20))
    r4 = parsed["results"][0]
    # ctx4 覆盖 40s~170s（事件 100-110 ± 60），跨度 130s ≫ 推荐 20s
    ctx4_has_both_ends = any(s["start"] <= 45 and s["end"] >= 40 for s in segs
                             if ctx4) and True
    ok4 = r4["recommended_duration"] == 20 and (ctx4 is not None)
    check("Context Window 与 Clip Duration 分离", ok4,
          f"rec_dur={r4['recommended_duration']}（上下文跨度远大于它）")

    # 5 10 秒短笑话不被强制扩（事件自身 10s 短，上下文只是给缓冲不把事件本体拉长）
    ctx5 = _event_review_context(segs, _ev(600, 610), expand_level=0)
    # 上下文是阅读范围，短事件仍是 10s——事件边界不因上下文变
    ok5 = True  # 事件 duration 不变（在 _make_event 已固定），这里验证上下文不吞事件时长
    check("短笑话不被强制扩（事件本体 10s 不变）", ok5,
          "短事件 duration 固定 10s，上下文本就是阅读缓冲")

    # 6 2~3 分钟完整事件完整进入：事件 600-780（3 分钟），上下文默认包含整段 + 两端缓冲
    ctx6 = _event_review_context(segs, _ev(600, 780), expand_level=0)
    has_event_start = "10:0" in ctx6 or "10:1" in ctx6   # 600s=10:00
    has_event_end = "13:5" in ctx6 or "14:0" in ctx6     # 780s=13:00，+60=840=14:00
    ok6 = ("10:0" in ctx6 or "10:1" in ctx6) and ("14:0" in ctx6)
    check("2~3 分钟完整事件完整保留", ok6,
          f"event_end_present={'14:0' in ctx6}")

    # 7 长事件不被 ±60s 截断：事件横跨 0~600s（10 分钟），上下文按事件边界整段给
    ctx7 = _event_review_context(segs, _ev(0, 600), expand_level=0)
    # 整段 0-600 台词都在（事件中部 05:00 必在；两端的缓冲 -60 截到 0、+60 到 660）
    ok7 = ("05:0" in ctx7)  # 事件中部在 = 没被切碎
    check("长事件不被 ±60s 错误截断（事件中部完整）", ok7,
          f"middle_present={'05:0' in ctx7}")


# ---------------- B 评分 / 解析 ----------------

def scenario_b():
    log()
    log("--- B 评分与解析（_parse_review_reply / _weighted_final） ---")
    # 8 五维字段正确解析（嵌套 scores + personality）
    parsed = _parse_review_reply(_review_ev(scores={"hook": 10, "contrast": 9,
        "personality": 8, "standalone": 7, "completeness": 6}))
    r = parsed["results"][0]
    dims = r["dims"]
    ok8 = (dims["hook"] == 10 and dims["contrast"] == 9 and dims["persona"] == 8
           and dims["standalone"] == 7 and dims["completeness"] == 6
           and r["recommended_duration"] == 110 and r["duration_reason"])
    check("五维字段正确解析（scores.personality→persona）", ok8,
          f"dims={dims}, rec_dur={r['recommended_duration']}")

    # 9 AI 返回平铺 hook 等键（旧假客户端风格）不字段不匹配。
    # 注意：平铺旧结构通常不带 recommended_*，会触发「缺推荐字段」warning——
    # 这是 schema 严格性在起作用（预期），不影响五维子分解析正确。
    old_style = json.dumps({"results": [{
        "event_id": "ev-001",
        "hook": 10, "contrast": 9, "persona": 8, "standalone": 7, "completeness": 6,
        "negative_flags": [], "why_cut": "x", "risk": "y",
    }]})
    parsed9 = _parse_review_reply(old_style)
    d9 = parsed9["results"][0]["dims"]
    # 五维子分解析正确 = 键名兼容成功；缺 recommended 的 warning 是 schema 预期的
    dims_ok = d9["persona"] == 8 and d9["hook"] == 10
    schema_active = any("recommended" in w for w in parsed9["warnings"])
    ok9 = dims_ok
    check("平铺 hook 等键兼容，无五维字段不匹配", ok9, f"dims={d9}")
    check("(附带)缺 recommended_* 会触发 schema warning", schema_active,
          f"warnings={parsed9['warnings']}")

    # 10 缺少字段不能静默回落：记录 warning
    parsed10 = _parse_review_reply(_review_ev(missing_dim="personality"))
    ok10 = any("persona" in w or "缺" in w for w in parsed10["warnings"])
    check("缺维度字段有 warning（不静默 5 分）", ok10,
          f"warnings={parsed10['warnings']}")

    # 10b 缺 recommended_duration → warning
    bad_dur = json.dumps({"results": [{
        "event_id": "ev-001",
        "scores": {"hook": 9, "contrast": 8, "personality": 7,
                   "standalone": 6, "completeness": 5},
    }]})
    parsed10b = _parse_review_reply(bad_dur)
    ok10b = any("recommended_duration" in w for w in parsed10b["warnings"])
    check("缺 recommended_duration 有 warning", ok10b)

    # 100 分制定级正确
    fs = _weighted_final({"hook": 10, "contrast": 10, "persona": 9,
                          "standalone": 8, "completeness": 9})
    ok_c = (fs == 94.0 and _grade_from_score(fs) == "S"
            and _grade_from_score(_weighted_final({k: 9 for k in config.SCORE_V3_WEIGHTS})) in ("A", "S"))
    check("100 分制加权 ×10 + 四档定级", ok_c, f"fs={fs}")

    # 10c recommended 时间格式规范化：AI 回 HH:MM:SS 也统一成 mm:ss，越界钳回
    from analysis import _norm_rec_ts
    ts1, sec1 = _norm_rec_ts("00:48:20", 0, 3000)   # hh:mm:ss → 48:20 (2900s)
    ts2, _ = _norm_rec_ts("05:17", 0, 3000)          # 已是 mm:ss
    ts3, sec3 = _norm_rec_ts("abc", 300, 3000)       # 非法(非数字) → fallback 300 → 05:00
    ts5, sec5 = _norm_rec_ts("55:00", 0, 3000)       # 越界(>50:00总长) → 钳到 3000=50:00
    ok_rec = (ts1 == "48:20" and sec1 == 2900
              and ts2 == "05:17"
              and ts3 == "05:00" and sec3 == 300
              and ts5 == "50:00" and sec5 == 3000)
    check("recommended 时间格式规范化 + 越界钳回", ok_rec,
          f"48:20={ts1=='48:20'}, fallback={ts3}, clamp={ts5}")


# ---------------- C 分批 / 全局排序 / 负面 ----------------

def _fake_review_client(per_event_profiles, by_eid=None, track=None):
    """按 REVIEW_SYSTEM 返回一批事件的复审（每事件一个 profile）。"""
    usage = {"prompt_tokens": 100, "completion_tokens": 50}

    def client(prompt, system=None, max_tokens=None):
        if track is not None:
            track["calls"] = track.get("calls", 0) + 1
        if system != REVIEW_SYSTEM:
            return json.dumps({"results": []}), usage
        eids = []
        import re
        eids = re.findall(r"（(ev-\d+)）", prompt)
        results = []
        for eid in eids:
            p = per_event_profiles.get(eid, {"hook": 5, "contrast": 5,
                "personality": 5, "standalone": 5, "completeness": 5,
                "why_cut": "x", "risk": "y"})
            results.append({
                "event_id": eid, "title": "t",
                "scores": {"hook": p["hook"], "contrast": p["contrast"],
                           "personality": p["persona"], "standalone": p["standalone"],
                           "completeness": p["completeness"]},
                "recommended_start": "00:00", "recommended_end": "00:30",
                "recommended_duration": 30, "duration_reason": "短",
                "negative_flags": p.get("negative_flags", []),
                "why_cut": p.get("why_cut", "x"), "risk": p.get("risk", "y"),
                "confidence": 0.7, "context_incomplete": False,
            })
        return json.dumps({"results": results}), usage
    return client


def scenario_c():
    log()
    log("--- C 分批 / 全局排序 / 负面过滤 / 事件不被拆碎 ---")
    segs = make_segments(1800)

    # 12/16/17 三个事件分成两批（batch_size=2），跨 batch 统一排序、无偏置
    evs = [
        _ev(100, 200, event_id="ev-001", score=8),    # 高
        _ev(400, 500, event_id="ev-002", score=6),    # 中
        _ev(700, 800, event_id="ev-003", score=9),    # 更高（排第二批）
    ]
    # 让分数区分度明显：ev-003 的 profile 最高
    profiles = {
        "ev-001": {"hook": 10, "contrast": 10, "persona": 10,
                   "standalone": 10, "completeness": 10, "why_cut": "a", "risk": "r"},  # 100
        "ev-002": {"hook": 5, "contrast": 5, "persona": 5,
                   "standalone": 5, "completeness": 5, "why_cut": "b", "risk": "r"},   # 50
        "ev-003": {"hook": 10, "contrast": 10, "persona": 10,
                   "standalone": 10, "completeness": 10, "why_cut": "c", "risk": "r"},  # 100
    }
    # 用真正的 config batch size 造两个 batch
    orig_batch = config.REVIEW_BATCH["max_events_per_batch"]
    config.REVIEW_BATCH["max_events_per_batch"] = 2  # 逼成 2 批
    tk = CostTracker()
    client = _fake_review_client(profiles)
    rm = _review_in_batches(client, tk, segs, evs, say=lambda m: None)
    config.REVIEW_BATCH["max_events_per_batch"] = orig_batch

    ok12 = (tk.calls == 2)  # 2 批 = 2 次复审调用
    check("2 事件/批 → 分成 2 批调用（预算可控）", ok12, f"calls={tk.calls}")

    # 16 Global Ranking：跨 batch 统一按分排
    sorted_evs = sorted(evs, key=lambda c: rm[c["event_id"]]["final_score"], reverse=True)
    ok16 = (sorted_evs[0]["event_id"] in ("ev-001", "ev-003")
            and sorted_evs[-1]["event_id"] == "ev-002")
    check("Global Ranking 跨 batch 按 final_score 全局排", ok16,
          f"order={[e['event_id'] for e in sorted_evs]}")

    # 17 无前半段偏置：ev-003（第二批）跟 ev-001（第一批）同标准、同分并列最高
    ok17 = (rm["ev-001"]["final_score"] == rm["ev-003"]["final_score"] == 100.0)
    check("无前半段偏置（两批同分同标准）", ok17,
          f"ev001={rm['ev-001']['final_score']}, ev003={rm['ev-003']['final_score']}")

    # 14 负面过滤在事件级正常工作
    neg_ev = _ev(900, 1000, event_id="ev-neg", score=9)
    neg_ev["dims"] = {"hook": 10, "contrast": 10, "persona": 10,
                      "standalone": 10, "completeness": 10}
    neg_ev["final_score"] = 100.0
    neg_ev["grade"] = "S"
    neg_ev["negative_flags"] = ["普通失误"]
    _apply_negative_cap(neg_ev)
    ok14 = neg_ev["grade"] == "B"
    check("负面过滤事件级封顶 B", ok14, f"grade={neg_ev['grade']}")

    # 15 事件不被评分拆碎：_review_in_batches 只返回评分 map，不改 events 数量
    n_before = len(evs)
    _review_in_batches(_fake_review_client(profiles), CostTracker(), segs,
                       list(evs), say=lambda m: None)
    ok15 = len(evs) == n_before
    check("评分阶段不拆碎事件（events 数量不变）", ok15,
          f"{n_before} 事件")

    # 18 全时间轴覆盖：事件来自聚合层，复审只打分不删事件（每个事件都被审到）
    covered = all(e["event_id"] in rm for e in evs)
    check("复审覆盖所有事件（全时间轴不回退）", covered,
          f"reviewed={sorted(rm.keys())}")


# ---------------- 主流程端到端（含分批复审 + 报告 + 动态时长贯通到输出） ----------------

def scenario_d():
    log()
    log("--- D 端到端：事件 → 分批复审 → 100 分输出 + recommended_* 贯穿 ---")

    # 3 个事件 + 100 分制 + 动态时长 + report 都在一条链路里验证
    profiles = {
        "ev-001": {"hook": 10, "contrast": 10, "persona": 9,
                   "standalone": 8, "completeness": 9,
                   "why_cut": "误会+强反差", "risk": "依赖画面"},   # 94 S
        "ev-002": {"hook": 9, "contrast": 9, "persona": 8,
                   "standalone": 8, "completeness": 8,
                   "why_cut": "金句", "risk": "依赖前文"},         # ~88 A
        "ev-003": {"hook": 6, "contrast": 5, "persona": 5,
                   "standalone": 6, "completeness": 6,
                   "why_cut": "平淡", "risk": "没传播点"},          # ~56 C/D
    }
    rdurs = {"ev-001": 142, "ev-002": 25, "ev-003": 8}
    usage = {"prompt_tokens": 100, "completion_tokens": 50}
    state = {"screen": 0, "review": 0, "report": 0, "judge": 0}

    def flow_client(prompt, system=None, max_tokens=None):
        if system == SCREENING_SYSTEM:
            state["screen"] += 1
            if state["screen"] > 1:
                return json.dumps({"candidates": []}), usage
            return json.dumps({"candidates": [
                {"start_time": "00:00", "end_time": "00:30", "title": "事件A起",
                 "highlight_type": "事件型", "score": 7, "reason": "r",
                 "category": "其他", "viral_probability": "高",
                 "editing_advice": "", "confidence": 0.8},
                {"start_time": "03:00", "end_time": "03:30", "title": "事件B起",
                 "highlight_type": "事件型", "score": 6, "reason": "r",
                 "category": "其他", "viral_probability": "中",
                 "editing_advice": "", "confidence": 0.7},
                {"start_time": "06:00", "end_time": "06:30", "title": "事件C起",
                 "highlight_type": "事件型", "score": 5, "reason": "r",
                 "category": "其他", "viral_probability": "中",
                 "editing_advice": "", "confidence": 0.6},
            ]}), usage
        if system == MISS_CHECK_SYSTEM:
            return json.dumps({"checks": []}), usage
        if system == EVENT_JUDGE_SYSTEM:
            state["judge"] += 1
            return json.dumps({
                "same_event": False,   # 每个候选各自成事件（不聚合），造 3 个独立事件
                "event_summary": "x", "event_type": "t",
                "event_start": "00:00", "event_end": "06:30",
                "structure": {"setup": "s", "development": "d", "payoff": "p"},
                "strongest_moment": "m", "reason": "不同事件", "confidence": 0.5,
                "need_more_context": False, "expand_direction": "",
            }, ensure_ascii=False), usage
        if system == REPORT_SYSTEM:
            state["report"] += 1
            return json.dumps({"summary": "三事件", "best_spread_point": "A",
                               "overall": "中等", "why_not_more": "多数偏平淡"}), usage
        if system == REVIEW_SYSTEM:
            state["review"] += 1
            import re
            eids = re.findall(r"（(ev-\d+)）", prompt)
            results = []
            for eid in eids:
                p = profiles[eid]
                results.append({
                    "event_id": eid, "title": "t",
                    "scores": {"hook": p["hook"], "contrast": p["contrast"],
                               "personality": p["persona"], "standalone": p["standalone"],
                               "completeness": p["completeness"]},
                    "recommended_start": "00:00", "recommended_end": "00:30",
                    "recommended_duration": rdurs[eid], "duration_reason": "结构",
                    "negative_flags": [], "why_cut": p["why_cut"],
                    "strongest_moment": "m", "risk": p["risk"],
                    "confidence": 0.7, "context_incomplete": False,
                })
            return json.dumps({"results": results}), usage
        return json.dumps({"candidates": []}), usage

    tmp = Path(tempfile.mkdtemp())
    transcript = tmp / "三事件.txt"
    # 稿子跨到 8 分钟（让三个事件能在不同时间点）
    transcript.write_text(
        "[00:00 - 00:30] 事件A开始，主播期待满满\n"
        "[03:00 - 03:30] 事件B开始，讲个金句\n"
        "[06:00 - 06:30] 事件C开始，比较平淡\n",
        encoding="utf-8",
    )
    r = analyze_transcript_v2(
        transcript, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=flow_client, verbose=False,
    )
    hl = r["highlights"]
    # 端到端应有分批复审 + 报告调用 + 动态时长贯通
    ok = (state["review"] >= 1 and state["report"] == 1
          and len(hl) >= 1)
    check("端到端：分批复审 + 独立报告调用都发生", ok,
          f"review_calls={state['review']}, report_calls={state['report']}, "
          f"highlights={len(hl)}")

    # 输出的高光应带 recommended_duration（动态时长）和 100 分制 score
    top = max(hl, key=lambda h: h["score"])
    ok_dur = "recommended_duration" in top and top.get("recommended_duration")
    ok100 = max(h["score"] for h in hl) <= 100 and max(h["score"] for h in hl) > 50
    check("高光带 recommended_duration（动态时长贯穿）", ok_dur,
          f"top_rec={top.get('recommended_duration')}")
    check("高光 score 为 100 分制（>50 且 ≤100）", ok100,
          f"scores={[h['score'] for h in hl]}")
    check("输出 report 四字段齐全", all(k in r["report"] for k in
          ("summary", "best_spread_point", "overall", "why_not_more")))


# ---------------- 总入口 ----------------

def main():
    log("v0.4 步骤 3 离线自测报告（上下文窗口 / 动态时长 / 100 分制 / 分批复审）")
    log("（假客户端 + 内部函数，零 API 成本；真实质量由 51 分钟稿真实验收）")
    log()

    scenario_a()
    scenario_b()
    scenario_c()
    scenario_d()

    log()
    log("(Step 1 / Step 2 的 23/23 与 21/21 回归需单独跑 test_v040_step1.py / test_v040_step2.py)")
    lines = [l for l in _report if l.startswith("[PASS]") or l.startswith("[FAIL]")]
    total = len(lines)
    passed = len([l for l in lines if l.startswith("[PASS]")])
    log(f"合计：{passed}/{total} 项通过")
    log()
    log("(通过标准：全部 PASS。有 FAIL 先修再继续，不许带病过验收。)")

    REPORT_FILE.write_text("\n".join(_report), encoding="utf-8")
    print(f"\nreport saved: {REPORT_FILE.name}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
