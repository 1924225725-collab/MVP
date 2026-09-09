# ============================================================
# test_phase1.py —— v0.3 阶段 1 自测脚本（纯本地、零成本）
#
# 验收目标：
#   1. 时间戳解析：能读 transcripts/ 里的文字稿
#   2. 信号扫描：分类型词库正常打分
#   3. 智能分区：热区细切、普通区粗切
#   4. 铁律：时间轴 100% 覆盖，不漏一秒、不重叠一秒
#
# 运行：.\.venv\Scripts\python test_phase1.py
# 结果写入 phase1_report.txt（避免控制台中文/emoji 乱码）
# ============================================================

from pathlib import Path

import config
from analysis.transcript_parser import parse_transcript_file, total_duration
from analysis.event_scanner import scan, AVAILABLE_TYPES
from analysis.chunker import build_chunks, check_coverage, format_time

BASE_DIR = Path(__file__).parent
TRANSCRIPT_DIR = BASE_DIR / "transcripts"
REPORT_PATH = BASE_DIR / "phase1_report.txt"

lines = []
def log(s=""):
    lines.append(s)


def test_one_transcript(name, live_type):
    """对一份文字稿跑完整三层流水线，把结果写进报告。"""
    log("=" * 70)
    log(f"测试对象：{name}（直播类型：{live_type}）")
    log("=" * 70)

    # ---- 第 1 层：解析 ----
    segments = parse_transcript_file(TRANSCRIPT_DIR / name)
    duration = total_duration(segments)
    if not segments:
        log("[失败] 没解析出任何台词！")
        return
    log(f"[解析] 共 {len(segments)} 句台词，总时长 {format_time(duration)}")

    # ---- 第 2 层：信号扫描 ----
    buckets = scan(segments, live_type)
    hot_count = sum(1 for b in buckets if b["hot"])
    log(f"[扫描] 共 {len(buckets)} 个分钟格子，其中热区 {hot_count} 格"
        f"（占比 {hot_count * 100 // len(buckets)}%）")

    # 打印最热的 5 个格子，看看扫描层到底被什么词点燃了
    top5 = sorted(buckets, key=lambda b: b["score"], reverse=True)[:5]
    log("[扫描] 最热的 5 个分钟格子：")
    for b in top5:
        log(f"    {format_time(b['start'])} - {format_time(b['end'])}"
            f"  信号分 {b['score']}（强 {b['strong']} / 普通 {b['normal']}）")

    # ---- 第 3 层：智能分区 ----
    chunks = build_chunks(buckets, segments)
    hot_chunks = [c for c in chunks if c["hot"]]
    normal_chunks = [c for c in chunks if not c["hot"]]
    log(f"[分区] 共 {len(chunks)} 个区块：热区细切 {len(hot_chunks)} 片，"
        f"普通区粗切 {len(normal_chunks)} 片")
    log("[分区] 区块明细：")
    for i, c in enumerate(chunks, 1):
        tag = "热" if c["hot"] else "普"
        length = c["end"] - c["start"]
        log(f"    #{i:02d} [{tag}] {format_time(c['start'])} - {format_time(c['end'])}"
            f"（{length // 60}分{length % 60:02d}秒）"
            f" 信号分 {c['score']}  台词 {len(c['segments'])} 句 / {c['char_count']} 字")

    # ---- 铁律验收：100% 覆盖 ----
    problems = check_coverage(chunks, duration)
    if problems:
        log("[验收] 覆盖检查未通过！问题如下：")
        for p in problems:
            log(f"    !! {p}")
    else:
        log("[验收] 时间轴覆盖 100%：从 00:00 到 "
            f"{format_time(duration)} 无漏盖、无重叠，铁律守住")
    log("")


def main():
    log("v0.3 阶段 1 自测报告")
    log(f"（直播类型词库共 {len(AVAILABLE_TYPES)} 种：{ '、'.join(AVAILABLE_TYPES) }）")
    log("")

    # 主测试：娱乐聊天词库跑两份测试稿
    for name in ["测试视频.txt", "测试视频2.txt"]:
        path = TRANSCRIPT_DIR / name
        if path.exists():
            test_one_transcript(name, config.LIVE_TYPE_DEFAULT)

    # 对照测试：同一份稿换游戏词库，确认扫描结果确实随类型变化
    log("=" * 70)
    log("对照测试：同一份稿子，娱乐词库 vs 游戏词库（结果应该不同）")
    log("=" * 70)
    segments = parse_transcript_file(TRANSCRIPT_DIR / "测试视频.txt")
    for live_type in ["娱乐聊天", "游戏竞技"]:
        buckets = scan(segments, live_type)
        hot = sum(1 for b in buckets if b["hot"])
        total_score = sum(b["score"] for b in buckets)
        log(f"    {live_type}：热区 {hot} 格，全场总信号分 {total_score}")
    log("")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"report written: {REPORT_PATH.name}")   # 控制台只打英文，防乱码


if __name__ == "__main__":
    main()
