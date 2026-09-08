# ============================================================
# 本地 Whisper 识别器（步骤 3 的主角，本次填肉）
#
# 用的库：faster-whisper（Whisper 的社区优化版，快且省内存）
# 模型首次使用时会自动从 HuggingFace 下载到用户缓存文件夹，
# 下载一次以后就反复用，不用每次联网。
# ============================================================

from .base import BaseRecognizer, Segment


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
        except ImportError:
            print("❌ 缺少 faster-whisper 库，请先安装：")
            print("    .\\.venv\\Scripts\\python -m pip install faster-whisper")
            raise SystemExit(1)

        print(f"正在加载本地模型（{model_size}）……首次运行会先下载模型文件，请耐心等待")
        # device="cpu"：用 CPU 跑（用 GPU 需要额外装 CUDA 环境，以后有需要再说）
        # compute_type="int8"：用 8 位整数做运算，速度快的压缩方式，对 CPU 最友好
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.model_size = model_size

    def transcribe(self, audio_path):
        """音频文件 → [Segment, ...]，遵守 base.py 里定的公约。"""
        # vad_filter=True：先用"人声检测"跳过没人说话的片段（比如片头静音），
        # 能明显减少胡言乱语和识别时间
        segments_iter, info = self.model.transcribe(
            str(audio_path),
            language="zh",        # 提前告诉模型是中文，省去开头几秒的语言猜测
            vad_filter=True,
        )

        # 把模型吐出的原始片段，逐条翻译成我们的统一格式 Segment
        results = []
        for seg in segments_iter:            # 模型是边识别边吐结果的，所以要循环收集
            text = seg.text.strip()          # 去掉句首句尾多余空格
            if text:                         # 跳过空句子
                results.append(Segment(start=seg.start, end=seg.end, text=text))

        # 顺手把检测到的语言信息存起来，main.py 可以拿去显示
        self.detected_language = info.language
        return results
