# -*- coding: utf-8 -*-
"""speaker_benchmark.py —— Speaker Benchmark 正式评估的推理步（PoC，不接生产）

每个 (fixture × 配置) 只跑 1 次，独立进程：
  A: SenseVoice + FSMN-VAD + CAM++            （无 ct-punc，vad_segment 路线）
  B: SenseVoice + FSMN-VAD + ct-punc + CAM++  （punc_segment 路线）
配置与 ab_experiment.py 的 A/B 组完全一致，不调任何参数。

用法：
  .venv-audio-poc/Scripts/python speaker_benchmark.py --key t2_0274_0360 --config A
输出：
  outputs/bench/<key>.<config>.json   完整 sentence_info + 计时
"""

import argparse
import json
import os
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
BENCH_DIR = os.path.join(HERE, "outputs", "bench")

ASR_MODEL_ID = "iic/SenseVoiceSmall"
VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
SPK_MODEL_ID = "iic/speech_campplus_sv_zh-cn_16k-common"
PUNC_ALIAS = "ct-punc"  # 仅 B 组；funasr 内置别名


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--config", required=True, choices=["A", "B"])
    args = ap.parse_args()

    wav = os.path.join(FIXTURES, f"benchmark_{args.key}.wav")
    with wave.open(wav, "rb") as w:
        audio_seconds = w.getnframes() / float(w.getframerate())

    t0 = time.perf_counter()
    import torch
    import funasr
    from funasr import AutoModel
    t_import = time.perf_counter() - t0

    kwargs = dict(
        model=ASR_MODEL_ID,
        vad_model=VAD_MODEL_ID,
        vad_kwargs={"max_single_segment_time": 15000},
        spk_model=SPK_MODEL_ID,
        device="cpu",
        disable_update=True,
        disable_pbar=True,
    )
    if args.config == "B":
        kwargs["punc_model"] = PUNC_ALIAS

    t0 = time.perf_counter()
    model = AutoModel(**kwargs)
    t_init = time.perf_counter() - t0

    t0 = time.perf_counter()
    res = model.generate(input=wav, cache={}, batch_size_s=60, hotword="")
    t_infer = time.perf_counter() - t0

    result = res[0] if res else {}
    sentences = result.get("sentence_info") or []

    os.makedirs(BENCH_DIR, exist_ok=True)
    out_path = os.path.join(BENCH_DIR, f"{args.key}.{args.config}.json")
    payload = {
        "key": args.key, "config": args.config,
        "config_detail": {
            "asr": ASR_MODEL_ID, "vad": VAD_MODEL_ID, "spk": SPK_MODEL_ID,
            "punc": kwargs.get("punc_model"), "vad_kwargs": kwargs["vad_kwargs"],
            "device": "cpu", "batch_size_s": 60,
        },
        "timing": {
            "audio_seconds": round(audio_seconds, 3),
            "import_seconds": round(t_import, 3),
            "init_seconds": round(t_init, 3),
            "infer_seconds": round(t_infer, 3),
            "rtf": round(t_infer / audio_seconds, 4),
        },
        "runtime": {"funasr": funasr.__version__, "torch": torch.__version__,
                    "python": sys.version.split()[0]},
        "raw": {
            "top_keys": sorted(result.keys()),
            "text": result.get("text"),
            "sentence_count": len(sentences),
            "sentence_info": sentences,
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    spk = sorted({s.get("spk") for s in sentences if s.get("spk") is not None})
    n_sw = sum(1 for a, b in zip(sentences, sentences[1:])
               if a.get("spk") is not None and b.get("spk") is not None
               and a["spk"] != b["spk"])
    print(f"[{args.key}/{args.config}] init={t_init:.1f}s infer={t_infer:.2f}s "
          f"rtf={t_infer / audio_seconds:.3f} sentences={len(sentences)} "
          f"spk={spk} pred_switches={n_sw} -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
