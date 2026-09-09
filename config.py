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

# ---------------- v0.3.2：评分体系 v3 + 五级分级 ----------------
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
SCORE_V3_WEIGHTS = {
    "hook": 30,
    "contrast": 25,
    "persona": 20,
    "standalone": 15,
    "completeness": 10,
}

# 高光三类型（提示词按类型换评分标准，见 prompt_builder.py）
HIGHLIGHT_TYPES = ["事件型", "情绪型", "梗型"]

# 终审分级线（final_score 由五维加权得出，1-10）：
#   S >= 9.0 爆款候选；A >= 8.0 强推荐（适合正式切片）；
#   B >= 6.0 测试素材（有潜力，需人工判断）；C >= 5.0 备用素材；D < 5.0 淘汰
GRADE_S_SCORE = 9.0
GRADE_A_SCORE = 8.0
GRADE_B_SCORE = 6.0
GRADE_C_SCORE = 5.0

# 「不值得剪」负面清单（DECISIONS.md D-023）：
#   AI 复审时若命中以下任一规则（填进 negative_flags），
#   本地强制把该候选封顶为 B 级——进不了 S/A，杜绝「事故 = 高光」。
#   （普通失误除非产生巨大反差或主播反应极强，由 AI 判断是否豁免）
NEGATIVE_RULES = ["普通失误", "普通展示", "单纯惊讶", "依赖上下文", "普通评价"]
# 命中负面清单后的最高等级（B = 测试素材，可看但 AI 不背书）
NEGATIVE_RULE_CAP_GRADE = "B"

# 零输出禁令：所有候选都低于 C 线时，只要最高分 >= 4，
# 强制保留最佳候选为 C 级（标 forced_keep），供用户自己判断
FORCED_KEEP_MIN_SCORE = 4.0

# 漏检质检（复审前置的独立角色）：最多重扫几个区块（防成本失控）
MISS_CHECK_MAX_CHUNKS = 3
# 质检调用的输出上限（只吐 chunk 编号 + 理由，用不了多少）
MISS_CHECK_OUTPUT_TOKENS = 800

# 数量三模式
QUANTITY_MODES = ["自动精选", "候选池", "自定义数量"]
QUANTITY_MODE_DEFAULT = "自动精选"
DEFAULT_CUSTOM_COUNT = 10  # 自定义数量模式的默认个数

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
