# ============================================================
# event_scanner —— 候选信号扫描层（v0.3 阶段 1）
#
# 职责：把整场直播按「每分钟一个格子」打信号分，
#       热度高的分钟以后会被切分得更细（1-3 分钟一片，
#       AI 看得更仔细），热度低的分钟切得粗（10 分钟一片，省钱）。
#
# 铁律（这一层的灵魂）：
#   它只负责「测热度、调深度」，绝对不负责「过滤」——
#   没有任何一秒钟会因为「扫描层觉得不热」而被扔掉，
#   时间轴 100% 覆盖，每个片段送到 AI 面前的机会人人平等。
#   值不值得剪，只有后面的 AI 海选层有权说话。
# ============================================================

import math
from pathlib import Path

import config
from .transcript_parser import total_duration

# V0.5：工作区根目录（开发态 = 项目根；桌面版 = %LOCALAPPDATA%\AILiveClipper）
import app_paths

BASE_DIR = app_paths.workspace_root()


# ---------------- 词库 ----------------
# 词分两档：
#   strong（强信号）：直接命中爆点的高危词，一个顶 2 分
#   normal（普通信号）：说明「这里有内容在展开」，一个 1 分
# 词表里故意放了 ASR 常见错字变体（语音识别听错的写法），
# 比如主播喊"卧槽"，Whisper 可能写成"卧草/我操/沃草"。

# 所有直播类型通用的强信号（情绪爆发是万能信号）
COMMON_STRONG = [
    "卧槽", "我操", "卧草", "沃草", "我靠", "妈呀", "我的天",
    "笑死", "离谱", "炸了", "牛逼", "NB", "服了",
]

LEXICONS = {
    "娱乐聊天": {
        "strong": [
            "反转", "塌房", "吃瓜", "瓜", "曝光", "爆料", "实锤",
            "分手", "恋爱", "情侣", "吵架", "怼", "骂", "翻脸", "上头",
        ],
        "normal": [
            "峰哥", "丰哥", "风哥", "老铁", "家人们", "兄弟们",
            "哈哈哈", "说实话", "你知道吗", "有点意思", "钱", "喜欢",
        ],
    },
    "游戏竞技": {
        "strong": [
            "一穿三", "一穿二", "五杀", "三杀", "团灭", "逆转", "翻盘",
            "反杀", "丝血", "残血", "极限", "爆头", "世界波", "高光",
        ],
        "normal": [
            "开局", "决赛圈", "走位", "枪法", "队友", "对手",
            "赢了", "输了", "操作", "意识", "上分", "开枪", "打他",
        ],
    },
    "知识分享": {
        "strong": [
            "反常识", "颠覆", "误区", "内幕", "揭秘", "真相",
            "本质", "底层逻辑", "认知", "千万不要", "一定要记住",
        ],
        "normal": [
            "首先", "其次", "举例", "比如", "也就是说", "换句话说",
            "重点", "记住", "方法", "建议", "原理", "为什么", "原因",
        ],
    },
    # ---- 以下类型先占好位置（词库先给基础版），v0.3 Phase 3 再打磨 ----
    "户外": {
        "strong": ["冲", "挑战", "被抓", "报警", "危险", "翻车", "突发"],
        "normal": ["大爷", "路人", "小姐姐", "多少钱", "老板", "走", "跑"],
    },
    "带货": {
        "strong": ["秒杀", "抢购", "上链接", "限量", "优惠", "折扣", "赠品"],
        "normal": ["下单", "库存", "便宜", "性价比", "价格", "宝宝们", "宝子们"],
    },
}

# 可选类型清单（UI 以后直接拿这个列表显示下拉框，"自定义"单独处理）
AVAILABLE_TYPES = list(LEXICONS)


def load_user_lexicon() -> list:
    """读用户专属词库（项目根目录的 user_lexicon.txt）。

    一行一个词；# 开头的是注释。没有这个文件就返回空列表（不是错误）。
    用户写的词一律按强信号处理——自己加的词，说明用户觉得它重要。
    """
    path = BASE_DIR / config.USER_LEXICON_FILE
    if not path.exists():
        return []
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.strip()
        if word and not word.startswith("#"):
            words.append(word)
    return words


def scan(segments: list, live_type: str = None, user_words: list = None) -> list:
    """候选信号扫描：把整场直播切成每分钟一个格子，逐格打分。

    参数：
        segments   —— transcript_parser 解析出的台词列表
        live_type  —— 直播类型（词库按类型换），默认读 config
        user_words —— 用户词库（一般不用传，默认自动读 user_lexicon.txt）

    返回：每分钟一个 dict 的列表：
        {"start": 秒, "end": 秒, "strong": 强信号次数, "normal": 普通信号次数,
         "score": 信号分, "hot": 是否算热区}
    """
    live_type = live_type or config.LIVE_TYPE_DEFAULT
    if live_type not in LEXICONS:
        raise ValueError(f"未知直播类型：{live_type}（可选：{AVAILABLE_TYPES}）")

    # 组装这一场的词表：通用强信号 + 类型词库 + 用户词库
    strong_words = set(COMMON_STRONG) | set(LEXICONS[live_type]["strong"])
    normal_words = set(LEXICONS[live_type]["normal"])
    if user_words is None:
        user_words = load_user_lexicon()
    strong_words.update(user_words)

    total = total_duration(segments)
    if total <= 0:
        return []

    bucket_sec = config.BUCKET_SECONDS
    n_buckets = math.ceil(total / bucket_sec)

    buckets = []
    for i in range(n_buckets):
        b_start = i * bucket_sec
        b_end = (i + 1) * bucket_sec

        # 把落在这个格子里的台词拼成一段文字（跨格子的台词两边都算，宁可多算不漏算）
        text = "".join(
            s["text"] for s in segments
            if s["start"] < b_end and s["end"] > b_start
        )

        strong_hits = sum(text.count(w) for w in strong_words)
        normal_hits = sum(text.count(w) for w in normal_words)
        score = strong_hits * 2 + normal_hits

        buckets.append({
            "start": b_start,
            "end": b_end,
            "strong": strong_hits,
            "normal": normal_hits,
            "score": score,
            "hot": score >= config.HOT_BUCKET_SCORE,
        })
    return buckets
