# ab_experiment.py —— ct-punc A/B 实验（设计文档实验轮，不接生产）
#
# 每次运行 = 一个独立 Python 进程（新进程冷启动路径：import → model init → inference → output）。
# 用法：
#   .venv-audio-poc/Scripts/python ab_experiment.py --group A --run 1
#   .venv-audio-poc/Scripts/python ab_experiment.py --group B --run 1   # 首次会下载 ct-punc
# 输出：outputs/ab/<group>_run<id>.json（完整原始 sentence_info + 计时，不覆盖别的 run）

import argparse
import json
import os
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
T_PROC_START = time.perf_counter()  # 脚本内首语句起（不含 Python 解释器进程拉起）

WAV = os.path.join(HERE, "fixtures", "clip_51min_000_090.wav")
ASR_MODEL_ID = "iic/SenseVoiceSmall"
VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
SPK_MODEL_ID = "iic/speech_campplus_sv_zh-cn_16k-common"
PUNC_ALIAS = "ct-punc"  # B 组唯一差异；funasr 内置别名映射


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=["A", "B"])
    ap.add_argument("--run", required=True, type=int)
    args = ap.parse_args()

    with wave.open(WAV, "rb") as w:
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
    if args.group == "B":
        kwargs["punc_model"] = PUNC_ALIAS

    t0 = time.perf_counter()
    model = AutoModel(**kwargs)
    t_init = time.perf_counter() - t0

    t0 = time.perf_counter()
    res = model.generate(input=WAV, cache={}, batch_size_s=60, hotword="")
    t_infer = time.perf_counter() - t0
    t_total = time.perf_counter() - T_PROC_START

    result = res[0] if res else {}
    sentences = result.get("sentence_info") or []

    out_dir = os.path.join(HERE, "outputs", "ab")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{args.group}_run{args.run}.json")
    payload = {
        "group": args.group,
        "run": args.run,
        "config": {
            "asr": ASR_MODEL_ID, "vad": VAD_MODEL_ID, "spk": SPK_MODEL_ID,
            "punc": kwargs.get("punc_model", None),
            "vad_kwargs": kwargs["vad_kwargs"], "device": "cpu",
            "batch_size_s": 60,
        },
        "timing": {
            "audio_seconds": round(audio_seconds, 3),
            "import_seconds": round(t_import, 3),
            "init_seconds": round(t_init, 3),
            "infer_seconds": round(t_infer, 3),
            "rtf": round(t_infer / audio_seconds, 4),
            "proc_total_seconds": round(t_total, 3),
            "_note": "计时从脚本内首语句起，不含 Python 解释器进程拉起",
        },
        "runtime": {
            "funasr": funasr.__version__, "torch": torch.__version__,
            "python": sys.version.split()[0],
        },
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
    print(f"[{args.group}{args.run}] init={t_init:.1f}s infer={t_infer:.2f}s "
          f"rtf={t_infer/audio_seconds:.3f} sentences={len(sentences)} spk={spk} -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
