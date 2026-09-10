# ============================================================
# test_v040_step2.py —— v0.4 步骤 2 离线自测（事件聚合层）
#
# 本次验证「事件聚合」：本地粗聚类 + AI 事件判断 + 事件级去重。
# AI 判断用假客户端（fake client）模拟，零 API 成本——
# 只测编排逻辑和本地算法，不测 DeepSeek 真实回答质量（那是真实验收）。
#
# 覆盖需求第十节指定的验收（逐条对应）：
#   A 本地粗聚类（build_clusters，纯本地）：
#     1. 三个连续同主题候选 → 合并成一簇（需求测试 1）
#     2. 主题完全不同 + 时间拉开 → 本地分成多簇（需求测试 3 本地侧）
#     3. 5~10 分钟长事件 → 链式串成一簇，不因时长硬拆（需求测试 4）
#     4. 短笑话单候选 → 自成一簇保持短（需求测试 5）
#     5. 孤立候选 → 自成一簇，一个不删（铁律）
#     6. 全时间轴覆盖：所有候选都落在某一簇、且只出现一次（需求测试 9）
#   B AI 回复解析（_parse_event_judge_reply）：
#     7. 正常 JSON → 字段齐全
#     8. 坏 JSON → None 不崩
#     9. need_more_context / expand_direction 正确解析
#   C 事件生成（_make_event）：
#     10. event_id == clip_id、structure/source_candidates 完整
#     11. reason/viral_probability/editing_advice/confidence 继承（回归修复项）
#     12. 多个原始候选聚合 → source_candidates 一个不丢
#   D 事件级去重（_dedupe_events）：
#     13. 时间重叠>50% 且主题相同 → 合并成一个（需求测试 8）
#     14. 主题不同 → 保留两个
#   E 完整编排（_run_event_aggregation，fake client）：
#     15. 三连续候选同事件 → 合并成 1 个事件（需求测试 1/2/6）
#     16. 时间接近但主题不同 → AI 拆开（需求测试 3 AI 侧）
#     17. payoff 在上下文外 → AI 请求扩大上下文重判（需求测试 7）
#     18. AI 翻车坏 JSON → 各自成事件，不崩不丢
#     19. 聚合后碎片减少（候选数 > 事件数）
#
# 运行：.\.venv\Scripts\python test_v040_step2.py
# 结果：v040_step2_report.txt
# ============================================================

import json
import re
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import analysis.event_cluster as ec
from analysis import (
    _parse_event_judge_reply,
    _make_event,
    _dedupe_events,
    _run_event_aggregation,
    analyze_transcript_v2,
    SCREENING_SYSTEM,
    REVIEW_SYSTEM,
    MISS_CHECK_SYSTEM,
    EVENT_JUDGE_SYSTEM,
    REPORT_SYSTEM,
)

BASE_DIR = Path(__file__).parent
REPORT_FILE = BASE_DIR / "v040_step2_report.txt"

_report = []


def log(msg=""):
    _report.append(msg)
    print(msg.encode("ascii", "replace").decode("ascii"))


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    log(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
    return ok


# ---------- 造候选的小工具 ----------

def cand(start_time, end_time, title, reason="", **kw):
    c = {
        "start_time": start_time,
        "end_time": end_time,
        "title": title,
        "reason": reason,
        "highlight_type": "事件型",
        "category": "其他",
        "score": 6,
        "confidence": 0.7,
        "viral_probability": "中",
        "editing_advice": "",
        "clip_id": "",
    }
    c.update(kw)
    return c


def make_segments(start_min, end_min, step=30):
    """造一段铺满时间轴的台词（每 step 秒一句），供上下文窗口用。"""
    segs = []
    t = start_min * 60
    end = end_min * 60
    i = 0
    while t < end:
        segs.append({"start": t, "end": t + step, "text": f"台词{i}号"})
        t += step
        i += 1
    return segs


# ---------- 假 AI 客户端 ----------

def make_fake_client(script):
    """按调用顺序返回预设回复；超过预设就返回空对象（兜底不崩）。

    script 每项是 (reply_json_str, usage_dict)。
    """
    state = {"n": 0}

    def client(prompt, system=None, max_tokens=None):
        i = state["n"]
        state["n"] += 1
        if i < len(script):
            return script[i]
        return "{}", {"prompt_tokens": 0, "completion_tokens": 0}

    return client, state


class FakeTracker:
    def __init__(self):
        self.calls = 0

    def add(self, usage):
        self.calls += 1

    def report(self):
        return ""

    def to_dict(self):
        return {"calls": self.calls}


def _judge_json(same_event=True, summary="口粮事件", start="00:00", end="01:50",
                setup="拆包装", development="发现份量少", payoff="吐槽像纸盒",
                strongest="吐槽像纸盒", confidence=0.9, need_more=False,
                direction="both", event_type="试吃"):
    return json.dumps({
        "same_event": same_event,
        "event_summary": summary,
        "event_type": event_type,
        "event_start": start,
        "event_end": end,
        "structure": {"setup": setup, "development": development, "payoff": payoff},
        "strongest_moment": strongest,
        "reason": "因果链连续",
        "confidence": confidence,
        "need_more_context": need_more,
        "expand_direction": direction,
    }, ensure_ascii=False)


# ---------------- A 本地粗聚类 ----------------

def scenario_a():
    log("--- A 本地粗聚类（build_clusters，纯本地） ---")

    # 1 三个连续同主题候选 → 合并
    c = [
        cand("00:00", "00:30", "主播拆开美军口粮", "期待满满"),
        cand("00:35", "01:10", "口粮份量好少", "发现份量少"),
        cand("01:15", "01:50", "尝一口像纸盒", "吐槽"),
    ]
    clusters = ec.build_clusters(c)
    ok1 = len(clusters) == 1 and sorted(clusters[0]["members"]) == [0, 1, 2]
    check("三个连续同主题候选合并成一簇", ok1,
          f"{len(clusters)} 簇，成员={[cl['members'] for cl in clusters]}")

    # 2 主题完全不同 + 时间拉开 → 分簇
    # （注意 reason 也不能撞词，否则主题分虚高会把它们错误连边）
    c2 = [
        cand("00:00", "00:30", "拆开美军口粮", "试吃开始"),
        cand("02:00", "02:30", "开始讲解游戏", "讲解对局"),
        cand("04:00", "04:30", "回答粉丝提问", "读弹幕"),
    ]
    clusters2 = ec.build_clusters(c2)
    ok2 = len(clusters2) == 3
    check("主题完全不同且时间拉开 → 本地分成多簇", ok2,
          f"{len(clusters2)} 簇（应为 3）")

    # 3 长事件 5~10 分钟不硬拆（链式连通）
    c3 = [
        cand("00:00", "00:30", "口粮拆包", "开始"),
        cand("01:30", "02:00", "口粮份量少", "发现"),
        cand("03:00", "03:30", "口粮试吃", "过程"),
        cand("04:30", "05:00", "口粮像纸盒", "转折"),
        cand("06:00", "06:30", "口粮总结", "结果"),
        cand("07:30", "08:00", "口粮收尾", "结束"),
    ]
    clusters3 = ec.build_clusters(c3)
    long_one = (len(clusters3) == 1 and len(clusters3[0]["members"]) == 6
                and clusters3[0]["start"] == 0 and clusters3[0]["end"] == 480)
    check("5~10 分钟长事件链式串成一簇不硬拆", long_one,
          f"{len(clusters3)} 簇，span={clusters3[0]['start']}-{clusters3[0]['end']}" if clusters3 else "空")

    # 4 短笑话单候选保持短
    c4 = [cand("10:00", "10:10", "一句话梗", "笑点")]
    clusters4 = ec.build_clusters(c4)
    ok4 = (len(clusters4) == 1 and clusters4[0]["members"] == [0]
           and clusters4[0]["start"] == 600 and clusters4[0]["end"] == 610)
    check("短笑话单候选自成一簇保持短", ok4,
          f"span={clusters4[0]['start']}-{clusters4[0]['end']}" if clusters4 else "空")

    # 5 孤立候选自成一簇不删 + 6 全时间轴覆盖
    c5 = [
        cand("00:00", "00:30", "口粮拆包", "事件A"),
        cand("00:35", "01:00", "口粮份量少", "事件A"),
        cand("05:00", "05:20", "突然开始唱歌", "无关"),
    ]
    clusters5 = ec.build_clusters(c5)
    all_members = sorted(m for cl in clusters5 for m in cl["members"])
    ok5 = (len(clusters5) == 2                      # 口粮两候选一簇 + 唱歌孤立一簇
           and all_members == [0, 1, 2])             # 一个不删
    check("孤立候选自成一簇且全时间轴覆盖（一个不删）", ok5,
          f"{len(clusters5)} 簇，成员分布={[cl['members'] for cl in clusters5]}")


# ---------------- B 解析 AI 回复 ----------------

def scenario_b():
    log()
    log("--- B AI 回复解析（_parse_event_judge_reply） ---")

    # 7 正常 JSON
    j = _judge_json()
    r = _parse_event_judge_reply(j)
    ok7 = (r is not None and r["same_event"] is True
           and r["event_summary"] == "口粮事件"
           and r["structure"]["payoff"] == "吐槽像纸盒"
           and r["strongest_moment"] == "吐槽像纸盒"
           and r["confidence"] == 0.9)
    check("正常 JSON 字段齐全", ok7, f"summary={r['event_summary'] if r else None}")

    # 8 坏 JSON
    check("坏 JSON 返回 None 不崩", _parse_event_judge_reply("这不是JSON") is None)

    # 9 need_more_context + expand_direction
    r9 = _parse_event_judge_reply(
        _judge_json(need_more=True, direction="after", confidence=0.6)
    )
    ok9 = (r9["need_more_context"] is True and r9["expand_direction"] == "after")
    check("need_more_context / expand_direction 正确解析", ok9,
          f"need={r9['need_more_context']} dir={r9['expand_direction']}")


# ---------------- C 事件生成 ----------------

def scenario_c():
    log()
    log("--- C 事件生成（_make_event） ---")

    members = [
        cand("00:00", "00:30", "拆开美军口粮", "期待", clip_id="clip-001"),
        cand("00:35", "01:10", "口粮份量好少", "发现", clip_id="clip-002"),
        cand("01:15", "01:50", "尝一口像纸盒", "吐槽", clip_id="clip-003"),
    ]
    cluster = {"cluster_id": "cluster-001", "start": 0.0, "end": 110.0}
    judge = _parse_event_judge_reply(_judge_json())

    ev = _make_event(members, cluster, judge, [], duration=3000, event_no=1)

    # 10 event_id == clip_id、结构完整
    ok10 = (ev["event_id"] == "ev-001" and ev["clip_id"] == ev["event_id"]
            and ev["structure"]["setup"] == "拆包装"
            and ev["strongest_moment"] == "吐槽像纸盒"
            and ev["summary"] == "口粮事件")
    check("event_id == clip_id、structure/strongest/summary 完整", ok10,
          f"{ev['event_id']} / {ev['clip_id']}")

    # 11 继承字段（回归修复项：_select_quantity 会取这些键，缺了会 KeyError）
    ok11 = ("reason" in ev and "viral_probability" in ev
            and "editing_advice" in ev and "confidence" in ev
            and ev["reason"] == "期待" and ev["viral_probability"] == "中"
            and ev["confidence"] == 0.9)
    check("reason/viral_probability/editing_advice/confidence 继承", ok11,
          f"reason={ev.get('reason')} conf={ev.get('confidence')}")

    # 12 source_candidates 一个不丢
    ok12 = (ev["source_candidates"] == ["clip-001", "clip-002", "clip-003"]
            and ev["source_count"] == 3)
    check("多个候选聚合 → source_candidates 一个不丢", ok12,
          f"{ev['source_candidates']}")


# ---------------- D 事件级去重 ----------------

def scenario_d():
    log()
    log("--- D 事件级去重（_dedupe_events） ---")

    base = {"event_id": "", "clip_id": "", "title": "", "structure": {},
            "strongest_moment": "", "source_candidates": [], "source_count": 0}
    # 13 时间重叠>50% 且主题相同 → 合并成一个
    a = dict(base, event_id="ev-001", clip_id="ev-001", start=0.0, end=100.0,
             summary="主播测试美军口粮事件")
    b = dict(base, event_id="ev-002", clip_id="ev-002", start=45.0, end=145.0,
             summary="主播测试美军口粮事件总结")
    merged = _dedupe_events([a, b])
    ok13 = (len(merged) == 1 and merged[0]["event_id"] == "ev-001"
            and "ev-002" in merged[0].get("merged_from", []))
    check("时间重叠>50%且主题相同 → 合并成一个", ok13,
          f"{len(merged)} 个，merged_from={merged[0].get('merged_from')}")

    # 14 主题不同 → 保留两个
    a2 = dict(base, event_id="ev-001", clip_id="ev-001", start=0.0, end=100.0,
              summary="主播测试口粮")
    b2 = dict(base, event_id="ev-002", clip_id="ev-002", start=60.0, end=160.0,
              summary="主播突然开始唱歌")
    kept = _dedupe_events([a2, b2])
    check("主题不同 → 保留两个", len(kept) == 2, f"{len(kept)} 个（应为 2）")


# ---------------- E 完整编排（fake client） ----------------

def scenario_e():
    log()
    log("--- E 完整编排（_run_event_aggregation，fake client） ---")

    segs = make_segments(0, 20)  # 0~20 分钟的台词，供上下文窗口

    # 15 三连续候选同事件 → 合并成 1 个事件
    c = [
        cand("00:00", "00:30", "拆开美军口粮", "期待", clip_id=""),
        cand("00:35", "01:10", "口粮份量好少", "发现", clip_id=""),
        cand("01:15", "01:50", "尝一口像纸盒", "吐槽", clip_id=""),
    ]
    client, _ = make_fake_client([
        (_judge_json(same_event=True), {"prompt_tokens": 100, "completion_tokens": 50}),
    ])
    events, stats = _run_event_aggregation(
        client, FakeTracker(), segs, c, duration=3000, say=lambda m: None)
    ok15 = (len(events) == 1 and events[0]["source_count"] == 3
            and stats["merged"] == 2 and stats["judge_calls"] == 1)
    check("三连续候选同事件 → 合并成 1 个事件", ok15,
          f"{len(events)} 事件，source_count={events[0]['source_count'] if events else 0}")

    # 16 时间接近但主题不同 → AI 拆开
    c2 = [
        cand("00:00", "00:30", "拆开美军口粮", "期待"),
        cand("00:35", "01:10", "开始讲游戏攻略", "切话题"),
    ]
    client2, _ = make_fake_client([
        (_judge_json(same_event=False), {"prompt_tokens": 100, "completion_tokens": 50}),
    ])
    events2, stats2 = _run_event_aggregation(
        client2, FakeTracker(), segs, c2, duration=3000, say=lambda m: None)
    ok16 = (len(events2) == 2 and stats2["split"] == 1
            and all(e["split_by_ai"] for e in events2))
    check("时间接近但主题不同 → AI 拆开", ok16,
          f"{len(events2)} 事件，split={stats2['split']}")

    # 17 payoff 在上下文外 → AI 请求扩大上下文重判
    c3 = [
        cand("00:00", "00:30", "拆开美军口粮", "期待"),
        cand("00:35", "01:10", "口粮份量好少", "发现"),
    ]
    client3, state3 = make_fake_client([
        (_judge_json(need_more=True, direction="after"),
         {"prompt_tokens": 100, "completion_tokens": 50}),
        (_judge_json(same_event=True),
         {"prompt_tokens": 200, "completion_tokens": 60}),
    ])
    events3, stats3 = _run_event_aggregation(
        client3, FakeTracker(), segs, c3, duration=3000, say=lambda m: None)
    ok17 = (len(events3) == 1 and stats3["expanded"] == 1
            and stats3["judge_calls"] == 2)
    check("payoff 在上下文外 → 扩大上下文重判", ok17,
          f"expanded={stats3['expanded']} calls={stats3['judge_calls']}")

    # 18 AI 翻车坏 JSON → 各自成事件，不崩不丢
    c4 = [
        cand("00:00", "00:30", "拆开美军口粮", "期待"),
        cand("00:35", "01:10", "口粮份量好少", "发现"),
        cand("01:15", "01:50", "尝一口像纸盒", "吐槽"),
    ]
    client4, _ = make_fake_client([
        ("这不是合法JSON{{{", {"prompt_tokens": 100, "completion_tokens": 50}),
    ])
    events4, stats4 = _run_event_aggregation(
        client4, FakeTracker(), segs, c4, duration=3000, say=lambda m: None)
    ok18 = (len(events4) == 3 and stats4["judge_failed"] == 1
            and all(e["judge_confidence"] == 0.0 for e in events4))
    check("AI 翻车坏 JSON → 各自成事件不崩不丢", ok18,
          f"{len(events4)} 事件，judge_failed={stats4['judge_failed']}")

    # 19 聚合后碎片减少（候选数 > 事件数，即真的「聚」了）
    c5 = [
        cand("00:00", "00:30", "拆开美军口粮", "期待"),
        cand("00:35", "01:10", "口粮份量好少", "发现"),
        cand("01:15", "01:50", "尝一口像纸盒", "吐槽"),
        cand("02:00", "02:30", "口粮总结", "收尾"),
    ]
    client5, _ = make_fake_client([
        (_judge_json(same_event=True, end="02:30"), {"prompt_tokens": 100, "completion_tokens": 50}),
    ])
    events5, stats5 = _run_event_aggregation(
        client5, FakeTracker(), segs, c5, duration=3000, say=lambda m: None)
    ok19 = len(events5) < len(c5) and stats5["events"] == len(events5)
    check("聚合后碎片减少（候选 > 事件）", ok19,
          f"{len(c5)} 候选 → {len(events5)} 事件")


# ---------------- F 事件级完整流程（评分逻辑不回退） ----------------

def _make_flow_client(review_profiles, same_event=True):
    """走完整 analyze_transcript_v2 的假 client，按 system 参数路由。

    海选固定吐 3 个「口粮事件」候选；事件判断按 same_event；
    复审按 prompt 里的 event_id 回填（用 v0.4 步骤 3 的新协议：
    嵌套 scores + personality 键 + recommended_* + is_worth_clipping）。
    """
    state = {"review_calls": 0, "judge_calls": 0, "screen_calls": 0,
             "report_calls": 0}
    usage = {"prompt_tokens": 100, "completion_tokens": 50}

    def client(prompt, system=None, max_tokens=None):
        if system == SCREENING_SYSTEM:
            state["screen_calls"] += 1
            if state["screen_calls"] > 1:
                return json.dumps({"candidates": []}), usage
            return json.dumps({"candidates": [
                {"start_time": "00:00", "end_time": "00:30", "title": "拆开美军口粮",
                 "highlight_type": "事件型", "score": 6, "reason": "期待",
                 "category": "其他", "viral_probability": "中",
                 "editing_advice": "", "confidence": 0.7},
                {"start_time": "00:35", "end_time": "01:10", "title": "口粮份量好少",
                 "highlight_type": "事件型", "score": 6, "reason": "发现份量少",
                 "category": "其他", "viral_probability": "中",
                 "editing_advice": "", "confidence": 0.7},
                {"start_time": "01:15", "end_time": "01:50", "title": "尝一口像纸盒",
                 "highlight_type": "事件型", "score": 8, "reason": "吐槽",
                 "category": "其他", "viral_probability": "高",
                 "editing_advice": "", "confidence": 0.8},
            ]}), usage
        if system == MISS_CHECK_SYSTEM:
            return json.dumps({"checks": []}), usage
        if system == EVENT_JUDGE_SYSTEM:
            state["judge_calls"] += 1
            return _judge_json(same_event=same_event), usage
        if system == REPORT_SYSTEM:
            state["report_calls"] += 1
            return json.dumps({"summary": "口粮试吃", "best_spread_point": "像纸盒",
                               "overall": "平淡", "why_not_more": "多数没传播点"}), usage
        if system == REVIEW_SYSTEM:
            state["review_calls"] += 1
            eids = re.findall(r"（(ev-\d+)）", prompt)
            results = []
            for i, eid in enumerate(eids):
                p = dict(review_profiles[i % len(review_profiles)])
                # v0.4 步骤 3 协议：嵌套 scores + personality 键 + recommended_*
                results.append({
                    "event_id": eid,
                    "title": f"事件{eid}",
                    "is_worth_clipping": True,
                    "scores": {
                        "hook": p["hook"], "contrast": p["contrast"],
                        "personality": p["persona"], "standalone": p["standalone"],
                        "completeness": p["completeness"],
                    },
                    "recommended_start": "00:00", "recommended_end": "01:50",
                    "recommended_duration": 110,
                    "duration_reason": "铺垫+反应",
                    "negative_flags": p.get("negative_flags", []),
                    "why_cut": p.get("why_cut", "有传播点"),
                    "strongest_moment": "吐槽",
                    "risk": p.get("risk", "依赖前文"),
                    "confidence": 0.7,
                    "context_incomplete": False,
                })
            return json.dumps({"results": results}), usage
        return json.dumps({"candidates": []}), usage

    return client, state


_S_PROFILE = {"hook": 10, "contrast": 10, "persona": 9,
              "standalone": 8, "completeness": 9,
              "why_cut": "误会+强反差", "risk": "依赖画面"}
_NEG_PROFILE = {"hook": 10, "contrast": 10, "persona": 9,
                "standalone": 8, "completeness": 9,
                "negative_flags": ["普通失误"],
                "why_cut": "看着热闹", "risk": "其实是普通失误"}
_LOW_PROFILE = {"hook": 4, "contrast": 5, "persona": 4,
                "standalone": 5, "completeness": 5,
                "why_cut": "平淡", "risk": "没传播点"}


def scenario_f():
    log()
    log("--- F 事件级完整流程（评分逻辑不回退） ---")

    tmp = Path(tempfile.mkdtemp())
    transcript = tmp / "稿子.txt"
    transcript.write_text(
        "[00:00 - 00:30] 主播拆开美军口粮\n"
        "[00:35 - 01:10] 发现份量好少\n"
        "[01:15 - 01:50] 尝一口像纸盒\n"
        "[02:00 - 02:30] 总结评价\n",
        encoding="utf-8",
    )

    # F1 五档定级 + 事件级合并 + clip_id=event_id
    client, state = _make_flow_client([_S_PROFILE], same_event=True)
    r = analyze_transcript_v2(
        transcript, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=client, verbose=False,
    )
    hl = r["highlights"]
    ok_f1 = (state["judge_calls"] == 1 and state["review_calls"] == 1
             and len(hl) == 1
             and hl[0]["clip_id"] == "ev-001"
             and hl[0]["grade"] == "S"
             and hl[0]["why_cut"] == "误会+强反差"
             and hl[0]["risk"] == "依赖画面"
             and hl[0]["source_count"] == 3)
    check("复审按 event_id 合并，S 档产出，clip_id=ev-001", ok_f1,
          f"{len(hl)} 高光，grade={hl[0]['grade'] if hl else None}，"
          f"clip_id={hl[0]['clip_id'] if hl else None}")

    # F2 负面封顶：高分但命中普通失误 → 封顶 B
    client2, _ = _make_flow_client([_NEG_PROFILE], same_event=True)
    r2 = analyze_transcript_v2(
        transcript, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=client2, verbose=False,
    )
    hl2 = r2["highlights"]
    ok_f2 = (len(hl2) == 1 and hl2[0]["grade"] == "B"
             and "普通失误" in hl2[0]["negative_flags"])
    check("负面清单封顶：高分命中普通失误 → B 级", ok_f2,
          f"grade={hl2[0]['grade'] if hl2 else None}，"
          f"flags={hl2[0]['negative_flags'] if hl2 else None}")

    # F3 零输出禁令：全灭（加权 4.5）→ forced_keep C
    client3, _ = _make_flow_client([_LOW_PROFILE], same_event=True)
    r3 = analyze_transcript_v2(
        transcript, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=client3, verbose=False,
    )
    hl3 = r3["highlights"]
    ok_f3 = (len(hl3) == 1 and hl3[0]["grade"] == "C"
             and hl3[0].get("forced_keep") is True)
    check("零输出禁令：全灭 4.5 分 → forced_keep C 级", ok_f3,
          f"{len(hl3)} 高光，grade={hl3[0]['grade'] if hl3 else None}，"
          f"forced_keep={hl3[0].get('forced_keep') if hl3 else None}")


# ---------------- 总入口 ----------------

def main():
    log("v0.4 步骤 2 离线自测报告（事件聚合层：本地聚类 + AI 判断 + 事件去重）")
    log("（AI 判断用假客户端模拟，零 API 成本；只测编排逻辑，不测真实回答质量）")
    log()

    scenario_a()
    scenario_b()
    scenario_c()
    scenario_d()
    scenario_e()
    scenario_f()

    log()
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
