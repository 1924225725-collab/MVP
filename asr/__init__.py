# ============================================================
# asr 模块的“总入口” —— 工厂函数
# ============================================================
# 别的代码（比如 main.py）只需要：
#     recognizer = create_recognizer()
#     segments = recognizer.transcribe("audio/xxx.mp3")
# 完全不需要关心背后是本地模型还是云端 API。
# ============================================================

import config
from .base import Segment  # noqa: F401  （方便外部统一从这里导入）
from .local_whisper import LocalWhisperRecognizer
from .cloud_api import CloudApiRecognizer


def create_recognizer():
    """根据 config.py 里的 ASR_BACKEND 设置，造出对应的识别器。"""

    if config.ASR_BACKEND == "local":
        recognizer = LocalWhisperRecognizer(model_size=config.WHISPER_MODEL_SIZE)

    elif config.ASR_BACKEND == "api":
        # getattr：如果 config.py 里没定义这两项，就用空字符串，不会崩
        recognizer = CloudApiRecognizer(
            api_key=getattr(config, "API_KEY", ""),
            provider=getattr(config, "API_PROVIDER", ""),
        )

    else:
        raise ValueError(
            f'config.py 里的 ASR_BACKEND 写错了："{config.ASR_BACKEND}"，'
            f'只能是 "local" 或 "api"'
        )

    print(f"语音识别方式：{recognizer.name}")
    return recognizer
