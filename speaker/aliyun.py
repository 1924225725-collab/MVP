# ============================================================
# speaker/aliyun.py —— 阿里云智能语音交互「录音文件识别」封装
# ============================================================
# 【走哪个接口】
#   录音文件识别（非实时）OpenAPI，两阶段异步：
#     1) SubmitTask    ：提交音频 URL，拿到 TaskId
#     2) GetTaskResult ：轮询 TaskId 直到 SUCCESS
#   说话人分离通过提交参数开启（见 _build_task）。
#
# 【官方文档】
#   录音文件识别：https://help.aliyun.com/zh/isi/developer-reference/api-reference-2
#   提交：POST/GET http://filetrans.<region>.aliyuncs.com/?Action=SubmitTask&Version=2018-08-17
#   查询：POST/GET http://filetrans.<region>.aliyuncs.com/?Action=GetTaskResult&Version=2018-08-17
#
# 【鉴权：RPC 风格签名（HMAC-SHA1）】
#   用 AccessKeyId / AccessKeySecret 对请求参数签名，不传 Bearer token。
#   算法（官方「签名机制」）：
#     1. 参数按 key 字典序排列，做 percent-encode 后拼成 k=v&k=v
#     2. StringToSign = "POST" + "&" + percentEncode("/") + "&" + percentEncode(canonicalQuery)
#     3. Signature = Base64(HMAC-SHA1(AccessKeySecret + "&", StringToSign))
#     4. 把 Signature 作为普通参数一起发出
#   本实现完整自包含，不依赖 aliyun SDK（减少部署依赖）。
#
# 【重要前提：音频必须是「可公网访问的 URL」】
#   该接口不吃本地文件。与火山同类，提供 upload_fn 回调钩子换 URL。
#
# 【返回统一格式】
#   [{"start": 0.0, "end": 5.0, "speaker": "spk_0"}, ...]
# ============================================================

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import uuid
from typing import Callable, List, Optional

from . import config
from .base import BaseSpeakerProvider, SpeakerTurn

try:
    import requests
except ImportError:
    requests = None

# ---- 任务状态（GetTaskResult 的 StatusText）----
STATUS_SUCCESS = "SUCCESS"
STATUS_RUNNING = "RUNNING"
STATUS_QUEUEING = "QUEUEING"
STATUS_FAILED = "FAILED"

# 轮询时视为「还没好」的状态
_PENDING_STATES = {STATUS_RUNNING, STATUS_QUEUEING}


class AliyunError(RuntimeError):
    """阿里云调用失败。消息里绝不包含 AccessKey / Secret 等敏感内容。"""


class AliyunSpeakerProvider(BaseSpeakerProvider):
    """阿里云智能语音交互 说话人分离。

    用法（音频已有公网 URL）：
        p = AliyunSpeakerProvider()
        turns = p.diarize("https://example.com/a.mp3")
        data  = p.diarize_unified("https://example.com/a.mp3")

    用法（本地文件）：
        p = AliyunSpeakerProvider(upload_fn=my_upload)
        turns = p.diarize("/path/to/a.mp3")

    环境变量：
        ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET  （必填）
        ALIYUN_APP_KEY                                   （必填，控制台项目 AppKey）
        ALIYUN_REGION_ID                （可选，默认 cn-shanghai）
        ALIYUN_FILE_TRANS_HOST          （可选，默认按 region 推导）
    """

    name = "阿里云智能语音说话人分离"
    provider_id = "aliyun"
    kind = "cloud"

    def __init__(self,
                 access_key_id: str = None,
                 access_key_secret: str = None,
                 app_key: str = None,
                 region_id: str = None,
                 host: str = None,
                 speaker_max: int = None,
                 upload_fn: Optional[Callable[[str], str]] = None,
                 timeout: int = 30,
                 poll_interval: int = 5,
                 poll_timeout: int = 1800):
        self.access_key_id = (access_key_id if access_key_id is not None
                              else config.get_aliyun_access_key_id())
        self.access_key_secret = (access_key_secret if access_key_secret is not None
                                  else config.get_aliyun_access_key_secret())
        self.app_key = app_key if app_key is not None else config.get_aliyun_app_key()
        self.region_id = region_id or config.get_aliyun_region()
        # host 未显式给出时，按「本实例的 region_id」推导（而不是环境里的 region），
        # 否则传入 region_id 会被环境配置悄悄覆盖。
        self.host = host or config.get_aliyun_file_trans_host(self.region_id)
        self.speaker_max = (speaker_max if speaker_max is not None
                            else config.get_aliyun_speaker_max())
        self.upload_fn = upload_fn
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    # ---------------- 能力声明 ----------------

    def is_available(self):
        """轻量检查：requests 在不在 + 本实例的钥匙够不够。不发网络请求。

        注意：判定依据是**实例自身的凭据**，而不是进程环境变量——
        这样显式构造的 provider（如测试/多账号场景）也能如实上报状态。
        """
        if requests is None:
            return False, "缺少 requests 库（pip install requests）"
        missing = self._describe_missing()
        if missing:
            return False, f"缺少凭据：{', '.join(missing)}"
        return True, "已配置（音频需为公网可访问 URL）"

    def _describe_missing(self) -> list:
        """本实例缺失的凭据名（只报有无，不含内容）。"""
        missing = []
        if not self.access_key_id:
            missing.append(config.ENV_ALI_AK_ID)
        if not self.access_key_secret:
            missing.append(config.ENV_ALI_AK_SECRET)
        if not self.app_key:
            missing.append(config.ENV_ALI_APP_KEY)
        return missing

    def info(self) -> dict:
        d = super().info()
        d["region_id"] = self.region_id
        d["host"] = self.host
        d["api_version"] = config.ALI_API_VERSION
        d["speaker_max"] = self.speaker_max
        d["has_upload_fn"] = self.upload_fn is not None
        d["configured"] = bool(self.access_key_id and self.access_key_secret
                               and self.app_key)
        return d

    # ---------------- 核心能力 ----------------

    def diarize(self, audio_path, **kwargs) -> List[SpeakerTurn]:
        """音频（URL 或本地路径）→ [SpeakerTurn, ...]（按 start 排序，合并相邻同人段）。

        额外参数：
          poll_interval / poll_timeout  覆盖轮询节奏
          raw_out      传 dict，函数把服务端原始响应塞进 raw_out["response"]
        """
        if requests is None:
            raise AliyunError("缺少 requests 库，请先 pip install requests")

        ok, reason = self.is_available()
        if not ok:
            raise AliyunError(f"阿里云配置不完整：{reason}")

        audio_url = self._resolve_url(audio_path)
        poll_interval = kwargs.get("poll_interval", self.poll_interval)
        poll_timeout = kwargs.get("poll_timeout", self.poll_timeout)

        task_id = self._submit(audio_url)
        response = self._poll(task_id, poll_interval, poll_timeout)

        raw_out = kwargs.get("raw_out")
        if isinstance(raw_out, dict):
            raw_out["response"] = response

        return self._merge_adjacent(self._parse_response(response))

    # ---------------- 内部：URL 解析 ----------------

    def _resolve_url(self, audio_path: str) -> str:
        if isinstance(audio_path, str) and audio_path.startswith(("http://", "https://")):
            return audio_path
        if self.upload_fn is not None:
            url = self.upload_fn(audio_path)
            if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
                raise AliyunError(
                    f"upload_fn 必须返回 http(s) URL，实际得到：{type(url)!r}")
            return url
        raise AliyunError(
            "阿里云录音文件识别只接受「公网可访问的音频 URL」，不支持本地文件。\n"
            "两种办法：\n"
            "  1) 先把音频上传到对象存储（推荐阿里云 OSS）或任意公网可访问地址，"
            "再传 URL；注意 URL 只能用域名、不能是 IP、不能含空格/中文。\n"
            "  2) 给 AliyunSpeakerProvider(upload_fn=你的上传函数) 传回调，"
            "本模块自动帮你换 URL。\n"
            f"当前传入：{audio_path!r}"
        )

    # ---------------- 内部：RPC 签名 ----------------

    @staticmethod
    def _percent_encode(s: str) -> str:
        """阿里云 RPC 签名要求的 percent-encode。

        规则：先按 UTF-8 编码，再 encode；空格 → %20（不是 +）；
        '/' → %2F；'~' 不编码；其余符合 RFC3986。
        """
        return (urllib.parse.quote(str(s), safe="~")
                .replace("+", "%20")
                .replace("*", "%2A")
                .replace("%7E", "~"))

    def _sign(self, params: dict, method: str = "POST") -> str:
        """对参数字典做 HMAC-SHA1 签名，返回 Base64 字符串。

        ⚠️ method 必须与实际发请求用的 HTTP 方法一致（签名覆盖 method），
           否则服务端会判 SignatureDoesNotMatch。
        """
        # 1. 按 key 字典序排列，拼 canonicalized query
        items = sorted(params.items())
        canonical = "&".join(
            f"{self._percent_encode(k)}={self._percent_encode(v)}" for k, v in items
        )
        # 2. StringToSign = METHOD & percentEncode("/") & percentEncode(canonical)
        string_to_sign = "&".join([
            method.upper(),
            self._percent_encode("/"),
            self._percent_encode(canonical),
        ])
        # 3. HMAC-SHA1 with key = AccessKeySecret + "&"
        key = (self.access_key_secret + "&").encode("utf-8")
        digest = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha1).digest()
        return base64.b64encode(digest).decode("utf-8")

    def _build_common_params(self, action: str) -> dict:
        """RPC 公共参数。"""
        return {
            "AccessKeyId": self.access_key_id,
            "Action": action,
            "Format": "JSON",
            "RegionId": self.region_id,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "Version": config.ALI_API_VERSION,
        }

    def _call(self, action: str, extra: dict = None) -> dict:
        """发起一次 RPC 调用，返回解析后的 JSON dict。

        用 POST 提交参数（阿里云录音文件识别两个接口都支持 POST；
        POST 无 URL 长度限制，且 Task 参数是 JSON 串，POST 更稳）。
        """
        params = self._build_common_params(action)
        if extra:
            params.update(extra)
        params["Signature"] = self._sign(params, method="POST")

        url = f"https://{self.host}/"
        try:
            resp = requests.post(url, data=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise AliyunError(f"{action} 网络失败：{type(e).__name__}") from None

        if resp.status_code != 200:
            raise AliyunError(
                f"{action} HTTP {resp.status_code}（请检查 host/region/网络）")

        try:
            data = resp.json()
        except ValueError:
            raise AliyunError(f"{action} 返回非 JSON 内容")

        # OpenAPI 错误响应形如 {"Code": "...", "Message": "..."}
        if isinstance(data, dict) and data.get("Code") and not data.get("TaskId") \
                and data.get("StatusText") is None:
            raise AliyunError(
                f"{action} 失败：Code={data.get('Code')} Message={data.get('Message')}")
        return data

    # ---------------- 内部：提交 ----------------

    def _build_task(self, audio_url: str) -> dict:
        """构造 SubmitTask 的 Task 参数（JSON 字符串）。

        关键开关：
          enable_words               = True  → 需要词级/句级时间戳
          enable_sample_rate_adaptive= True  → 自动重采样
          enable_speaker_diarization = True  → ★ 开启说话人分离（结果带 SpeakerId）
          diarization_enabled        = True  → 部分版本的等价开关（一并带上，稳妥）
        """
        task = {
            "appkey": self.app_key,
            "file_link": audio_url,
            "version": "4.0",                  # 结果返回 sentence 时间戳（官方推荐）
            "enable_words": True,
            "enable_sample_rate_adaptive": True,
            "enable_speaker_diarization": True,   # ★ 说话人分离
            "diarization_enabled": True,          # 兼容旧字段名
            "enable_timestamp_alignment": True,
        }
        if self.speaker_max and self.speaker_max > 0:
            task["speaker_count"] = int(self.speaker_max)
        return task

    def _submit(self, audio_url: str) -> str:
        task = self._build_task(audio_url)
        data = self._call("SubmitTask", {"Task": json.dumps(task, ensure_ascii=False)})

        task_id = data.get("TaskId")
        status = data.get("StatusText")
        if not task_id:
            raise AliyunError(
                f"提交未返回 TaskId：StatusCode={data.get('StatusCode')} "
                f"StatusText={status}")
        return task_id

    # ---------------- 内部：轮询 ----------------

    def _poll(self, task_id: str, poll_interval: int, poll_timeout: int) -> dict:
        deadline = time.monotonic() + poll_timeout
        while True:
            data = self._call("GetTaskResult", {"TaskId": task_id})
            status = data.get("StatusText")

            if status == STATUS_SUCCESS:
                return data
            if status in _PENDING_STATES:
                if time.monotonic() > deadline:
                    raise AliyunError(
                        f"查询超时（{poll_timeout}s），任务仍在处理 status={status}")
                time.sleep(poll_interval)
                continue
            if status == STATUS_FAILED:
                raise AliyunError(
                    f"识别任务失败：StatusCode={data.get('StatusCode')} "
                    f"StatusText={data.get('StatusText')} "
                    f"Message={data.get('StatusMessage') or data.get('Message')}")
            # 未知状态：按失败处理（不静默吞掉）
            raise AliyunError(
                f"未知任务状态：{status!r}（StatusCode={data.get('StatusCode')}）")

    # ---------------- 内部：解析 ----------------

    def _parse_response(self, response: dict) -> List[SpeakerTurn]:
        """把 GetTaskResult 响应解析成 [SpeakerTurn, ...]。

        结果路径：Result.Sentences[]，每项含 BeginTime/EndTime(ms)、Text、
        以及说话人分离开启时的 SpeakerId（也可能是 ChannelId 兜底）。

        找不到说话人字段时**返回空列表**，绝不伪造。
        """
        sentences = self._extract_sentences(response)
        turns = []
        for s in sentences:
            if not isinstance(s, dict):
                continue
            begin = s.get("BeginTime")
            end = s.get("EndTime")
            if begin is None or end is None:
                continue
            speaker = self._extract_speaker(s)
            if speaker is None:
                continue
            turns.append(SpeakerTurn(
                start=float(begin) / 1000.0,
                end=float(end) / 1000.0,
                speaker=str(speaker),
                text=s.get("Text") or None,
            ))
        turns.sort(key=lambda t: (t.start, t.end))
        return turns

    @staticmethod
    def _extract_sentences(response: dict) -> list:
        """从响应里挖出 Sentences 列表（兼容多种嵌套）。"""
        if not isinstance(response, dict):
            return []
        result = response.get("Result")
        if isinstance(result, dict):
            s = result.get("Sentences")
            if isinstance(s, list):
                return s
            return []
        # 有些版本 Result 直接是 list
        if isinstance(result, list):
            out = []
            for item in result:
                if isinstance(item, dict) and isinstance(item.get("Sentences"), list):
                    out.extend(item["Sentences"])
                elif isinstance(item, dict):
                    out.append(item)
            return out
        if isinstance(response.get("Sentences"), list):
            return response["Sentences"]
        return []

    @staticmethod
    def _extract_speaker(s: dict):
        """从 sentence 里找说话人字段。

        已见候选：SpeakerId（说话人分离）、speaker_id、PersonId。
        找不到返回 None（绝不猜）。
        """
        for key in ("SpeakerId", "speaker_id", "PersonId"):
            v = s.get(key)
            if v is None:
                continue
            if isinstance(v, (int, float)):
                return f"spk_{int(v)}"
            if isinstance(v, str) and v.strip():
                val = v.strip()
                return f"spk_{val}" if val.isdigit() else val
        return None

    @staticmethod
    def _merge_adjacent(turns: List[SpeakerTurn], gap_s: float = 0.0) -> List[SpeakerTurn]:
        """合并首尾相接/重叠且同一说话人的段。"""
        if not turns:
            return []
        turns = sorted(turns, key=lambda t: (t.start, t.end))
        merged = [turns[0]]
        for t in turns[1:]:
            prev = merged[-1]
            if t.speaker == prev.speaker and t.start <= prev.end + gap_s + 1e-9:
                prev.end = max(prev.end, t.end)
                if t.text and not prev.text:
                    prev.text = t.text
            else:
                merged.append(t)
        return merged
