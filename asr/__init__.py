# ============================================================
# asr 模块的“总入口” —— 工厂函数
# ============================================================
# 别的代码（比如 main.py）只需要：
#     recognizer = create_recognizer()
#     segments = recognizer.transcribe("audio/xxx.mp3")
# 完全不需要关心背后是本地模型还是云端 API。
# ============================================================

import config
from errors import ProcessError, STAGE_DEPENDENCY
from .base import Segment  # noqa: F401  （方便外部统一从这里导入）
from .local_whisper import LocalWhisperRecognizer
from .cloud_api import CloudApiRecognizer


def create_recognizer():
    """根据 config.py 里的 ASR_BACKEND 设置，造出对应的识别器。

    V0.4.5：配置写错时不再抛裸 ValueError（UI 只会显示"未知错误"），
    而是抛带 stage 的 ProcessError，让界面能说清楚"是配置写错了"。
    """

    if config.ASR_BACKEND == "local":
        recognizer = LocalWhisperRecognizer(model_size=config.WHISPER_MODEL_SIZE)

    elif config.ASR_BACKEND == "api":
        # getattr：如果 config.py 里没定义这两项，就用空字符串，不会崩
        recognizer = CloudApiRecognizer(
            api_key=getattr(config, "API_KEY", ""),
            provider=getattr(config, "API_PROVIDER", ""),
        )

    else:
        raise ProcessError(
            STAGE_DEPENDENCY,
            f'config.py 里的 ASR_BACKEND 写错了："{config.ASR_BACKEND}"'
            f'，只能是 "local" 或 "api"',
            f"当前值：{config.ASR_BACKEND!r}",
        )

    print(f"语音识别方式：{recognizer.name}")
    return recognizer
