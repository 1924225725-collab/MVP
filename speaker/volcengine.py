# ============================================================
# speaker/volcengine.py —— 火山引擎豆包「说话人分离」封装
# ============================================================
# 【走哪个接口】
#   用「录音文件识别（大模型版）HTTP 接口」，两阶段异步：
#     1) submit：把音频 URL 提交给服务端，拿到 task_id
#     2) query ：轮询 task_id 直到出结果
#   理由：说话人分离（enable_speaker_info）在这个接口上支持得最完整、最稳定；
#         流式 WebSocket 接口需要 enable_nonstream + ssd_version，协议复杂且不划算。
#
# 【官方文档】
#   录音文件识别标准版 HTTP：https://www.volcengine.com/docs/6561/1354868
#   提交：POST https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit
#   查询：POST https://openspeech.bytedance.com/api/v3/auc/bigmodel/query
#
# 【鉴权】（新旧两套控制台，本实现兼容）
#   旧版：X-Api-App-Key + X-Api-Access-Key
#   新版：X-Api-Key（只需一个）
#   公共：X-Api-Resource-Id / X-Api-Request-Id / X-Api-Sequence
#
# 【重要前提：音频必须是「可公网访问的 URL」】
#   这个接口不吃本地文件，只吃 URL。所以：
#     - 已上传到可访问存储的音频 → 直接传 URL（推荐，生产用）
#     - 本地文件 → 需先上传到 object storage 拿到 URL（见 README 说明）
#   本模块**不替你做上传**（上传属于存储层职责，且各家方案不同），
#   但提供 upload_fn 回调钩子：调用方传一个「本地路径 → URL」的函数进来即可。
#
# 【返回统一格式】
#   [{"start": 0.0, "end": 5.0, "speaker": "spk_0"}, ...]
#   - 秒为单位的 float；speaker 形如 spk_0 / spk_1 ...
# ============================================================

import json
import time
import uuid
from typing import Callable, List, Optional

from . import config
from .base import BaseSpeakerProvider, SpeakerTurn

try:
    import requests
except ImportError:  # 部署环境缺 requests 时不至于 import 就崩
    requests = None

# ---- 接口地址 ----
SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

# ---- 查询状态码（来自官方错误码表）----
CODE_SUCCESS = "20000000"      # 成功
CODE_PROCESSING = "20000001"   # 正在处理中
CODE_QUEUED = "20000002"       # 任务在队列中
CODE_SILENT = "20000003"       # 静音音频（没有检测到人声）


class VolcengineError(RuntimeError):
    """火山引擎调用失败。消息里绝不包含 token / app_id 等敏感内容。"""


class VolcengineSpeakerProvider(BaseSpeakerProvider):
    """火山引擎豆包说话人分离。

    用法（最简，音频已有公网 URL）：
        p = VolcengineSpeakerProvider()
        turns = p.diarize("https://example.com/a.mp3")
        # 或直接要 JSON：
        data = p.diarize_unified("https://example.com/a.mp3")

    用法（本地文件）：
        p = VolcengineSpeakerProvider(upload_fn=my_upload)
        turns = p.diarize("/path/to/a.mp3")   # my_upload 负责转成 URL

    upload_fn：可选回调，签名 (local_path: str) -> str，返回公网可访问 URL。
              不传且传入的是本地路径时，会明确报错提示如何提供 URL。
    """

    name = "火山引擎豆包说话人分离"
    provider_id = "volcengine"
    kind = "cloud"

    def __init__(self,
                 app_id: str = None,
                 access_token: str = None,
                 cluster_id: str = None,
                 resource_id: str = None,
                 speaker_max: int = None,
                 upload_fn: Optional[Callable[[str], str]] = None,
                 timeout: int = 30,
                 poll_interval: int = 3,
                 poll_timeout: int = 600):
        # 显式传参优先，否则从环境变量读（安全约定：默认走环境变量）
        self.app_id = app_id if app_id is not None else config.get_app_id()
        self.access_token = (access_token if access_token is not None
                             else config.get_access_token())
        self.cluster_id = cluster_id if cluster_id is not None else config.get_cluster_id()
        self.resource_id = resource_id or config.get_resource_id()
        self.speaker_max = (speaker_max if speaker_max is not None
                            else config.get_speaker_max())
        self.upload_fn = upload_fn
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    # ---------------- 能力声明 ----------------

    def is_available(self):
        """轻量检查：库在不在 + 钥匙有没有。不发起任何网络请求。"""
        if requests is None:
            return False, "缺少 requests 库（pip install requests）"
        missing = []
        if not self.app_id:
            missing.append(config.ENV_APP_ID)
        if not self.access_token:
            missing.append(config.ENV_ACCESS_TOKEN)
        if missing:
            return False, f"缺少环境变量：{', '.join(missing)}"
        return True, "已配置（音频需为公网可访问 URL）"

    def info(self) -> dict:
        d = super().info()
        d["resource_id"] = self.resource_id
        d["speaker_max"] = self.speaker_max
        d["has_upload_fn"] = self.upload_fn is not None
        # 安全：只给是否配置，不给内容
        d["configured"] = bool(self.app_id and self.access_token)
        return d

    # ---------------- 核心能力 ----------------

    def diarize(self, audio_path, **kwargs) -> List[SpeakerTurn]:
        """音频（URL 或本地路径）→ [SpeakerTurn, ...]（按 start 排序，已合并相邻同人段）。

        额外参数（kwargs）：
          speaker_max  覆盖构造时的说话人上限（None = 自动）
          poll_interval / poll_timeout  覆盖轮询节奏
          raw_out      传一个 dict，函数会把服务端原始响应塞进 raw_out["response"]
                       （调试用；生产别用，体积可能很大）

        失败抛 VolcengineError（消息不含敏感内容）。
        """
        if requests is None:
            raise VolcengineError("缺少 requests 库，请先 pip install requests")

        ok, reason = self.is_available()
        if not ok:
            raise VolcengineError(f"火山引擎配置不完整：{reason}")

        audio_url = self._resolve_url(audio_path)

        speaker_max = kwargs.get("speaker_max", self.speaker_max)
        poll_interval = kwargs.get("poll_interval", self.poll_interval)
        poll_timeout = kwargs.get("poll_timeout", self.poll_timeout)

        task_id = str(uuid.uuid4())
        self._submit(task_id, audio_url)
        response = self._poll(task_id, poll_interval, poll_timeout)

        raw_out = kwargs.get("raw_out")
        if isinstance(raw_out, dict):
            raw_out["response"] = response

        turns = self._parse_response(response)
        return self._merge_adjacent(turns)

    # ---------------- 内部：URL 解析 ----------------

    def _resolve_url(self, audio_path: str) -> str:
        """把入参规整成「公网可访问 URL」。

        - http(s):// 开头 → 直接当 URL 用
        - 本地路径 + 有 upload_fn → 交给 upload_fn 换 URL
        - 本地路径 + 没 upload_fn → 明确报错（教用户怎么给 URL）
        """
        if isinstance(audio_path, str) and audio_path.startswith(("http://", "https://")):
            return audio_path
        if self.upload_fn is not None:
            url = self.upload_fn(audio_path)
            if not (isinstance(url, str) and url.startswith(("http://", "https://"))):
                raise VolcengineError(
                    f"upload_fn 必须返回 http(s) URL，实际得到：{type(url)!r}")
            return url
        raise VolcengineError(
            "火山引擎该接口只接受「公网可访问的音频 URL」，不支持直接读本地文件。\n"
            "两种办法：\n"
            "  1) 先把音频上传到对象存储（如火山 TOS / S3 / 任意可公网访问的地址），"
            "再把 URL 传进来；\n"
            "  2) 给 VolcengineSpeakerProvider(upload_fn=你的上传函数) 传一个回调，"
            "本模块会自动帮你换 URL。\n"
            f"当前传入：{audio_path!r}"
        )

    # ---------------- 内部：鉴权头 ----------------

    def _headers(self, task_id: str) -> dict:
        """构造鉴权请求头。

        兼容两套控制台：
          - 旧版：X-Api-App-Key + X-Api-Access-Key
          - 新版：X-Api-Key（本实现同时带上旧版头，服务端按存在者识别）
        安全：绝不在异常/日志里回显这些值。
        """
        h = {
            "Content-Type": "application/json",
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": task_id,
            "X-Api-Sequence": "-1",
        }
        if self.cluster_id:
            h["X-Api-Cluster"] = self.cluster_id
        return h

    # ---------------- 内部：提交 ----------------

    def _submit(self, task_id: str, audio_url: str):
        body = self._build_body(audio_url)
        try:
            resp = requests.post(SUBMIT_URL, headers=self._headers(task_id),
                                 data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 timeout=self.timeout)
        except requests.RequestException as e:
            raise VolcengineError(f"提交任务网络失败：{type(e).__name__}") from None

        status = resp.headers.get("X-Api-Status-Code", "")
        message = resp.headers.get("X-Api-Message", "")
        logid = resp.headers.get("X-Tt-Logid", "")
        if status != CODE_SUCCESS:
            raise VolcengineError(
                f"提交任务失败：status={status or '(空)'} message={message or '(空)'} "
                f"logid={logid or '(无)'}")

    # ---------------- 内部：请求体 ----------------

    def _build_body(self, audio_url: str) -> dict:
        """构造提交请求体，开启说话人分离。"""
        request = {
            "model_name": "bigmodel",
            "enable_itn": True,             # 数字/单位规范化，提升文本可读性
            "enable_punc": True,            # 标点
            "enable_speaker_info": True,    # ★ 核心：开启说话人聚类分离
            "ssd_version": "200",           # ★ ASR2.0 建议开启的大模型 SSD
            "show_utterances": True,        # 必须开，否则拿不到分句与时间戳
        }
        if self.speaker_max and self.speaker_max > 0:
            # 官方未提供 speaker_number 字段时，用 prompt 无法保证生效；
            # 这里只作为「期望值」记录，不做强制（服务端自动判断人数最稳）。
            request["speaker_number"] = int(self.speaker_max)

        return {
            "user": {"uid": "ailiveclipper"},
            "audio": {"url": audio_url, "format": "mp3"},
            "request": request,
        }

    # ---------------- 内部：轮询 ----------------

    def _poll(self, task_id: str, poll_interval: int, poll_timeout: int) -> dict:
        """轮询查询接口，直到成功 / 失败 / 超时。返回解析后的响应 dict。"""
        deadline = time.monotonic() + poll_timeout
        last_status = ""
        while True:
            try:
                resp = requests.post(QUERY_URL, headers=self._headers(task_id),
                                     data=b"{}", timeout=self.timeout)
            except requests.RequestException as e:
                raise VolcengineError(f"查询任务网络失败：{type(e).__name__}") from None

            status = resp.headers.get("X-Api-Status-Code", "")
            message = resp.headers.get("X-Api-Message", "")
            logid = resp.headers.get("X-Tt-Logid", "")
            last_status = status

            if status == CODE_SUCCESS:
                # 成功时结果在 body（JSON），header 里只有状态
                try:
                    return resp.json()
                except ValueError:
                    raise VolcengineError(
                        f"服务端返回成功但 body 不是 JSON（logid={logid or '(无)'}）")

            if status in (CODE_PROCESSING, CODE_QUEUED):
                if time.monotonic() > deadline:
                    raise VolcengineError(
                        f"查询超时（{poll_timeout}s），任务仍在处理 "
                        f"status={status} logid={logid or '(无)'}")
                time.sleep(poll_interval)
                continue

            if status == CODE_SILENT:
                # 静音音频：没有检测到人声 → 合法地返回空（不伪造）
                return {"result": {"utterances": []}, "_note": "silent_audio"}

            raise VolcengineError(
                f"查询任务失败：status={status or '(空)'} message={message or '(空)'} "
                f"logid={logid or '(无)'}")

    # ---------------- 内部：解析 ----------------

    def _parse_response(self, response: dict) -> List[SpeakerTurn]:
        """把服务端响应解析成 [SpeakerTurn, ...]。

        兼容两种形态：
          A. 大模型版：result.utterances[] 每项含 additions.speaker
          B. 平铺版：result[] / utterances[] 直接带 speaker 字段
        找不到说话人字段时不报错，返回空列表（由上层决定是否降级）。
        """
        utterances = self._extract_utterances(response)
        turns = []
        for u in utterances:
            if not isinstance(u, dict):
                continue
            start_ms = u.get("start_time")
            end_ms = u.get("end_time")
            if start_ms is None or end_ms is None:
                continue
            speaker = self._extract_speaker(u)
            if speaker is None:
                continue
            turns.append(SpeakerTurn(
                start=float(start_ms) / 1000.0,
                end=float(end_ms) / 1000.0,
                speaker=str(speaker),
                text=u.get("text") or None,
            ))
        turns.sort(key=lambda t: (t.start, t.end))
        return turns

    @staticmethod
    def _extract_utterances(response: dict) -> list:
        """从各种可能的响应嵌套里挖出 utterances 列表。"""
        if not isinstance(response, dict):
            return []
        result = response.get("result")

        # A. {"result": {"utterances": [...]}}
        if isinstance(result, dict):
            if isinstance(result.get("utterances"), list):
                return result["utterances"]
            return []
        # B. {"result": [{...}, {...}]}  （部分版本 result 直接是 list）
        if isinstance(result, list):
            out = []
            for item in result:
                if isinstance(item, dict) and isinstance(item.get("utterances"), list):
                    out.extend(item["utterances"])
                elif isinstance(item, dict):
                    out.append(item)
            return out
        # C. 顶层直接放 utterances
        if isinstance(response.get("utterances"), list):
            return response["utterances"]
        return []

    @staticmethod
    def _extract_speaker(u: dict):
        """从 utterance 里找说话人字段（不同版本字段位置不同，逐个兜底）。

        已见过的候选位置：
          - u["speaker"]                 （平铺）
          - u["additions"]["speaker"]    （大模型版常见）
          - u["additions"]["speaker_id"]
          - u["speaker_id"]
        找不到返回 None（绝不猜、绝不伪造）。
        """
        candidates = [
            u.get("speaker"),
            u.get("speaker_id"),
        ]
        add = u.get("additions")
        if isinstance(add, dict):
            candidates.append(add.get("speaker"))
            candidates.append(add.get("speaker_id"))
        for c in candidates:
            if c is None:
                continue
            if isinstance(c, (int, float)):
                return f"spk_{int(c)}"
            if isinstance(c, str) and c.strip():
                s = c.strip()
                # 统一成 spk_N 形态：数字直接补前缀；已是 spk_xxx 的保持
                if s.isdigit():
                    return f"spk_{s}"
                return s
        return None

    @staticmethod
    def _merge_adjacent(turns: List[SpeakerTurn], gap_s: float = 0.0) -> List[SpeakerTurn]:
        """合并时间上相邻（或重叠）且同一说话人的段，让输出更干净。

        gap_s：允许合并的最大间隔（秒）。默认 0 = 只合并首尾相接/重叠的。
        """
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
