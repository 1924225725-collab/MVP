# ============================================================
# AI 直播切片助手 —— 程序入口
#
# 阶段一目标：MP4 视频 → 提取音频 → 语音识别 → 带时间戳的文字稿
# 当前进度：步骤 2（从视频提取音频，保存到 audio/）
# ============================================================

from pathlib import Path   # pathlib 是 Python 自带的"路径工具箱"
import subprocess          # subprocess：让 Python 去调用外部程序（比如 ffmpeg）

import config              # 我们的开关面板（选 local 还是 api）
from asr import create_recognizer  # 裁判：按配置造出一个识别器

# 项目文件夹都相对 main.py 所在位置来定，这样无论从哪里运行都不会找错地方
BASE_DIR = Path(__file__).parent
VIDEO_DIR = BASE_DIR / "videos"
AUDIO_DIR = BASE_DIR / "audio"
TRANSCRIPT_DIR = BASE_DIR / "transcripts"


def format_time(seconds):
    """把秒数变成人看的时间：83.4 秒 → "01:23"（方便直接对照视频找片段）"""
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)   # divmod：一次算出"分"和"余下的秒"
    return f"{minutes:02d}:{sec:02d}"    # :02d 表示不足两位补零，比如 3 → "03"


def save_transcript(video_name, segments):
    """把一组 Segment 写成文字稿文件，返回文件路径。"""
    TRANSCRIPT_DIR.mkdir(exist_ok=True)  # transcripts/ 不存在就自动建
    out_path = TRANSCRIPT_DIR / (Path(video_name).stem + ".txt")

    lines = []
    for seg in segments:
        lines.append(f"[{format_time(seg.start)} - {format_time(seg.end)}] {seg.text}")
    out_path.write_text("\n".join(lines), encoding="utf-8")  # utf-8：中文不乱码的关键
    return out_path


def scan_videos(folder):
    """扫描指定文件夹，找出所有 .mp4 文件，返回文件名列表。"""
    if not folder.exists():
        print(f"找不到文件夹：{folder}")
        return []

    videos = []
    for file in folder.iterdir():          # iterdir()：把文件夹里的东西一个个拿出来
        if file.suffix.lower() == ".mp4":  # suffix：文件的扩展名，.lower() 统一成小写再比较
            videos.append(file.name)       # 命中就记到列表里
    return videos


def find_ffmpeg():
    """找到 ffmpeg 程序的位置。ffmpeg 由 imageio-ffmpeg 库提供（装在 .venv 里）。"""
    try:
        import imageio_ffmpeg
    except ImportError:
        # 用错 Python 运行（比如直接 python main.py）就会走到这里
        print("❌ 缺少 imageio-ffmpeg 库，请用项目自带的 Python 来运行：")
        print("    .\\.venv\\Scripts\\python main.py")
        raise SystemExit(1)
    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_audio(video_path):
    """从视频里提取音频，保存为 MP3（16kHz、单声道，语音识别的标准格式）。

    成功返回音频文件的路径，失败返回 None。
    """
    AUDIO_DIR.mkdir(exist_ok=True)  # 确保 audio/ 存在（万一被误删了也能自动补上）
    audio_path = AUDIO_DIR / (video_path.stem + ".mp3")  # "xxx.mp4" → "xxx.mp3"

    command = [
        find_ffmpeg(),         # ffmpeg 程序本身
        "-y",                  # 如果输出文件已存在，直接覆盖
        "-i", str(video_path),  # 输入：要处理的视频
        "-vn",                 # 只要声音，不要画面（vn = video no）
        "-ar", "16000",        # 采样率 16kHz：语音识别的标准采样率
        "-ac", "1",            # 单声道：人声不需要立体声，文件更小
        str(audio_path),       # 输出：生成的 MP3 文件
    ]
    # subprocess.run：替我们在命令行里执行上面这串命令
    # capture_output=True：把 ffmpeg 打印的信息收起来，别刷满我们的屏幕
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode == 0 and audio_path.exists():
        return audio_path

    # 走到这里说明失败了，把 ffmpeg 的报错显示出来，方便排查
    print("  ffmpeg 报错（最后几行）：")
    for line in result.stderr.splitlines()[-5:]:
        print(f"    {line}")
    return None


# ---------- 程序从这里开始往下执行 ----------

print("AI直播切片助手启动成功")
print()

# ---- 第 1 步：扫描视频 ----
video_list = scan_videos(VIDEO_DIR)

if len(video_list) == 0:
    print("videos/ 文件夹里还没有 MP4 视频。")
    print("提示：把一个 MP4 文件复制到 videos/ 文件夹里，再重新运行本程序。")
else:
    print(f"共找到 {len(video_list)} 个视频：")
    for name in video_list:
        print(f"  - {name}")
    print()

    # ---- 第 2 步：提取音频 ----
    print("开始提取音频（视频越长等得越久）……")
    print()
    audio_list = []  # 记住每个视频对应的音频，留给第 3 步用
    for name in video_list:
        video_path = VIDEO_DIR / name
        print(f"正在处理：{name}")
        audio_path = extract_audio(video_path)
        if audio_path is None:
            print(f"  ❌ 提取失败：{name}")
            continue
        size_kb = audio_path.stat().st_size / 1024
        print(f"  ✅ 音频已保存：audio/{audio_path.name}（{size_kb:.0f} KB）")
        audio_list.append((name, audio_path))  # 把"视频名 + 音频路径"配对存好
    print()
    print("本步骤完成：视频 → 音频")

    # ---- 第 3 步：语音识别，生成带时间戳的文字稿 ----
    if audio_list:  # 只有成功拿到音频才继续
        print()
        # 按配置造识别器：config.py 里写 "local" 就用本地模型，写 "api" 就用云端
        # （工厂函数自己会去读 config，我们不用传）
        recognizer = create_recognizer()
        print(f"当前识别引擎：{recognizer.name}")
        print()

        for name, audio_path in audio_list:
            print(f"正在识别：{audio_path.name}（视频越长等得越久）……")
            segments = recognizer.transcribe(audio_path)  # 不管哪个引擎，都是同一句调用

            if not segments:
                print(f"  ⚠️ 没识别出任何内容：{name}")
                continue

            out_path = save_transcript(name, segments)
            print(f"  ✅ 共 {len(segments)} 句，文字稿已保存：transcripts/{out_path.name}")
            print()
            # 把前 3 句打印出来，不用打开文件就能快速检查效果
            print("  前 3 句预览：")
            for seg in segments[:3]:
                print(f"    [{format_time(seg.start)} - {format_time(seg.end)}] {seg.text}")
        print()
        print("本步骤完成：音频 → 带时间戳的文字稿")
        print()
        print("阶段一全流程打通 🎉")
