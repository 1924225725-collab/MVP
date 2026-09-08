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

    def transcribe(self, audio_path):
        # 以后实现：把音频上传/发给云端，收回结果，
        # 转成和本地一模一样的 [Segment, ...] 格式返回
        raise NotImplementedError("以后实现：云端 API 识别")
