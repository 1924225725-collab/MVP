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
