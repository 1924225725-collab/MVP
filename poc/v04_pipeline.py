"""V0.4 Pipeline —— Chapter → Story → Event → Review 完整接入

设计原则（来自 HANDOVER_20260910）：
  - Chapter/Story 是软边界，不改主流程，只通过 config.STORY_CONTEXT 注入
  - 不推翻 A1/A2/A3/B1 已冻结的底层能力
  - 最小修改：直接在 analyze_transcript_v2 基础上跑，Story 层自动生效
  - 产物存到 poc/v04_result.json，与 B1 基线 highlights_v2.json 并列对比

运行方式：
  cd live_clipper
  ./.venv/Scripts/python poc/v04_pipeline.py
  ./.venv/Scripts/python poc/v04_pipeline.py --transcript transcripts/测试视频2.txt --mode 标准
"""
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from analysis import analyze_transcript_v2
from analysis.transcript_parser import parse_transcript_file, total_duration
from analysis.chunker import format_time


# ── 路径约定 ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
TRANSCRIPT = BASE_DIR / "transcripts" / "测试视频2.txt"
B1_PATH = BASE_DIR / "highlights_v2.json"
V04_PATH = BASE_DIR / "poc" / "v04_result.json"
CHAPTER_PATH = BASE_DIR / "poc" / "fixtures" / "ai_chapter_result.json"  # PoC 夹具
STORY_PATH = BASE_DIR / "poc" / "fixtures" / "story_segmentation_result.json"  # PoC 夹具


def _ts2s(t) -> int:
    """时间字符串 → 秒（'mm:ss' / 'hh:mm:ss' / 纯数字）。"""
    try:
        s = str(t).strip()
        if s.isdigit():
            return int(s)
        parts = [int(p) for p in s.split(":")]
        return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 \
            else parts[0] * 60 + parts[1]
    except (ValueError, AttributeError):
        return 0


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _event_span(ev: dict) -> tuple:
    """事件起止秒。B1 用 start_time/end_time；V0.4 用 start/end（秒）。"""
    if "start" in ev and "end" in ev:
        return _ts2s(ev["start"]), _ts2s(ev["end"])
    return _ts2s(ev.get("start_time", 0)), _ts2s(ev.get("end_time", 0))


def _event_duration(ev: dict) -> int:
    s, e = _event_span(ev)
    return max(0, e - s)


def _summary_stats(events: list) -> dict:
    """从事件列表统计核心指标。"""
    singles = [e for e in events if (e.get("source_count") or 1) == 1]
    small = [e for e in singles if _event_duration(e) <= 28]
    long_ev = [e for e in events if _event_duration(e) > 60]
    return {
        "total": len(events),
        "single_source": len(singles),
        "single_pct": round(len(singles) / max(1, len(events)) * 100),
        "small_28s": len(small),
        "long_60s": len(long_ev),
        "duration_range": (
            min(_event_duration(e) for e in events),
            max(_event_duration(e) for e in events),
        ) if events else (0, 0),
    }


def _grade_dist(events: list) -> dict:
    from collections import Counter
    return dict(Counter(e.get("grade", "?") for e in events))


def _top_events(events: list, n: int = 5) -> list:
    """返回前 N 个事件的摘要（按分数降序，已是 Global Ranking 排序）。"""
    out = []
    for e in events[:n]:
        out.append({
            "event_id": e.get("event_id", e.get("clip_id", "?")),
            "grade": e.get("grade", "?"),
            "score": e.get("final_score", e.get("score", 0)),
            "start_time": e.get("start_time", ""),
            "end_time": e.get("end_time", ""),
            "duration": _event_duration(e),
            "title": e.get("title", "")[:40],
            "source_count": e.get("source_count", 1),
        })
    return out


def _story_mapping(events: list) -> dict:
    """把事件映射到 Story（按时间交集）。"""
    try:
        stories = _load_json(STORY_PATH).get("stories", [])
    except Exception:
        return {}
    mapping = {}
    for st in stories:
        sid = f"{st['chapter_id']}-{st['story_id']}"
        st_start = _ts2s(st["start_time"])
        st_end = _ts2s(st["end_time"])
        mapped = []
        for e in events:
            es, ee = _event_span(e)
            if es < st_end and ee > st_start:  # 有交集
                mapped.append(e.get("event_id", e.get("clip_id", "?")))
        mapping[sid] = {"title": st.get("story_title", ""), "events": mapped}
    return mapping


def run_v04(
    transcript_path: str = None,
    live_type: str = None,
    token_mode: str = None,
    quantity_mode: str = None,
    custom_count: int = None,
    save: bool = True,
) -> dict:
    """V0.4 主流程：调用 analyze_transcript_v2（含 Story 层），保存结果。

    参数与 analyze_v2.py 一致；save=False 时只返回结果不写文件（用于测试）。
    """
    transcript_path = transcript_path or str(TRANSCRIPT)
    live_type = live_type or config.LIVE_TYPE_DEFAULT
    token_mode = token_mode or config.TOKEN_MODE_DEFAULT
    quantity_mode = quantity_mode or config.QUANTITY_MODE_DEFAULT
    custom_count = custom_count or config.DEFAULT_CUSTOM_COUNT

    print("=" * 70)
    print("V0.4 Pipeline  ——  Chapter → Story → Event → Review")
    print("=" * 70)
    print(f"直播类型：{live_type}   模式：{token_mode}   数量：{quantity_mode}")
    print(f"文字稿：{transcript_path}")
    print(f"Story 文件：{config.STORY_CONTEXT.get('story_file', '（未配置）')}")
    print()

    start = time.time()

    # 前置：打印 Chapter 结构（供审计）
    try:
        chapters = _load_json(CHAPTER_PATH).get("chapters", [])
        print(f"[Chapter] 共 {len(chapters)} 个：")
        for ch in chapters:
            print(f"  {ch['chapter_id']}: {ch['chapter_title']} ({ch['start_time']}-{ch['end_time']})")
    except Exception:
        chapters = []
        print("[Chapter] 未找到 ai_chapter_result.json，跳过")

    # Step 1: 解析 Transcript
    segments = parse_transcript_file(transcript_path)
    duration = total_duration(segments)
    print(f"\n[Transcript] {len(segments)} 行，总时长 {format_time(duration)}")

    # Step 2: 完整分析（内部已含 Story 层 + 事件聚合 + 分批复审）
    print("\n[分析] 开始调用 analyze_transcript_v2（含 Story 前置层）...")
    result = analyze_transcript_v2(
        transcript_path,
        live_type=live_type,
        token_mode=token_mode,
        quantity_mode=quantity_mode,
        custom_count=custom_count,
    )

    elapsed = time.time() - start

    # ── 附加 V0.4 专属元数据 ──────────────────────────────────────────────────
    meta = result["meta"]
    meta["v04_story_layer"] = True
    meta["v04_chapters"] = chapters
    meta["v04_story_mapping"] = _story_mapping(result["highlights"] + result["rejected"])
    meta["elapsed_seconds"] = round(elapsed, 1)

    # 事件聚合统计（来自 meta.event_stats）
    event_stats = meta.get("event_stats", {})
    print(f"\n[事件聚合] {event_stats}")

    # ── 保存 ──────────────────────────────────────────────────────────────────
    if save:
        V04_PATH.parent.mkdir(parents=True, exist_ok=True)
        V04_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n[保存] {V04_PATH}")

    # ── 摘要打印 ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("V0.4 结果摘要")
    print("=" * 70)
    print(f"候选数：{meta['candidate_count']}")
    print(f"事件数（聚合后）：{event_stats.get('events', '?')}")
    print(f"高光滑光：{len(result['highlights'])} 个")
    print(f"被拒候选：{len(result['rejected'])} 个")
    print(f"成本：¥{result['cost']['cost_yuan']:.4f}")
    print(f"耗时：{elapsed:.1f}s")

    print("\n推荐高光（前5）：")
    for h in result["highlights"][:5]:
        tag = h.get("quality", "")
        forced = " [强制保留]" if h.get("forced_keep") else ""
        dur = _event_duration(h)
        src = f"[{h.get('source_count', 1)}个候选]" if h.get("source_count", 1) > 1 else ""
        print(f"  {h['grade']}级 {h['score']}分 | {h['start_time']}-{h['end_time']} ({dur}s) "
              f"{h['title'][:35]} {src}{forced}")

    print("\n" + "=" * 70)
    print("V0.4 Pipeline 完成")
    print("=" * 70)

    return result


def compare_b1_vs_v04(b1_path: str = None, v04_path: str = None) -> dict:
    """B1 vs V0.4 对比报告。"""
    b1 = _load_json(B1_PATH if b1_path is None else Path(b1_path))
    v04 = _load_json(V04_PATH if v04_path is None else Path(v04_path))

    b1_all = b1["highlights"] + b1["rejected"]
    v04_all = v04["highlights"] + v04["rejected"]

    b1_stats = _summary_stats(b1_all)
    v04_stats = _summary_stats(v04_all)

    report = {
        "b1": {
            "stats": b1_stats,
            "grade_dist": _grade_dist(b1_all),
            "top_events": _top_events(b1_all, 5),
            "cost_yuan": b1["cost"]["cost_yuan"],
        },
        "v04": {
            "stats": v04_stats,
            "grade_dist": _grade_dist(v04_all),
            "top_events": _top_events(v04_all, 5),
            "cost_yuan": v04["cost"]["cost_yuan"],
        },
        "delta": {
            "event_count": v04_stats["total"] - b1_stats["total"],
            "small_28s_change": v04_stats["small_28s"] - b1_stats["small_28s"],
            "long_60s_change": v04_stats["long_60s"] - b1_stats["long_60s"],
            "single_pct_change": v04_stats["single_pct"] - b1_stats["single_pct"],
            "cost_delta": round(v04["cost"]["cost_yuan"] - b1["cost"]["cost_yuan"], 4),
        },
    }

    COMPARE_PATH = BASE_DIR / "poc" / "v04_b1_compare.json"
    COMPARE_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[对比报告] 已保存至 {COMPARE_PATH}")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="V0.4 Pipeline（含 Story 前置层）")
    parser.add_argument("--transcript", default=str(TRANSCRIPT))
    parser.add_argument("--type", default=config.LIVE_TYPE_DEFAULT)
    parser.add_argument("--mode", default=config.TOKEN_MODE_DEFAULT)
    parser.add_argument("--quantity", default=config.QUANTITY_MODE_DEFAULT)
    parser.add_argument("--count", type=int, default=config.DEFAULT_CUSTOM_COUNT)
    parser.add_argument("--compare", action="store_true",
                        help="跑完 V0.4 后立即生成 B1 vs V0.4 对比报告")
    args = parser.parse_args()

    result = run_v04(
        transcript_path=args.transcript,
        live_type=args.type,
        token_mode=args.mode,
        quantity_mode=args.quantity,
        custom_count=args.count,
    )

    if args.compare:
        compare_b1_vs_v04()
