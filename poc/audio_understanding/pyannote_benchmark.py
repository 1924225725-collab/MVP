# -*- coding: utf-8 -*-
"""pyannote_benchmark.py —— pyannote community-1 vs CAM++ 对照推理（PoC，不接生产）

用途：
  对 2 个 benchmark fixture 跑 pyannote/speaker-diarization-community-1：
    - auto 模式（Primary）：不传 num_speakers，与 CAM++ 同条件
    - oracle 模式（Secondary，诊断用）：--oracle，从 GT 读 total_human_speakers 传入
  输出 outputs/bench_pyannote/<key>.<mode>.json + .rttm

Token 约定（用户规则，勿改）：
  - 任何 token 不写进代码/日志/Git；依赖标准渠道：
      HF_TOKEN 环境变量 或 %USERPROFILE%\\.cache\\huggingface\\token
    huggingface_hub 自动读取，本脚本不显式接触 token。

用法：
  python pyannote_benchmark.py --mode auto
  python pyannote_benchmark.py --mode auto --warm   # 同进程第二遍 = warm 推理
  python pyannote_benchmark.py --mode oracle
  # 官方直连超时时：加 --endpoint https://hf-mirror.com（同一 token，镜像代理鉴权）
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
OUT_DIR = os.path.join(HERE, "outputs", "bench_pyannote")
MODEL_ID = "pyannote/speaker-diarization-community-1"
KEYS = ["t2_0274_0360", "t2_2630_2685"]


def load_gt_total(key):
    with open(os.path.join(FIXTURES, f"speaker_ground_truth_{key}.json"),
              encoding="utf-8") as f:
        return int(json.load(f)["total_human_speakers"])


def wav_path(key):
    return os.path.join(FIXTURES, f"benchmark_{key}.wav")


def wav_duration_s(path):
    import wave
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def extract_segments(diarization):
    """Annotation -> [{start_ms, end_ms, spk}]，按 start 排序。"""
    segs = []
    for turn, _, label in diarization.itertracks(yield_label=True):
        segs.append({"start": int(round(turn.start * 1000)),
                     "end": int(round(turn.end * 1000)),
                     "spk": str(label)})
    segs.sort(key=lambda s: (s["start"], s["end"]))
    return segs


def write_rttm(path, key, segs):
    lines = []
    for s in segs:
        dur = max(0.0, (s["end"] - s["start"]) / 1000.0)
        lines.append(f"SPEAKER {key} 1 {s['start'] / 1000.0:.3f} {dur:.3f} "
                     f"<NA> <NA> {s['spk']} <NA> <NA>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def hf_cache_size_mb():
    """统计 HF hub cache 中 pyannote 相关模型的落盘体积（MB）。"""
    root = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
    total = 0
    if os.path.isdir(root):
        for r, _dirs, files in os.walk(root):
            if "pyannote" not in r:
                continue
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(r, fn))
                except OSError:
                    pass
    return round(total / 1024 / 1024, 1)


def cuda_available():
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def run_one(pipeline, key, mode):
    wp = wav_path(key)
    dur = wav_duration_s(wp)
    n_spk = load_gt_total(key) if mode == "oracle" else None
    t0 = time.perf_counter()
    diar = pipeline(wp, num_speakers=n_spk)
    t_infer = time.perf_counter() - t0
    return extract_segments(diar), t_infer, dur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto", "oracle"], default="auto")
    ap.add_argument("--keys", nargs="*", default=KEYS)
    ap.add_argument("--warm", action="store_true",
                    help="每个 fixture 同进程再推理一遍，记录 warm 耗时")
    ap.add_argument("--endpoint", default=None,
                    help="覆盖 HF_ENDPOINT（如 https://hf-mirror.com）；不传=官方")
    args = ap.parse_args()
    if args.endpoint:
        os.environ["HF_ENDPOINT"] = args.endpoint

    os.makedirs(OUT_DIR, exist_ok=True)

    t0 = time.perf_counter()
    from pyannote.audio import Pipeline
    t_import = time.perf_counter() - t0

    t0 = time.perf_counter()
    # token 由 huggingface_hub 从 HF_TOKEN / 标准缓存文件自动读取
    pipeline = Pipeline.from_pretrained(MODEL_ID)
    t_init = time.perf_counter() - t0

    print(f"model={MODEL_ID} mode={args.mode} "
          f"endpoint={os.environ.get('HF_ENDPOINT', 'official(default)')} "
          f"device={'cuda' if cuda_available() else 'cpu'}", flush=True)
    print(f"import={t_import:.1f}s init={t_init:.1f}s", flush=True)

    for key in args.keys:
        segs, t_infer, dur = run_one(pipeline, key, args.mode)

        t_warm = None
        if args.warm:
            segs2, t_warm, _ = run_one(pipeline, key, args.mode)
            if segs2 != segs:
                print(f"[{key}] WARN: warm 推理结果与 cold 不一致", flush=True)

        n_spk_pred = len({s["spk"] for s in segs})
        out = {
            "key": key, "model": MODEL_ID, "mode": args.mode,
            "num_speakers_param": load_gt_total(key) if args.mode == "oracle" else None,
            "predicted_speakers": sorted({s["spk"] for s in segs}),
            "predicted_speaker_count": n_spk_pred,
            "duration_s": round(dur, 2),
            "rtf": round(t_infer / dur, 3) if dur else None,
            "timing": {"import_s": round(t_import, 2),
                       "init_s": round(t_init, 2),
                       "infer_s": round(t_infer, 2),
                       "warm_infer_s": round(t_warm, 2) if t_warm else None,
                       "total_cold_s": round(t_import + t_init + t_infer, 2)},
            "segment_count": len(segs),
            "hf_cache_mb": hf_cache_size_mb(),
            "device": "cuda" if cuda_available() else "cpu",
            "segments": segs,
        }
        jp = os.path.join(OUT_DIR, f"{key}.{args.mode}.json")
        rp = os.path.join(OUT_DIR, f"{key}.{args.mode}.rttm")
        with open(jp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        write_rttm(rp, key, segs)
        print(f"[{key}] speakers={n_spk_pred} segments={len(segs)} "
              f"infer={out['timing']['infer_s']}s rtf={out['rtf']} -> {jp}",
              flush=True)

    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
