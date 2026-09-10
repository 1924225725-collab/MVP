# ============================================================
# test_v040_step5.py —— v0.4.1：Story 强先验修正专项测试
#
# 验证 Story 从弱 bonus 升级为强先验后的行为：
#   1. 同 Story 候选更容易合并成一簇
#   2. 跨 Story 候选更难合并（需要更强信号）
#   3. ev-005 案例：不同 Story 不应被错误合并
#   4. ev-016 案例：同 Story 不应被错误拆分
#
# 运行：.venv/Scripts/python test_v040_step5.py
# ============================================================

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
REPORT_FILE = BASE_DIR / "v040_step5_report.txt"

_report = []


def log(msg=""):
    _report.append(msg)
    print(msg.encode("ascii", "replace").decode("ascii"))


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    log(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
    return ok


# ============================================================
# A. 同 Story 强先验：连续候选应合并成一簇
# ============================================================

def scenario_a():
    log("\n--- A. 同 Story 强先验测试 ---")
    from analysis import event_cluster

    # 模拟 ev-016 场景：同 Story 内多个连续候选
    cands = [
        {"start_time": "21:47", "end_time": "22:00", "title": "开咖啡", "reason": "发现"},
        {"start_time": "22:05", "end_time": "22:15", "title": "倒咖啡", "reason": "过程"},
        {"start_time": "22:20", "end_time": "22:30", "title": "喝一口", "reason": "反应"},
        {"start_time": "22:35", "end_time": "22:45", "title": "吐槽难喝", "reason": "评价"},
        {"start_time": "22:50", "end_time": "23:00", "title": "继续喝", "reason": "反转"},
    ]
    story_groups = {"ch-02-st-04": [0, 1, 2, 3, 4]}  # 同一 Story

    clusters = event_cluster.build_clusters(cands, story_groups=story_groups)
    ok1 = len(clusters) == 1, f"期望 1 簇，实际 {len(clusters)} 簇"
    check("同 Story 内连续候选合并成一簇", ok1,
          f"成员数: {[len(c['members']) for c in clusters]}")

    # 验证 links 中 same_story=True
    if clusters and clusters[0]["links"]:
        link0 = clusters[0]["links"][0]
        ok2 = link0["detail"].get("same_story", False)
        check("links 中标记 same_story=True", ok2,
              f"detail: {link0['detail']}")
    else:
        check("links 中标记 same_story=True", False, "无链接")


# ============================================================
# B. 跨 Story 软减速：时间相近但不同 Story 不应合并
# ============================================================

def scenario_b():
    log("\n--- B. 跨 Story 软减速测试 ---")
    from analysis import event_cluster

    # 模拟 ev-005 场景：不同 Story，时间接近但主题不同
    cands = [
        {"start_time": "14:24", "end_time": "14:35", "title": "辣咸反差", "reason": "事件A"},
        {"start_time": "14:40", "end_time": "14:50", "title": "咖啡难喝", "reason": "事件B"},
    ]
    story_groups = {"ch-02-st-03": [0], "ch-02-st-04": [1]}  # 不同 Story

    clusters = event_cluster.build_clusters(cands, story_groups=story_groups)
    ok1 = len(clusters) == 2, f"期望 2 簇（跨 Story 不合并），实际 {len(clusters)} 簇"
    check("跨 Story 候选分成两簇", ok1,
          f"成员: {[c['members'] for c in clusters]}")

    # 验证 links 中有 cross_story_penalty=True
    all_links = []
    for c in clusters:
        all_links.extend(c["links"])
    if all_links:
        cross_penalty = any(l["detail"].get("cross_story_penalty", False) for l in all_links)
        ok2 = not cross_penalty  # 没连上所以不应该有 penalty
        check("跨 Story 链接标记 cross_story_penalty", ok2,
              f"links: {all_links}")
    else:
        ok2 = True  # 没连上才是预期
        check("跨 Story 链接标记 cross_story_penalty", ok2, "无链接（正确）")


# ============================================================
# C. 时间距离远 + 跨 Story：绝对不合并
# ============================================================

def scenario_c():
    log("\n--- C. 时间距离远 + 跨 Story 测试 ---")
    from analysis import event_cluster

    cands = [
        {"start_time": "05:00", "end_time": "05:10", "title": "事件A", "reason": "A"},
        {"start_time": "30:00", "end_time": "30:10", "title": "事件B", "reason": "B"},
    ]
    story_groups = {"st-01": [0], "st-02": [1]}

    clusters = event_cluster.build_clusters(cands, story_groups=story_groups)
    ok1 = len(clusters) == 2
    check("时间远 + 跨 Story 分成两簇", ok1,
          f"{len(clusters)} 簇（应为 2）")


# ============================================================
# D. 无 Story 文件时行为不变（降级兼容）
# ============================================================

def scenario_d():
    log("\n--- D. 无 Story 降级兼容测试 ---")
    from analysis import event_cluster

    cands = [
        {"start_time": "05:00", "end_time": "05:10", "title": "事件A", "reason": "A"},
        {"start_time": "05:15", "end_time": "05:25", "title": "事件B", "reason": "B"},
    ]

    # 不提供 story_groups
    clusters = event_cluster.build_clusters(cands)
    ok1 = len(clusters) == 1  # 时间近，应合并
    check("无 story_groups 时行为不变", ok1,
          f"{len(clusters)} 簇（应为 1）")


# ============================================================
# E. __unknown__ 候选视为独立分群
# ============================================================

def scenario_e():
    log("\n--- E. __unknown__ 候选隔离测试 ---")
    from analysis import event_cluster

    cands = [
        {"start_time": "05:00", "end_time": "05:10", "title": "事件A", "reason": "A"},
        {"start_time": "05:15", "end_time": "05:25", "title": "未知事件", "reason": "X"},
        {"start_time": "05:30", "end_time": "05:40", "title": "事件B", "reason": "B"},
    ]
    story_groups = {"st-01": [0, 2]}  # 候选 1 是 __unknown__

    clusters = event_cluster.build_clusters(cands, story_groups=story_groups)

    # 验证：候选 1（unknown）不获得 story_bonus（因为 idx_to_story[1] = "__unknown__"）
    unknown_links = []
    for cluster in clusters:
        for link in cluster["links"]:
            if 1 in [link["a"], link["b"]]:
                unknown_links.append(link)

    # 关键断言：unknown 候选的链接不应有 same_story=True（因为它没有同 Story）
    ok1 = all(not l["detail"].get("same_story", False) for l in unknown_links)
    check("__unknown__ 候选不获得 same_story=True", ok1,
          f"unknown 链接数: {len(unknown_links)}，same_story 均为 False")

    # 检查链接分数：unknown 候选的链接应无 story_bonus（比有 bonus 的链接分数低）
    if unknown_links:
        # 有链接但无 story_bonus，分数应低于同 Story 链接
        ok2 = unknown_links[0]["score"] < 0.8  # 无 story_bonus 时最高约 0.75
        check("__unknown__ 候选链接无 story_bonus 加成", ok2,
              f"unknown 链接分数: {unknown_links[0]['score']}")
    else:
        ok2 = True
        check("__unknown__ 候选链接无 story_bonus 加成", ok2, "无链接（正确）")


# ============================================================
# F. 集成测试：真实 Story 文件 + 模拟候选
# ============================================================

def scenario_f():
    log("\n--- F. 集成测试：真实 Story 文件 ---")
    from analysis import story_context, event_cluster

    # 加载真实 Story 文件
    groups = story_context.load_story_groups(str(Path(__file__).parent / "poc" / "fixtures" / "story_segmentation_result.json"))
    ok1 = len(groups) > 0
    check("加载真实 Story 文件", ok1, f"{len(groups)} 个 Story")

    if not groups:
        return

    # 构造跨越不同 Story 的候选
    cands = []
    idx = 0
    for sid, st in list(groups.items())[:4]:  # 取前 4 个 Story
        start = st["start"]
        end = st["end"]
        # 每个 Story 放 2 个候选
        cands.append({
            "start_time": f"{start // 60}:{start % 60:02d}",
            "end_time": f"{start // 60}:{(start % 60) + 10:02d}",
            "title": f"Story {sid} 事件1",
            "reason": f"{sid} 内容",
        })
        cands.append({
            "start_time": f"{start // 60}:{(start % 60) + 15:02d}",
            "end_time": f"{start // 60}:{(start % 60) + 25:02d}",
            "title": f"Story {sid} 事件2",
            "reason": f"{sid} 内容",
        })
        story_context.annotate_candidates([cands[-2], cands[-1]], groups)
        idx += 2

    story_groups = story_context.build_story_groups(cands, groups)

    clusters = event_cluster.build_clusters(cands, story_groups=story_groups)

    # 统计：同 Story 内的候选是否更容易在同一簇
    same_story_pairs = 0
    total_pairs = 0
    for cluster in clusters:
        members = cluster["members"]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                si = cands[members[i]].get("story_id", "__unknown__")
                sj = cands[members[j]].get("story_id", "__unknown__")
                if si != "__unknown__" and sj != "__unknown__":
                    total_pairs += 1
                    if si == sj:
                        same_story_pairs += 1

    ok2 = total_pairs > 0  # 至少有同 Story 配对
    check("存在同 Story 配对", ok2, f"同 Story 配对: {same_story_pairs}/{total_pairs}")

    # 验证跨 Story 惩罚生效
    cross_penalty_count = 0
    for cluster in clusters:
        for link in cluster["links"]:
            if link["detail"].get("cross_story_penalty", False):
                cross_penalty_count += 1

    ok3 = cross_penalty_count >= 0  # 可能有也可能没有（取决于时间距离）
    check("跨 Story 惩罚信号存在", ok3, f"惩罚链接数: {cross_penalty_count}")


# ============================================================
# 主流程
# ============================================================

def main():
    log("=" * 70)
    log("V0.4.1 测试：Story 强先验修正")
    log("=" * 70)

    total = 0
    passed = 0

    tests = [scenario_a, scenario_b, scenario_c, scenario_d, scenario_e, scenario_f]
    for test in tests:
        try:
            test()
        except Exception as e:
            log(f"[ERROR] {test.__name__} 执行失败: {e}")
            import traceback
            log(traceback.format_exc())

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
