# -*- coding: utf-8 -*-
"""
scorer.py —— ASR 纠错「置信度评分」。

这里**不做替换**，只回答一个问题：
    把这个候选错误词换成标准词，有多大把握是对的？

评分不是拍脑袋，而是四个可解释的维度加权：

    score = 0.15 * 分类先验(category_prior)
          + 0.25 * 字形/字音相似度(similarity)
          + 0.40 * 上下文匹配(context)
          + 0.20 * 替换后通顺度(fluency)
    再乘以歧义系数(ambiguity)

为什么这么配重：
- **上下文权重最高(0.40)**：同一个词在不同语境下对错完全不同。
  「今天玩永久无间」有游戏语境 → 高；「永久无间的等待」没有 → 低。
  这正是「不能暴力替换」的核心——决定对错的不是词本身，是语境。
- **相似度次之(0.25)**：ASR 错字几乎都是同音/近形替换，
  一个跟标准词毫不相干的词被听错的概率很低。
- **通顺度(0.20)**：替换后如果落在「的等待 / 很xx」这类通用搭配里，
  说明它在这句话里是**普通词**而不是专有名词。
- **分类先验(0.15)**：人名/作品名是专有名词，听错了就该改；
  网络热词多义性强（「致敬」「接」都是正常词），先验给低。

三档决策（阈值写死在 Thresholds，改前先读 README）：
    score >= 0.62            → replace      替换
    0.40 <= score < 0.62     → keep_suggest 保留原文 + 提示候选（交给人工/上层）
    score <  0.40            → keep         保留原文，不打扰

纯标准库实现，无第三方依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------- 配置

#: 分类先验：这个分类「听到就该怀疑听错了」的基准可信度
CATEGORY_PRIOR = {
    "person": 0.55,   # 人名：专有名词、ASR 高频错误，但仍有同名歧义
    "book": 0.60,     # 书名：专有名词，歧义更少
    "movie": 0.62,    # 影视名：专有名词，歧义最少
    "hotword": 0.45,  # 热词：多义性最强（致敬 / 接 / 拼好饭 都是正常词）
}

#: 分类领域关键词（strong = 强证据，weak = 弱证据）
CATEGORY_KEYWORDS = {
    "person": {
        "strong": ("主播", "直播间", "博主", "网红", "UP主", "up主", "粉丝",
                   "观众", "连麦", "榜一", "打赏", "解说", "老师"),
        "weak": ("直播", "视频", "账号", "微博", "抖音", "B站", "b站", "发布", "更新", "带货"),
    },
    "movie": {
        "strong": ("电影", "电视剧", "影院", "电影院", "追剧", "影视", "番剧", "动漫",
                   "动画", "剧组", "票房", "上映", "豆瓣", "剧情", "主角", "演员",
                   "导演", "结局", "剧场版", "第二季", "全集", "预告"),
        "weak": ("看", "追", "刷", "角色", "片", "剧", "剪辑"),
    },
    "book": {
        "strong": ("小说", "网文", "出版社", "作者", "章节", "文学", "名著", "电子书"),
        "weak": ("书", "读", "出版", "卷", "译本", "看"),
    },
    "hotword": {
        "strong": ("梗", "热梗", "玩梗", "弹幕", "出圈", "爆火", "网络用语", "流行语"),
        "weak": ("网友", "评论区", "短视频", "直播", "流行"),
    },
}

#: context_tags → 领域关键词。条目自带标签比分类更精准，命中即强证据
TAG_KEYWORDS = {
    "game": ("游戏", "电竞", "排位", "上分", "开黑", "段位", "副本", "皮肤", "赛季",
             "服务器", "端游", "手游", "主机", "Steam", "steam", "通关", "Boss",
             "boss", "装备", "升级", "打野", "抽卡", "玩", "开黑"),
    "livestream": ("直播间", "主播", "弹幕", "礼物", "上票", "连麦", "带货", "榜"),
    "anime": ("番剧", "动漫", "二次元", "追番", "声优", "漫画"),
    "film": ("演员", "导演", "剧组", "票房", "上映", "影视", "电影"),
    "book": ("小说", "作者", "出版", "网文", "文学", "读"),
}

#: 动作动词：出现在候选词附近，说明后面多半跟一个「对象」（游戏/作品/人名）
DOMAIN_VERBS = ("玩", "打", "看", "追", "读", "刷", "推荐", "通关", "播", "下载", "安装")

#: 通用搭配：命中说明候选词在这句话里被当作**普通词**用，不该当专有名词替换
GENERIC_RIGHT_MARKERS = (
    "的等待", "的爱情", "的人生", "的时光", "的感觉", "的时候", "的日子", "的岁月",
    "的青春", "的承诺", "的誓言", "的旅程", "的态度", "的生活", "的东西", "的样子",
    "的地方", "的方式", "的心情", "的故事",
)
GENERIC_LEFT_MARKERS = ("很", "非常", "特别", "挺", "太", "十分", "极其")

#: 决策阈值
THRESHOLD_REPLACE = 0.62
THRESHOLD_SUGGEST = 0.40

WEIGHTS = {"prior": 0.15, "similarity": 0.25, "context": 0.40, "fluency": 0.20}


# ---------------------------------------------------------------- 数据结构

@dataclass
class ScoreBreakdown:
    """一次评分的全部中间量——必须可解释，方便人工复核和调参。"""

    alias: str
    canonical: str
    category: str
    score: float
    decision: str                       # replace / keep_suggest / keep
    prior: float = 0.0
    similarity: float = 0.0
    context: float = 0.0
    fluency: float = 0.0
    ambiguity: float = 1.0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "alias": self.alias,
            "canonical": self.canonical,
            "category": self.category,
            "score": round(self.score, 4),
            "decision": self.decision,
            "breakdown": {
                "prior": round(self.prior, 4),
                "similarity": round(self.similarity, 4),
                "context": round(self.context, 4),
                "fluency": round(self.fluency, 4),
                "ambiguity": round(self.ambiguity, 4),
            },
            "reasons": list(self.reasons),
        }
        return d


@dataclass
class DocumentProfile:
    """
    整篇文稿的领域画像。

    直播里「这场在聊什么」是强先验：哪怕某一句本身没关键词，
    只要通篇都在聊游戏，那句里的游戏名听错的概率也更高。
    """

    _scores: dict = field(default_factory=dict)

    @classmethod
    def from_text(cls, text: str, keys) -> "DocumentProfile":
        scores: dict[str, float] = {}
        for key in set(keys):
            hits = cls._count_hits(text, key)
            if hits:
                scores[key] = min(1.0, hits)
        return cls(_scores=scores)

    @staticmethod
    def _count_hits(text: str, key: str) -> float:
        strong = weak = 0
        if key in CATEGORY_KEYWORDS:
            kw = CATEGORY_KEYWORDS[key]
            strong = sum(text.count(k) for k in kw.get("strong", ()))
            weak = sum(text.count(k) for k in kw.get("weak", ()))
        if key in TAG_KEYWORDS:
            strong += sum(text.count(k) for k in TAG_KEYWORDS[key])
        return 0.5 * strong + 0.25 * weak

    def strength(self, keys) -> float:
        if not self._scores:
            return 0.0
        vals = [self._scores.get(k, 0.0) for k in keys]
        return max(vals) if vals else 0.0


# ---------------------------------------------------------------- 基础算法

def levenshtein(a: str, b: str) -> int:
    """标准编辑距离（中文按字），带长度差剪枝。"""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max(la, lb):
        return max(la, lb)
    if la < lb:
        a, b, la, lb = b, a, lb, la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i]
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[lb]


def form_similarity(alias: str, canonical: str) -> float:
    """
    字形/字音相似度（0~1）。

    - 编辑距离：同音替换通常只差 1~2 个字
    - 字符集合重合：ASR 错字几乎总保留部分原字
    - 长度比：长度一致更像「同音替换」而不是「另一个词」
    """
    if not alias or not canonical:
        return 0.0
    if alias == canonical:
        return 1.0
    maxlen = max(len(alias), len(canonical))
    lev_sim = 1.0 - levenshtein(alias, canonical) / maxlen
    set_a, set_c = set(alias), set(canonical)
    union = set_a | set_c
    overlap = len(set_a & set_c) / len(union) if union else 0.0
    minlen, maxlen2 = min(len(alias), len(canonical)), max(len(alias), len(canonical))
    len_ratio = minlen / maxlen2 if maxlen2 else 0.0
    return max(0.0, min(1.0, 0.5 * lev_sim + 0.3 * overlap + 0.2 * len_ratio))


# ---------------------------------------------------------------- 各维度评分

def prior_score(category: str) -> float:
    return CATEGORY_PRIOR.get(category, 0.45)


def _keyword_hits(sentence: str, keywords, span=None) -> list[str]:
    """
    在句子里找关键词命中，但**排除与候选词区间重合的那些**。

    这是关键的一条防线：候选词自己的字不能拿来当「上下文证据」。
    实例：候选「王博」+ 右侧「主测评」拼出了「博主」，
    而「博主」正是人物的强语境词 → 候选词自己给自己作证，把「王博主测评」
    误判成了「王勃主测评」。
    """
    hits: list[str] = []
    for kw in keywords:
        pos = sentence.find(kw)
        while pos != -1:
            end = pos + len(kw)
            if span is None or end <= span[0] or pos >= span[1]:
                hits.append(kw)
                break                       # 同一个词只算一次（保持旧语义）
            pos = sentence.find(kw, pos + 1)
    return hits


def context_score(entry, sentence: str, doc: DocumentProfile | None,
                  span=None, consistent: bool = False) -> tuple[float, list[str]]:
    """上下文匹配（0~1）。返回 (分数, 命中的证据)。

    span       —— 候选词在句子里的 (起, 止) 相对位置；命中区间与它重合的关键词会被剔除。
    consistent —— 文档级一致性证据成立（见 corrector._apply_consistency）。
                  成立时等同于一次「分类强语境命中」：同一场直播里同一个名字
                  已经出现过正确写法，ASR 再写成另一种是听错，不是另一个人。
    """
    reasons: list[str] = []
    local = 0.0

    if consistent:
        local = min(1.0, local + 0.60)
        reasons.append(
            f"文档级一致性：标准词『{entry.canonical}』的写法已在本篇被确认，"
            f"同一写法不应两种结果"
        )

    kw = CATEGORY_KEYWORDS.get(entry.category, {})
    s_hits = _keyword_hits(sentence, kw.get("strong", ()), span)
    w_hits = _keyword_hits(sentence, kw.get("weak", ()), span)
    # 用 max 而不是直接赋值：证据只增不减，弱线索不能把一致性加成覆盖掉
    if s_hits:
        local = max(local, min(1.0, 0.6 + 0.15 * (len(s_hits) - 1)))
        reasons.append(f"分类强语境命中：{'/'.join(s_hits[:3])}")
    elif w_hits:
        local = max(local, 0.30)
        reasons.append(f"分类弱语境命中：{'/'.join(w_hits[:3])}")

    tag_hits: list[str] = []
    for tag in entry.context_tags:
        tag_hits.extend(_keyword_hits(sentence, TAG_KEYWORDS.get(tag, ()), span))
    if tag_hits:
        local = min(1.0, local + 0.60 + 0.10 * (len(tag_hits) - 1))
        reasons.append(f"条目领域标签命中：{'/'.join(sorted(set(tag_hits))[:3])}")

    doc_boost = 0.0
    if doc is not None:
        keys = list(entry.context_tags) + [entry.category]
        strength = doc.strength(keys)
        if strength > 0:
            doc_boost = 0.35 * strength
            reasons.append(f"全文领域倾向加成（{strength:.2f}）")

    if not local and not doc_boost:
        reasons.append("无任何领域语境线索")

    return max(0.0, min(1.0, local + doc_boost)), reasons


def fluency_score(alias: str, canonical: str, left: str, right: str) -> tuple[float, list[str]]:
    """
    替换后的通顺度（0~1）——离线无语言模型，用可解释的启发式：

    - 基准 0.55
    - 相邻有动作动词（玩/看/追/读…）→ +0.15，后面多半接一个「对象」
    - 边界干净（紧邻标点/换行/句首句尾）→ +0.15
    - 右侧命中通用搭配（的等待/的爱情…）→ -0.35，说明被当普通词用
    - 左侧是程度副词（很/非常/挺…）→ -0.20，说明被当形容词用
    """
    reasons: list[str] = []
    score = 0.55

    if any(v and v in left[-3:] for v in DOMAIN_VERBS):
        score += 0.15
        reasons.append("紧邻动作动词，后面更像一个对象名词")
    if any(left.endswith(p) or left == "" or right == "" or right.startswith(p)
           for p in ("，", "。", "！", "？", "、", "；", " ", "\n")):
        score += 0.15
        reasons.append("候选词处于分句/标点边界，替换不会破坏词组")

    if any(m in right[:3] for m in GENERIC_RIGHT_MARKERS):
        score -= 0.35
        reasons.append("后接通用抽象搭配，此处更像普通词而非专有名词")
    if any(left.endswith(m) for m in GENERIC_LEFT_MARKERS):
        score -= 0.20
        reasons.append("前面是程度副词，此处更像形容词用法")

    return max(0.0, min(1.0, score)), reasons


def ambiguity_factor(alias: str, entry, alias_owners: int, alias_is_canonical: bool) -> tuple[float, list[str]]:
    """
    歧义系数（0~1，越小越可疑）。多义词是暴力替换最大的坑，这里显式打折。
    """
    reasons: list[str] = []
    factor = 1.0

    if alias_owners > 1:
        factor *= 0.65
        reasons.append(f"该写法同时是 {alias_owners} 个标准词的候选，多义风险高")
    if alias_is_canonical:
        factor *= 0.70
        reasons.append("该写法本身也是另一词条的标准词，替换会破坏原词")
    if len(alias) <= 2:
        factor *= 0.90
        reasons.append("候选词过短，误伤面大")
    if entry.priority <= 0:
        factor *= 0.95
        reasons.append("词条优先级最低")

    return max(0.4, factor), reasons


# ---------------------------------------------------------------- 主入口

def score_candidate(
    alias: str,
    entry,
    sentence: str,
    left: str,
    right: str,
    doc: DocumentProfile | None = None,
    alias_owners: int = 1,
    alias_is_canonical: bool = False,
    span: tuple[int, int] | None = None,
    consistent: bool = False,
) -> ScoreBreakdown:
    """对单个候选打分并给出三档决策。

    span       —— 候选词在 sentence 里的 (起, 止)。传入后，与候选区间重合的
                  关键词命中会被剔除，杜绝「候选自己给自己作证」。
    consistent —— 文档级一致性证据是否成立（整篇层面的证据，不是句子层面的）。
    """
    prior = prior_score(entry.category)
    sim = form_similarity(alias, entry.canonical)
    ctx, ctx_reasons = context_score(entry, sentence, doc, span, consistent)
    flu, flu_reasons = fluency_score(alias, entry.canonical, left, right)
    amb, amb_reasons = ambiguity_factor(alias, entry, alias_owners, alias_is_canonical)

    raw = (
        WEIGHTS["prior"] * prior
        + WEIGHTS["similarity"] * sim
        + WEIGHTS["context"] * ctx
        + WEIGHTS["fluency"] * flu
    )
    score = max(0.0, min(1.0, raw * amb))

    if score >= THRESHOLD_REPLACE:
        decision = "replace"
    elif score >= THRESHOLD_SUGGEST:
        decision = "keep_suggest"
    else:
        decision = "keep"

    reasons = ctx_reasons + flu_reasons + amb_reasons
    if decision == "replace":
        reasons.append(f"综合置信度 {score:.2f} ≥ {THRESHOLD_REPLACE}，判定为听错")
    elif decision == "keep_suggest":
        reasons.append(f"综合置信度 {score:.2f} 处于灰区，保留原文并提示候选")
    else:
        reasons.append(f"综合置信度 {score:.2f} < {THRESHOLD_SUGGEST}，保留原文")

    return ScoreBreakdown(
        alias=alias,
        canonical=entry.canonical,
        category=entry.category,
        score=score,
        decision=decision,
        prior=prior,
        similarity=sim,
        context=ctx,
        fluency=flu,
        ambiguity=amb,
        reasons=reasons,
    )
