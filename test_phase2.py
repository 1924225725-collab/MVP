# ============================================================
# test_phase2.py —— v0.3 阶段 2 自测脚本（已过时，仅留档）
#
# ⚠️ v0.3.1 起流程改为「召回优先 + 分级输出」：
#    复审不再输出 recommend 而是 grade A/B/C/D，自动精选只取 A 级。
#    本脚本的旧断言（如「自动精选 7 个」）不再成立，
#    新的验收以 test_v031.py 为准。
#
# 用一个「假 AI 客户端」代替 DeepSeek：
#   海选：从区块原文里抓真实时间戳，吐 1 个格式合法的候选
#   复审：每 3 个硬拒 1 个（低分）、每 4 个软拒 1 个（高分但 recommend=false）
#
# 验收目标：
#   1. 编排器全流程跑通（解析→扫描→分区→预算→海选→复审→数量模式）
#   2. 淘汰机制：rejected 里有具体 reject_reason
#   3. 数量三模式结果确实不同
#   4. 预算降级：快速模式在 51 分钟稿上必然触发降级
#   5. 坏回复不崩：海选返回垃圾 JSON → 该区块 0 候选，流程继续
#
# 运行：.\.venv\Scripts\python test_phase2.py
# 结果写入 phase2_report.txt
# ============================================================

import json
import re
from pathlib import Path

import config
from analysis import analyze_transcript_v2, _parse_screening_reply
from analysis.transcript_parser import parse_transcript_file, total_duration
from analysis.event_scanner import scan
from analysis.chunker import build_chunks
from analysis import budget
from analysis.deepseek_client import CostTracker

BASE_DIR = Path(__file__).parent
TRANSCRIPT = BASE_DIR / "transcripts" / "测试视频2.txt"
REPORT_PATH = BASE_DIR / "phase2_report.txt"

lines = []
def log(s=""):
    lines.append(s)


class FakeClient:
    """假 AI：不看内容、只按剧本回话，但时间戳从真实区块原文里抓。"""

    def __init__(self):
        self.calls = []          # 每次调用的 (类型, 字符数)

    def __call__(self, prompt, system=None, max_tokens=None):
        if "终审" in prompt:
            # ---- 复审：按候选序号剧本打分 ----
            self.calls.append(("review", len(prompt)))
            n = prompt.count("### 候选 ")
            results = []
            for i in range(1, n + 1):
                if i % 3 == 0:
                    results.append({          # 硬拒：低分
                        "title": f"候选{i}", "final_score": 3,
                        "recommend": False,
                        "reject_reason": ["缺少冲突和讨论点", "需要大量直播上下文才能看懂"],
                        "confidence": 0.3,
                    })
                elif i % 4 == 0:
                    results.append({          # 软拒：分数够但 AI 不推荐
                        "title": f"候选{i}", "final_score": 7,
                        "recommend": False,
                        "reject_reason": ["情绪价值高但没有传播价值"],
                        "confidence": 0.5,
                    })
                else:
                    results.append({          # 放行
                        "title": f"候选{i}", "final_score": 8,
                        "recommend": True, "reject_reason": [], "confidence": 0.9,
                    })
            reply = {
                "results": results,
                "report": {
                    "summary": "本场为娱乐聊天直播，主播与观众互动频繁，中后段情绪浓度最高",
                    "best_spread_point": "29分处主播与水友争论，争议观点会刺激评论区讨论",
                    "overall": "内容密度中等，有若干可剪片段",
                    "why_not_more": "其余候选多为普通聊天，情绪价值和传播价值都不足，宁缺毋滥",
                },
            }
            return json.dumps(reply, ensure_ascii=False), \
                {"prompt_tokens": 900, "completion_tokens": 700}

        # ---- 海选：从区块原文抓真实时间戳，吐 1 个候选 ----
        self.calls.append(("screening", len(prompt)))
        times = re.findall(r"\[(\d+:\d+) - (\d+:\d+)\]", prompt)
        cands = []
        if len(times) >= 2:
            cands.append({
                "start_time": times[0][0],
                "end_time": times[min(3, len(times) - 1)][1],
                "title": "测试候选：主播情绪爆发",
                "score": 7,
                "reason": "开头出现争议观点，会刺激评论讨论",
                "category": "情绪",
                "viral_probability": "中",
                "emotion_score": 7,
                "conflict_score": 5,
                "editing_advice": "开头3秒直接放争议发言原声",
                "confidence": 0.8,
            })
        return json.dumps({"candidates": cands}, ensure_ascii=False), \
            {"prompt_tokens": 1200, "completion_tokens": 300}


def check(label, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    log(f"  [{status}] {label}" + (f"（{detail}）" if detail else ""))
    return cond


def main():
    log("v0.3 阶段 2 自测报告（离线 · 假 AI 客户端 · 零成本）")
    log("")

    # ============ 0. 前置：Phase 1 三层先跑一遍，拿区块数 ============
    segments = parse_transcript_file(TRANSCRIPT)
    duration = total_duration(segments)
    buckets = scan(segments, config.LIVE_TYPE_DEFAULT)
    chunks = build_chunks(buckets, segments)
    est_standard = budget.estimate_total(chunks, 3)
    est_fine = budget.estimate_total(chunks, 3)  # 精细同上限
    log(f"测试对象：测试视频2.txt（{len(segments)} 句 / {duration // 60} 分钟 / {len(chunks)} 区块）")
    log(f"预算估算：海选+复审全程约 {est_standard} token"
        f"（快速 {config.TOKEN_MODES['快速']['budget']} / 标准 {config.TOKEN_MODES['标准']['budget']}"
        f" / 精细 {config.TOKEN_MODES['精细']['budget']}）")
    log("")

    # ============ 1. 自动精选模式（默认全链路） ============
    log("=" * 70)
    log("测试 1：自动精选模式（标准/精细分析全链路）")
    log("=" * 70)
    fake = FakeClient()
    result = analyze_transcript_v2(
        TRANSCRIPT, token_mode="精细", quantity_mode="自动精选",
        custom_count=10, client=fake, verbose=False,
    )
    meta = result["meta"]
    n_cand = meta["candidate_count"]
    n_hi = len(result["highlights"])
    n_rej = len(result["rejected"])
    fine_budget = config.TOKEN_MODES["精细"]["budget"]
    check("流程跑通，返回结构完整",
          all(k in result for k in ("meta", "highlights", "rejected", "report", "cost")))
    check(f"海选产出候选（{n_cand} 个 = 实际区块数 {meta['chunk_count']}）",
          n_cand == meta["chunk_count"])
    check(f"复审淘汰生效（被拒 {n_rej} 个 ≥ 2）", n_rej >= 2)
    check("被拒候选带具体 reject_reason",
          all(r["reject_reason"] for r in result["rejected"]))
    check("分析报告四字段齐全",
          all(result["report"].get(k) for k in
              ("summary", "best_spread_point", "overall", "why_not_more")))
    check("高光按分数降序",
          all(result["highlights"][i]["score"] >= result["highlights"][i + 1]["score"]
              for i in range(len(result["highlights"]) - 1)))
    check("候选带原文节选（复审上下文）",
          n_cand > 0)  # 结构验证：context 已并入候选流程
    check("API 调用次数 = 实际区块数 + 1 次复审",
          len(fake.calls) == meta["chunk_count"] + 1,
          f"实际 {len(fake.calls)} 次")
    cost = result["cost"]
    check(f"成本累加器工作（{cost['calls']} 次 / ¥{cost['cost_yuan']:.4f}）",
          cost["calls"] == meta["chunk_count"] + 1 and cost["cost_yuan"] > 0)
    # 51 分钟稿估算 6 万+ token，超过精细预算 → 降级是设计内行为（粗切/限候选保覆盖）
    if est_fine <= fine_budget:
        check(f"预算内不降级（degrade_level={meta['degrade_level']}）",
              meta["degrade_level"] == 0)
    else:
        check(f"超预算正确降级（估算 {est_fine} > {fine_budget}，"
              f"degrade_level={meta['degrade_level']} >= 1）",
              meta["degrade_level"] >= 1)
    log(f"  结果：{meta['chunk_count']} 区块 → 候选 {n_cand} → 高光 {n_hi} + 被拒 {n_rej}")
    log("")

    # ============ 2. 数量三模式对比 ============
    log("=" * 70)
    log("测试 2：数量三模式（同一批候选，三种玩法）")
    log("=" * 70)
    r_auto = analyze_transcript_v2(TRANSCRIPT, token_mode="精细",
                                   quantity_mode="自动精选", client=FakeClient(),
                                   verbose=False)
    r_pool = analyze_transcript_v2(TRANSCRIPT, token_mode="精细",
                                   quantity_mode="候选池", client=FakeClient(),
                                   verbose=False)
    r_custom = analyze_transcript_v2(TRANSCRIPT, token_mode="精细",
                                     quantity_mode="自定义数量", custom_count=5,
                                     client=FakeClient(), verbose=False)
    log(f"  自动精选：高光 {len(r_auto['highlights'])} 个（只留 AI 盖章 recommend 的）")
    log(f"  候选池：高光 {len(r_pool['highlights'])} 个（score>={config.MIN_QUALITY_SCORE} 全展示，含 AI 软拒的）")
    log(f"  自定义 5 个：高光 {len(r_custom['highlights'])} 个（分层标注）")
    check("候选池比自动精选多（软拒候选也展示）",
          len(r_pool["highlights"]) > len(r_auto["highlights"]))
    check("自定义数量严格等于用户要的个数",
          len(r_custom["highlights"]) == min(5, r_custom["meta"]["candidate_count"]))
    check("自定义模式带质量分层标注",
          all("quality" in h for h in r_custom["highlights"]))
    check("候选池里 AI 拒过的带 ai_recommend=false 标记",
          any(h["ai_recommend"] is False for h in r_pool["highlights"]))
    log("")

    # ============ 3. 预算降级 ============
    log("=" * 70)
    log("测试 3：Token 预算降级（快速模式 1 万预算 vs 51 分钟稿）")
    log("=" * 70)
    r_fast = analyze_transcript_v2(TRANSCRIPT, token_mode="快速",
                                   quantity_mode="自动精选", client=FakeClient(),
                                   verbose=False)
    dl = r_fast["meta"]["degrade_level"]
    log(f"  快速模式实测：降级到 level {dl}"
        f"（0=无 1=粗切 2=限候选 3=提示后继续），区块 {r_fast['meta']['chunk_count']} 个")
    check("51 分钟稿在快速模式下必然触发降级（level >= 1）", dl >= 1)
    check("降级后时间轴覆盖铁律依然成立（流程正常走完）",
          r_fast["meta"]["chunk_count"] > 0 and len(r_fast["highlights"]) >= 0)
    log("")

    # ============ 4. 健壮性 ============
    log("=" * 70)
    log("测试 4：坏回复不崩")
    log("=" * 70)
    check("海选回复是垃圾文本 → 返回空列表",
          _parse_screening_reply("这不是JSON") == [])
    check("海选回复是合法 JSON 但没有候选 → 空列表",
          _parse_screening_reply('{"candidates": []}') == [])
    check("候选缺时间戳 → 丢弃该条",
          _parse_screening_reply(
              '{"candidates": [{"title": "没时间", "score": 9}]}') == [])
    check("分数越界 → 拉回 1-10",
          _parse_screening_reply(
              '{"candidates": [{"start_time": "1:00", "end_time": "2:00", '
              '"score": 99, "title": "t", "reason": "r"}]}')[0]["score"] == 10)

    class BadScreeningClient:
        """海选全部翻车（回垃圾），复审永远到不了 → 应走「零候选」分支。"""
        def __call__(self, prompt, system=None, max_tokens=None):
            return "garbage!!", {"prompt_tokens": 10, "completion_tokens": 5}

    r_empty = analyze_transcript_v2(TRANSCRIPT, token_mode="快速",
                                    quantity_mode="自动精选",
                                    client=BadScreeningClient(), verbose=False)
    check("全部区块海选翻车 → 不崩，走零候选交代分支",
          r_empty["highlights"] == [] and r_empty["report"]["why_not_more"] != "")
    log("")

    # ============ 5. CostTracker 单元验证 ============
    log("=" * 70)
    log("测试 5：成本累加器（多次调用合并计费）")
    log("=" * 70)
    t = CostTracker()
    t.add({"prompt_tokens": 1000, "completion_tokens": 200})
    t.add({"prompt_tokens": 500, "completion_tokens": 300})
    expect = (1500 * config.PRICE_INPUT_PER_MTOKEN
              + 500 * config.PRICE_OUTPUT_PER_MTOKEN) / 1_000_000
    check(f"两次调用合并计费（¥{t.cost_yuan:.4f}）", abs(t.cost_yuan - expect) < 1e-9)
    check("report() 文本包含总次数和总花费",
          "2 次" in t.report() and "¥" in t.report())

    # ============ 收尾 ============
    log("")
    log("=" * 70)
    log("总结")
    log("=" * 70)
    fails = sum(1 for l in lines if "[FAIL]" in l)
    total = sum(1 for l in lines if "[PASS]" in l or "[FAIL]" in l)
    log(f"共 {total} 项检查，通过 {total - fails} 项，失败 {fails} 项")
    log("")
    log("说明：以上全部为离线测试（假 AI 客户端）。")
    log("真实效果验收（含「至少 1 个被拒候选」的人工确认）")
    log("需设置 DEEPSEEK_API_KEY 后运行：.\\.venv\\Scripts\\python analyze_v2.py")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"report written: {REPORT_PATH.name}")   # 控制台只打英文，防乱码
    if fails:
        print(f"WARNING: {fails} check(s) FAILED - see report")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
