# legacy_projection.py —— sidecar → 旧 Segment(start,end,text) 兼容投影
#
# 依据设计文档 §7 P2：实现"但不接入正式 pipeline"，产物写 transcript_candidate.txt。
# 行格式与 pipeline.format_time / save_transcript 完全一致：
#   [MM:SS - MM:SS] 台词        （分钟可超过 59，如 75:30）
# 旧 analysis/transcript_parser.parse_transcript 必须能原样解析投影产物。

_SAFE_TEXT_RE = None  # 行内不允许出现换行（会破坏一行一句的格式）


def format_time(seconds):
    """秒 → 'MM:SS'。与生产 pipeline.format_time 行为一致（分钟可>59）。"""
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    return f"{minutes:02d}:{sec:02d}"


def project_utterances(utterances):
    """sidecar utterances → 旧 Segment 等价物 [{'start': 秒, 'end': 秒, 'text': str}, ...]。

    富信息（speaker/emotion/events）在投影中**有意丢弃**——旧契约只有三字段；
    speaker_id 缺失的句子照常投影（富数据是可选证据，缺失时行为与旧版一致）。
    """
    segments = []
    for u in utterances or []:
        text = (u.get("text") or "").replace("\n", " ").replace("\r", " ").strip()
        if not text:
            continue  # 空文本句对旧链路无意义，跳过（与旧 parser 的容错方向一致）
        segments.append({
            "start": u["start_ms"] / 1000.0,
            "end": u["end_ms"] / 1000.0,
            "text": text,
        })
    return segments


def to_transcript_text(utterances):
    """投影成与生产 save_transcript 相同格式的整份文字稿字符串。"""
    lines = []
    for seg in project_utterances(utterances):
        lines.append(f"[{format_time(seg['start'])} - {format_time(seg['end'])}] {seg['text']}")
    return "\n".join(lines)


def write_transcript_candidate(doc, out_path):
    """把 sidecar 投影写出为 transcript_candidate.txt（绝不动生产 transcripts/）。"""
    text = to_transcript_text(doc.get("utterances"))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return text
