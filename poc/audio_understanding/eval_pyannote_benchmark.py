# -*- coding: utf-8 -*-
"""eval_pyannote_benchmark.py —— pyannote 结果用与 CAM++ 完全相同的协议评估

复用 eval_speaker_benchmark.py 的 load_gt / match_switches / attribution / 容差，
保证两轮对照可比：
  - switches：segments 按 start 排序后，相邻 segment spk 变化处取后一个 start
    （与 CAM++ 的"新句子开始且 spk 变化"同构）
  - attribution：多说话人同时活跃的 overlap 区间剔除，时长单独报告
    （CAM++ 轮无 overlap 概念，pyannote 轮按约定排除并如实计数）
用法：
  python eval_pyannote_benchmark.py --mode auto
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from eval_speaker_benchmark import (  # noqa: E402
    PRIMARY_TOL_MS, TOLERANCES_MS, attribution, load_gt, match_switches)

BENCH_DIR = os.path.join(HERE, "outputs", "bench_pyannote")
KEYS = ["t2_0274_0360", "t2_2630_2685"]


def load_pred_pyannote(key, mode):
    with open(os.path.join(BENCH_DIR, f"{key}.{mode}.json"), encoding="utf-8") as f:
        d = json.load(f)
    pool = [s for s in d["segments"] if s["end"] > s["start"]]
    pool.sort(key=lambda s: (s["start"], s["end"]))
    switches = [pool[k]["start"] for k in range(1, len(pool))
                if pool[k]["spk"] != pool[k - 1]["spk"]]
    spks = sorted({s["spk"] for s in pool})

    # overlap 剔除：在所有边界处切开时间轴，只有单一说话人活跃的片段保留
    bounds = sorted({s["start"] for s in pool} | {s["end"] for s in pool})
    clean, overlap_ms = [], 0
    for a, b in zip(bounds, bounds[1:]):
        active = [s for s in pool if s["start"] <= a and s["end"] >= b]
        if not active:
            continue
        if len({s["spk"] for s in active}) == 1:
            clean.append({"start": a, "end": b, "spk": active[0]["spk"]})
        else:
            overlap_ms += b - a

    return {"clean_sentences": clean, "switches": switches, "spks": spks,
            "overlap_ms": overlap_ms, "segment_count": len(pool),
            "meta": {k: v for k, v in d.items() if k != "segments"},
            "timing": d["timing"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["auto", "oracle"], default="auto")
    args = ap.parse_args()

    results = {}
    for key in KEYS:
        gt = load_gt(key)
        pred = load_pred_pyannote(key, args.mode)
        r = {
            "gt": {
                "human_total": gt["human_total"],
                "human_switch_count": len(gt["switches"]),
                "human_switches_ms": [round(s["t_ms"]) for s in gt["switches"]],
                "excluded_labels": [l["idx"] for l in gt["excluded_labels"]],
            },
            "pred": {
                "cluster_count": len(pred["spks"]),
                "segment_count": pred["segment_count"],
                "pred_switch_count": len(pred["switches"]),
                "pred_switches_ms": pred["switches"],
                "overlap_excluded_ms": pred["overlap_ms"],
            },
            "count": {"pred": len(pred["spks"]), "human": gt["human_total"],
                      "correct": len(pred["spks"]) == gt["human_total"]},
            "switch": {},
            "attribution": attribution(pred["clean_sentences"], gt["labels"],
                                       gt["human_spks"], pred["spks"]),
            "timing": pred["timing"],
        }
        for tol in TOLERANCES_MS:
            matched = match_switches(pred["switches"],
                                     [s["t_ms"] for s in gt["switches"]], tol)
            tp = len(matched)
            r["switch"][str(tol)] = {
                "recall": round(tp / len(gt["switches"]), 3) if gt["switches"] else None,
                "precision": round(tp / len(pred["switches"]), 3) if pred["switches"] else None,
                "tp": tp,
            }
        results[f"{key}/{args.mode}"] = r
        sw = r["switch"][str(PRIMARY_TOL_MS)]
        att = r["attribution"]["accuracy"]
        att_s = f"{att * 100:.1f}%" if att is not None else "N/A"
        print(f"[{key}/{args.mode}] count {len(pred['spks'])}/{gt['human_total']} "
              f"({'OK' if r['count']['correct'] else 'X'}) "
              f"switch R={sw['recall']} P={sw['precision']} (+-{PRIMARY_TOL_MS}ms) "
              f"attribution={att_s} "
              f"mapping={r['attribution']['mapping']} "
              f"overlap_excluded={pred['overlap_ms']}ms", flush=True)

    out = os.path.join(HERE, "outputs", "pyannote_benchmark_eval.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"tolerances_ms": TOLERANCES_MS,
                   "primary_tol_ms": PRIMARY_TOL_MS, "results": results},
                  f, ensure_ascii=False, indent=2)
    print(f"-> {out}", flush=True)


if __name__ == "__main__":
    main()
