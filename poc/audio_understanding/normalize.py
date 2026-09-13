# normalize.py —— SenseVoice rich token 的解析与归一化
#
# SenseVoiceSmall 输出的 text 是 rich token 串，例如：
#   <|zh|><|NEUTRAL|><|Speech|><|woitn|>欢迎大家来直播间<|Laughter|>
# 本模块只做"真实输出的转译"：
#   - raw token 一律保留（raw_label 永不覆盖）
#   - 归一化映射是纯查表，表里没有的 token 原样保留为 unknown 类，绝不猜
#   - 句子里没有 emotion/event token 就返回空，由上层决定留空（不伪造）

import re

_TOKEN_RE = re.compile(r"<\|[^|]*\|>")

# 情绪 token → 归一化标签（词表见设计文档 §5.4）
EMOTION_MAP = {
    "<|HAPPY|>": "happy",
    "<|SAD|>": "sad",
    "<|ANGRY|>": "angry",
    "<|NEUTRAL|>": "neutral",
    "<|FEARFUL|>": "fearful",
    "<|DISGUSTED|>": "disgusted",
    "<|SURPRISED|>": "surprised",
    "<|EMO_UNKNOWN|>": "other",
}

# 音频事件 token → 归一化标签（设计文档 §5.5 紧凑词表的 SenseVoice 子集）
EVENT_MAP = {
    "<|BGM|>": "bgm",
    "<|Speech|>": "speech",
    "<|Applause|>": "applause",
    "<|Laughter|>": "laughter",
    "<|Cry|>": "cry",
    "<|Sneeze|>": "sneeze",
    "<|Cough|>": "cough",
    "<|Breath|>": "breath",
}

# 语言 token → ISO 简码
LANG_MAP = {
    "<|zh|>": "zh", "<|en|>": "en", "<|yue|>": "yue", "<|ja|>": "ja",
    "<|ko|>": "ko", "<|nospeech|>": None,
}

# ITN 标记（仅剥离，不产出语义）
_ITN_TOKENS = {"<|withitn|>", "<|woitn|>"}


def parse_rich_text(text):
    """把 SenseVoice rich text 拆成结构化结果。

    返回 {"language", "emotion_raw", "events_raw", "clean_text", "unknown_tokens"}：
    - emotion_raw: 第一个命中的情绪 token（模型每句至多一个），没有则 None
    - events_raw:  命中的事件 token 列表（可能多个），没有则 []
    - clean_text:  剥离全部 token 后的纯文本
    """
    tokens = _TOKEN_RE.findall(text or "")
    language = None
    emotion_raw = None
    events_raw = []
    unknown = []
    for t in tokens:
        if t in LANG_MAP:
            language = LANG_MAP[t]
        elif t in EMOTION_MAP:
            if emotion_raw is None:
                emotion_raw = t
        elif t in EVENT_MAP:
            events_raw.append(t)
        elif t in _ITN_TOKENS:
            continue
        else:
            unknown.append(t)
    clean_text = _TOKEN_RE.sub("", text or "").strip()
    return {
        "language": language,
        "emotion_raw": emotion_raw,
        "events_raw": events_raw,
        "clean_text": clean_text,
        "unknown_tokens": unknown,
    }


def normalize_emotion(emotion_raw):
    """raw token → 归一化标签；不认识的返回 None（上层留空，不伪造）。"""
    return EMOTION_MAP.get(emotion_raw)


def normalize_event(event_raw):
    return EVENT_MAP.get(event_raw)
