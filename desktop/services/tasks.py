# ============================================================
# desktop/services/tasks.py —— 业务任务层
#
# 桌面 UI 只跟这里打交道，不直接碰 analysis / pipeline / asr。
# 好处：以后换 UI 框架、加云端 ASR、加批处理，都不用动算法代码。
#
# 本层**只做编排与包装**，不改任何分析算法：
#   视频 → 文字稿   → pipeline.process_video（含 D-046 分层错误）
#   文字稿 → 分析结果 → analysis.analyze_transcript_v2
# ============================================================

import contextlib
import io
import re
import traceback
from pathlib import Path

from errors import ProcessError


# ---------------- 工具 ----------------

def _fmt_duration(ffmpeg_duration: str) -> str:
    """'00:06:28.07' → '06:28'；'00:51:40.13' → '51:40'。"""
    if not ffmpeg_duration:
        return ""
    m = re.match(r"(\d+):(\d+):(\d+)", str(ffmpeg_duration))
    if not m:
        return str(ffmpeg_duration)
    h, mi, s = (int(x) for x in m.groups())
    total_min = h * 60 + mi
    return f"{total_min:02d}:{s:02d}"


def probe_video(video_path) -> dict:
    """探测视频（时长 / 是否有音轨 / 是否可读）。失败抛 ProcessError。"""
    import pipeline
    path = pipeline.check_video_readable(video_path)
    info = pipeline.probe_media(path)
    return {
        "path": str(path),
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "readable": info["readable"],
        "has_audio": info["has_audio"],
        "duration": _fmt_duration(info.get("duration", "")),
        "duration_raw": info.get("duration", ""),
    }


def import_video(video_path, dest_dir=None) -> str:
    """把外部视频登记进工作区（保留原文件，不做无谓拷贝）。

    返回工作区里的视频路径：
      - 已经在工作区 videos/ 里 → 原样返回
      - 在别处 → 复制进 videos/（用户后续删原文件也不影响项目）
    """
    import shutil
    import app_paths

    src = Path(video_path).expanduser().resolve()
    if not src.exists():
        raise ProcessError("media_unreadable", f"文件不存在：{src}", str(src))

    videos = Path(dest_dir) if dest_dir else app_paths.videos_dir()
    videos.mkdir(parents=True, exist_ok=True)
    if src.parent == videos:
        return str(src)

    dst = videos / src.name
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dst)
    return str(dst)


def transcript_duration(transcript_path) -> str:
    """从文字稿最后一句推算时长（本地零成本）。"""
    try:
        from analysis import transcript_parser, chunker
        segs = transcript_parser.parse_transcript_file(str(transcript_path))
        if not segs:
            return ""
        return chunker.format_time(transcript_parser.total_duration(segs))
    except Exception:
        return ""


def count_lines(path) -> int:
    try:
        return sum(1 for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip())
    except OSError:
        return 0


# ---------------- 任务 1：视频 → 文字稿（本地 ASR） ----------------

def transcribe_video(video_path, progress=None) -> dict:
    """导入的视频 → 文字稿。

    progress(stage:str) 可选，用来更新界面进度文字。
    失败抛 ProcessError（stage 见 errors.py，界面据此分层提示）。
    返回 {"transcript", "lines", "segments", "duration", "log"}
    """
    import pipeline

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        result = pipeline.process_video(Path(video_path), progress=progress)

    transcript = Path(result["transcript"])
    duration = probe_video(video_path).get("duration", "") or transcript_duration(transcript)
    return {
        "transcript": str(transcript),
        "lines": count_lines(transcript),
        "segments": len(result["segments"]),
        "duration": duration,
        "dictionary_hits": result.get("dictionary_hits", 0),
        "log": buf.getvalue(),
    }


# ---------------- 任务 2：文字稿 → 分析结果 ----------------

def analyze_transcript(transcript_path, live_type=None, token_mode=None,
                       quantity_mode=None, custom_count=None, progress=None) -> dict:
    """文字稿 → 完整分析结果（Chapter / Story / Event / Highlight / 推荐）。

    **直接调用原有 analyze_transcript_v2，算法一行不改。**
    返回原始结果 dict，另加 "_log" 字段（界面日志用）。
    """
    from analysis import analyze_transcript_v2

    if progress:
        progress("AI 海选 → 质检 → 事件聚合 → 复审 → 内容结构")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        result = analyze_transcript_v2(
            transcript_path,
            live_type=live_type,
            token_mode=token_mode,
            quantity_mode=quantity_mode,
            custom_count=custom_count,
            verbose=True,
        )
    result["_log"] = buf.getvalue()
    return result


# ---------------- 统一错误包装 ----------------

def wrap_error(exc: BaseException) -> ProcessError:
    """把任意异常规整成带 stage 的 ProcessError（界面能分层提示）。"""
    if isinstance(exc, ProcessError):
        return exc
    if isinstance(exc, SystemExit):
        return ProcessError("config", f"配置或参数有问题：{exc}", traceback.format_exc())
    return ProcessError("unknown", f"{type(exc).__name__}: {exc}", traceback.format_exc())
