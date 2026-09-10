# ============================================================
# asr/registry.py —— ASR Provider 注册表
#
# 业务层只问这里要 provider，不认识具体引擎：
#     provider = build_provider("local-faster-whisper", model_path=...)
#     segments = provider.transcribe(audio_path)
#
# 新增引擎 = 写一个 AsrProvider 子类 + 在这里注册一行，别处不用改。
# ============================================================

from errors import ProcessError, STAGE_DEPENDENCY

from .provider import (
    AsrProvider,
    CloudAsrProvider,
    FasterWhisperProvider,
    TwoPassProvider,
)

DEFAULT_PROVIDER_ID = FasterWhisperProvider.id   # 本期默认（也是唯一真正可用的）

_PROVIDERS = {
    FasterWhisperProvider.id: FasterWhisperProvider,
    CloudAsrProvider.id: CloudAsrProvider,
    TwoPassProvider.id: TwoPassProvider,
}


def provider_ids() -> list:
    return list(_PROVIDERS)


def get_provider_class(provider_id: str):
    cls = _PROVIDERS.get(provider_id)
    if cls is None:
        raise ProcessError(
            STAGE_DEPENDENCY,
            f"未知的语音识别引擎：{provider_id}",
            f"可选：{provider_ids()}",
        )
    return cls


def build_provider(provider_id: str = None, **kwargs) -> AsrProvider:
    """按 id 造一个 provider（不会自动加载模型，需要时再 prepare()）。"""
    return get_provider_class(provider_id or DEFAULT_PROVIDER_ID)(**kwargs)


def list_providers() -> list:
    """列出所有引擎及其当前可用状态（供「设置 → 语音识别引擎」显示）。"""
    out = []
    for pid, cls in _PROVIDERS.items():
        try:
            inst = cls()
            ok, reason = inst.is_available()
        except ProcessError as e:          # 构造都失败也不能崩
            inst, ok, reason = None, False, str(e)
        info = inst.info() if inst is not None else {"id": pid, "name": pid,
                                                     "kind": "", "description": ""}
        info.update({"available": bool(ok), "reason": reason,
                     "default": pid == DEFAULT_PROVIDER_ID})
        out.append(info)
    return out
