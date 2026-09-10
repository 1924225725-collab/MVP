# ============================================================
# AI 直播切片助手 —— v0.3 高光分析入口（海选 + 复审）
#
# 用法（在 live_clipper 文件夹里，先设置好 API Key）：
#   .\.venv\Scripts\python analyze_v2.py
#   .\.venv\Scripts\python analyze_v2.py --transcript transcripts\测试视频2.txt --type 娱乐聊天
#   .\.venv\Scripts\python analyze_v2.py --mode 精细 --quantity 自定义数量 --count 15
#
# 输入：transcripts/ 里的文字稿（默认用第二份测试稿，51 分钟那场）
# 输出：highlights_v2.json（项目根目录）
# ============================================================

import argparse
import json
import sys
from pathlib import Path

import config

# Windows 控制台默认 GBK，成本报表里的 ¥ 等字符会炸，强制 UTF-8 + 容错
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
from analysis import analyze_transcript_v2
from analysis.event_scanner import AVAILABLE_TYPES

BASE_DIR = Path(__file__).parent

TRANSCRIPT_FILE = BASE_DIR / "transcripts" / "测试视频2.txt"
OUTPUT_FILE = BASE_DIR / "highlights_v2.json"


def main():
    parser = argparse.ArgumentParser(
        description="AI 直播切片助手 v0.3 高光分析（AI 海选 + AI 复审）"
    )
    parser.add_argument(
        "--transcript", default=str(TRANSCRIPT_FILE),
        help="文字稿路径（默认 transcripts/测试视频2.txt）",
    )
    parser.add_argument(
        "--type", dest="live_type", default=config.LIVE_TYPE_DEFAULT,
        choices=AVAILABLE_TYPES, help="直播类型（默认 %(default)s）",
    )
    parser.add_argument(
        "--mode", dest="token_mode", default=config.TOKEN_MODE_DEFAULT,
        choices=list(config.TOKEN_MODES),
        help="分析模式：快速/标准/精细（默认 %(default)s）",
    )
    parser.add_argument(
        "--quantity", dest="quantity_mode", default=config.QUANTITY_MODE_DEFAULT,
        choices=config.QUANTITY_MODES,
        help="数量模式：自动精选/候选池/自定义数量（默认 %(default)s）",
    )
    parser.add_argument(
        "--count", type=int, default=config.DEFAULT_CUSTOM_COUNT,
        help="自定义数量模式的个数（默认 %(default)s）",
    )
    args = parser.parse_args()

    print("AI直播切片助手 —— v0.3 高光分析（海选 + 复审）")
    print("-" * 50)
    print(f"直播类型：{args.live_type}    分析模式：{args.token_mode}"
          f"    数量模式：{args.quantity_mode}")

    result = analyze_transcript_v2(
        args.transcript,
        live_type=args.live_type,
        token_mode=args.token_mode,
        quantity_mode=args.quantity_mode,
        custom_count=args.count,
    )

    OUTPUT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ---- 摘要打印（控制台只打安全字符，不整花活） ----
    print("-" * 50)
    recs = [h for h in result["highlights"] if h.get("recommended")]
    print(f"候选 {result['meta']['candidate_count']} 个，"
          f"最终高光 {len(result['highlights'])} 个（其中推荐剪辑 {len(recs)} 条），"
          f"被拒 {len(result['rejected'])} 个")
    struct_stats = (result.get("structure") or {}).get("stats") or {}
    if struct_stats:
        print(f"内容结构：{struct_stats.get('chapter_count', 0)} 章 / "
              f"{struct_stats.get('story_count', 0)} 个 Story"
              f"（{struct_stats.get('stories_with_events', 0)} 个含高光）")
    if result["meta"].get("miss_check_chunks"):
        print(f"质检重扫区块：{result['meta']['miss_check_chunks']}")
    if result["report"].get("why_not_more"):
        print(f"AI 解释：{result['report']['why_not_more']}")
    print()
    rec_ids = {h.get("clip_id") for h in recs}
    for h in result["highlights"]:
        tag = h.get("quality", "")
        star = "*推荐* " if h.get("clip_id") in rec_ids else "      "
        forced = "（召回保留，请人工复核）" if h.get("forced_keep") else ""
        # V0.4.3：控制台也不露 S/A/B/C/D 字母（与 UI 一致，D-044）
        badge = config.GRADE_UI.get(h.get("grade", ""), "")
        print(f"  {star}[{h['start_time']} - {h['end_time']}] "
              f"{h['score']}分 {badge} {h['title']} {tag}{forced}")
    print()
    print(f"完整结果（含推荐剪辑/内容结构/被拒候选/AI 报告）已保存：{OUTPUT_FILE}")
    print(f"总成本：约 ¥{result['cost']['cost_yuan']:.4f}")


if __name__ == "__main__":
    main()
