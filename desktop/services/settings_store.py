# ============================================================
# desktop/services/settings_store.py —— 用户设置（工作区/settings.json）
#
# 【为什么不用注册表】用户数据一律落在工作区，卸载/升级不丢，也便于备份。
#
# 保存内容：
#   api_key         DeepSeek 钥匙（同时镜像到 api_key.txt，兼容命令行/网页版）
#   live_type       直播类型
#   token_mode      分析模式（快速/标准/精细）
#   quantity_mode   数量模式（自动精选/候选池/自定义数量）
#   custom_count    自定义数量
#   asr_provider    语音识别引擎 id（默认 local-faster-whisper）
#   asr_model_id    本地模型 id（空 = 用清单里的默认模型）
#
# 【容错】坏 JSON / 缺字段一律回落默认值，绝不让设置文件把程序搞崩。
# ============================================================

import json
from pathlib import Path

import app_paths

try:
    import config
    _LIVE_TYPE_DEFAULT = config.LIVE_TYPE_DEFAULT
    _TOKEN_MODE_DEFAULT = config.TOKEN_MODE_DEFAULT
    _QUANTITY_MODE_DEFAULT = config.QUANTITY_MODE_DEFAULT
    _DEFAULT_CUSTOM_COUNT = int(config.DEFAULT_CUSTOM_COUNT)
except Exception:                                   # 极端情况下也给得出默认值
    _LIVE_TYPE_DEFAULT = "娱乐聊天"
    _TOKEN_MODE_DEFAULT = "标准"
    _QUANTITY_MODE_DEFAULT = "自动精选"
    _DEFAULT_CUSTOM_COUNT = 10

DEFAULT_PROVIDER_ID = "local-faster-whisper"


def defaults() -> dict:
    return {
        "api_key": "",
        "live_type": _LIVE_TYPE_DEFAULT,
        "token_mode": _TOKEN_MODE_DEFAULT,
        "quantity_mode": _QUANTITY_MODE_DEFAULT,
        "custom_count": _DEFAULT_CUSTOM_COUNT,
        "asr_provider": DEFAULT_PROVIDER_ID,
        "asr_model_id": "",
    }


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else app_paths.settings_file()
        self._data = None

    # ---------------- 读写 ----------------

    def load(self) -> dict:
        if self._data is not None:
            return self._data
        data = defaults()
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for k in data:
                        if k in raw and raw[k] is not None:
                            data[k] = raw[k]
            except (OSError, json.JSONDecodeError):
                pass                                # 坏文件 → 用默认值，不崩
        # 兼容：以前网页版存在 api_key.txt 里的钥匙，自动接管
        if not str(data.get("api_key") or "").strip():
            kf = app_paths.api_key_file()
            if kf.exists():
                try:
                    data["api_key"] = kf.read_text(encoding="utf-8").strip()
                except OSError:
                    pass
        self._data = data
        return data

    def save(self, data: dict = None) -> Path:
        if data is not None:
            self._data = dict(data)
        cur = dict(defaults())
        cur.update(self._data or {})
        self._data = cur
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(cur, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        # 钥匙镜像到 api_key.txt，命令行 / 网页版 / 桌面版三者行为一致
        key = str(cur.get("api_key") or "").strip()
        try:
            kf = app_paths.api_key_file()
            kf.parent.mkdir(parents=True, exist_ok=True)
            kf.write_text(key, encoding="utf-8")
        except OSError:
            pass
        return self.path

    # ---------------- 便捷访问 ----------------

    def get(self, key, default=None):
        return self.load().get(key, default)

    def set(self, **kwargs):
        data = self.load()
        data.update(kwargs)
        self.save(data)
        return data

    def api_key(self) -> str:
        return str(self.load().get("api_key") or "").strip()

    def analysis_options(self) -> dict:
        """给 analyze_transcript 用的三个设置。"""
        d = self.load()
        return {
            "live_type": d.get("live_type") or _LIVE_TYPE_DEFAULT,
            "token_mode": d.get("token_mode") or _TOKEN_MODE_DEFAULT,
            "quantity_mode": d.get("quantity_mode") or _QUANTITY_MODE_DEFAULT,
            "custom_count": int(d.get("custom_count") or _DEFAULT_CUSTOM_COUNT),
        }
