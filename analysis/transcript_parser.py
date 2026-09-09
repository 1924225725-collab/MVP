# ============================================================
# transcript_parser —— 时间戳解析层（v0.3 阶段 1）
#
# 职责：把文字稿文件（[00:12 - 00:18] 台词 这种格式）
#       解析成程序能用的数据：每一行变成一个 dict：
#       {"start": 秒, "end": 秒, "text": "台词"}
#
# 它是整条 v0.3 新流水线的第一环，后面所有环节
# （扫描热度、智能分区、AI 海选）都吃它吐出来的数据。
# ============================================================

import re

# 匹配一行文字稿：[00:12 - 00:18] 台词内容
# 时间部分支持两种写法：
#   分:秒      → 00:12（我们 pipeline.py 目前的输出格式，分钟可以超过 59，如 75:30）
#   时:分:秒   → 01:00:12（1 小时以上的直播，以后可能用到）
_LINE_PATTERN = re.compile(
    r"^\[(\d+:\d{2}(?::\d{2})?)\s*-\s*(\d+:\d{2}(?::\d{2})?)\]\s*(.*)$"
)


def _time_to_seconds(text: str):
    """把时间字符串换算成秒。'01:23' → 83；'01:00:12' → 3612。不合法返回 None。"""
    try:
        parts = [int(p) for p in text.split(":")]
    except ValueError:
        return None

    if len(parts) == 2:                      # 分:秒
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:                      # 时:分:秒
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


def parse_transcript(transcript_text: str) -> list:
    """解析整份文字稿，返回 [{'start': 秒, 'end': 秒, 'text': 台词}, ...]。

    坏行（时间戳格式不对、结束时间早于开始时间）直接跳过，
    不让一行坏数据毁掉整份稿子。
    """
    segments = []
    for line in transcript_text.splitlines():
        line = line.strip()
        if not line:
            continue                          # 空行跳过

        matched = _LINE_PATTERN.match(line)
        if not matched:
            continue                          # 格式不认识，跳过（不报错，容忍手改过的稿子）

        start = _time_to_seconds(matched.group(1))
        end = _time_to_seconds(matched.group(2))
        if start is None or end is None or end < start:
            continue                          # 时间不合法，跳过

        segments.append({"start": start, "end": end, "text": matched.group(3).strip()})
    return segments


def parse_transcript_file(transcript_path) -> list:
    """读一个文字稿文件并解析（方便外部直接传路径调用）。"""
    from pathlib import Path
    path = Path(transcript_path)
    if not path.exists():
        raise SystemExit(f"[找不到文件] {path}")
    return parse_transcript(path.read_text(encoding="utf-8"))


def total_duration(segments: list) -> int:
    """整场直播的时长（秒）：以最后一句台词的结束时间为准。"""
    if not segments:
        return 0
    return max(s["end"] for s in segments)
