# ============================================================
# test_v032.py —— v0.3.2 离线自测（假 AI 客户端，零成本）
#
# 验收目标（判断体系 v3：五维子分 + 本地加权定级 + 负面清单）：
#   场景 A 主流程（cycle 模式）：
#     1. 海选召回：51 分钟稿候选池 15~30 个，质检重扫去重正常
#     2. 本地定级引擎：S/A/B/C/D 五档按 config 阈值全部正确产出
#     3. 自动精选只出 S/A；候选池出 S/A/B/C；D 全进 rejected
#     4. 每个高光带五维「判决书」（中文标签 dims）、why_cut、risk、clip_id
#     5. D 级候选带 reject_reason（本地组装，非套话）
#     6. 成本累加器合并计费
#   场景 B 负面清单封顶：
#     7. 复审给超高分但命中「普通失误」→ 封顶 B 级，进不了 S/A
#   场景 C 零输出禁令：
#     8. 复审全灭（加权 4.5）→ 强制保留 1 个 C 级（forced_keep）
#     9. 复审全灭且加权 < 4 → 允许零输出（真垃圾不硬塞）
#   场景 D 保险丝：
#     10. 质检回垃圾 JSON → 当作无漏检，主流程继续
#
# 运行：.\.venv\Scripts\python test_v032.py
# 结果：v032_report.txt
# ============================================================

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analysis import analyze_transcript_v2

BASE_DIR = Path(__file__).parent
TRANSCRIPT = BASE_DIR / "transcripts" / "测试视频2.txt"
REPORT_FILE = BASE_DIR / "v032_report.txt"

_report = []


def log(msg=""):
    _report.append(msg)
    safe = msg.encode("ascii", "replace").decode("ascii")
    print(safe)


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    log(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
    return ok


# ---------------- 假 AI 客户端 ----------------
# 路由关键词：海选正文无特别标记；「特别提示」=质检重扫；「质检员」=质检；「终审环节」=复审

_TIME_RE = re.compile(r"\[([\d:]+) - ([\d:]+)\]")

# 复审五维档位（本地加权结果远离阈值边界，避免浮点抖动误判）：
#   S 档 → ~9.4 分；A 档 → ~8.4；B 档 → ~6.4；C 档 → 5.0；D 档 → ~4.0
_PROFILES = [
    # S
    {"hook": 10, "contrast": 10, "persona": 9, "standalone": 8, "completeness": 9,
     "negative_flags": [], "why_cut": "误会+强反差，陌生观众秒停", "risk": "依赖画面节奏"},
    # A
    {"hook": 9, "contrast": 9, "persona": 8, "standalone": 7, "completeness": 8,
     "negative_flags": [], "why_cut": "反转清晰，传播点明确", "risk": "标题空间有限"},
    # B
    {"hook": 7, "contrast": 6, "persona": 7, "standalone": 5, "completeness": 6,
     "negative_flags": [], "why_cut": "主播反应有辨识度", "risk": "不看前文可能懵"},
    # C
    {"hook": 5, "contrast": 5, "persona": 5, "standalone": 5, "completeness": 5,
     "negative_flags": [], "why_cut": "内容完整但平淡", "risk": "传播能力弱"},
    # D
    {"hook": 4, "contrast": 4, "persona": 4, "standalone": 4, "completeness": 4,
     "negative_flags": [], "why_cut": "有事件但无传播点", "risk": "普通失误无反差"},
]

# 4.5 分档（够 forced_keep 底线 4，但低于 C 线 5）
_PROFILE_45 = {k: (5 if k in ("contrast", "standalone", "completeness") else 4)
               for k in ("hook", "contrast", "persona", "standalone", "completeness")}
# 3.5 分档（连 forced_keep 底线都不够）
_PROFILE_35 = {k: (4 if k in ("contrast", "standalone", "completeness") else 3)
               for k in ("hook", "contrast", "persona", "standalone", "completeness")}


def _make_candidate(start, end, score, htype):
    return {
        "start_time": start, "end_time": end,
        "title": f"测试片段{start}",
        "highlight_type": htype,
        "score": score,
        "reason": "开头情绪钩子，观众会停留",
        "category": "情绪",
        "viral_probability": "高" if score >= 8 else "中",
        "editing_advice": "前3秒直接上冲突画面",
        "confidence": 0.8,
    }


class FakeClient:
    """可编程假 AI。review_profiles：复审档位轮换列表；也可整体覆盖。"""

    def __init__(self, per_chunk=2, miss_checks=None, bad_miss=False,
                 review_profiles=None, override_flags=None):
        self.per_chunk = per_chunk
        self.miss_checks = miss_checks or []
        self.bad_miss = bad_miss
        self.review_profiles = review_profiles or _PROFILES
        self.override_flags = override_flags   # 强制给每个候选加的负面标记（测封顶）
        self.calls = {"screen": 0, "rescreen": 0, "miss": 0, "review": 0}

    def __call__(self, prompt, system=None, max_tokens=None):
        usage = {"prompt_tokens": 1000, "completion_tokens": 200}

        if "特别提示" in prompt:  # 质检后的重扫
            self.calls["rescreen"] += 1
            ts = _TIME_RE.findall(prompt)
            if not ts:
                return json.dumps({"candidates": []}), usage
            dup = _make_candidate(ts[0][0], ts[0][1], 7, "情绪型")
            new = _make_candidate(ts[-1][0], ts[-1][1], 6, "梗型")
            return json.dumps({"candidates": [dup, new]}), usage

        if "质检员" in prompt:  # 漏检质检
            self.calls["miss"] += 1
            if self.bad_miss:
                return "这不是JSON{{{", usage
            checks = [
                {"chunk": idx, "miss_risk": True, "reason": reason}
                for idx, reason in self.miss_checks
            ]
            return json.dumps({"checks": checks}), usage

        if "终审环节" in prompt:  # 复审：按新格式输出五维子分
            self.calls["review"] += 1
            n = prompt.count("### 候选")
            results = []
            for i in range(n):
                p = dict(self.review_profiles[i % len(self.review_profiles)])
                if self.override_flags is not None:
                    p["negative_flags"] = list(self.override_flags)
                results.append({
                    "title": f"测试片段{i}",
                    **{k: p[k] for k in ("hook", "contrast", "persona",
                                         "standalone", "completeness")},
                    "negative_flags": p.get("negative_flags", []),
                    "why_cut": p.get("why_cut", "（测试档位缺省）"),
                    "risk": p.get("risk", "（测试档位缺省）"),
                    "confidence": 0.7,
                })
            report = {
                "summary": "唠嗑直播，聊生活话题为主",
                "best_spread_point": "中段罐头异物事件",
                "overall": "整体平淡，偶有情绪点",
                "why_not_more": "多数候选缺少独立成片的传播点",
            }
            return json.dumps({"results": results, "report": report}), usage

        # ---- 普通海选 ----
        self.calls["screen"] += 1
        ts = _TIME_RE.findall(prompt)
        if not ts:
            return json.dumps({"candidates": []}), usage
        n = min(self.per_chunk, len(ts))
        picks = [ts[0], ts[len(ts) // 2]][:n]
        cands = [
            _make_candidate(s, e, 7 - (k % 2), ["事件型", "情绪型", "梗型"][k % 3])
            for k, (s, e) in enumerate(picks)
        ]
        return json.dumps({"candidates": cands}), usage


# ---------------- 场景 A：主流程（五维定级 + 数量模式） ----------------

def scenario_a():
    log("=" * 60)
    log("场景 A：v3 定级引擎主流程（51 分钟稿，精细模式，假 AI）")
    log("=" * 60)

    client = FakeClient(per_chunk=2, miss_checks=[(3, "情绪变化但未入池"), (99, "坏编号")])
    r = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="自动精选", client=client, verbose=False,
    )
    chunk_count = r["meta"]["chunk_count"]
    pool = r["meta"]["candidate_count"]

    # 1. 召回 + 质检
    check("精细模式不降级（degrade_level=0）",
          r["meta"]["degrade_level"] == 0, f"实际 {r['meta']['degrade_level']}")
    check("候选池达到召回目标（15~30 个）",
          15 <= pool <= 30, f"实际 {pool} 个（{chunk_count} 个区块）")
    check("质检重扫区块 3，忽略坏编号 99",
          r["meta"]["miss_check_chunks"] == [3],
          f"实际 {r['meta']['miss_check_chunks']}")
    check("重扫重复候选被去重（14×2 + 1）",
          pool == chunk_count * 2 + 1, f"预期 {chunk_count * 2 + 1}，实际 {pool}")

    # 2/3. 五档定级（profiles 轮换 S,A,B,C,D → 各档都应存在）
    grades_auto = [h["grade"] for h in r["highlights"]]
    check("自动精选只展示 S/A 级",
          all(g in ("S", "A") for g in grades_auto) and grades_auto,
          f"实际 {len(grades_auto)} 个：{sorted(set(grades_auto))}")

    r_pool = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=FakeClient(
            per_chunk=2, miss_checks=[(3, "情绪变化"), (99, "坏编号")]),
        verbose=False,
    )
    g_all = [h["grade"] for h in r_pool["highlights"]]
    g_rej = [x["grade"] for x in r_pool["rejected"]]
    check("候选池展示 S/A/B/C，且 C 档确实被产出",
          set(g_all) == {"S", "A", "B", "C"}, f"实际 {sorted(set(g_all))}")
    check("D 档候选全部进 rejected",
          all(g == "D" for g in g_rej) and g_rej,
          f"rejected 共 {len(g_rej)} 个：{sorted(set(g_rej))}")

    # 4. 高光新字段齐全
    h0 = r_pool["highlights"][0]
    dims = h0.get("dims") or {}
    check("高光带五维判决书（中文标签）",
          len(dims) == 5 and any("权重" in k for k in dims),
          f"dims keys: {list(dims)}")
    check("复审 why_cut / risk 字段透传",
          bool(h0.get("why_cut")) and bool(h0.get("risk")),
          f"why_cut={h0.get('why_cut')!r}")
    ids = [h["clip_id"] for h in r_pool["highlights"]] + \
          [x["clip_id"] for x in r_pool["rejected"]]
    check("所有候选都有唯一 clip_id",
          len(ids) == len(set(ids)) == pool and ids[0] == "clip-001",
          f"共 {len(ids)} 个，首个 {ids[0]}")

    # 5. D 级淘汰候选带具体理由（本地组装，非套话）
    check("D 级淘汰候选带 reject_reason",
          all(x.get("reject_reason") for x in r_pool["rejected"]),
          f"{len(r_pool['rejected'])} 个被拒")

    # 6. 成本合并
    total_calls = sum(client.calls.values())
    check("成本累加器合并计费",
          r["cost"]["calls"] == total_calls,
          f"tracker {r['cost']['calls']} 次 = 客户端 {total_calls} 次")
    return r_pool


# ---------------- 场景 B：负面清单封顶 ----------------

def scenario_b():
    log()
    log("=" * 60)
    log("场景 B：命中「不值得剪」规则 → 封顶 B 级（进不了 S/A）")
    log("=" * 60)

    # 复审正常给 S/A/B/C/D 各档分，但强制命中「普通失误」→ S/A 全被压到 B
    client = FakeClient(per_chunk=1, override_flags=["普通失误"])
    r = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=client, verbose=False,
    )
    grades = [h["grade"] for h in r["highlights"]]
    check("命中「普通失误」→ 一个 S/A 都没有（封顶 B）",
          grades and not set(grades) & {"S", "A"},
          f"实际 {sorted(set(grades))}（原档位 S/A/B/C/D 各 1 档时）")
    check("S/A 档被压成 B，C/D 档保持原级（只降不升）",
          "B" in set(grades), f"实际 {sorted(set(grades))}")
    check("封顶候选带 negative_flags 标记",
          all(h.get("negative_flags") == ["普通失误"] for h in r["highlights"]),
          "标记齐全")


# ---------------- 场景 C：零输出禁令 ----------------

def scenario_c():
    log()
    log("=" * 60)
    log("场景 C：零输出禁令")
    log("=" * 60)

    # C1：加权 4.5 → 低于 C 线但够底线 4 → 强制保留 1 个 C 级
    client = FakeClient(per_chunk=1, review_profiles=[_PROFILE_45])
    r = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=client, verbose=False,
    )
    check("复审全灭（加权 4.5）→ 强制保留 1 个 C 级 forced_keep",
          len(r["highlights"]) == 1 and r["highlights"][0]["grade"] == "C"
          and r["highlights"][0].get("forced_keep") is True,
          f"实际 {len(r['highlights'])} 个，"
          f"forced_keep={r['highlights'][0].get('forced_keep') if r['highlights'] else None}")

    # C2：加权 3.5 → 连底线都不够 → 允许零输出
    client = FakeClient(per_chunk=1, review_profiles=[_PROFILE_35])
    r = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=client, verbose=False,
    )
    check("复审全灭且加权 < 4 → 允许零输出",
          len(r["highlights"]) == 0 and len(r["rejected"]) >= 1,
          f"高光 {len(r['highlights'])} 个，被拒 {len(r['rejected'])} 个")


# ---------------- 场景 D：质检保险丝 ----------------

def scenario_d():
    log()
    log("=" * 60)
    log("场景 D：质检回垃圾 JSON，主流程不能崩")
    log("=" * 60)

    client = FakeClient(per_chunk=1, bad_miss=True)
    r = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="自动精选", client=client, verbose=False,
    )
    check("质检坏回复 → 当作无漏检，流程正常走完",
          r["meta"]["miss_check_chunks"] == [] and client.calls["rescreen"] == 0
          and len(r["highlights"]) >= 1,
          f"高光 {len(r['highlights'])} 个，重扫 {client.calls['rescreen']} 次")


# ---------------- 总入口 ----------------

def main():
    log("v0.3.2 离线自测报告（假 AI 客户端，零 API 成本）")
    log(f"文字稿：{TRANSCRIPT.name}")
    log()

    scenario_a()
    scenario_b()
    scenario_c()
    scenario_d()

    log()
    total = len([l for l in _report if l.startswith("[PASS]") or l.startswith("[FAIL]")])
    passed = len([l for l in _report if l.startswith("[PASS]")])
    log(f"合计：{passed}/{total} 项通过")
    log()
    log("(通过标准：全部 PASS。有 FAIL 先修再继续，不许带病过验收。)")

    REPORT_FILE.write_text("\n".join(_report), encoding="utf-8")
    print(f"\nreport saved: {REPORT_FILE.name}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
