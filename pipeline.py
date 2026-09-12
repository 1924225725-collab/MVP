# ============================================================
# AI 直播切片助手 —— 核心流水线
#
# 这里面是"真正干活"的函数：提取音频、语音识别、存文字稿、高光分析。
# main.py（命令行入口）和 ui.py（网页入口）都只是"界面"，
# 干活的代码只在这一份，改一处两边都生效。
#
# 每个函数都可以单独调用，也方便以后做测试。
#
# 【V0.4.5 错误处理修复】（严重问题）
#   以前：extract_audio / process_video 失败只 `return None`，
#   ui.py 把所有失败统一显示成「视频处理失败，请换一个文件试试」。
#   后果：正常视频也显示同一句（真因是加载本地 Whisper 模型时联网校验被代理拦成 502），
#   且「损坏」「没音轨」「模型没装」全都无法区分。
#   现在：分四步显式检查，每层失败抛 `ProcessError(stage=...)`，
#   UI 按 stage 给不同提示，开发者视图保留原始错误。
#   —— 只增加检查与错误分类，**不改流水线阶段划分、不改 ASR 架构**。
# ============================================================

import re
import subprocess
import traceback
from pathlib import Path

import app_paths
import stages
from errors import (
    ProcessError,
    STAGE_ASR_EMPTY,
    STAGE_ASR_INFERENCE,
    STAGE_AUDIO_EXTRACT,
    STAGE_DEPENDENCY,
    STAGE_FFMPEG,
    STAGE_MEDIA_UNREADABLE,
    STAGE_MODEL_LOAD,
    STAGE_NO_AUDIO,
)

# ---------- 项目文件夹 ----------
# V0.5：路径统一由 app_paths 解析（程序目录 / 用户数据目录分离）
#   开发态 = 项目根目录（与改造前完全一致）；桌面版 = %LOCALAPPDATA%\AILiveClipper
BASE_DIR = app_paths.program_root()
VIDEO_DIR = app_paths.videos_dir()
AUDIO_DIR = app_paths.audio_dir()
TRANSCRIPT_DIR = app_paths.transcripts_dir()


# ---------- 工具函数 ----------

def format_time(seconds):
    """把秒数变成人看的时间：83.4 秒 → "01:23"（方便直接对照视频找片段）"""
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)   # divmod：一次算出"分"和"余下的秒"
    return f"{minutes:02d}:{sec:02d}"    # :02d 表示不足两位补零，比如 3 → "03"


def scan_videos(folder):
    """扫描指定文件夹，找出所有 .mp4 文件，返回文件名列表。"""
    if not folder.exists():
        return []
    videos = []
    for file in folder.iterdir():          # iterdir()：把文件夹里的东西一个个拿出来
        if file.suffix.lower() == ".mp4":  # suffix：扩展名，.lower() 统一成小写再比较
            videos.append(file.name)
    return videos


def find_ffmpeg():
    """找到 ffmpeg 程序的位置。ffmpeg 由 imageio-ffmpeg 库提供（装在 .venv 里）。"""
    try:
        import imageio_ffmpeg   # 放在函数里：只有真正要用时才检查，报错信息更友好
    except ImportError as e:
        raise ProcessError(
            STAGE_DEPENDENCY,
            "缺少 imageio-ffmpeg 库（它提供 ffmpeg 程序）",
            f"{e}\n安装：.\\.venv\\Scripts\\python -m pip install imageio-ffmpeg",
        )
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:      # 库在但找不到可执行文件
        raise ProcessError(
            STAGE_FFMPEG,
            "ffmpeg 程序不可用（imageio-ffmpeg 已装但找不到可执行文件）",
            traceback.format_exc(),
        )


# ---------- V0.4.5：三层输入检查（可读性 → 媒体探测 → 音轨检测） ----------

# ffmpeg 明确表示"这文件读不了"的关键字
_FATAL_MARKERS = (
    "Invalid data found when processing input",
    "moov atom not found",
    "Error opening input",
    "No such file or directory",
    "Is a directory",
)
_AUDIO_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?: Audio:")
_VIDEO_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?: Video:")
_DURATION_RE = re.compile(r"Duration: (\d+:\d+:\d+\.\d+)")


def check_video_readable(video_path):
    """第 1 步：视频文件本身是否可读（存在、非空、是文件）。

    失败抛 ProcessError(STAGE_MEDIA_UNREADABLE)。
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise ProcessError(STAGE_MEDIA_UNREADABLE,
                           f"文件不存在：{video_path.name}",
                           f"路径：{video_path}")
    if video_path.is_dir():
        raise ProcessError(STAGE_MEDIA_UNREADABLE,
                           f"这是一个文件夹，不是视频文件：{video_path.name}",
                           f"路径：{video_path}")
    if video_path.stat().st_size == 0:
        raise ProcessError(STAGE_MEDIA_UNREADABLE,
                           f"文件是空的（0 字节）：{video_path.name}",
                           f"路径：{video_path}，size=0")
    return video_path


def probe_media(video_path):
    """第 2 步：用 `ffmpeg -i` 探测媒体文件（不需要额外装 ffprobe）。

    返回 dict：
      {readable, has_audio, has_video, duration, raw}
      readable  —— 是不是有效的、能解开的媒体文件
      has_audio —— 里面有没有音轨
      raw       —— ffmpeg 原始输出（排查用）
    """
    ffmpeg = find_ffmpeg()
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(video_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except Exception as e:
        raise ProcessError(STAGE_FFMPEG, "调用 ffmpeg 探测媒体文件失败",
                           traceback.format_exc())

    # ffmpeg -i（不给输出文件）本身就以非 0 退出，真正有用的信息在 stderr 里
    raw = (result.stderr or "") + "\n" + (result.stdout or "")

    has_input = "Input #0" in raw
    fatal = next((m for m in _FATAL_MARKERS if m in raw), None)
    has_audio = bool(_AUDIO_STREAM_RE.search(raw))
    has_video = bool(_VIDEO_STREAM_RE.search(raw))
    dur_match = _DURATION_RE.search(raw)

    readable = bool(has_input and not fatal and (has_audio or has_video))
    return {
        "readable": readable,
        "has_audio": has_audio,
        "has_video": has_video,
        "duration": dur_match.group(1) if dur_match else "",
        "fatal": fatal,
        "raw": raw,
    }


def _raw_tail(raw, n=8):
    """取 ffmpeg 输出的最后几行（给开发者视图看）。"""
    lines = [ln for ln in (raw or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def media_duration_seconds(media_info) -> float:
    """把 probe_media() 探到的 '00:51:40.13' 换算成秒（算不出来返回 0）。

    V0.5.2：语音识别的真实百分比要用它当分母（已处理时间 / 总时长）。
    """
    raw = (media_info or {}).get("duration") or ""
    m = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", str(raw))
    if not m:
        return 0.0
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


# ---------- 流水线各环节 ----------

def extract_audio(video_path, media_info=None):
    """第 3~4 步：检查可读性 → 探测音轨 → 提取音频为 MP3（16kHz 单声道）。

    成功返回音频文件路径；失败抛 ProcessError（带 stage）。
    media_info 可传 probe_media() 的结果，避免重复探测（可选）。
    """
    video_path = check_video_readable(video_path)

    info = media_info or probe_media(video_path)
    if not info["readable"]:
        detail = f"ffmpeg 关键报错：{info.get('fatal') or '（无明确关键字）'}\n{_raw_tail(info['raw'])}"
        raise ProcessError(
            STAGE_MEDIA_UNREADABLE,
            f"媒体文件无法读取：{video_path.name}（可能已损坏或不是有效视频）",
            detail,
        )
    if not info["has_audio"]:
        raise ProcessError(
            STAGE_NO_AUDIO,
            f"未检测到音轨：{video_path.name}（视频里没有声音轨道）",
            f"ffmpeg 探测到的流：\n{_raw_tail(info['raw'])}",
        )

    ffmpeg = find_ffmpeg()
    AUDIO_DIR.mkdir(exist_ok=True)  # 确保 audio/ 存在（万一被误删了也能自动补上）
    audio_path = AUDIO_DIR / (video_path.stem + ".mp3")  # "xxx.mp4" → "xxx.mp3"

    command = [
        ffmpeg,                 # ffmpeg 程序本身
        "-y",                   # 如果输出文件已存在，直接覆盖
        "-i", str(video_path),  # 输入：要处理的视频
        "-vn",                  # 只要声音，不要画面（vn = video no）
        "-ar", "16000",         # 采样率 16kHz：语音识别的标准采样率
        "-ac", "1",             # 单声道：人声不需要立体声，文件更小
        str(audio_path),        # 输出：生成的 MP3 文件
    ]
    # capture_output=True：把 ffmpeg 打印的信息收起来，别刷满屏幕
    # encoding="utf-8"：ffmpeg 输出是 UTF-8，Windows 中文系统默认用 GBK 解码会崩
    # errors="replace"：万一混进奇怪的字符，用占位符顶替而不是报错
    result = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )

    if result.returncode == 0 and audio_path.exists() and audio_path.stat().st_size > 0:
        return audio_path

    # 提取失败：把 ffmpeg 的报错尾巴带上（开发者视图可见）
    stderr = result.stderr or ""
    detail = (f"ffmpeg 退出码：{result.returncode}\n"
              f"输出文件：{audio_path}（存在={audio_path.exists()}，"
              f"大小={audio_path.stat().st_size if audio_path.exists() else 0} 字节）\n"
              f"--- ffmpeg 输出（最后 8 行）---\n{_raw_tail(stderr)}")
    raise ProcessError(
        STAGE_AUDIO_EXTRACT,
        f"音频提取失败：{video_path.name}",
        detail,
    )


def transcribe_audio(audio_path, recognizer=None, progress=None, duration=None):
    """第 5~7 步：加载识别引擎 → 语音识别：音频 → [Segment, ...] 列表。

    recognizer —— 可以从外面传进来（比如网页版只加载一次模型反复用），
                  不传就现场造一个（读 config.py 的配置）。
    progress   —— V0.5.2：直接透传给识别器，让它上报**真实进度**
                  （已处理音频时间 / 总时长）。
    duration   —— 音频总时长（秒），优先用调用方从视频探到的时长当分母。
    失败抛 ProcessError（模型未装 / 模型加载失败 / 推理失败分别归类）。
    """
    if recognizer is None:
        try:
            recognizer = get_recognizer()
        except ProcessError:
            raise                      # asr 层已经分好类了，原样上抛
        except BaseException as e:     # 兜住 SystemExit 这类非 Exception
            raise ProcessError(STAGE_MODEL_LOAD,
                               f"语音识别引擎初始化失败：{e}",
                               traceback.format_exc())

    try:
        # 不同引擎的 transcribe 签名可能不同（预留的云端引擎还没实现进度），
        # 这里按能力调用，绝不让"多传一个参数"把识别搞挂。
        return recognizer.transcribe(audio_path, progress=progress, duration=duration)
    except TypeError:
        return recognizer.transcribe(audio_path)
    except ProcessError:
        raise
    except Exception as e:
        raise ProcessError(STAGE_ASR_INFERENCE,
                           f"语音识别推理失败：{audio_path.name} —— {e}",
                           traceback.format_exc())


def save_transcript(video_name, segments):
    """把一组 Segment 写成文字稿文件，返回文件路径。"""
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    out_path = TRANSCRIPT_DIR / (Path(video_name).stem + ".txt")

    lines = []
    for seg in segments:
        lines.append(f"[{format_time(seg.start)} - {format_time(seg.end)}] {seg.text}")
    out_path.write_text("\n".join(lines), encoding="utf-8")  # utf-8：中文不乱码的关键
    return out_path


def apply_dictionary(segments):
    """v0.4：按 custom_dictionary.json 纠正刚识别出来的台词（改的是内存里的结果）。

    ASR 不认识主播名、游戏名、品牌、热词，这里按用户的词库把错字改回来，
    让存下来的文字稿一开始就是干净的——输入干净，后面 AI 才判断得准。

    segments —— Segment 列表（原地修改 text）
    返回改了几处（0 = 词库是空的或没命中）
    """
    from analysis.dictionary import correct_segments   # 延迟导入：不用纠错时不用加载
    return correct_segments(segments)


def correct_existing_transcript(transcript_path):
    """v0.4：对已经存在的文字稿文件执行纠错（用来处理历史稿子）。

    只改台词，时间戳一个字不动。返回改了几行。
    """
    from analysis.dictionary import correct_transcript_file
    return correct_transcript_file(transcript_path)


def analyze_highlights(transcript_path):
    """高光分析：文字稿 → 高光列表（字典组成的列表）。"""
    from analysis import analyze_transcript   # 延迟导入：不分析高光时不用加载它
    return analyze_transcript(transcript_path)


# ---------- 识别器缓存 ----------

_recognizer_cache = None   # 模型加载一次要好几秒，造好了就存起来反复用


def get_recognizer():
    """造一个识别器（读 config.py 配置），造好后缓存，第二次调用直接复用。

    V0.4.5：只缓存**成功**的识别器；加载失败时不留半成品，
    下次调用会重新尝试（用户装好模型后不用重启网页版）。
    """
    global _recognizer_cache
    if _recognizer_cache is None:
        from asr import create_recognizer   # 裁判：按配置决定用本地还是云端
        _recognizer_cache = create_recognizer()
    return _recognizer_cache


# ---------- 一条龙 ----------

def process_video(video_path, progress=None, recognizer=None):
    """完整处理一个视频：可读性检查 → 音轨检测 → 提取音频 → 语音识别 → 存文字稿。

    progress   —— 可选的进度回调。V0.5.2 起传**结构化事件**（见 stages.py）：
                    进度事件 = {stage, title, percent, detail, index, total_steps}
                  percent 是真实算出来的（语音识别 = 已处理音频时间 / 总时长）。
                  兼容老的 `progress("阶段名")` 单字符串回调（会自动降级）。
    recognizer —— 可选的识别器实例（桌面版会传入指定模型的识别器；
                  不传则按 config 现场造一个）。

    成功返回 dict：{"video", "audio", "segments", "transcript", "dictionary_hits"}

    V0.4.5：失败**不再返回 None**，而是抛 ProcessError（带 stage），
    让界面能按「损坏 / 没音轨 / 模型没装 / 模型加载失败 / 提取失败 / 推理失败」分别提示。
    """
    # 已经是 ProgressSink 就直接沿用（否则会套两层，事件被内层当成"阶段名"吞掉）
    report = (progress if isinstance(progress, stages.ProgressSink)
              else stages.ProgressSink(progress))

    video_path = check_video_readable(video_path)

    report(stages.STAGE_VIDEO_READ, None, "正在检查视频文件…")
    info = probe_media(video_path)
    duration = media_duration_seconds(info)

    report(stages.STAGE_AUDIO_EXTRACT, None,
           f"正在提取音频…（时长 {stages.fmt_clock(duration)}）" if duration
           else "正在提取音频…")
    audio_path = extract_audio(video_path, media_info=info)

    # VAD 检测 + 语音识别由识别器内部上报真实进度
    report(stages.STAGE_VAD, None, "正在检测哪里有人说话…")
    segments = transcribe_audio(audio_path, recognizer,
                                progress=report, duration=duration)

    if not segments:
        raise ProcessError(
            STAGE_ASR_EMPTY,
            f"没有识别出任何内容：{video_path.name}",
            "音频能正常读取、模型也跑通了，但整段几乎没有人声"
            "（可能是纯静音 / 纯 BGM / 纯环境音）。",
        )

    report(stages.STAGE_FINALIZE, None,
           f"正在整理文字稿…（共 {len(segments)} 句）")
    # v0.4：识别完先按自定义词库纠一遍错字（人名/游戏名/品牌/热词），
    # 再存成文字稿——这样 transcripts/ 里的稿子一开始就是干净的
    dict_hits = apply_dictionary(segments)

    transcript_path = save_transcript(video_path.name, segments)
    report(stages.STAGE_ASR, 100.0,
           f"共 {len(segments)} 句，已存文字稿", force=True)
    return {
        "video": video_path.name,
        "audio": audio_path,
        "segments": segments,
        "transcript": transcript_path,
        "dictionary_hits": dict_hits,   # 词库改了几处（界面可以显示"已纠正 N 处"）
        "duration_seconds": duration,
    }
