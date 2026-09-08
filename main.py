# ============================================================
# AI 直播切片助手 —— 命令行入口
#
# 阶段一：MP4 视频 → 提取音频 → 语音识别 → 带时间戳的文字稿
# v0.2 起，干活的函数都搬到 pipeline.py，本文件只负责"按顺序喊话 + 打印"。
# 网页版入口是 ui.py，两边共用同一套流水线。
#
# 用法（在 live_clipper 文件夹里）：
#   .\.venv\Scripts\python main.py
# ============================================================

# 先检查工具箱带对了没有（用错 Python 运行时给出友好提示）
try:
    import imageio_ffmpeg   # noqa: F401  只是检查能不能导入，不用它本身
except ImportError:
    print("❌ 缺少 imageio-ffmpeg 库，请用项目自带的 Python 来运行：")
    print("    .\\.venv\\Scripts\\python main.py")
    raise SystemExit(1)

from pipeline import (
    AUDIO_DIR, TRANSCRIPT_DIR, VIDEO_DIR,
    extract_audio, format_time, get_recognizer,
    save_transcript, scan_videos, transcribe_audio,
)


def run():
    print("AI直播切片助手启动成功")
    print()

    # ---- 第 1 步：扫描视频 ----
    video_list = scan_videos(VIDEO_DIR)

    if len(video_list) == 0:
        print("videos/ 文件夹里还没有 MP4 视频。")
        print("提示：把一个 MP4 文件复制到 videos/ 文件夹里，再重新运行本程序。")
        return

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
        recognizer = get_recognizer()
        print(f"当前识别引擎：{recognizer.name}")
        print()

        for name, audio_path in audio_list:
            print(f"正在识别：{audio_path.name}（视频越长等得越久）……")
            segments = transcribe_audio(audio_path, recognizer)

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
        print()
        print("提示：网页版已上线，运行 .\\.venv\\Scripts\\streamlit run ui.py 试试")


# 只有直接运行本文件才执行 run()；被别的文件 import 时不会自动跑
if __name__ == "__main__":
    run()
