# ============================================================
# test_v040_step4.py —— v0.4 步骤 4：Chapter→Story 前置层接入
#
# 验证 Story 前置层正确工作：
#   1. 加载已验证的 Story 分割结果（poc/story_segmentation_result.json）
#   2. 候选打上 story_id 字段
#   3. 同 Story 内候选关联分 +0.05，跨 Story 不额外减速
#   4. _run_event_aggregation 完整集成测试
#   5. 找不到 Story 文件时静默降级
#
# 运行：.venv/Scripts/python test_v040_step4.py
# ============================================================

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 测试目录
BASE_DIR = Path(__file__).parent
REPORT_FILE = BASE_DIR / "v040_step4_report.txt"

_report = []


def log(msg=""):
    _report.append(msg)
    print(msg.encode("ascii", "replace").decode("ascii"))


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    log(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
    return ok


# ============================================================
# A. story_context 模块测试（纯本地）
# ============================================================

def scenario_a():
    log("--- A. story_context 模块测试 ---")
    from analysis import story_context

    # 1. 加载 Story 文件
    groups = story_context.load_story_groups(str(Path(__file__).parent / "poc" / "fixtures" / "story_segmentation_result.json"))
    ok1 = len(groups) == 10  # 已验证的 Story 结果有 10 个
    check("加载 Story 分割结果（应有 10 个）", ok1, f"实际 {len(groups)} 个")

    # 2. 验证 Story 时间范围（注意：key 现在是 chapter_id-story_id 格式）
    st_ch01 = groups.get("ch-01-st-01", {})
    ok2 = st_ch01.get("start") == 115 and st_ch01.get("end") == 209  # 01:55-03:29
    check("ch-01-st-01 时间范围正确（01:55-03:29）", ok2,
          f"start={st_ch01.get('start')}, end={st_ch01.get('end')}")

    st_ch02_st01 = groups.get("ch-02-st-01", {})
    ok3 = st_ch02_st01.get("start") == 275 and st_ch02_st01.get("end") == 672  # 04:35-11:12
    check("ch-02-st-01 时间范围正确（04:35-11:12）", ok3,
          f"start={st_ch02_st01.get('start')}, end={st_ch02_st01.get('end')}")

    # 3. 候选标注：命中 Story
    cands = [
        {"start_time": "02:00", "end_time": "03:00"},  # 应命中 ch-01-st-01
        {"start_time": "05:00", "end_time": "06:00"},  # 应命中 ch-02-st-01
        {"start_time": "10:00", "end_time": "11:00"},  # 应命中 ch-02-st-01
    ]
    story_context.annotate_candidates(cands, groups)
    ok4 = cands[0]["story_id"] == "ch-01-st-01"
    check("候选 02:00-03:00 命中 ch-01-st-01", ok4, f"实际: {cands[0]['story_id']}")
    ok5 = cands[1]["story_id"] == "ch-02-st-01"
    check("候选 05:00-06:00 命中 ch-02-st-01", ok5, f"实际: {cands[1]['story_id']}")

    # 4. 候选标注：未命中 → __unknown__
    cands_unknown = [{"start_time": "99:00", "end_time": "99:30"}]
    story_context.annotate_candidates(cands_unknown, groups)
    ok6 = cands_unknown[0]["story_id"] == "__unknown__"
    check("候选 99:00-99:30 标记为 __unknown__", ok6)

    # 5. build_story_groups
    groups_map = story_context.build_story_groups(cands, groups)
    ok7 = "ch-01-st-01" in groups_map and len(groups_map["ch-01-st-01"]) == 1
    check("build_story_groups 结构正确", ok7, f"ch-01-st-01 成员: {groups_map.get('ch-01-st-01')}")

    # 6. 找不到 Story 文件时静默降级
    empty_groups = story_context.load_story_groups("nonexistent.json")
    ok8 = empty_groups == {}
    check("找不到文件返回空 dict", ok8)

    # 7. 空文件也兼容
    with open(BASE_DIR / "poc" / "empty_story_test.json", "w", encoding="utf-8") as f:
        json.dump({"stories": []}, f)
    empty_groups2 = story_context.load_story_groups("poc/empty_story_test.json")
    ok9 = empty_groups2 == {}
    check("空 stories 列表返回空 dict", ok9)
    # 清理
    (BASE_DIR / "poc" / "empty_story_test.json").unlink(missing_ok=True)


# ============================================================
# B. event_cluster 聚类测试（带 story_groups）
# ============================================================

def scenario_b():
    log("\n--- B. event_cluster 聚类测试（带 story_groups）---")
    from analysis import event_cluster

    # 1. 同 Story 内的连续候选 → 更容易合并
    cands_same_story = [
        {"start_time": "05:00", "end_time": "05:10", "title": "口粮份量少", "reason": "发现"},
        {"start_time": "05:15", "end_time": "05:25", "title": "尝一口像纸盒", "reason": "吐槽"},
        {"start_time": "05:30", "end_time": "05:40", "title": "总结口粮", "reason": "评价"},
    ]
    story_groups = {"st-01": [0, 1, 2]}
    clusters_with = event_cluster.build_clusters(cands_same_story, story_groups=story_groups)
    ok1 = len(clusters_with) == 1  # 同 Story 应该合并成一簇
    check("同 Story 内连续候选合并成一簇", ok1,
          f"{len(clusters_with)} 簇，成员: {[c['members'] for c in clusters_with]}")

    # 2. 跨 Story 的候选 → 不强制合并（仍看时间距离）
    cands_cross_story = [
        {"start_time": "05:00", "end_time": "05:10", "title": "口粮份量少", "reason": "事件A"},
        {"start_time": "10:00", "end_time": "10:10", "title": "突然唱歌", "reason": "事件B"},
    ]
    story_groups_cross = {"st-01": [0], "st-02": [1]}
    clusters_cross = event_cluster.build_clusters(cands_cross_story, story_groups=story_groups_cross)
    ok2 = len(clusters_cross) == 2  # 时间距离远，应分开
    check("跨 Story 时间距离远的候选分成两簇", ok2,
          f"{len(clusters_cross)} 簇（应为 2）")

    # 3. 同 Story 内的候选，即使时间稍远也更可能合并
    cands_near = [
        {"start_time": "05:00", "end_time": "05:10", "title": "口粮份量少", "reason": "事件A"},
        {"start_time": "05:20", "end_time": "05:30", "title": "尝一口像纸盒", "reason": "事件A"},
    ]
    story_groups_near = {"st-01": [0, 1]}
    clusters_near = event_cluster.build_clusters(cands_near, story_groups=story_groups_near)
    ok3 = len(clusters_near) == 1
    check("同 Story 内时间相近候选合并", ok3,
          f"{len(clusters_near)} 簇（应为 1）")

    # 4. links 中包含 same_story 字段
    if clusters_with[0]["links"]:
        link0 = clusters_with[0]["links"][0]
        ok4 = "same_story" in link0["detail"]
        check("links 包含 same_story 字段", ok4)
    else:
        ok4 = False
        check("links 包含 same_story 字段", ok4, "无链接")

    # 5. 不提供 story_groups 时行为不变
    clusters_no_story = event_cluster.build_clusters(cands_same_story)
    ok5 = len(clusters_no_story) == 1
    check("无 story_groups 时行为与之前一致", ok5,
          f"{len(clusters_no_story)} 簇（应为 1）")


# ============================================================
# C. 集成测试：_run_event_aggregation 完整流程
# ============================================================

def scenario_c():
    log("\n--- C. 集成测试：_run_event_aggregation ---")
    from analysis import _run_event_aggregation
    from analysis.deepseek_client import CostTracker
    from analysis import chunker

    # 模拟 51 分钟的真实直播片段
    duration = 51 * 60 + 39  # 51:39
    segments = []
    for i in range(duration // 30):
        start = i * 30
        end = min(start + 30, duration)
        segments.append({"start": start, "end": end, "text": f"台词{i+1}号内容测试"})

    # 模拟候选池（来自海选）
    candidates = [
        {"start_time": "02:00", "end_time": "02:30", "title": "回应质疑", "reason": "互动", "score": 7,
         "highlight_type": "情绪型", "category": "互动", "viral_probability": "中",
         "editing_advice": "", "confidence": 0.6, "event_context": "", "event_boundary_note": ""},
        {"start_time": "05:00", "end_time": "05:10", "title": "发现份量少", "reason": "反应", "score": 6,
         "highlight_type": "事件型", "category": "试吃", "viral_probability": "中",
         "editing_advice": "", "confidence": 0.5, "event_context": "", "event_boundary_note": ""},
        {"start_time": "05:15", "end_time": "05:25", "title": "吐槽像纸盒", "reason": "评价", "score": 7,
         "highlight_type": "情绪型", "category": "试吃", "viral_probability": "中",
         "editing_advice": "", "confidence": 0.6, "event_context": "", "event_boundary_note": ""},
        {"start_time": "25:00", "end_time": "25:10", "title": "咖啡难喝", "reason": "吐槽", "score": 8,
         "highlight_type": "事件型", "category": "试吃", "viral_probability": "高",
         "editing_advice": "", "confidence": 0.7, "event_context": "", "event_boundary_note": ""},
        {"start_time": "25:15", "end_time": "25:25", "title": "硬喝两杯", "reason": "反转", "score": 7,
         "highlight_type": "事件型", "category": "试吃", "viral_probability": "中",
         "editing_advice": "", "confidence": 0.6, "event_context": "", "event_boundary_note": ""},
        {"start_time": "50:00", "end_time": "50:10", "title": "微波炉炸了", "reason": "事故", "score": 8,
         "highlight_type": "事件型", "category": "事故", "viral_probability": "高",
         "editing_advice": "", "confidence": 0.7, "event_context": "", "event_boundary_note": ""},
    ]

    # 使用真实的 Story 分组
    from analysis import story_context
    story_groups_data = story_context.load_story_groups(str(Path(__file__).parent / "poc" / "fixtures" / "story_segmentation_result.json"))
    story_context.annotate_candidates(candidates, story_groups_data)
    story_groups = story_context.build_story_groups(candidates, story_groups_data)

    # 假客户端（记录调用，不真正请求 API）
    call_log = []

    def fake_client(prompt, system=None, max_tokens=1000):
        call_log.append({"prompt": prompt[:50], "system": system, "max_tokens": max_tokens})
        # 返回假的分批复审回复
        if "复审" in prompt or "review" in prompt.lower():
            return json.dumps({
                "results": [
                    {
                        "event_id": "ev-001",
                        "dims": {"hook": 8, "contrast": 7, "persona": 9, "standalone": 6, "completeness": 7},
                        "recommended_start": "02:00", "recommended_end": "02:30",
                        "recommended_duration": 30, "duration_reason": "完整互动过程",
                        "why_cut": "互动感强", "risk": "", "confidence": 0.7,
                        "negative_flags": [], "reject_reason_kind": ""
                    }
                ],
                "warnings": []
            })
        else:
            # 事件判断回复
            return json.dumps({
                "same_event": True,
                "event_summary": "测试事件",
                "event_type": "试吃",
                "event_start": "05:00",
                "event_end": "05:30",
                "structure": {"setup": "发现", "development": "吐槽", "payoff": "评价"},
                "strongest_moment": "吐槽像纸盒",
                "reason": "同一事件",
                "confidence": 0.8,
                "need_more_context": False,
                "expand_direction": ""
            })

    tracker = CostTracker()
    result = _run_event_aggregation(fake_client, tracker, segments, candidates, duration, log)
    
    # _run_event_aggregation 返回 (events, stats) 元组
    if isinstance(result, tuple):
        events, stats = result
    else:
        events = result
        stats = {}

    ok1 = len(events) >= 1  # 至少生成一个事件
    check("事件聚合生成事件", ok1, f"生成 {len(events)} 个事件")

    ok2 = events[0].get("story_id") in story_groups_data or events[0].get("story_id") == "__unknown__"
    check("事件带有 story_id 字段", ok2, f"story_id: {events[0].get('story_id')}")

    ok3 = stats.get("clusters", 0) > 0
    check("聚类数 > 0", ok3, f"聚类等: {stats.get('clusters', 0)}")

    ok4 = stats.get("judge_calls", 0) > 0
    check("AI 调用次数 > 0", ok4, f"调用次数: {stats.get('judge_calls', 0)}")

    ok5 = all('story_id' in ev for ev in events)
    check("所有事件都有 story_id", ok5)


# ============================================================
# D. 边界情况测试
# ============================================================

def scenario_d():
    log("\n--- D. 边界情况测试 ---")
    from analysis import story_context

    # 1. 候选时间格式异常（秒级 vs 分秒级）
    cands = [
        {"start_time": "120", "end_time": "150"},  # 秒级格式
        {"start_time": "02:00", "end_time": "02:30"},  # 分秒级格式
    ]
    groups = {"st-01": {"start": 100, "end": 200}}
    story_context.annotate_candidates(cands, groups)
    ok1 = all(c.get("story_id") == "st-01" for c in cands)
    check("混合时间格式都能正确匹配 Story", ok1,
          f"结果: {[c['story_id'] for c in cands]}")

    # 2. 候选跨越多个 Story 边界
    cands_cross = [{"start_time": "03:00", "end_time": "05:00"}]
    groups_multi = {"st-01": {"start": 100, "end": 200}, "st-02": {"start": 250, "end": 400}}
    story_context.annotate_candidates(cands_cross, groups_multi)
    ok2 = cands_cross[0]["story_id"] == "st-01"  # 取第一个命中的
    check("跨越 Story 边界的候选取第一个命中的", ok2,
          f"实际: {cands_cross[0]['story_id']}")

    # 3. 候选完全在 Story 外
    cands_outside = [{"start_time": "99:00", "end_time": "99:30"}]
    story_context.annotate_candidates(cands_outside, groups_multi)
    ok3 = cands_outside[0]["story_id"] == "__unknown__"
    check("完全在 Story 外的候选标记为 __unknown__", ok3)


# ============================================================
# 主流程
# ============================================================

def main():
    log("=" * 70)
    log("V0.4 Step 4 测试：Chapter→Story 前置层接入")
    log("=" * 70)

    total = 0
    passed = 0

    tests = [scenario_a, scenario_b, scenario_c, scenario_d]
    for test in tests:
        try:
            test()
        except Exception as e:
            log(f"[ERROR] {test.__name__} 执行失败: {e}")

    for line in _report:
        if "PASS" in line:
            passed += 1
        if "PASS" in line or "FAIL" in line:
            total += 1

    log(f"\n{'='*70}")
    log(f"测试结果：{passed}/{total} PASS")
    log(f"{'='*70}")
    log("\n(通过标准：全部 PASS。有 FAIL 先修再继续，不许带病过验收。)")

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(_report))

    log(f"\nreport saved: {REPORT_FILE}")


if __name__ == "__main__":
    main()
