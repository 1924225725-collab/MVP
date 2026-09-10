# ============================================================
# AI 直播切片助手 —— 配置面板
# 想改行为，改这里，不用动业务代码
# ============================================================

# ---------------- 语音识别（阶段一） ----------------
ASR_BACKEND = "local"          # "local" = 本地 Whisper；"api" = 云端接口（暂未实现）
WHISPER_MODEL_SIZE = "small"   # 本地模型大小：tiny / base / small / medium / large

# ---------------- DeepSeek 高光分析（阶段二） ----------------
DEEPSEEK_MODEL = "deepseek-chat"   # DeepSeek 的主力对话模型

# --- 成本控制（4 道闸门） ---
# 闸门 1：发给 AI 的文字稿最大字数，超出就截断（防止超长直播把钱包掏空）
MAX_TRANSCRIPT_CHARS = 6000
# 闸门 2：限制 AI 最多输出多少 token（高光列表撑死用不了 1500）
MAX_OUTPUT_TOKENS = 1500

# --- 成本估算价格表（单位：元 / 百万 token） ---
# ⚠️ 价格以 DeepSeek 官网为准，会不定期调整，改这里就能更新估算
PRICE_INPUT_PER_MTOKEN = 2.0
PRICE_OUTPUT_PER_MTOKEN = 8.0

# ---------------- v0.3 阶段 1：本地分析层（零成本） ----------------
# 直播类型默认值（可选类型见 analysis/event_scanner.py 的 LEXICONS）
LIVE_TYPE_DEFAULT = "娱乐聊天"

# 候选信号扫描：每多少秒打一格分
BUCKET_SECONDS = 60
# 一格（每分钟）的信号分达到多少算「热区」
# 当前 2 分 = 至少 1 个强信号词（强词 1 个顶 2 分），或 2 个普通信号词
HOT_BUCKET_SCORE = 2

# 智能分区：热区每片最长（秒）——细切，AI 看得仔细
HOT_CHUNK_SECONDS = 180
# 智能分区：普通区每片最长（秒）——粗切，省 token
NORMAL_CHUNK_SECONDS = 600
# 热区中间允许的短暂冷场（分钟）：不超过这个数的冷场不打断热区
BRIDGE_MINUTES = 2

# 用户专属词库文件名（放项目根目录，一行一个词，# 开头是注释）
USER_LEXICON_FILE = "user_lexicon.txt"

# ---------------- v0.3 阶段 2：AI 海选 + 复审 ----------------
# 注意：UI 一律不显示 token 数字，只显示模式名和 desc 描述（用户只关心效果/速度/价格）
#
# Token 三模式：
#   budget                  这一场分析的总 token 预算（估算值，超了自动三级降级）
#   max_candidates_per_chunk 海选时每个区块最多吐几个候选
TOKEN_MODES = {
    "快速": {"budget": 10000, "max_candidates_per_chunk": 2,
             "desc": "成本低、速度快，适合先粗测一遍"},
    "标准": {"budget": 20000, "max_candidates_per_chunk": 3,
             "desc": "默认模式，效果和成本均衡"},
    "精细": {"budget": 80000, "max_candidates_per_chunk": 3,
             "desc": "长直播 / 精挑细选用，成本最高"},
}
TOKEN_MODE_DEFAULT = "标准"

# ---------------- v0.4 步骤 3：100 分制 + 上下文窗口 + 动态时长 ----------------
# 从这一步起，复审的评审对象是「完整事件」（step 2 事件聚合的产物），
# 复审从「一次调用审完所有事件」改成分批（每批控制事件数与上下文，防止
# 单次 prompt 过大、后半段事件被忽略、前半段偏置）。
#
# 评分制升级为 100 分制（需求五/六）：
#   复审 AI 仍只输出五维子分（1-10 整数，AI 不自由发挥总分），
#   本地把五维子分按权重加权后 ×10 得到 0-100 的总分 —— 可解释、可审计。
#   对外四档：S 90~100 / A 80~89 / B 60~79 / C 0~59；
#   D 仅作为「内部淘汰标记」，不再作为对外展示档（C 即最低对外档）。
# ---------------- 评分体系 v3 + 分级（历史注释，保留到 v0.3.2） ----------------
# 判断视角转变（DECISIONS.md D-022）：AI 不是「直播总结助手」，
# 而是「短视频运营剪辑师」——每个候选先回答一个问题：
#   一个不了解主播的新用户刷到这个片段，为什么会停下来？
#
# 评分模型 v3：复审时 AI 只输出五个维度的子分（1-10），
# final_score 由本地按下面权重加权算出（可解释、可审计，
# 也防止 AI「先给理由再顺手打个高分」）。

# 五维权重（加起来 100）：
#   hook(三秒吸引力) 最高 —— 标题 + 开头 3 秒留不留得住陌生用户
#   contrast(反差/意外) —— 以为 A 结果 B、高期待低结果、认知冲突
#   persona(人物表现力) —— 主播独特反应 / 经典表达 / 夸张情绪
#   standalone(独立成片) —— 不靠直播上下文，陌生人能看懂
#   completeness(事件完整度) —— 开始 → 过程 → 结果
# 注意：内部键用 persona（不是 personality）。AI 输出协议层会把 personality 认作
# persona 的别名（见 prompt_builder + _parse_review_reply），保证全链路键名统一。
SCORE_V3_WEIGHTS = {
    "hook": 30,
    "contrast": 25,
    "persona": 20,
    "standalone": 15,
    "completeness": 10,
}

# 高光三类型（提示词按类型换评分标准，见 prompt_builder.py）
HIGHLIGHT_TYPES = ["事件型", "情绪型", "梗型"]

# 终审分级线（v0.4 步骤 3 起 final_score 是 0-100 整数，由五维加权 ×10 得出）：
#   S >= 90 爆款候选（必剪）；A >= 80 强推荐（强烈推荐剪成正式切片）；
#   B >= 60 值得测试（有潜力，需人工判断）；C >= 50 备用素材（对外最低档）；
#   D < 50 内部淘汰标记（进 rejected，不进对外展示）。
# 100 分制阈值 = 原 1-10 制阈值 ×10，语义完全同构，改动最小且不回退。
GRADE_S_SCORE = 90
GRADE_A_SCORE = 80
GRADE_B_SCORE = 60
GRADE_C_SCORE = 50
# 对外展示文案（V0.4.3，D-044）：
# 内部 grade 仍是 S/A/B/C/D（评分体系不变，D-022 不动），但**界面不再露出字母**——
# 用户看到「B / C」会误以为「不值得剪」，从而错过好内容。
# 因此展示层把五档「模糊化」成两档 + 隐藏：
#   S / A  → 高光内容（全场最值得看的一类）
#   B / C  → 有看点（同样有内容、有观看价值，只是系统不替用户排先后）
#   D      → 界面不展示（仅开发者视图保留原始 grade，供排查）
GRADE_UI = {
    "S": "🌟 高光内容",
    "A": "🌟 高光内容",
    "B": "✨ 有看点",
    "C": "✨ 有看点",
    "D": "",              # 空 = 普通界面不显示评级徽章
}
# 内部排序用（不展示给用户，仅用于列表次序）
GRADE_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}

# 「不值得剪」负面清单（DECISIONS.md D-023）：
#   AI 复审时若命中以下任一规则（填进 negative_flags），
#   本地强制把该候选封顶为 B 级——进不了 S/A，杜绝「事故 = 高光」。
#   （普通失误除非产生巨大反差或主播反应极强，由 AI 判断是否豁免）
#   负面过滤作用于「完整事件」而非单个瞬间：事件里某一刻普通，
#   不因此把整件事判掉（见 D-037）。
NEGATIVE_RULES = ["普通失误", "普通展示", "单纯惊讶", "依赖上下文", "普通评价"]
# 命中负面清单后的最高等级（B = 测试素材，可看但 AI 不背书）
NEGATIVE_RULE_CAP_GRADE = "B"

# v0.4 A3：复审「不值得剪」的四类原因（AI 在 reject_reason_kind 里填）
# 只有 truly_low_value 才算真淘汰；其余三种不能因「AI 不确定/事件不完整/上下文不够」
# 直接判 D——应降为 C 档供人工复核（召回优先，宁可多给人看，不把困惑当低价值）。
REJECT_KINDS = ["truly_low_value", "context_insufficient",
                "event_incomplete", "ai_uncertain"]

# 零输出禁令（100 分制）：所有候选都低于 C 线时，只要最高分 >= 50×0.8=40，
# 强制保留最佳候选为 C 级（标 forced_keep），供用户自己判断
FORCED_KEEP_MIN_SCORE = 40.0

# 漏检质检（复审前置的独立角色）：最多重扫几个区块（防成本失控）
MISS_CHECK_MAX_CHUNKS = 3
# 质检调用的输出上限（只吐 chunk 编号 + 理由，用不了多少）
MISS_CHECK_OUTPUT_TOKENS = 800

# 数量三模式
QUANTITY_MODES = ["自动精选", "候选池", "自定义数量"]
QUANTITY_MODE_DEFAULT = "自动精选"
DEFAULT_CUSTOM_COUNT = 10  # 自定义数量模式的默认个数

# ---------------- V0.4.2：评分/评级 与 推荐剪辑 解耦（DECISIONS.md D-041） ----------------
# 设计原则：
#   评分/评级（grade / score）—— 只描述「内容质量」，由五维加权本地定级，不掺产品策略。
#   推荐剪辑（recommended）—— 产品层的筛选结果：从高质量内容里挑出「这场最值得先看/先剪」的。
# 两者解耦后：一个 B 级片段可以在 A 不足时进入推荐；一个 A 级片段也可能因数量控制不入选。
#
# 自动精选模式的推荐策略：A 优先 → A 不足用高质量 B 补位 → 连 B 都没有时兜底少量 C。
# 目标数量服从「数量策略」，而不是简单等于「所有 A」（否则 A=0 时会输出空列表）。
AUTO_SELECT_TARGET = 8          # 自动精选的目标推荐条数（上限，不是必须凑满）
AUTO_B_FILL_MIN_SCORE = 60.0    # 自动精选从 B 补位的最低分（= B 线，低于此不补）
AUTO_C_FALLBACK_MAX = 3         # S/A/B 全无时的兜底 C 数量上限（避免 0 输出）

# 推荐层级标签（UI 用来解释「它为什么会进推荐名单」；同样不露 S/A/B/C/D 字母）
RECOMMEND_TIER_LABEL = {
    "S": "🚀 重点推荐",
    "A": "⭐ 推荐",
    "B_fill": "👌 值得一看",
    "C_fallback": "📎 备选参考",
}

# 直播类型的评分侧重（v3 视角，写进海选提示词，让 AI 按类型换脑子）
LIVE_TYPE_WEIGHTS = {
    "娱乐聊天": "主播个人表现力和反差（离谱发言/误会/突然变脸）权重最高；金句、梗是加分项",
    "游戏竞技": "关键操作的反差与高潮（极限翻盘/惊天失误/名场面）权重最高；纯聊天片段降分",
    "知识分享": "独立成片和观点反差权重最高；反常识结论、能当标题的一句话优先",
    "户外": "意外冲突和画面反差权重最高；与路人的意外互动、突发事件是看点",
    "带货": "真实反应的反差（翻车/真香/当场打脸）和记忆点表达权重最高；纯产品参数朗读降分",
}

# 复审环节的输出上限（v0.3.2 起每个候选要输出五维子分 + 推荐/不推荐理由，量更大）
REVIEW_MAX_OUTPUT_TOKENS = 6000

# ---------------- v0.4 第一步：ASR 词库纠错 + 人工反馈（纯本地） ----------------
# 这一版先做两个「零成本、不动 AI 判断逻辑」的基础能力，
# 为后面的事件级评价铺路：输入干净了，AI 才判断得准；反馈攒下来了，将来才有得学。

# 自定义纠错词库文件名（放项目根目录）
# 格式：分类 → {错词: 正确词}，例：{"品牌": {"福岛": "伏特加"}}
# 作用：ASR 识别完之后做纯字符串替换，把主播名/游戏名/品牌/热词改对
CUSTOM_DICTIONARY_FILE = "custom_dictionary.json"

# 人工反馈文件名（放项目根目录，本地记录，不上传服务器）
# 格式：JSON 数组，每条 {clip_id, user_choice, reason, timestamp, snapshot}
FEEDBACK_FILE = "feedback.json"
# 反馈选项（未来 UI 的 👍/👎 就是这两个）
FEEDBACK_CHOICES = ["喜欢", "不喜欢"]
# 常见反馈原因（界面做成快捷选项，也允许用户自己填）
FEEDBACK_REASONS = ["太普通", "很好笑", "缺上下文", "剪辑点不对", "标题不准", "其他"]

# ---------------- v0.4 步骤 2：事件聚合层 ----------------
#
# 本地粗聚类（analysis/event_cluster.py）：
#   只负责「提出可能属于同一事件的候选分组」，**不替 AI 做决定**。
#   所有信号都是 soft（连续打分），没有任何「超过 X 秒就断开」的硬规则；
#   每个候选必定落在某一簇里，孤立候选自成一簇——本地绝不删候选。
EVENT_CLUSTER = {
    # 关联分 ≥ 这个数就连一条边（连通分量成簇）
    "merge_threshold": 0.42,
    # 时间距离的 soft 窗口（秒）：间隔到 300 秒时时间分衰减到 0，不是硬切断
    "soft_time_window": 300,
    # 三个 soft 信号权重（time 时间距离 / overlap 时间重叠 / topic 主题相似）
    "weights": {"time": 0.30, "overlap": 0.25, "topic": 0.30},
    # 时间序上紧挨着（中间没有别的候选）的额外加分
    "adjacency_bonus": 0.15,
    # 主题相似是否把原文也算进去（默认只看标题+理由，原文太吵）
    "use_context_for_topic": False,
}

# AI 事件判断的上下文策略（自适应：先小窗口，故事不完整再扩大）
EVENT_JUDGE_CONTEXT = {
    "first_before": 90,        # 第一轮：簇开始往前 90 秒
    "first_after": 90,         # 第一轮：簇结束往后 90 秒
    "expand_before": 240,      # 扩大后：往前 4 分钟（需求要求 ±3~5 分钟）
    "expand_after": 240,       # 扩大后：往后 4 分钟
    "char_limit": 4000,        # 单次喂给 AI 的原文字符上限
    "max_expand_rounds": 1,    # 最多扩大几轮（控制成本）
}
# 事件判断的输出上限（每个簇只吐一个 JSON，用不了太多）
EVENT_JUDGE_MAX_OUTPUT_TOKENS = 1600

# 复审时每个「事件」带的原文上限（v0.3 是 600 字/候选；事件比单句长，
# 不给足原文 AI 看不出故事结构，所以放宽到 1200 字）
# v0.4 步骤 3 起复审上下文改为**时间窗口**（见 REVIEW_CONTEXT），这个字符上限
# 仅作为兜底保险（防止极端情况下一段原文特别长把 budget 撑爆）。
EVENT_REVIEW_CONTEXT_LIMIT = 1200

# ---------------- v0.4 步骤 3：复审上下文窗口（时间窗，与剪辑时长完全分离） ----------------
# 需求核心：Context Window（AI 为了理解事件而阅读的范围）≠ Clip Duration（最终剪辑长度）。
# 例如 AI 读了事件前后 5 分钟，但真正值得剪的只有 2 分 18 秒——context 是 5 分钟，
# recommended_duration 是 138 秒，两者绝不能互相污染。
REVIEW_CONTEXT = {
    # 复审上下文默认窗口：事件开始前/结束后各 ±60 秒（只是初始值，不是硬上限）
    "default_before": 60,
    "default_after": 60,
    # 自适应扩展阶梯：AI 判断 setup 不完整 / 事件未结束 / payoff 在窗口外 / 前后强因果
    # → 依次扩到 ±180 秒 → ±300 秒（受 REVIEW_BATCH 的字符预算控制）
    "expand_levels": [180, 300],
    # 每次复审单条 prompt 里塞给 AI 的原文字符预算（多了分批/降级，不硬截断成看不懂）
    "char_budget": 4000,
}

# ---------------- v0.4 步骤 3：分批复审 ----------------
# 一次把所有事件交给 AI 复审的坏处（需求八）：
#   单次 prompt 过大、后面的事件被忽略、前半段事件天然占便宜（前半段偏置）、
#   预算难控、失败难重试、将来难并发。
# 所以复审改成：事件 → 若干 batch → 每个 batch 独立复审 → 全局排序（Global Ranking）。
REVIEW_BATCH = {
    # 每批最多几个事件（事件数超了拆下一批；每批上下文共享 REVIEW_CONTEXT.char_budget）
    "max_events_per_batch": 3,
    # 每个事件在批内最多占用多少上下文字符（预算不足时从低优先级事件上扣）
    "max_context_per_event": 1200,
}

# AI 返回的 recommended 起止距事件边界允许的最大偏移（秒）——
# 超过说明 AI 把推荐剪辑点定位到了错误位置（实测偶发指向全场末尾），
# 按事件边界兜底。允许小偏移是合法的（往前取铺垫、往后收 payoff），>2 分钟就是错了。
RECOMMEND_MAX_DRIFT = 120

# 分批复审的输出上限（每个事件一条 JSON 评审 + 单批无整场报告 → 不需要 6000 那么大）
REVIEW_MAX_OUTPUT_TOKENS = 2000

# 整场 AI 分析报告的输出上限（基于事件精华卡，只吐四字段，量小）
REPORT_OUTPUT_TOKENS = 1200

# 全局排序时用的「事件综合分」在本地算，不分批差异；批内用同一评分标准（config 权重）。
# 前半段偏置的天然解：批次之间不做任何排序/权重差异，最后统一按 final_score 全局排。

# ---------------- v0.4 步骤 4 + V0.4.1：Chapter→Story 前置层 ----------------
# Story 是强先验（V0.4.1）：
#   · 同 Story 内候选：关联分 +0.25（强连续性，默认倾向保持同一 Event）
#   · 跨 Story 候选：关联分 -0.15（软减速，只有明确新事件证据才允许合并）
#   · __unknown__ 视为独立分群，不与任何候选合并
# Chapter/Story 仍是软边界，允许必要时跨边界取上下文。
# 失败时静默降级，不影响主流程。
#
# ⚠️ V0.4.4 修复（严重数据绑定 bug）：这里原来有一项
#   "story_file": "poc/story_segmentation_result.json"
# 那是开发阶段对**一场固定 51 分钟测试视频**跑 PoC 得到的产物，被当成生产默认数据，
# 导致换任何视频 UI 的「直播内容结构」都显示同一套 ch-01~ch-04。
# 现已删除该默认项：Chapter/Story 由主流程按当前视频现算（analysis/chapter_story.py），
# 并按 transcript 分别缓存在 cache_dir 下，**绝不跨视频复用**。
STORY_CONTEXT = {
    # 结构缓存目录（每个视频一份，见 analysis/chapter_story.py）
    "cache_dir": "structures",
    # 同 Story 内候选的强先验加分（V0.4.1 从 0.05 提升到 0.25）
    "story_bonus": 0.25,
    # 跨 Story 候选的软减速惩罚
    "cross_story_penalty": -0.15,
}

# V0.4.4：Chapter / Story 分割（主流程按视频生成）
CHAPTER_STORY = {
    "enabled": True,          # 关掉就退化成「无内容结构」，不影响其他分析结果
    "max_chapters": 8,        # Chapter 数量上限（提示词里也会告诉 AI）
    "chapter_output_tokens": 2000,
    "story_output_tokens": 2000,
    # 默认每次分析都重新生成，保证结构与本场事件严格对应；
    # 想要省钱可改成 True（仅当事件数一致时复用本视频上次的缓存）
    "reuse_cache": False,
}
