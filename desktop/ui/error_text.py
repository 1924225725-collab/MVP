# ============================================================
# desktop/ui/error_text.py —— 出错在哪一层 → 界面怎么跟用户说
#
# 延续 V0.4.5（D-046）的分层思路：**不同层的错，给不同的话**，
# 绝不再出现「视频处理失败，请换一个文件试试」这种万能句。
#
# 桌面版比网页版多说一件事：告诉用户「点哪个按钮能修好」。
# ============================================================

from errors import (
    STAGE_ASR_EMPTY, STAGE_ASR_INFERENCE, STAGE_AUDIO_EXTRACT, STAGE_DEPENDENCY,
    STAGE_FFMPEG, STAGE_MEDIA_UNREADABLE, STAGE_MODEL_LOAD, STAGE_MODEL_MISSING,
    STAGE_NO_AUDIO, STAGE_UNKNOWN,
)

# stage → (标题, 说明, 建议动作)
#   建议动作取值： "models"（打开模型管理）/ "settings"（打开设置）/ None
ERROR_UI = {
    STAGE_MEDIA_UNREADABLE: (
        "媒体文件无法读取",
        "这个文件不是有效的视频，或者已经损坏。请先用播放器确认能正常播放，再换一个 MP4。",
        None,
    ),
    STAGE_NO_AUDIO: (
        "未检测到音轨",
        "视频能正常打开，但里面没有声音轨道（常见于无声录屏、或音轨被剥离的文件）。"
        "请换一个有声音的视频。",
        None,
    ),
    STAGE_AUDIO_EXTRACT: (
        "音频提取失败",
        "文件能被识别，但 FFmpeg 没能抽出音频，可能是文件部分损坏或编码异常。"
        "可以先在播放器里拖到中段确认能正常播放，再换文件重试。",
        None,
    ),
    STAGE_FFMPEG: (
        "缺少音视频处理组件",
        "程序里没有找到 FFmpeg（视频解码要用）。重装本程序通常能修好。",
        None,
    ),
    STAGE_DEPENDENCY: (
        "缺少依赖组件",
        "本地语音识别所需的库没装好（还没轮到这个视频本身有问题）。重装本程序通常能修好。",
        None,
    ),
    STAGE_MODEL_MISSING: (
        "本地模型未安装",
        "本机还没有这个语音识别模型，自动下载也没成功 —— 程序已经依次尝试了"
        "国内镜像和官方源，都不通（常见于网络受限的环境）。"
        "可以稍后重试；或在「模型管理」里用「手动指定文件夹」加载本机已有的模型；"
        "也可以按错误详情里的地址手动下载后放到指定目录。",
        "models",
    ),
    STAGE_MODEL_LOAD: (
        "模型加载失败",
        "模型文件在本地，但加载不了（可能下载不完整或文件损坏）。"
        "建议在「模型管理」里做一次完整性校验，或卸载后重新安装。",
        "models",
    ),
    STAGE_ASR_INFERENCE: (
        "语音识别推理失败",
        "模型加载成功，但在识别这段音频时出错。请把「开发者视图 → 运行日志」里的原始报错发出来。",
        None,
    ),
    STAGE_ASR_EMPTY: (
        "没有识别出内容",
        "音频能读、模型也跑通了，但整段几乎没有人声（可能是纯静音 / 纯 BGM / 纯环境音）。",
        None,
    ),
    STAGE_UNKNOWN: (
        "处理失败",
        "发生了未预期的错误。请把「开发者视图 → 运行日志」里的 traceback 发出来方便定位。",
        None,
    ),
}


def error_ui(stage: str) -> tuple:
    return ERROR_UI.get(stage, ERROR_UI[STAGE_UNKNOWN])
