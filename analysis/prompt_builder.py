"""prompt_builder —— 把带时间戳的文字稿，拼成一份发给 DeepSeek 的「需求单」。

成本控制第 1 道闸门在这里：
文字稿超过 config.MAX_TRANSCRIPT_CHARS 字时，按「行」截断（不切半句话）。
"""

import config

# 需求单模板。{transcript} 是占位符，会被真实文字稿替换掉。
# 模板里 JSON 示例的花括号要写成 {{ }} 才不会被 .format() 误认成占位符。
_PROMPT_TEMPLATE = """你是一位资深的直播内容运营，擅长从直播录像中挑出适合做成短视频切片的「高光时刻」。

下面是一场直播的带时间戳文字稿，每行格式为：[开始时间 - 结束时间] 台词。时间格式为「分:秒」。

请从中挑选 3~6 个最适合做切片的片段，只输出一个 JSON 对象，不要输出任何其他文字（包括解释、问候、markdown 代码块标记）。

JSON 格式（严格遵守）：
{{
  "highlights": [
    {{
      "start_time": "片段开始时间，如 01:23（必须用文字稿里出现过的原始时间戳）",
      "end_time": "片段结束时间，如 01:58",
      "score": 8,
      "reason": "这个片段值得切片的理由，40字以内",
      "suggested_title": "适合发短视频平台的标题，20字以内"
    }}
  ]
}}

评分标准（score 为 1-10 的整数）：
- 9-10：爆点密集 / 观点炸裂 / 情绪拉满，切片必火
- 7-8：话题性强，容易引发评论区讨论
- 5-6：内容尚可但平淡
- 低于 5 的片段不值得切片，不要输出

挑选要求：
- 可以把相邻几行合并成一个片段，成片时长建议在 30 秒 ~ 3 分钟
- 优先选：金句、反转、吵架、离谱言论、情绪高潮
- suggested_title 要吸引点击，但不要失实

文字稿如下：
{transcript}"""


def build_prompt(transcript_text: str):
    """把文字稿装进需求单。

    返回三个东西：
        prompt    —— 拼好的完整需求单（发给 AI 的全部内容）
        used_chars —— 实际使用的文字稿字数（成本报表要用）
        truncated —— 是否因超长被截断（True = 文字稿没装完）
    """
    # 按行装填：一行一行往需求单里放，放不下就停
    # （比直接切字符串好，不会把某句台词或时间戳切成两半）
    kept_lines = []
    used_chars = 0
    for line in transcript_text.splitlines():
        if used_chars + len(line) > config.MAX_TRANSCRIPT_CHARS:
            break
        kept_lines.append(line)
        used_chars += len(line)

    truncated = used_chars < len(transcript_text.replace("\n", ""))
    prompt = _PROMPT_TEMPLATE.format(transcript="\n".join(kept_lines))
    return prompt, used_chars, truncated
