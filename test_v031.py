# ============================================================
# test_v031.py —— v0.3.1 离线自测（假 AI 客户端，零成本）
#
# ⚠️ 过时留档（v0.4 步骤 2 起）：
#   本测试基于 v0.3.x「候选级」架构编写。v0.4 把基本单位从「爆点候选」
#   升级为「完整事件」，复审提示词从「### 候选」改为「### 事件（ev-xxx）」，
#   导致本文件的假客户端路由（prompt.count("### 候选")）数到 0、复审返回空。
#   事件化后的回归由 test_v040_step2.py 的「F 事件级完整流程」场景承担
#   （五档定级 / 负面封顶 / 零输出禁令 / 质检保险丝均已覆盖）。
#   本文件仅作历史参考，不再作为验收标准。
#
# 验收目标（召回优先 + 分级输出）：
#   场景 A 主流程：
#     1. 海选宁多勿少：51 分钟稿候选池达到 15~30 个
#     2. 漏检质检：报可疑区块 → 重扫该区块，新候选并入，重复候选去重
#     3. 质检报了不存在的区块编号（99）→ 忽略，不崩
#     4. 复审分级 A/B/C/D：自动精选只出 A，候选池出 A+B+C
#     5. 每个候选都有 clip_id（未来 👍/👎 反馈记账用）
#     6. highlight_type 三类高光字段齐全
#     7. 成本累加器把海选+质检+重扫+复审全部合并计费
#   场景 B 零输出禁令：
#     8. 复审全灭（都打 4 分）→ 强制保留最佳 1 个为 C 级（forced_keep）
#     9. 复审全灭且都不够 4 分 → 允许零输出（真垃圾不硬塞）
#   场景 C 保险丝：
#     10. 质检回垃圾 JSON → 当作无漏检，主流程继续
#
# 运行：.\.venv\Scripts\python test_v031.py
# 结果：v031_report.txt（控制台只打英文，防 GBK 乱码）
# ============================================================

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analysis import analyze_transcript_v2
from analysis.event_scanner import COMMON_STRONG

BASE_DIR = Path(__file__).parent
TRANSCRIPT = BASE_DIR / "transcripts" / "测试视频2.txt"
REPORT_FILE = BASE_DIR / "v031_report.txt"

_report = []


def log(msg=""):
    _report.append(msg)
    # 控制台只打英文（旧教训：GBK 控制台遇到 ¥ 等字符会炸）
    safe = msg.encode("ascii", "replace").decode("ascii")
    print(safe)


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    log(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
    return ok


# ---------------- 假 AI 客户端 ----------------
# 按 prompt 里的身份关键词路由（编排器传的 system 不进 prompt，只看正文）：
#   「特别提示」 → 质检后的重扫海选
#   「质检员」   → 漏检质检
#   「终审环节」 → 复审
#   其他         → 普通海选

_TIME_RE = re.compile(r"\[([\d:]+) - ([\d:]+)\]")


def _make_candidate(start, end, score, htype):
    return {
        "start_time": start, "end_time": end,
        "title": f"测试片段{start}",
        "highlight_type": htype,
        "score": score,
        "reason": "开头情绪钩子，观众会停留",
        "category": "情绪",
        "viral_probability": "高" if score >= 8 else "中",
        "emotion_score": score, "conflict_score": max(1, score - 2),
        "editing_advice": "前3秒直接上冲突画面",
        "confidence": 0.8,
    }


class FakeClient:
    """可编程的假 AI：用字典配置每个环节怎么回话。"""

    def __init__(self, per_chunk=2, miss_checks=None, bad_miss=False,
                 review_mode="cycle", review_score=4):
        self.per_chunk = per_chunk              # 每个区块海选吐几个候选
        self.miss_checks = miss_checks or []    # 质检要报的 [(区块号, 原因)]
        self.bad_miss = bad_miss                # 质检回垃圾 JSON
        self.review_mode = review_mode          # cycle=A/B/C/D 轮流；all_low=全灭
        self.review_score = review_score        # all_low 模式给的分数
        self.calls = {"screen": 0, "rescreen": 0, "miss": 0, "review": 0}
        # 记住每个区块第一轮吐过的时间（重扫时用来造「重复候选」测去重）
        self.chunk_times = {}

    def __call__(self, prompt, system=None, max_tokens=None):
        usage = {"prompt_tokens": 1000, "completion_tokens": 200}

        # ---- 质检后的重扫 ----
        if "特别提示" in prompt:
            self.calls["rescreen"] += 1
            # 从区块编号推断这是哪个区块被重扫：正文里没有编号，
            # 但重扫一定发生在质检之后，直接用第一个未重扫过的区块时间造重复
            ts = _TIME_RE.findall(prompt)
            if not ts:
                return json.dumps({"candidates": []}), usage
            # 1 个和第一轮重复的（测去重）+ 1 个新的
            dup = _make_candidate(ts[0][0], ts[0][1], 7, "情绪型")
            new = _make_candidate(ts[-1][0], ts[-1][1], 6, "梗型")
            return json.dumps({"candidates": [dup, new]}), usage

        # ---- 漏检质检 ----
        if "质检员" in prompt:
            self.calls["miss"] += 1
            if self.bad_miss:
                return "这不是JSON{{{", usage
            checks = [
                {"chunk": idx, "miss_risk": True, "reason": reason}
                for idx, reason in self.miss_checks
            ]
            return json.dumps({"checks": checks}), usage

        # ---- 复审 ----
        if "终审环节" in prompt:
            self.calls["review"] += 1
            n = prompt.count("### 候选")
            results = []
            for i in range(n):
                if self.review_mode == "cycle":
                    grade = "ABCD"[i % 4]
                    score = {"A": 9, "B": 7, "C": 5, "D": 3}[grade]
                else:  # all_low：全部灭掉，都给 review_score 分
                    grade = "D"
                    score = self.review_score
                results.append({
                    "title": f"测试片段{i}",
                    "final_score": score,
                    "grade": grade,
                    "reject_reason": ["垃圾高光：无冲突无讨论点"] if grade == "D" else [],
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
        picks = [ts[0], ts[len(ts) // 2]][:n]   # 第 1 句 + 中间 1 句
        cands = [
            _make_candidate(s, e, 7 - (k % 2), ["事件型", "情绪型", "梗型"][k % 3])
            for k, (s, e) in enumerate(picks)
        ]
        return json.dumps({"candidates": cands}), usage


# ---------------- 场景 A：主流程（召回优先 + 质检 + 分级） ----------------

def scenario_a():
    log("=" * 60)
    log("场景 A：召回优先主流程（51 分钟稿，精细模式，假 AI）")
    log("=" * 60)

    # 质检报区块 3（真的重扫）+ 区块 99（不存在的编号，应被忽略）
    client = FakeClient(per_chunk=2, miss_checks=[(3, "存在明显情绪变化但未入池"), (99, "坏编号")])
    r = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="自动精选", client=client, verbose=False,
    )

    chunk_count = r["meta"]["chunk_count"]
    pool = r["meta"]["candidate_count"]

    # 1. 候选池规模：14 块 × 2 个 + 重扫新增 1 个（另一个是重复被去重）
    check("精细模式不降级（degrade_level=0）",
          r["meta"]["degrade_level"] == 0, f"实际 {r['meta']['degrade_level']}")
    check("候选池达到召回目标（15~30 个）",
          15 <= pool <= 30, f"实际 {pool} 个（{chunk_count} 个区块）")

    # 2. 质检：只重扫了真实存在的区块 3，编号 99 被忽略
    check("质检重扫了区块 3，忽略了不存在的区块 99",
          r["meta"]["miss_check_chunks"] == [3],
          f"实际 {r['meta']['miss_check_chunks']}")
    check("重扫确实多调了一次 AI（14 海选 + 1 质检 + 1 重扫 + 1 复审）",
          client.calls == {"screen": chunk_count, "rescreen": 1,
                           "miss": 1, "review": 1},
          f"实际 {client.calls}")

    # 3. 去重：重扫回来的重复候选没把池子撑大
    #    14×2=28，重扫 2 个候选里 1 个重复 → 28 + 1 = 29
    check("重扫的重复候选被去重",
          pool == chunk_count * 2 + 1, f"预期 {chunk_count * 2 + 1}，实际 {pool}")

    # 4. 分级输出：自动精选只出 A 级
    grades_auto = [h["grade"] for h in r["highlights"]]
    n_a = sum(1 for i in range(pool) if i % 4 == 0)   # 假 AI 按 ABCD 轮流给级
    check("自动精选只展示 A 级",
          len(grades_auto) == n_a and all(g == "A" for g in grades_auto),
          f"实际 {len(grades_auto)} 个，全部 {set(grades_auto)}")

    # 5. 候选池模式：A+B+C 全出
    r_pool = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=FakeClient(
            per_chunk=2, miss_checks=[(3, "情绪变化"), (99, "坏编号")]),
        verbose=False,
    )
    grades_pool = [h["grade"] for h in r_pool["highlights"]]
    check("候选池模式展示 A+B+C（含备用素材）",
          set(grades_pool) == {"A", "B", "C"} and len(grades_pool) >= 15,
          f"实际 {len(grades_pool)} 个：{sorted(set(grades_pool))}")

    # 6. clip_id：人人有身份证，且不重复
    ids = [h["clip_id"] for h in r_pool["highlights"]] + \
          [x["clip_id"] for x in r_pool["rejected"]]
    check("所有候选都有唯一 clip_id",
          len(ids) == len(set(ids)) == pool and ids[0] == "clip-001",
          f"共 {len(ids)} 个，首个 {ids[0]}")

    # 7. highlight_type 三类字段齐全
    types = {h["highlight_type"] for h in r_pool["highlights"]}
    check("三类高光类型字段齐全",
          types == {"事件型", "情绪型", "梗型"}, f"实际 {sorted(types)}")

    # 8. 成本累加：所有环节合并计费
    total_calls = sum(client.calls.values())
    check("成本累加器合并计费（海选+质检+重扫+复审）",
          r["cost"]["calls"] == total_calls,
          f"tracker {r['cost']['calls']} 次 = 客户端 {total_calls} 次")

    # 9. 被拒候选带 AI 的具体理由
    d_reasons = [x for x in r_pool["rejected"] if x["grade"] == "D"]
    check("D 级淘汰候选保留 AI 的 reject_reason",
          all(x.get("reject_reason") for x in d_reasons),
          f"{len(d_reasons)} 个 D 级候选")

    return r


# ---------------- 场景 B：零输出禁令 ----------------

def scenario_b():
    log()
    log("=" * 60)
    log("场景 B：零输出禁令（复审全灭时强制捞回最佳候选）")
    log("=" * 60)

    # B1：全打 4 分 → 最佳候选够底线（4），强制保留为 C
    client = FakeClient(per_chunk=1, review_mode="all_low", review_score=4)
    r = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=client, verbose=False,
    )
    check("复审全灭（都 4 分）→ 强制保留 1 个 C 级",
          len(r["highlights"]) == 1 and r["highlights"][0]["grade"] == "C"
          and r["highlights"][0].get("forced_keep") is True,
          f"实际 {len(r['highlights'])} 个，"
          f"forced_keep={r['highlights'][0].get('forced_keep') if r['highlights'] else None}")

    # B2：全打 3 分 → 连底线（4）都不够，允许零输出（真垃圾不硬塞）
    client = FakeClient(per_chunk=1, review_mode="all_low", review_score=3)
    r = analyze_transcript_v2(
        TRANSCRIPT, live_type="娱乐聊天", token_mode="精细",
        quantity_mode="候选池", client=client, verbose=False,
    )
    check("全灭且最高分 < 4 → 允许零输出（不硬塞垃圾）",
          len(r["highlights"]) == 0 and len(r["rejected"]) >= 1,
          f"高光 {len(r['highlights'])} 个，被拒 {len(r['rejected'])} 个")


# ---------------- 场景 C：质检保险丝 ----------------

def scenario_c():
    log()
    log("=" * 60)
    log("场景 C：质检回垃圾 JSON，主流程不能崩")
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
    log("v0.3.1 离线自测报告（假 AI 客户端，零 API 成本）")
    log(f"文字稿：{TRANSCRIPT.name}")
    log()

    scenario_a()
    scenario_b()
    scenario_c()

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
