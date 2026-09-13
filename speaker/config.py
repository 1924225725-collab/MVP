# ============================================================
# speaker/config.py —— 说话人识别的配置（钥匙只从环境变量读）
# ============================================================
# 【安全约定 · 与项目 DeepSeek 一致】
#   密钥永远不写进代码 / 不提交 Git / 不打印到日志。
#   本文件只负责「去哪里读」，读到什么内容一律不外泄。
#   summary() 只返回打码后的概览，绝不返回密钥原文。
#
# ------------------------------------------------------------
# 【阿里云智能语音交互（当前主用）】
#   ALIYUN_ACCESS_KEY_ID       访问密钥 ID
#   ALIYUN_ACCESS_KEY_SECRET   访问密钥 Secret
#   ALIYUN_APP_KEY             智能语音交互控制台「项目」的 AppKey（录音文件识别必填）
#
#   可选：
#   ALIYUN_REGION_ID           区域，默认 cn-shanghai
#   ALIYUN_FILE_TRANS_HOST     录音文件识别接入点，默认 filetrans.<region>.aliyuncs.com
#   ALIYUN_SPEAKER_MAX         期望说话人上限（1~10），默认 0 = 服务端自动判断
#
# ------------------------------------------------------------
# 【火山引擎（保留，未暂停使用，勿删）】
#   VOLC_APP_ID / VOLC_ACCESS_TOKEN / VOLC_CLUSTER_ID
#   可选：VOLC_RESOURCE_ID / VOLC_SPEAKER_MAX
# ============================================================

import os

# ---- 阿里云环境变量名（勿改，对外契约）----
ENV_ALI_AK_ID = "ALIYUN_ACCESS_KEY_ID"
ENV_ALI_AK_SECRET = "ALIYUN_ACCESS_KEY_SECRET"
ENV_ALI_APP_KEY = "ALIYUN_APP_KEY"
ENV_ALI_REGION = "ALIYUN_REGION_ID"
ENV_ALI_FILE_TRANS_HOST = "ALIYUN_FILE_TRANS_HOST"
ENV_ALI_SPEAKER_MAX = "ALIYUN_SPEAKER_MAX"

# ---- 火山引擎环境变量名（保留）----
ENV_APP_ID = "VOLC_APP_ID"
ENV_ACCESS_TOKEN = "VOLC_ACCESS_TOKEN"
ENV_CLUSTER_ID = "VOLC_CLUSTER_ID"
ENV_RESOURCE_ID = "VOLC_RESOURCE_ID"
ENV_SPEAKER_MAX = "VOLC_SPEAKER_MAX"

# ---- 默认值 ----
DEFAULT_RESOURCE_ID = "volc.seedasr.auc"     # 豆包录音文件识别模型 2.0
DEFAULT_ALI_REGION = "cn-shanghai"           # 阿里云区域
DEFAULT_ALI_FILE_TRANS_HOST = "filetrans.cn-shanghai.aliyuncs.com"
ALI_API_VERSION = "2018-08-17"               # 录音文件识别 OpenAPI 版本
SPEAKER_HARD_MAX = 10                         # 说话人分离硬上限


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default


# ============================================================
# 阿里云
# ============================================================

def get_aliyun_access_key_id() -> str:
    return _env(ENV_ALI_AK_ID)


def get_aliyun_access_key_secret() -> str:
    return _env(ENV_ALI_AK_SECRET)


def get_aliyun_app_key() -> str:
    """智能语音交互控制台「项目」的 AppKey。录音文件识别必填。"""
    return _env(ENV_ALI_APP_KEY)


def get_aliyun_region() -> str:
    return _env(ENV_ALI_REGION, DEFAULT_ALI_REGION)


def derive_aliyun_file_trans_host(region_id: str = None) -> str:
    """按 region 推导录音文件识别的接入点域名。

    优先尊重显式传入的 region_id；没有则回落到环境配置的 region。
    """
    region = (region_id or "").strip() or get_aliyun_region()
    return f"filetrans.{region}.aliyuncs.com"


def get_aliyun_file_trans_host(region_id: str = None) -> str:
    """录音文件识别接入点。

    优先级：
      1. 环境变量 ALIYUN_FILE_TRANS_HOST（显式指定，最高优先）
      2. 传入 region_id 推导
      3. 环境配置的 region 推导
    """
    host = _env(ENV_ALI_FILE_TRANS_HOST)
    if host:
        return host
    return derive_aliyun_file_trans_host(region_id)


def get_aliyun_speaker_max() -> int:
    return _clamp_speaker_max(_env(ENV_ALI_SPEAKER_MAX))


def aliyun_credentials_present() -> bool:
    """AK/SK 是否齐备（只报有无，绝不返回内容）。appkey 单独判定。"""
    return bool(get_aliyun_access_key_id()) and bool(get_aliyun_access_key_secret())


def aliyun_describe_missing() -> list:
    missing = []
    if not get_aliyun_access_key_id():
        missing.append(ENV_ALI_AK_ID)
    if not get_aliyun_access_key_secret():
        missing.append(ENV_ALI_AK_SECRET)
    if not get_aliyun_app_key():
        missing.append(ENV_ALI_APP_KEY)
    return missing


def aliyun_summary() -> dict:
    """阿里云配置概览（安全：密钥打码）。"""
    return {
        "access_key_id": _masked(get_aliyun_access_key_id()),
        "access_key_secret": _masked(get_aliyun_access_key_secret()),
        "app_key": _masked(get_aliyun_app_key()),
        "region_id": get_aliyun_region(),
        "file_trans_host": get_aliyun_file_trans_host(),
        "api_version": ALI_API_VERSION,
        "speaker_max": get_aliyun_speaker_max(),
        "credentials_present": aliyun_credentials_present(),
        "missing": aliyun_describe_missing(),
    }


# ============================================================
# 火山引擎（保留）
# ============================================================

def get_app_id() -> str:
    return _env(ENV_APP_ID)


def get_access_token() -> str:
    return _env(ENV_ACCESS_TOKEN)


def get_cluster_id() -> str:
    return _env(ENV_CLUSTER_ID)


def get_resource_id() -> str:
    return _env(ENV_RESOURCE_ID, DEFAULT_RESOURCE_ID)


def get_speaker_max() -> int:
    return _clamp_speaker_max(_env(ENV_SPEAKER_MAX))


def credentials_present() -> bool:
    return bool(get_app_id()) and bool(get_access_token())


def describe_missing() -> list:
    missing = []
    if not get_app_id():
        missing.append(ENV_APP_ID)
    if not get_access_token():
        missing.append(ENV_ACCESS_TOKEN)
    return missing


# ============================================================
# 通用
# ============================================================

def _clamp_speaker_max(raw: str) -> int:
    """把原始字符串规整成 0~SPEAKER_HARD_MAX 的 int；无效值返回 0。"""
    if not raw:
        return 0
    try:
        n = int(raw)
    except ValueError:
        return 0
    return max(0, min(n, SPEAKER_HARD_MAX))


def summary() -> dict:
    """全部 provider 的配置概览（安全：全部打码）。"""
    return {
        "aliyun": aliyun_summary(),
        "volcengine": {
            "app_id": _masked(get_app_id()),
            "access_token": _masked(get_access_token()),
            "cluster_id": _masked(get_cluster_id()),
            "resource_id": get_resource_id(),
            "speaker_max": get_speaker_max(),
            "credentials_present": credentials_present(),
            "missing": describe_missing(),
        },
    }


def _masked(value: str) -> str:
    """只暴露「有没有」和长度，中间打码，防止误打印泄露。"""
    if not value:
        return "(未配置)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"
