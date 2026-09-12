# ============================================================
# 云端 API 识别器（预留的接口，以后再实现）
# ============================================================

from .base import BaseRecognizer, Segment


class CloudApiRecognizer(BaseRecognizer):
    """调用云端语音识别服务。

    优点：速度快、不吃自己电脑的性能
    代价：要注册账号拿密钥，多数按用量付费
    """

    name = "云端API"

    def __init__(self, api_key="", provider=""):
        # 以后接 API 时，从 config.py 读取密钥和服务商
        self.api_key = api_key
        self.provider = provider

    def transcribe(self, audio_path, progress=None, duration=None):
        """音频文件路径 → [Segment, ...]

        progress / duration —— V0.5.2 新增的进度上报入口（见 base.py 的说明）。
        云端引擎**预留接口**：接通后按服务端返回的进度调用 progress 即可。
        """
        # 以后实现：把音频上传/发给云端，收回结果，
        # 转成和本地一模一样的 [Segment, ...] 格式返回
        raise NotImplementedError("以后实现：云端 API 识别")
