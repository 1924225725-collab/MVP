# ============================================================
# AI 直播切片助手 —— 高光分析入口（阶段二）
#
# 用法（在 live_clipper 文件夹里，先设置好 API Key）：
#   .\.venv\Scripts\python analyze.py
#
# 输入：transcripts/ 里的第一份文字稿（目前只处理一个测试文件）
# 输出：highlights.json（项目根目录）
# ============================================================

import json
from pathlib import Path

from analysis import analyze_transcript

BASE_DIR = Path(__file__).parent

# 目前只处理一个文件：写死为测试视频的文字稿
TRANSCRIPT_FILE = BASE_DIR / "transcripts" / "测试视频.txt"
OUTPUT_FILE = BASE_DIR / "highlights.json"


def main():
    print("AI直播切片助手 —— 高光分析")
    print("-" * 40)

    highlights = analyze_transcript(TRANSCRIPT_FILE)

    # 存成 highlights.json（ensure_ascii=False 让中文直接可读，不变成 \uXXXX）
    OUTPUT_FILE.write_text(
        json.dumps(highlights, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("-" * 40)
    print(f"共挑出 {len(highlights)} 个高光片段：")
    for h in highlights:
        print(f"  [{h['start_time']} - {h['end_time']}] {h['score']}分 {h['suggested_title']}")
    print(f"\n完整结果已保存：{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
