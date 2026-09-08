# ============================================================
# AI 直播切片助手 —— 核心流水线（v0.2 新增）
#
# 这里面是"真正干活"的函数：提取音频、语音识别、存文字稿、高光分析。
# main.py（命令行入口）和 ui.py（网页入口）都只是"界面"，
# 干活的代码只在这一份，改一处两边都生效。
#
# 每个函数都可以单独调用，也方便以后做测试。
# ============================================================

import subprocess
from pathlib import Path

# ---------- 项目文件夹（都以本文件位置为准） ----------
BASE_DIR = Path(__file__).parent
VIDEO_DIR = BASE_DIR / "videos"
AUDIO_DIR = BASE_DIR / "audio"
TRANSCRIPT_DIR = BASE_DIR / "transcripts"


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
    import imageio_ffmpeg   # 放在函数里：只有真正要用时才检查，报错信息更友好
    return imageio_ffmpeg.get_ffmpeg_exe()


# ---------- 流水线各环节 ----------

def extract_audio(video_path):
    """从视频里提取音频，保存为 MP3（16kHz、单声道，语音识别的标准格式）。

    成功返回音频文件的路径，失败返回 None。
    """
    AUDIO_DIR.mkdir(exist_ok=True)  # 确保 audio/ 存在（万一被误删了也能自动补上）
    audio_path = AUDIO_DIR / (video_path.stem + ".mp3")  # "xxx.mp4" → "xxx.mp3"

    command = [
        find_ffmpeg(),          # ffmpeg 程序本身
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

    if result.returncode == 0 and audio_path.exists():
        return audio_path

    # 走到这里说明失败了，把 ffmpeg 的报错尾巴显示出来，方便排查
    print("  ffmpeg 报错（最后几行）：")
    for line in result.stderr.splitlines()[-5:]:
        print(f"    {line}")
    return None


def transcribe_audio(audio_path, recognizer=None):
    """语音识别：音频 → [Segment, ...] 列表。

    recognizer 可以从外面传进来（比如网页版只加载一次模型反复用），
    不传就现场造一个（读 config.py 的配置）。
    """
    if recognizer is None:
        recognizer = get_recognizer()
    return recognizer.transcribe(audio_path)   # 不管哪个引擎，都是同一句调用


def save_transcript(video_name, segments):
    """把一组 Segment 写成文字稿文件，返回文件路径。"""
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    out_path = TRANSCRIPT_DIR / (Path(video_name).stem + ".txt")

    lines = []
    for seg in segments:
        lines.append(f"[{format_time(seg.start)} - {format_time(seg.end)}] {seg.text}")
    out_path.write_text("\n".join(lines), encoding="utf-8")  # utf-8：中文不乱码的关键
    return out_path


def analyze_highlights(transcript_path):
    """高光分析：文字稿 → 高光列表（字典组成的列表）。"""
    from analysis import analyze_transcript   # 延迟导入：不分析高光时不用加载它
    return analyze_transcript(transcript_path)


# ---------- 识别器缓存 ----------

_recognizer_cache = None   # 模型加载一次要好几秒，造好了就存起来反复用


def get_recognizer():
    """造一个识别器（读 config.py 配置），造好后缓存，第二次调用直接复用。"""
    global _recognizer_cache
    if _recognizer_cache is None:
        from asr import create_recognizer   # 裁判：按配置决定用本地还是云端
        _recognizer_cache = create_recognizer()
    return _recognizer_cache


# ---------- 一条龙 ----------

def process_video(video_path, progress=None):
    """完整处理一个视频：提取音频 → 语音识别 → 存文字稿。

    progress 是可选的进度汇报函数 progress(阶段名)，界面可以拿它显示进度条。
    返回 dict：{"video": 名字, "audio": 音频路径, "segments": 识别结果, "transcript": 文字稿路径}
    失败时对应字段为 None；完全失败（没拿到文字稿）返回 None。
    """
    if progress:
        progress("提取音频")
    audio_path = extract_audio(video_path)
    if audio_path is None:
        return None

    if progress:
        progress("语音识别")
    segments = transcribe_audio(audio_path)
    if not segments:
        return None

    transcript_path = save_transcript(video_path.name, segments)
    return {
        "video": video_path.name,
        "audio": audio_path,
        "segments": segments,
        "transcript": transcript_path,
    }
