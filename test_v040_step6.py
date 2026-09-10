# ============================================================
# test_v040_step6.py —— V0.4.2 离线自测
#
# 验证两件事（都零 API 成本，用假客户端 + 直接调内部函数）：
#   A/B 评分与推荐解耦：_pick_recommendations / _select_quantity
#        - 自动精选不再等于「只取 S/A」，A 不足时用高质量 B 补位（修 0 输出问题）
#        - A 超过目标数量时按数量策略截断（内容好 ≠ 一定进推荐名单）
#        - C 不无条件自动推荐；D 永不推荐
#        - 候选池 / 自定义数量行为不变
#   C/D 内容结构层：story_context.load_structure / build_content_structure
#        - Chapter → Story → Event 层级正确；Story 评分 = 最强事件分
#        - 结构缺失时静默降级不崩
#
# 运行：.\.venv\Scripts\python test_v040_step6.py
# 结果：v040_step6_report.txt
# ============================================================

import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from analysis import (
    _pick_recommendations,
    _select_quantity,
    _tier_of,
    analyze_transcript_v2,
    SCREENING_SYSTEM,
    REVIEW_SYSTEM,
    MISS_CHECK_SYSTEM,
    EVENT_JUDGE_SYSTEM,
    REPORT_SYSTEM,
)
from analysis import story_context as sc

LINES = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    LINES.append(f"[{tag}] {name} —— {detail}")
    print(f"[{tag}] {name} —— {detail}")
    return ok


def _cand(cid, grade, score, start="00:00", end="00:30", dims=None, title=None):
    """造一个内部候选（字段对齐事件结构，够 _select_quantity 用）。"""
    return {
        "clip_id": cid,
        "event_id": cid,
        "start_time": start,
        "end_time": end,
        "title": title or f"事件{cid}",
        "final_score": score,
        "score": 7,
        "grade": grade,
        "reason": "海选理由",
        "category": "其他",
        "viral_probability": "中",
        "editing_advice": "",
        "confidence": 0.8,
        "dims": dims or {},
        "negative_flags": [],
        "reject_reason": [],
        "summary": "这是摘要",
        "story_id": "__unknown__",
    }


# helper：把 _select_quantity 的返回压成 (grade, cid) 便于断言
def _ids(entries):
    return [e["clip_id"] for e in entries]


print("=" * 70)
print("V0.4.2 测试：评分/推荐解耦 + 内容结构层")
print("=" * 70)


# ============================================================
# A. _pick_recommendations（产品层推荐筛选）
# ============================================================
print("\n--- A. 推荐筛选 _pick_recommendations（A 优先 → B 补位 → C 兜底） ---")

# A1. A 充足（>= 目标）→ 只推荐 A，B 不进
cands = [_cand(f"ev-{i:03d}", "A", 95 - i * 0.1) for i in range(1, 12)]  # 11 个 A
cands += [_cand("ev-100", "B", 79), _cand("ev-101", "B", 77)]
rec = _pick_recommendations(cands)
ok = (len(rec) == config.AUTO_SELECT_TARGET
      and all(c["grade"] == "A" for c in rec))
check("A 充足时只推荐 A，B 不掺进来", ok,
      f"推荐 {len(rec)} 条（目标 {config.AUTO_SELECT_TARGET}），"
      f"grades={sorted({c['grade'] for c in rec})}")

# A2. 全 B（无 A）→ B 补位（这是修 0 输出的核心场景）
cands = [_cand(f"ev-{i:03d}", "B", 79.5 - i) for i in range(1, 6)]
rec = _pick_recommendations(cands)
ok = (len(rec) >= 1
      and all(c["recommend_tier"] == "B_fill" for c in rec)
      and all(c["recommended"] for c in rec))
check("无 A 时 B 级按分数补位（不再输出 0 条）", ok,
      f"推荐 {len(rec)} 条，tier={[c['recommend_tier'] for c in rec]}")

# A3. B 分数低于补位线（60）→ 不补，宁缺毋滥
cands = [_cand("ev-001", "B", 55.0), _cand("ev-002", "B", 52.0)]
rec = _pick_recommendations(cands)
ok = len(rec) == 0
check("B 级未达补位线（<60）时不硬凑", ok, f"推荐 {len(rec)} 条")

# A4. 连 B 都没有（全 C）→ 兜底少量 C，上限 AUTO_C_FALLBACK_MAX
cands = [_cand(f"ev-{i:03d}", "C", 59 - i) for i in range(1, 8)]
rec = _pick_recommendations(cands)
ok = (len(rec) == config.AUTO_C_FALLBACK_MAX
      and all(c["recommend_tier"] == "C_fallback" for c in rec))
check("全 C 时兜底保留不超过上限的 C", ok,
      f"推荐 {len(rec)} 条（上限 {config.AUTO_C_FALLBACK_MAX}）")

# A5. D 永不推荐
cands = [_cand("ev-001", "D", 30.0), _cand("ev-002", "C", 55.0)]
rec = _pick_recommendations(cands)
ok = all(c["grade"] != "D" for c in rec)
check("D 级永不进入推荐名单", ok, f"推荐 {[(c['clip_id'], c['grade']) for c in rec]}")

# A6. A 数量超过目标 → 按数量策略截断（内容好 ≠ 一定进推荐名单）
many = [_cand(f"ev-{i:03d}", "A", 95 - i * 0.1) for i in range(1, 15)]
rec = _pick_recommendations(many)
ok = len(rec) == config.AUTO_SELECT_TARGET
check("A 超过目标数量时被数量策略截断", ok,
      f"14 个 A → 推荐 {len(rec)} 条（目标 {config.AUTO_SELECT_TARGET}）")

# A7. tier 标签映射
ok = (_tier_of({"grade": "S"}) == "S" and _tier_of({"grade": "A"}) == "A"
      and _tier_of({"grade": "B"}) == "B_fill"
      and _tier_of({"grade": "C"}) == "C_fallback"
      and _tier_of({"grade": "D"}) == "")
check("推荐层级标签映射正确", ok,
      f"S/A/B/C/D → {_tier_of({'grade':'S'})}/{_tier_of({'grade':'A'})}/"
      f"{_tier_of({'grade':'B'})}/{_tier_of({'grade':'C'})}/'{_tier_of({'grade':'D'})}'")


# ============================================================
# B. _select_quantity（三种数量模式）
# ============================================================
print("\n--- B. 数量模式 _select_quantity ---")

# B1. 自动精选 + 无 A（复现用户遇到的实际问题）→ 必须非空
all_b = [_cand(f"ev-{i:03d}", "B", 79.5 - i * 5) for i in range(1, 14)]  # 79.5 ~ 19.5
hl, rj = _select_quantity(all_b, "自动精选", None)
ok = len(hl) >= 1 and all(h["recommended"] for h in hl)
check("自动精选：全场无 A 时仍产出推荐（原 bug 场景）", ok,
      f"highlights={len(hl)}, rejected={len(rj)}, "
      f"tier={[h['recommend_tier'] for h in hl]}")

# B2. 自动精选 + A 超量 → 截断 + A 落选进 rejected（解耦体现）
many_a = [_cand(f"ev-{i:03d}", "A", 95 - i * 0.1) for i in range(1, 15)]
hl, rj = _select_quantity(many_a, "自动精选", None)
ok = (len(hl) == config.AUTO_SELECT_TARGET and len(rj) == 14 - config.AUTO_SELECT_TARGET
      and any("推荐数量已达目标" in "".join(r.get("reject_reason", [])) for r in rj))
check("自动精选：A 超量按数量策略截断，落选 A 带解释", ok,
      f"highlights={len(hl)}, rejected={len(rj)}, "
      f"reject_reason={rj[0].get('reject_reason') if rj else '无'}")

# B3. 候选池 → 展示 S/A/B/C 全部，但 recommended 是子集
pool = ([_cand("ev-001", "A", 88)] + [_cand(f"ev-{i:03d}", "B", 75 - i)
                                       for i in range(2, 12)]
        + [_cand(f"ev-{i:03d}", "C", 55 - i) for i in range(20, 23)]
        + [_cand("ev-090", "D", 30)])
hl, rj = _select_quantity(pool, "候选池", None)
rec_in_hl = [h for h in hl if h["recommended"]]
# pool = 1 A + 10 B + 3 C = 14 条 S/A/B/C，1 条 D（进 rejected）
ok = (len(hl) == 14 and len(rec_in_hl) < len(hl) and len(rj) == 1)
check("候选池：S/A/B/C 全展示，推荐名单是其中子集", ok,
      f"highlights={len(hl)}（其中推荐 {len(rec_in_hl)}）, rejected={len(rj)}")

# B4. 自定义数量 → 按分数取前 N，全部 recommended
cust = [_cand(f"ev-{i:03d}", "B", 70 - i) for i in range(1, 12)]
hl, rj = _select_quantity(cust, "自定义数量", 5)
ok = len(hl) == 5 and all(h["recommended"] for h in hl)
check("自定义数量：取前 N 个且全部标记推荐", ok,
      f"highlights={len(hl)}, 全部推荐={all(h['recommended'] for h in hl)}")

# B5. ai_recommend 仍是 S/A 语义（内容级背书，不受推荐策略影响）
hl, _ = _select_quantity([_cand("ev-001", "A", 85), _cand("ev-002", "B", 75)],
                         "候选池", None)
a = next(h for h in hl if h["grade"] == "A")
b = next(h for h in hl if h["grade"] == "B")
ok = a["ai_recommend"] is True and b["ai_recommend"] is False
check("ai_recommend 仍 = S/A（内容级背书，与推荐解耦）", ok,
      f"A:ai_recommend={a['ai_recommend']}, B:ai_recommend={b['ai_recommend']}, "
      f"B.recommended={b['recommended']}")


# ============================================================
# C. 内容结构层（load_structure / build_content_structure）
# ============================================================
print("\n--- C. 内容结构层 story_context ---")

structure_raw = sc.load_structure(str(Path(__file__).parent / "poc" / "fixtures" / "story_segmentation_result.json"))
ok = len(structure_raw["chapters"]) == 4 and len(structure_raw["stories"]) == 10
check("加载已验证 Chapter/Story 结构（4 章 / 10 故事）", ok,
      f"chapters={len(structure_raw['chapters'])}, stories={len(structure_raw['stories'])}")

ok = all("start" in s and "end" in s for s in structure_raw["stories"])
check("Story 已补 seconds 区间（供时间交集匹配）", ok,
      f"首个 story: {structure_raw['stories'][0]['story_id']} "
      f"{structure_raw['stories'][0]['start']}-{structure_raw['stories'][0]['end']}")

# 用真实 V0.4.1 结果构造事件，验证挂载 + 派生评分
events = [
    {"event_id": "ev-005", "clip_id": "ev-005", "grade": "B", "final_score": 79.5,
     "start_time": "21:11", "end_time": "22:09", "title": "咖啡鞠躬道歉",
     "summary": "咖啡吐槽", "recommended": True, "recommend_tier": "B_fill"},
    {"event_id": "ev-008", "clip_id": "ev-008", "grade": "B", "final_score": 70.0,
     "start_time": "36:12", "end_time": "39:50", "title": "过期罐头",
     "summary": "罐头试吃", "recommended": False, "recommend_tier": ""},
]
struct = sc.build_content_structure(structure_raw, events)
ok = len(struct["chapters"]) == 4 and struct["stats"]["story_count"] == 10
check("构建内容结构：Chapter 数 / Story 数不变", ok,
      f"chapters={len(struct['chapters'])}, stories={struct['stats']['story_count']}")

story_coffee = next(s for ch in struct["chapters"] for s in ch["stories"]
                    if s["story_id"] == "ch-02-st-04")
ok = (story_coffee["score"] == 79.5 and story_coffee["grade"] == "B"
      and story_coffee["best_event_id"] == "ev-005")
check("Story 评分 = 该 Story 内最强事件分（不新造评分模型）", ok,
      f"ch-02-st-04 score={story_coffee['score']} grade={story_coffee['grade']} "
      f"best={story_coffee['best_event_id']}")

story_empty = next(s for ch in struct["chapters"] for s in ch["stories"]
                   if s["story_id"] == "ch-02-st-03")
ok = story_empty["score"] is None and story_empty["grade"] == "" and story_empty["event_count"] == 0
check("无匹配事件的 Story → 未评（None / 空等级）不崩", ok,
      f"ch-02-st-03 score={story_empty['score']} grade='{story_empty['grade']}' "
      f"events={story_empty['event_count']}")

# 结构缺失 → 静默降级
empty_struct = sc.build_content_structure({"chapters": [], "stories": []}, events)
ok = empty_struct["chapters"] == [] and empty_struct["stats"]["chapter_count"] == 0
check("结构缺失时静默降级为空结构（UI 可退化展示）", ok,
      f"chapters={len(empty_struct['chapters'])}")

ok = sc.load_structure("不存在的文件.json") == {"chapters": [], "stories": []}
check("结构文件不存在 → 返回空结构不抛异常", ok, "已返回空结构")

# 推荐标记随事件带进结构（UI 关联用）
all_briefs = [e for ch in struct["chapters"] for s in ch["stories"] for e in s["events"]]
rec_briefs = [e for e in all_briefs if e["recommended"]]
check("推荐标记随事件进入结构层（供 UI 建立关联）", len(rec_briefs) == 1,
      f"结构中推荐事件 {[(e['event_id'], e['recommend_tier']) for e in rec_briefs]}")


# ============================================================
# D. 端到端（假客户端，零成本）
# ============================================================
print("\n--- D. 端到端：自动精选 + 结构层贯通（全 B 场景） ---")

usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
state = {"screen": 0, "review": 0, "report": 0}
# 全部子分 = 7 → 加权 70 分 → B 级（全场无 A，复现真实场景）
PROF = {"hook": 7, "contrast": 7, "persona": 7, "standalone": 7, "completeness": 7}


def flow_client(prompt, system=None, max_tokens=None):
    if system == SCREENING_SYSTEM:
        state["screen"] += 1
        if state["screen"] > 1:
            return json.dumps({"candidates": []}), usage
        return json.dumps({"candidates": [
            {"start_time": "00:00", "end_time": "00:30", "title": "事件A",
             "highlight_type": "事件型", "score": 7, "reason": "r",
             "category": "其他", "viral_probability": "高",
             "editing_advice": "", "confidence": 0.8},
            {"start_time": "03:00", "end_time": "03:30", "title": "事件B",
             "highlight_type": "事件型", "score": 7, "reason": "r",
             "category": "其他", "viral_probability": "中",
             "editing_advice": "", "confidence": 0.7},
        ]}), usage
    if system == MISS_CHECK_SYSTEM:
        return json.dumps({"checks": []}), usage
    if system == EVENT_JUDGE_SYSTEM:
        return json.dumps({
            "same_event": False, "event_summary": "s", "event_type": "t",
            "event_start": "00:00", "event_end": "03:30",
            "structure": {"setup": "s", "development": "d", "payoff": "p"},
            "strongest_moment": "m", "reason": "不同事件", "confidence": 0.5,
            "need_more_context": False, "expand_direction": "",
        }, ensure_ascii=False), usage
    if system == REPORT_SYSTEM:
        state["report"] += 1
        return json.dumps({"summary": "两事件", "best_spread_point": "A",
                           "overall": "中等", "why_not_more": "偏平淡"}), usage
    if system == REVIEW_SYSTEM:
        state["review"] += 1
        import re
        eids = re.findall(r"（(ev-\d+)）", prompt)
        return json.dumps({"results": [{
            "event_id": eid, "title": "t",
            "scores": {"hook": PROF["hook"], "contrast": PROF["contrast"],
                       "personality": PROF["persona"],
                       "standalone": PROF["standalone"],
                       "completeness": PROF["completeness"]},
            "recommended_start": "00:00", "recommended_end": "00:30",
            "recommended_duration": 30, "duration_reason": "完整",
            "negative_flags": [], "why_cut": "有反差", "strongest_moment": "m",
            "risk": "无", "confidence": 0.7, "context_incomplete": False,
        } for eid in eids]}), usage
    return json.dumps({"candidates": []}), usage


tmp = Path(tempfile.mkdtemp())
transcript = tmp / "全B场景.txt"
transcript.write_text(
    "[00:00 - 00:30] 主播开始试吃，期待满满\n"
    "[03:00 - 03:30] 主播讲了句金句，反应强烈\n",
    encoding="utf-8",
)

r = analyze_transcript_v2(
    transcript, live_type="娱乐聊天", token_mode="精细",
    quantity_mode="自动精选", client=flow_client, verbose=False,
)

hl = r["highlights"]
ok = len(hl) >= 1 and all(h["grade"] == "B" for h in hl)
check("端到端：全场只有 B 时自动精选仍输出推荐（原问题已修）", ok,
      f"highlights={len(hl)}, grades={[h['grade'] for h in hl]}, "
      f"tiers={[h['recommend_tier'] for h in hl]}")

ok = all("recommended" in h and "recommend_tier" in h for h in hl)
check("端到端：高光条目带 recommended / recommend_tier 字段", ok,
      f"字段齐全={ok}")

ok = "structure" in r and isinstance(r["structure"], dict)
check("端到端：结果包含 structure 内容结构段", ok,
      f"structure keys={list(r.get('structure', {}).keys())}")

# 结构层在端到端里也应能挂上事件（假稿时间落在 story 区间外时允许 0 个事件）
struct_e2e = r["structure"]
ok = "stats" in struct_e2e and "chapter_count" in struct_e2e["stats"]
check("端到端：结构层带 stats 统计", ok, f"stats={struct_e2e.get('stats')}")


# ============================================================
print("\n" + "=" * 70)
total = len(LINES)
passed = sum(1 for l in LINES if l.startswith("[PASS]"))
failed = total - passed
print(f"结果：{passed}/{total} 通过" + (f"，{failed} 个失败" if failed else "，全部通过 ✅"))
print("=" * 70)

report = Path(__file__).parent / "v040_step6_report.txt"
report.write_text(
    "V0.4.2 离线自测报告（评分/推荐解耦 + 内容结构层，纯本地零成本）\n\n"
    + "\n".join(LINES)
    + f"\n\n结果：{passed}/{total} 通过\n",
    encoding="utf-8",
)
print(f"report saved: {report}")
