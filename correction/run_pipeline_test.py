# -*- coding: utf-8 -*-
"""
run_pipeline_test.py —— 把 correction 接进**测试流程**的完整跑测脚本。

不改变任何核心业务逻辑：本脚本只是把现有能力按顺序串起来，
ASR 用的是 pipeline 现成的函数，DeepSeek 分析用的是 analysis 现成的函数，
**两者都没被修改**，只是在中间插入了一个新的纠错步骤。

    ASR 输出（transcripts/<name>.txt，原样保留）
      ↓ 【新增步骤】correction 纠错
    corrected_transcript
      ↓
    DeepSeek 高光分析（默认读 corrected；对照跑一次原始稿）

用法
----
    # 1) 只跑纠错，不调 API（离线，验证接线 + 看纠错效果）
    python correction/run_pipeline_test.py --transcript 测试视频.txt --no-api

    # 2) 完整流程：纠错 + DeepSeek 分析 corrected 稿，并跑一遍原始稿做对照
    python correction/run_pipeline_test.py --transcript 测试视频.txt --mode 快速

    # 3) 真实重跑 ASR（需要本地模型），再走完整流程
    python correction/run_pipeline_test.py --transcript 测试视频.txt --retranscribe --mode 快速

    # 4) 演示用：往**副本**里注入几个典型 ASR 错字，看纠错前后高光差异（原稿不动）
    python correction/run_pipeline_test.py --transcript 测试视频.txt --demo-errors --mode 快速

产物（都在 transcripts/corrected/）：
    <name>.corrected.txt            纠错后的稿子
    <name>.correction_report.json   原文本 / 修正文本 / 修改位置 / 置信度
    <name>.comparison.json          纠错前后高光对比
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 让脚本既能 `python correction/run_pipeline_test.py` 跑，也能被 import
LIVE_CLIPPER = Path(__file__).resolve().parent.parent
if str(LIVE_CLIPPER) not in sys.path:
    sys.path.insert(0, str(LIVE_CLIPPER))

from correction.corrector import AsrCorrector, Entry          # noqa: E402
from correction.pipeline_step import run_correction_step      # noqa: E402


# ---------------------------------------------------------------- 演示注入

#: 演示用：把标准词替换成它在词库里的错写形式（**只作用于副本，原稿永不动**）
DEMO_INJECTIONS = [
    ("陈泽", "陈则"),        # 人物库：13/陈泽/(陈泽儿 陈则 陈泽c)
    ("陈泽", "陈则"),
]


def parse_extra_entries(specs) -> list[Entry]:
    """
    解析临时词条：`标准词=错写1,错写2`

    只进内存，**不写进任何词库文件**。用途：验证「如果词库覆盖了主播名，
    纠错能不能修好」这类假设，或临时补一个词跑一次，不必改词库。
    """
    entries: list[Entry] = []
    for spec in specs or []:
        if "=" not in spec:
            continue
        canonical, aliases = spec.split("=", 1)
        canonical = canonical.strip()
        alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
        if canonical and alias_list:
            entries.append(Entry(
                canonical=canonical, aliases=alias_list, category="person",
                priority=2, context_tags=["person"],
                description="命令行临时词条（不落盘）", source="cli(不落盘)",
                updated_at="2026-09-13",
            ))
    return entries


def inject_demo_errors(text: str, pairs=None) -> tuple[str, list[dict]]:
    """往副本里注入典型 ASR 错字，返回 (新文本, 注入记录)。仅用于演示，不改原稿。"""
    pairs = pairs or DEMO_INJECTIONS
    log = []
    for canonical, wrong in pairs:
        idx = text.find(canonical)
        if idx == -1:
            continue
        text = text[:idx] + wrong + text[idx + len(canonical):]
        log.append({"canonical": canonical, "injected": wrong, "at": idx})
    return text, log


# ---------------------------------------------------------------- 高光对比

def _brief(result: dict) -> list[dict]:
    """从分析结果里抽出可对比的高光摘要。"""
    out = []
    for h in (result or {}).get("highlights", []) or []:
        out.append({
            "event_id": h.get("event_id", ""),
            "title": h.get("title", ""),
            "start": h.get("start"),
            "end": h.get("end"),
            "score": h.get("final_score"),
            "grade": h.get("grade", ""),
            "recommended": bool(h.get("recommended")),
        })
    return out


def _time_key(h: dict) -> tuple:
    s = h.get("start") or ""
    return (s, h.get("end") or "")


def compare_highlights(before: list[dict], after: list[dict]) -> dict:
    """
    对比两批高光。用**时间重叠**配对（event_id 是各自重新生成的，不能直接比 id）。
    """
    def to_sec(v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        parts = str(v).split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
        except ValueError:
            return None
        return None

    def parse(h):
        return to_sec(h.get("start")), to_sec(h.get("end"))

    matched, only_before, only_after = [], list(before), []
    for a in after:
        a_s, a_e = parse(a)
        hit = None
        for b in only_before:
            b_s, b_e = parse(b)
            if None in (a_s, a_e, b_s, b_e):
                continue
            ov = min(a_e, b_e) - max(a_s, b_s)
            short = min(a_e - a_s, b_e - b_s) or 1
            if ov > 0 and ov / short >= 0.5:
                hit = b
                break
        if hit:
            only_before.remove(hit)
            d_score = None
            if isinstance(a.get("score"), (int, float)) and isinstance(hit.get("score"), (int, float)):
                d_score = round(float(a["score"]) - float(hit["score"]), 2)
            matched.append({
                "time": f"{hit.get('start')}-{hit.get('end')}",
                "title_before": hit.get("title", ""),
                "title_after": a.get("title", ""),
                "score_before": hit.get("score"),
                "score_after": a.get("score"),
                "score_delta": d_score,
                "grade_before": hit.get("grade", ""),
                "grade_after": a.get("grade", ""),
                "recommended_before": hit.get("recommended"),
                "recommended_after": a.get("recommended"),
                "changed": (
                    hit.get("title", "") != a.get("title", "")
                    or hit.get("grade", "") != a.get("grade", "")
                    or bool(hit.get("recommended")) != bool(a.get("recommended"))
                    or (d_score not in (None, 0))
                ),
            })
        else:
            only_after.append(a)

    return {
        "count_before": len(before),
        "count_after": len(after),
        "recommended_before": sum(1 for h in before if h.get("recommended")),
        "recommended_after": sum(1 for h in after if h.get("recommended")),
        "identical": (len(only_before) == 0 and len(only_after) == 0
                      and all(not m["changed"] for m in matched)),
        "matched": matched,
        "only_before": only_before,
        "only_after": only_after,
    }


# ---------------------------------------------------------------- 主流程

def run_full_test(
    transcript,
    token_mode: str = "快速",
    quantity_mode: str = "自动精选",
    do_api: bool = True,
    do_compare: bool = True,
    demo_errors: bool = False,
    retranscribe: bool = False,
    video: str | None = None,
    verbose: bool = True,
    analyze_fn=None,
    out_dir=None,
    extra_entries: list[Entry] | None = None,
) -> dict:
    """
    analyze_fn —— 分析函数注入口（默认 analysis.analyze_transcript_v2）。
    测试时可以塞一个假函数，用来断言「DeepSeek 分析读的是 corrected 稿」而不真烧 API。
    """
    """跑一遍完整测试流程，返回汇总 dict（并落盘 comparison.json）。"""
    transcript = Path(transcript)
    if not transcript.exists():
        cand = Path(LIVE_CLIPPER) / "transcripts" / str(transcript)
        transcript = cand if cand.exists() else transcript
    if not transcript.exists():
        raise FileNotFoundError(f"找不到文字稿：{transcript}")

    def say(msg):
        if verbose:
            print(msg)

    say("=" * 68)
    say(f"[0] 输入文字稿：{transcript}")

    # ---------- 1) ASR（可选重跑） ----------
    if retranscribe:
        say("[1] 重新跑 ASR（需要本地模型）…")
        import pipeline
        vpath = Path(video) if video else Path(LIVE_CLIPPER) / "videos" / (transcript.stem + ".mp4")
        if not vpath.exists():
            raise FileNotFoundError(f"找不到视频：{vpath}")
        res = pipeline.process_video(vpath)
        transcript = Path(res["transcript"])
        say(f"    ASR 完成 → {transcript}")
    else:
        say("[1] 复用已有 ASR 文字稿（原样保留，不重跑识别）")

    original_text = transcript.read_text(encoding="utf-8")

    # ---------- 2) 纠错步骤 ----------
    say("[2] correction 纠错…")
    if demo_errors:
        say("    （演示模式：往**副本**注入典型 ASR 错字，原稿不动）")
        from correction.pipeline_step import default_output_dir
        if out_dir:
            demo_dir = Path(out_dir)
        else:
            demo_dir = default_output_dir(transcript)
        demo_dir.mkdir(parents=True, exist_ok=True)
        injected, log = inject_demo_errors(original_text)
        tmp_path = demo_dir / f"{transcript.stem}.demo_injected.txt"
        tmp_path.write_text(injected, encoding="utf-8")
        say(f"    注入 {len(log)} 处：{[(x['canonical'], x['injected']) for x in log]}")
        step = run_correction_step(tmp_path, out_dir=demo_dir,
                                   extra_entries=extra_entries)
    else:
        step = run_correction_step(transcript, out_dir=out_dir,
                                   extra_entries=extra_entries)

    say(f"    {step.summary()}")
    say(f"    corrected → {step.corrected_path}")
    say(f"    report    → {step.report_path}")
    for c in step.applied[:20]:
        say(f"      · 第{c['line']}行 {c['original']} → {c['corrected']} "
            f"（置信度 {c['score']:.2f}，{c['category']}）")

    out = {
        "transcript": str(transcript),
        "corrected": str(step.corrected_path),
        "report": str(step.report_path),
        "stats": step.stats,
        "changes": step.applied,
        "suggestions": step.suggestions,
    }

    # ---------- 3) DeepSeek 高光分析 ----------
    if not do_api:
        say("[3] --no-api：跳过 DeepSeek 分析（离线接线验证完成）")
        out["analysis"] = None
        return out

    if analyze_fn is None:
        from analysis import analyze_transcript_v2 as analyze_fn

    say(f"[3] DeepSeek 高光分析（模式={token_mode}）：corrected 稿")
    res_after = analyze_fn(
        step.corrected_path, token_mode=token_mode,
        quantity_mode=quantity_mode, verbose=verbose,
    )
    after = _brief(res_after)
    say(f"    高光 {len(after)} 条，推荐 {sum(1 for h in after if h['recommended'])} 条")

    before, res_before = [], None
    if do_compare:
        say("[3b] 对照：同一份稿子的**纠错前**版本")
        source_before = step.original_path
        res_before = analyze_fn(
            source_before, token_mode=token_mode,
            quantity_mode=quantity_mode, verbose=verbose,
        )
        before = _brief(res_before)
        say(f"    高光 {len(before)} 条，推荐 {sum(1 for h in before if h['recommended'])} 条")

    comparison = compare_highlights(before, after) if do_compare else None
    if comparison:
        say("-" * 68)
        say(f"[4] 对比：{'结果完全一致' if comparison['identical'] else '存在差异'}"
            f"（高光 {comparison['count_before']} → {comparison['count_after']}，"
            f"推荐 {comparison['recommended_before']} → {comparison['recommended_after']}）")
        for m in comparison["matched"]:
            if m["changed"]:
                say(f"    · {m['time']} 分数 {m['score_before']} → {m['score_after']}"
                    f"（{m['grade_before']}→{m['grade_after']}）"
                    f" 推荐 {m['recommended_before']}→{m['recommended_after']}")
                if m["title_before"] != m["title_after"]:
                    say(f"      标题：{m['title_before']}  →  {m['title_after']}")
        for h in comparison["only_after"]:
            say(f"    + 纠错后新增：{h.get('start')}-{h.get('end')} {h.get('title','')}")
        for h in comparison["only_before"]:
            say(f"    - 纠错后消失：{h.get('start')}-{h.get('end')} {h.get('title','')}")

    comparison_path = step.corrected_path.parent / f"{step.corrected_path.stem}.comparison.json"
    payload = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "transcript_original": str(transcript),
            "transcript_corrected": str(step.corrected_path),
            "token_mode": token_mode,
            "quantity_mode": quantity_mode,
            "demo_errors": demo_errors,
            "cost_before": (res_before or {}).get("cost", {}),
            "cost_after": (res_after or {}).get("cost", {}),
        },
        "correction": {"stats": step.stats, "changes": step.applied,
                       "suggestions": step.suggestions},
        "highlights_before": before,
        "highlights_after": after,
        "comparison": comparison,
    }
    comparison_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    say(f"[5] 对比报告 → {comparison_path}")

    out["analysis"] = {"highlights": len(after)}
    out["comparison_path"] = str(comparison_path)
    out["comparison"] = comparison
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="correction 接入测试流程：ASR → 纠错 → DeepSeek")
    ap.add_argument("--transcript", default="测试视频.txt", help="文字稿文件名或路径")
    ap.add_argument("--mode", default="快速", help="分析模式：快速/标准/精细")
    ap.add_argument("--quantity", default="自动精选", help="数量模式")
    ap.add_argument("--no-api", action="store_true", help="不调 DeepSeek，只跑纠错")
    ap.add_argument("--no-compare", action="store_true", help="不跑纠错前对照")
    ap.add_argument("--demo-errors", action="store_true",
                    help="往副本注入典型 ASR 错字（原稿不动），用于演示效果")
    ap.add_argument("--retranscribe", action="store_true", help="真实重跑 ASR（需本地模型）")
    ap.add_argument("--video", help="--retranscribe 时指定视频路径")
    ap.add_argument("--extra-entry", action="append", default=[],
                    metavar="标准词=错写1,错写2",
                    help="临时词条（只进内存，不写进词库），可重复传")
    args = ap.parse_args(argv)

    run_full_test(
        transcript=args.transcript,
        token_mode=args.mode,
        quantity_mode=args.quantity,
        do_api=not args.no_api,
        do_compare=not args.no_compare,
        demo_errors=args.demo_errors,
        retranscribe=args.retranscribe,
        video=args.video,
        extra_entries=parse_extra_entries(args.extra_entry),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
