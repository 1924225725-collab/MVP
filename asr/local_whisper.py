# ============================================================
# 本地 Whisper 识别器
#
# 用的库：faster-whisper（Whisper 的社区优化版，快且省内存）
# 模型首次使用时会自动从 HuggingFace 下载到用户缓存文件夹，
# 下载一次以后就反复用，不用每次联网。
#
# 【V0.4.5 修复：模型加载不再强制联网】
#   问题：faster-whisper 加载模型时会走 huggingface_hub 做一次远程校验，
#   即使模型文件本地已存在也要联网。本机网络走代理时这一步直接
#   502 Bad Gateway → 抛异常 → 被 UI 统一吞成「视频处理失败，请换一个文件试试」，
#   于是**正常视频也全部失败**，而且看起来像"视频坏了"。
#   修复：先 local_files_only=True 从本地缓存离线加载（不联网）；
#   只有缓存里确实没有该模型时，才允许联网下载（首次安装路径保留）。
#   同时把「模型未安装 / 模型加载失败 / 推理失败」分别抛成可识别的错误。
# ============================================================

import traceback
from pathlib import Path

from errors import (
    ProcessError,
    STAGE_ASR_INFERENCE,
    STAGE_DEPENDENCY,
    STAGE_MODEL_LOAD,
    STAGE_MODEL_MISSING,
)

from .base import BaseRecognizer, Segment


def _is_not_cached(err) -> bool:
    """这个异常是不是「本地缓存里没有这个模型」。

    不直接 import huggingface_hub：用类名判断，避免多一个硬依赖。
    """
    return type(err).__name__ in ("LocalEntryNotFoundError", "EntryNotFoundError")


def _model_cache_hint(model_size: str) -> str:
    """给出模型缓存目录，方便用户手动放模型 / 删除重下。"""
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    return (f"模型缓存目录：{hub}\n"
            f"该模型对应子目录：models--Systran--faster-whisper-{model_size}\n"
            f"命令行预下载：.\\.venv\\Scripts\\python -c \""
            f"from faster_whisper import WhisperModel; "
            f"WhisperModel('{model_size}', device='cpu', compute_type='int8')\"")


class LocalWhisperRecognizer(BaseRecognizer):
    """在自己电脑上跑 Whisper 模型。

    优点：免费、离线、隐私安全
    代价：要下载模型文件（几十~几百 MB），速度取决于电脑配置
    """

    name = "本地Whisper"

    def __init__(self, model_size="small"):
        # 加载模型这件事比较重（要读几百 MB 进内存），
        # 所以放在创建识别器的时候做，只做一次，之后反复用。
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise ProcessError(
                STAGE_DEPENDENCY,
                "缺少 faster-whisper 库（本地语音识别引擎）",
                f"{e}\n安装：.\\.venv\\Scripts\\python -m pip install faster-whisper",
            )

        print(f"正在加载本地模型（{model_size}）……首次运行会先下载模型文件，请耐心等待")
        self.model = self._load_model(WhisperModel, model_size)
        self.model_size = model_size

    @staticmethod
    def _load_model(WhisperModel, model_size: str):
        """离线优先加载模型（V0.4.5 核心修复）。

        1）先 local_files_only=True：只用本地缓存，**完全不联网**
           —— 这一步能避免"网络不通/代理 502"把正常视频也拖下水；
        2）缓存里没有该模型时才联网下载（首次安装路径）；
        3）两条路都失败 → 抛可识别的 ProcessError。
        """
        # device="cpu"：用 CPU 跑（GPU 需额外装 CUDA 环境）
        # compute_type="int8"：8 位整数运算，对 CPU 最友好
        common = {"device": "cpu", "compute_type": "int8"}

        try:
            model = WhisperModel(model_size, local_files_only=True, **common)
            print(f"本地模型已就绪（离线加载）")
            return model
        except Exception as e_local:
            if not _is_not_cached(e_local):
                # 本地有模型但加载不了（文件损坏、版本不兼容等）
                raise ProcessError(
                    STAGE_MODEL_LOAD,
                    f"本地模型加载失败（{model_size}）：{type(e_local).__name__}",
                    traceback.format_exc() + "\n\n" + _model_cache_hint(model_size),
                )

        # 缓存里没有 → 允许联网下载（首次安装）
        print(f"本地没有 {model_size} 模型缓存，尝试联网下载……")
        try:
            model = WhisperModel(model_size, **common)
            print("模型下载完成并已加载")
            return model
        except Exception as e_dl:
            raise ProcessError(
                STAGE_MODEL_MISSING,
                f"本地模型未安装（{model_size}），自动下载也没成功："
                f"{type(e_dl).__name__}",
                traceback.format_exc() + "\n\n" + _model_cache_hint(model_size)
                + "\n\n提示：当前网络可能访问不了 HuggingFace（代理/防火墙）。"
                  "可以联网后重跑一次自动下载，或按上面的目录手动放入模型。",
            )

    def transcribe(self, audio_path):
        """音频文件 → [Segment, ...]，遵守 base.py 里定的公约。"""
        # vad_filter=True：先用"人声检测"跳过没人说话的片段（比如片头静音），
        # 能明显减少胡言乱语和识别时间
        try:
            segments_iter, info = self.model.transcribe(
                str(audio_path),
                language="zh",        # 提前告诉模型是中文，省去开头几秒的语言猜测
                vad_filter=True,
            )

            # 把模型吐出的原始片段，逐条翻译成我们的统一格式 Segment
            # 注意：faster-whisper 是惰性生成器，真正的推理发生在循环里，
            # 所以 try 必须包住整个循环，否则推理错误会漏出去变成"未知错误"。
            results = []
            for seg in segments_iter:
                text = seg.text.strip()      # 去掉句首句尾多余空格
                if text:                     # 跳过空句子
                    results.append(Segment(start=seg.start, end=seg.end, text=text))
        except ProcessError:
            raise
        except Exception as e:
            raise ProcessError(
                STAGE_ASR_INFERENCE,
                f"语音识别推理失败：{type(e).__name__}: {e}",
                traceback.format_exc(),
            )

        # 顺手把检测到的语言信息存起来，main.py 可以拿去显示
        self.detected_language = info.language
        return results
