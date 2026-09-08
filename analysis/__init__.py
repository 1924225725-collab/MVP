"""analysis 模块对外入口 —— 别的文件只需要 import 这一个包。

流程：读文字稿 → 拼需求单 → 调 DeepSeek → 报成本 → 解析成高光列表
"""

import json
from pathlib import Path

from .deepseek_client import call_deepseek, print_cost_report
from .prompt_builder import build_prompt


def analyze_transcript(transcript_path) -> list:
    """分析一份文字稿，返回高光片段列表（字典的列表）。"""
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        raise SystemExit(f"[找不到文件] {transcript_path}")

    # ---- 1. 读文字稿 ----
    text = transcript_path.read_text(encoding="utf-8")

    # ---- 2. 拼需求单（超过字数上限会自动截断） ----
    prompt, used_chars, truncated = build_prompt(text)
    if truncated:
        print(f"[截断] 文字稿太长，只装了前 {used_chars} 字（上限在 config.py 里调）")

    # ---- 3. 调 DeepSeek（缺钥匙会在这里友好报错） ----
    reply_text, usage = call_deepseek(prompt)

    # ---- 4. 报账单 ----
    print_cost_report(len(prompt), usage)

    # ---- 5. 解析 AI 的回复 ----
    highlights = _parse_reply(reply_text)

    # 按分数从高到低排个序，最好的放最前面
    highlights.sort(key=lambda h: h["score"], reverse=True)
    return highlights


def _parse_reply(reply_text: str) -> list:
    """把 AI 回复的 JSON 文本，清洗成规规矩矩的高光列表。"""
    try:
        data = json.loads(reply_text)
    except json.JSONDecodeError:
        raise SystemExit(
            f"[解析失败] DeepSeek 回复的不是合法 JSON：\n{reply_text[:300]}"
        )

    # 兼容两种返回：{"highlights": [...]} 或直接 [...]
    items = data.get("highlights", []) if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise SystemExit(f"[空结果] AI 没有挑出任何片段，原始回复：\n{reply_text[:300]}")

    # 逐条体检：字段齐全、分数在 1-10 之间
    clean = []
    for item in items:
        try:
            score = int(item["score"])
        except (KeyError, ValueError, TypeError):
            continue  # 分数坏的条目直接丢弃，不让一颗老鼠屎坏一锅粥
        if not (1 <= score <= 10):
            score = min(10, max(1, score))  # 越界就拉回来
        clean.append(
            {
                "start_time": str(item.get("start_time", "")),
                "end_time": str(item.get("end_time", "")),
                "score": score,
                "reason": str(item.get("reason", "")),
                "suggested_title": str(item.get("suggested_title", "")),
            }
        )
    if not clean:
        raise SystemExit("[空结果] 所有片段都没通过体检，看看上面的原始回复。")
    return clean
