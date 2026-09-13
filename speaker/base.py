# ============================================================
# speaker/base.py —— 说话人识别模块的「公约」
# ============================================================
# 这个文件里没有任何实际功能，它只定义两样东西：
#   1. SpeakerTurn：一段「谁在什么时候说话」（统一输出格式）
#   2. BaseSpeakerProvider：一个说话人识别器必须会做什么（统一接口）
#
# 【设计目的】
#   说话人识别（Diarization）应可替换：火山引擎 → pyannote → 本地模型，
#   将来换任何一家，上层只用认 SpeakerTurn，不用改一行代码。
#
# 【统一输出格式】（需求给定，勿改字段名）
#   [
#       {"start": 0, "end": 5, "speaker": "spk_0"},
#       {"start": 5, "end": 9.4, "speaker": "spk_1"},
#   ]
#   - start / end ：秒（float），支持小数
#   - speaker     ：说话人标识（str），同一段音频内同名 = 同一个人
#
# 【铁律】
#   模型没给出可靠结果时，宁可返回空列表，禁止伪造说话人标签。
# ============================================================

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SpeakerTurn:
    """一段「谁在什么时候说话」。

    不管是火山引擎、pyannote 还是本地模型识别出来的，
    最终都转成这种统一格式，后面融合、展示都只用认它。
    """

    start: float          # 这段开始的时间（秒），比如 12.5 表示第 12.5 秒
    end: float            # 这段结束的时间（秒）
    speaker: str          # 说话人标识，如 "spk_0"（同一段音频内同名 = 同一人）
    confidence: Optional[float] = None   # 置信度 0~1，模型没给就 None
    text: Optional[str] = None           # 这段说的话（识别器附带时才有，可空）

    def to_dict(self) -> dict:
        """转成需求给定的统一 JSON 格式（只含 start/end/speaker 三个必填字段）。

        额外的 confidence / text 只有真的有时才带上，避免污染契约。
        """
        d = {"start": round(float(self.start), 3),
             "end": round(float(self.end), 3),
             "speaker": str(self.speaker)}
        if self.confidence is not None:
            d["confidence"] = round(float(self.confidence), 4)
        if self.text:
            d["text"] = self.text
        return d


def to_unified(turns) -> List[dict]:
    """把 [SpeakerTurn, ...] 转成统一格式的 list[dict]。

    也接受已经是 dict 的项（幂等），方便上层混用。
    """
    out = []
    for t in turns:
        if isinstance(t, SpeakerTurn):
            out.append(t.to_dict())
        elif isinstance(t, dict):
            out.append({
                "start": round(float(t["start"]), 3),
                "end": round(float(t["end"]), 3),
                "speaker": str(t["speaker"]),
            })
        else:
            raise TypeError(f"不认识的说话人片段类型：{type(t)!r}")
    return out


class BaseSpeakerProvider:
    """所有说话人识别器的「模板」。

    约定：任何说话人识别器都必须有：
      - name            ：识别器名字（显示用）
      - is_available()  ：现在能不能用（轻量检查，不联网）
      - diarize()       ：吃进音频文件路径，吐出 [SpeakerTurn, ...]
    """

    name = "base"            # 识别器名字，屏幕上显示用
    provider_id = "base"     # 稳定标识，代码里用来选 provider
    kind = "local"           # "local" | "cloud"

    def is_available(self):
        """现在能不能用？返回 (bool, 原因)。不发起真实请求，只做轻量检查。"""
        return False, "未实现"

    def info(self) -> dict:
        return {"provider_id": self.provider_id, "name": self.name, "kind": self.kind}

    def diarize(self, audio_path, **kwargs) -> List[SpeakerTurn]:
        """音频文件路径 → [SpeakerTurn, ...]（按时间排序）

        失败应抛异常（见各实现的异常说明），不要静默返回假数据。
        """
        raise NotImplementedError("这个说话人识别器还没实现，子类必须重写 diarize()")

    def diarize_unified(self, audio_path, **kwargs) -> List[dict]:
        """便捷方法：直接返回需求给定的统一格式 list[dict]。

        上层若只想要 JSON 格式，调这个方法即可，不用自己再转。
        """
        return to_unified(self.diarize(audio_path, **kwargs))
