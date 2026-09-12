# ============================================================
# 语音识别模块的“公约” —— 所有识别器都要遵守的约定
# ============================================================
# 这个文件里没有任何实际功能，它只定义两样东西：
#   1. Segment：一条字幕长什么样（统一输出格式）
#   2. BaseRecognizer：一个识别器必须会做什么（统一接口）
# ============================================================

from dataclasses import dataclass


@dataclass
class Segment:
    """一条带时间戳的文字。

    不管是本地 Whisper 还是云端 API 识别出来的，
    最终都转成这种统一的格式，后面写文件、找高光都只用认它。
    """
    start: float   # 这句话开始的时间（秒），比如 12.5 表示第 12.5 秒
    end: float     # 这句话结束的时间（秒）
    text: str      # 这句话的内容


class BaseRecognizer:
    """所有识别器的“模板”。

    约定：任何识别器都必须有一个 transcribe 方法，
    吃进一个音频文件路径，吐出一组 Segment。
    """

    name = "base"  # 识别器的名字，用来在屏幕上显示

    def transcribe(self, audio_path, progress=None, duration=None):
        """音频文件路径 → [Segment, Segment, ...]（按时间排序）

        progress —— 可选（V0.5.2）。识别器边跑边上报**真实进度**：
                    progress(stages.STAGE_ASR, 45.2, "23:10 / 51:00　已识别 312 句")
                    分子 = 当前这句话在音频里的结束时间，分母 = duration。
                    不要在这里编假百分比；算不出进度就传 percent=None。
        duration —— 可选。音频总时长（秒），拿它当进度分母。

        实现进度上报时，直接用传进来的 progress 对象调用即可
        （它是 stages.ProgressSink，自带节流与旧回调兼容）。
        """
        raise NotImplementedError("这个识别器还没实现，子类必须重写这个方法")
