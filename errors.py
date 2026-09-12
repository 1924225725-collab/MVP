# ============================================================
# errors.py —— 全项目统一的「可分类错误」（V0.4.5）
#
# 【为什么需要它】（严重问题记录）
#   以前 pipeline 失败只 `return None`，ui.py 把所有失败都显示成同一句
#   「视频处理失败，请换一个文件试试」。
#   结果：正常视频也走进了失败分支——真因是**加载本地 Whisper 模型时会联网校验**，
#   本机网络走代理返回 502 Bad Gateway，模型加载抛异常被统一 catch 掉；
#   而「没有音轨」「文件损坏」「模型未安装」也全部显示成同一句话，
#   用户无法知道到底哪一层坏了，开发者也拿不到 traceback。
#
# 【做法】
#   每一层抛出带 stage 的 ProcessError；UI 按 stage 给出不同提示，
#   开发者视图保留完整 traceback 与原始日志（不吞底层异常）。
#
# 【边界】
#   只增加错误分类与提示，**不改任何 ASR 架构、不改流水线阶段划分**。
# ============================================================

# ---- stage 常量（UI 的错误映射以这些为 key） ----
STAGE_DEPENDENCY = "dependency"              # 缺少依赖库（faster-whisper 等）
STAGE_FFMPEG = "ffmpeg_missing"              # 找不到 ffmpeg
STAGE_MEDIA_UNREADABLE = "media_unreadable"  # 文件损坏 / 无法读取
STAGE_NO_AUDIO = "no_audio_track"            # 文件能读，但没有音轨
STAGE_AUDIO_EXTRACT = "audio_extract"        # FFmpeg 提取音频失败
STAGE_MODEL_MISSING = "model_missing"        # 本地模型未安装（缓存里没有）
STAGE_MODEL_LOAD = "model_load"              # 模型加载失败
STAGE_ASR_INFERENCE = "asr_inference"        # ASR 推理失败
STAGE_ASR_EMPTY = "asr_empty"                # 识别跑通但没内容（静音/无人声）
STAGE_PERMISSION = "permission"              # 文件/目录没权限（写不进去、删不掉）
STAGE_CONFIG = "config"                      # 配置或参数写错了
STAGE_UNKNOWN = "unknown"                    # 未归类


class ProcessError(Exception):
    """带分类的处理错误。

    stage   —— 出错在哪一层（见上面常量），UI 用它决定提示文案
    message —— 给人看的一句话
    detail  —— 原始错误 / stderr 尾巴（开发者视图显示，不进普通提示）
    """

    def __init__(self, stage, message, detail=""):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.detail = detail

    def __str__(self):
        return self.message
