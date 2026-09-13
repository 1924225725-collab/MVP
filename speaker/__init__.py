# ============================================================
# speaker/ —— 说话人识别（Diarization）Provider 模块
# ============================================================
# 设计目标：说话人识别可替换，且与生产流程解耦。
#
# 【统一输出格式】
#   [
#       {"start": 0, "end": 5, "speaker": "spk_0"},
#   ]
#
# 【快速上手】
#   from speaker import AliyunSpeakerProvider
#   p = AliyunSpeakerProvider()             # 从环境变量读钥匙
#   ok, why = p.is_available()
#   turns = p.diarize("https://example.com/a.mp3")         # [SpeakerTurn, ...]
#   data  = p.diarize_unified("https://example.com/a.mp3")  # list[dict]（需求格式）
#
# 【边界】
#   本模块只负责「音频 → 说话人时间段」。
#   不碰 ASR / DeepSeek 高光 / Chapter·Story·Event·Recommendation / 评分 / UI。
# ============================================================

from .base import BaseSpeakerProvider, SpeakerTurn, to_unified
from .aliyun import AliyunError, AliyunSpeakerProvider
from .volcengine import VolcengineError, VolcengineSpeakerProvider

# 已实现的 Provider 注册表（将来加 pyannote / 本地模型，在这里加一行）
_PROVIDERS = {
    AliyunSpeakerProvider.provider_id: AliyunSpeakerProvider,
    VolcengineSpeakerProvider.provider_id: VolcengineSpeakerProvider,
}

# 当前默认引擎（用户当前选定阿里云）
DEFAULT_PROVIDER_ID = AliyunSpeakerProvider.provider_id

__all__ = [
    "BaseSpeakerProvider",
    "SpeakerTurn",
    "to_unified",
    "AliyunSpeakerProvider",
    "AliyunError",
    "VolcengineSpeakerProvider",
    "VolcengineError",
    "get_provider_class",
    "build_provider",
    "list_providers",
    "provider_ids",
    "DEFAULT_PROVIDER_ID",
]


def provider_ids() -> list:
    return list(_PROVIDERS)


def get_provider_class(provider_id: str):
    cls = _PROVIDERS.get(provider_id)
    if cls is None:
        raise KeyError(f"未知的说话人识别引擎：{provider_id}；可选：{provider_ids()}")
    return cls


def build_provider(provider_id: str = None, **kwargs) -> BaseSpeakerProvider:
    """按 id 造一个 provider（不会自动联网，调用 diarize 才发请求）。"""
    return get_provider_class(provider_id or DEFAULT_PROVIDER_ID)(**kwargs)


def list_providers() -> list:
    """列出所有说话人识别引擎及当前可用状态。"""
    out = []
    for pid, cls in _PROVIDERS.items():
        try:
            inst = cls()
            ok, reason = inst.is_available()
        except Exception as e:                      # 构造失败也不能崩
            inst, ok, reason = None, False, f"{type(e).__name__}: {e}"
        info = inst.info() if inst is not None else {"provider_id": pid, "name": pid}
        info.update({"available": bool(ok), "reason": reason,
                     "default": pid == DEFAULT_PROVIDER_ID})
        out.append(info)
    return out
