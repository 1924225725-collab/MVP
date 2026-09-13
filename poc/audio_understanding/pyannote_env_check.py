# -*- coding: utf-8 -*-
"""pyannote_env_check.py —— Windows 兼容性实测（不下载模型，不需要 token）

逐项验证（对应任务约定的检查清单）：
  1. torch / torchaudio / torchcodec 版本与可用性
  2. torchcodec 实际解码一个 fixture wav（验证 ffmpeg 依赖在 Windows 上是否成立）
  3. pyannote.audio 版本 + Pipeline 可导入
  4. HF token 存在性（只报存在与否，绝不打印内容）
  5. HF endpoint 环境变量状态
"""
import importlib.metadata as im
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")

info = {"python": os.sys.version.split()[0]}

for pkg in ("torch", "torchaudio", "torchcodec", "pyannote.audio",
            "huggingface-hub"):
    try:
        info[pkg] = im.version(pkg)
    except Exception as e:
        info[f"{pkg}_missing"] = repr(e)

try:
    import torch
    info["cuda_available"] = bool(torch.cuda.is_available())
except Exception as e:
    info["cuda_check_error"] = repr(e)

try:
    from torchcodec.decoders import AudioDecoder
    wav = os.path.join(FIXTURES, "benchmark_t2_0274_0360.wav")
    d = AudioDecoder(wav)
    m = d.metadata
    info["torchcodec_decode"] = {
        "ok": True,
        "sample_rate": getattr(m, "sample_rate", None),
        "num_channels": getattr(m, "num_channels", None),
        "duration_seconds": round(float(getattr(m, "duration_seconds", 0.0)), 2),
    }
except Exception as e:
    info["torchcodec_decode_error"] = f"{type(e).__name__}: {e}"

try:
    from pyannote.audio import Pipeline  # noqa: F401
    info["pipeline_import"] = "ok"
except Exception as e:
    info["pipeline_import_error"] = f"{type(e).__name__}: {e}"

token_file = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "token")
info["hf_token_file_present"] = os.path.isfile(token_file)
info["hf_token_env_present"] = bool(os.environ.get("HF_TOKEN"))
info["hf_endpoint_env"] = os.environ.get("HF_ENDPOINT") or "(unset -> official)"

print(json.dumps(info, ensure_ascii=False, indent=2))
