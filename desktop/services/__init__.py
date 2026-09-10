# ============================================================
# desktop/services/ —— 服务层
#
# 【唯一边界】桌面 UI **只**通过这一层访问能力，绝不直接调用
# analysis / pipeline / asr。这样以后换界面框架、加云端 ASR、
# 加批处理，都不用动算法代码。
#
#   tasks.py          视频→文字稿 / 文字稿→分析结果（只编排与包装，不改算法）
#   project_store.py  每个视频一份独立项目结果（防串场，延续 V0.4.4 要求）
#   model_manager.py  本地 ASR 模型的检测 / 下载 / 校验 / 卸载（Model Registry）
#   settings_store.py 用户设置（钥匙、直播类型、分析模式、语音识别引擎）
# ============================================================

from .project_store import ProjectStore
from .settings_store import SettingsStore

__all__ = ["ProjectStore", "SettingsStore"]
