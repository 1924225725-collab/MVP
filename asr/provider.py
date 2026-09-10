# ============================================================
# asr/provider.py —— ASR Provider 抽象（V0.5 桌面化）
#
# 【为什么要有这一层】
#   需求明确：Chapter / Story / Event / Highlight **不应该直接依赖 faster-whisper**。
#   现在业务层只说「给我一个 ASR Provider」，由 Provider 决定背后是本地还是云端。
#
# 【能力矩阵】
#   ASR
#   ├── LocalASR  →  FasterWhisperProvider（本次真正实现）
#   └── CloudASR  →  CloudAsrProvider（只预留接口，不接具体服务）
#
#   未来可组合：本地初步识别 + 云端二次修正（见 TwoPassProvider 占位）
#
# 【边界】
#   - Provider 只管「音频文件 → [Segment]」
#   - 不碰 Chapter/Story/Event/Highlight/评分/推荐
#   - 与 pipeline 的分层错误（errors.ProcessError）保持一致
# ============================================================

import traceback
from pathlib import Path

from errors import ProcessError, STAGE_DEPENDENCY, STAGE_MODEL_LOAD, STAGE_MODEL_MISSING

from .base import BaseRecognizer, Segment  # noqa: F401  （对外统一出口）


class AsrProvider:
    """所有 ASR Provider 的约定。"""

    id = "base"
    name = "未命名识别引擎"
    kind = "local"          # "local" | "cloud"
    description = ""

    # ---- 能力声明 ----

    def is_available(self):
        """现在能不能用？返回 (bool, 原因)。不加载模型，只做轻量检查。"""
        return False, "未实现"

    def info(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind,
                "description": self.description}

    # ---- 生命周期 ----

    def prepare(self, progress=None):
        """按需加载模型/建立连接（可能较慢）。失败抛 ProcessError。"""
        return None

    def release(self):
        """释放资源（可选）。"""
        return None

    # ---- 核心能力 ----

    def transcribe(self, audio_path):
        """音频文件路径 → [Segment, ...]。失败抛 ProcessError。"""
        raise NotImplementedError


class FasterWhisperProvider(AsrProvider):
    """本地 ASR：faster-whisper。

    model_path 给了 → 直接用该文件夹（桌面版，完全离线）；
    否则退回 model_size + HuggingFace 缓存（网页版/命令行老路径）。
    """

    id = "local-faster-whisper"
    name = "本地语音识别（faster-whisper）"
    kind = "local"
    description = "免费、离线、隐私安全；首次使用需要下载模型"

    def __init__(self, model_path=None, model_size="small"):
        self.model_path = str(model_path) if model_path else None
        self.model_size = model_size
        self._recognizer = None

    def is_available(self):
        if self.model_path:
            d = Path(self.model_path)
            if not d.is_dir():
                return False, f"模型目录不存在：{d}"
            if not (d / "model.bin").exists():
                return False, f"模型目录里没有 model.bin：{d}"
            return True, "模型已就绪（本地目录）"
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False, "缺少 faster-whisper 库"
        return True, "将按需从缓存加载模型"

    def prepare(self, progress=None):
        if self._recognizer is not None:
            return self._recognizer
        from .local_whisper import LocalWhisperRecognizer
        if progress:
            progress("加载本地语音识别模型")
        self._recognizer = LocalWhisperRecognizer(
            model_size=self.model_size, model_path=self.model_path
        )
        return self._recognizer

    def transcribe(self, audio_path):
        rec = self.prepare()
        return rec.transcribe(audio_path)

    def info(self) -> dict:
        d = super().info()
        d["model_path"] = self.model_path or ""
        d["model_size"] = self.model_size
        return d


class CloudAsrProvider(AsrProvider):
    """云端 AI 语音识别（**预留接口，本期不接具体服务**）。

    未来接入时只需要实现 transcribe()，并把配置放进 settings/模型清单；
    上层（pipeline / Chapter / Story / Event / Highlight）一行都不用改。
    """

    id = "cloud-asr"
    name = "云端语音识别（未接入）"
    kind = "cloud"
    description = "预留接口：接入云端 AI 语音识别服务后可获得更高准确率与更快速度"

    def __init__(self, api_key="", provider="", endpoint=""):
        self.api_key = api_key
        self.provider_name = provider
        self.endpoint = endpoint

    def is_available(self):
        if not self.provider_name:
            return False, "云端语音识别尚未接入具体服务"
        if not self.api_key:
            return False, "缺少云端语音识别服务的密钥"
        return False, "云端语音识别尚未接入具体服务（接口已预留）"

    def transcribe(self, audio_path):
        raise ProcessError(
            STAGE_DEPENDENCY,
            "云端语音识别尚未接入具体服务",
            "接口已预留：实现 CloudAsrProvider.transcribe() 并配置 provider/api_key 即可启用。",
        )


class TwoPassProvider(AsrProvider):
    """预留：第一遍本地识别 + 第二遍云端修正（提升长直播的人名/专名准确率）。

    组合方式的思路（未实现）：
      1. local.transcribe() 得到初稿
      2. 把初稿 + 关键片段交给云端做纠错与补全
      3. 合并结果（保持时间戳来自第一遍，文本来自第二遍）
    """

    id = "two-pass"
    name = "本地初识 + 云端修正（未接入）"
    kind = "hybrid"
    description = "预留接口：先用本地模型出初稿，再用云端模型校正文本"

    def __init__(self, local_provider=None, cloud_provider=None):
        self.local = local_provider
        self.cloud = cloud_provider

    def is_available(self):
        return False, "两遍识别尚未实现（接口已预留）"

    def transcribe(self, audio_path):
        raise ProcessError(
            STAGE_DEPENDENCY,
            "两遍识别（本地初识 + 云端修正）尚未接入",
            "接口已预留：组合 FasterWhisperProvider 与云端 provider 即可实现。",
        )
