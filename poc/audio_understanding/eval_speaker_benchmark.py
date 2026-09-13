# -*- coding: utf-8 -*-
"""eval_speaker_benchmark.py —— Speaker Benchmark 指标评估（PoC，不接生产）

输入：
  outputs/bench/<key>.<config>.json          4 份推理结果（A/B × 2 fixture）
  fixtures/speaker_ground_truth_<key>.json   人工确认 GT
输出：
  outputs/speaker_benchmark_eval.json        全部指标 + 明细
  控制台摘要

指标（与任务约定一致）：
  1. Speaker Count Accuracy      预测簇数 vs 人工真实人数
  2. Speaker Change Detection    人工切换点的 recall / precision（一对一贪心匹配）
  3. Speaker Attribution         簇→人 穷举最佳映射后的时长加权正确率
  - unsure / 多人共现轮次从 attribution 排除，单独计数
  - GT 切换点是字符插值估算（精度约 ±1~2s），主容差 ±1.5s，附 ±1.0/±2.0 敏感性
"""

import glob
import itertools
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
BENCH_DIR = os.path.join(HERE, "outputs", "bench")

TOLERANCES_MS = [1000, 1500, 2000]
PRIMARY_TOL_MS = 1500

KEYS = ["t2_0274_0360", "t2_2630_2685"]
CONFIGS = ["A", "B"]


def load_gt(key):
    with open(os.path.join(FIXTURES, f"speaker_ground_truth_{key}.json"),
              encoding="utf-8") as f:
        gt = json.load(f)
    labels = gt["labels"]
    human_spks = sorted({l["speaker"] for l in labels if l["speaker"] != "unsure"})
    excluded = [l for l in labels
                if l["speaker"] == "unsure" or "," in l["speaker"]]
    switches = []
    for a, b in zip(labels, labels[1:]):
        if a["speaker"] != b["speaker"]:
            mid = (a["est_end_ms"] + b["est_start_ms"]) / 2.0
            switches.append({"t_ms": mid, "from": a["speaker"], "to": b["speaker"]})
    return {"labels": labels, "human_spks": human_spks,
            "human_total": gt["total_human_speakers"],
            "switches": switches, "excluded_labels": excluded}


def load_pred(key, config):
    with open(os.path.join(BENCH_DIR, f"{key}.{config}.json"), encoding="utf-8") as f:
        d = json.load(f)
    sents = [s for s in d["raw"]["sentence_info"]]
    pool = [s for s in sents if s.get("spk") is not None and s.get("end", 0) > s.get("start", 0)]
    pool.sort(key=lambda s: s["start"])
    switches = [pool[k]["start"] for k in range(1, len(pool))
                if pool[k]["spk"] != pool[k - 1]["spk"]]
    spks = sorted({s["spk"] for s in pool})
    runs = []
    cur = None
    for s in pool:
        if cur is None or s["spk"] != cur["spk"]:
            if cur is not None:
                runs.append(cur)
            cur = {"spk": s["spk"], "start_ms": s["start"], "end_ms": s["end"], "n": 1}
        else:
            cur["end_ms"] = s["end"]
            cur["n"] += 1
    if cur is not None:
        runs.append(cur)
    unattributed_ms = sum(s.get("end", 0) - s.get("start", 0)
                          for s in sents if s.get("spk") is None)
    return {"sentences": pool, "switches": switches, "spks": spks,
            "runs": runs, "unattributed_ms": unattributed_ms,
            "sentence_count": len(sents), "timing": d["timing"]}


def match_switches(pred_ts, human_ts, tol_ms):
    """一对一贪心：按距离升序锁定互不重复的匹配。"""
    pairs = sorted((abs(p - h), p, h) for p in pred_ts for h in human_ts)
    used_p, used_h, matched = set(), set(), []
    for dist, p, h in pairs:
        if dist <= tol_ms and p not in used_p and h not in used_h:
            used_p.add(p)
            used_h.add(h)
            matched.append({"pred_ms": p, "human_ms": h, "dist_ms": round(dist)})
    return matched


def attribution(pred_sentences, labels, human_spks, pred_spks):
    """时长加权混淆矩阵 + 穷举最佳映射（允许多簇→同人）。"""
    matrix = {c: {h: 0 for h in human_spks} for c in pred_spks}
    total_ov = 0
    for s in pred_sentences:
        for l in labels:
            if l["speaker"] == "unsure" or "," in l["speaker"]:
                continue  # 排除区
            ov = min(s["end"], l["est_end_ms"]) - max(s["start"], l["est_start_ms"])
            if ov > 0:
                matrix[s["spk"]][l["speaker"]] += ov
                total_ov += ov
    if not pred_spks or total_ov <= 0:
        return {"accuracy": None, "mapping": {}, "matrix_ms": matrix,
                "total_overlap_ms": total_ov}
    best_map, best_correct = None, -1
    for mapping in itertools.product(human_spks, repeat=len(pred_spks)):
        m = dict(zip(pred_spks, mapping))
        correct = sum(matrix[c][m[c]] for c in pred_spks)
        if correct > best_correct:
            best_correct, best_map = correct, m
    return {"accuracy": round(best_correct / total_ov, 4),
            "mapping": {str(k): v for k, v in best_map.items()},
            "matrix_ms": matrix, "total_overlap_ms": total_ov}


def main():
    results = {}
    for key in KEYS:
        gt = load_gt(key)
        for config in CONFIGS:
            pred = load_pred(key, config)
            r = {
                "gt": {
                    "human_total": gt["human_total"],
                    "human_switch_count": len(gt["switches"]),
                    "human_switches_ms": [round(s["t_ms"]) for s in gt["switches"]],
                    "excluded_labels": [l["idx"] for l in gt["excluded_labels"]],
                },
                "pred": {
                    "cluster_count": len(pred["spks"]),
                    "sentence_count": pred["sentence_count"],
                    "pred_switch_count": len(pred["switches"]),
                    "pred_switches_ms": pred["switches"],
                    "run_count": len(pred["runs"]),
                    "unattributed_ms": pred["unattributed_ms"],
                },
                "count": {"pred": len(pred["spks"]), "human": gt["human_total"],
                          "correct": len(pred["spks"]) == gt["human_total"]},
                "switch": {},
                "attribution": attribution(pred["sentences"], gt["labels"],
                                           gt["human_spks"], pred["spks"]),
                "runs": pred["runs"],
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
            results[f"{key}/{config}"] = r
            sw = r["switch"][str(PRIMARY_TOL_MS)]
            att = r["attribution"]["accuracy"]
            att_s = f"{att * 100:.1f}%" if att is not None else "N/A"
            print(f"[{key}/{config}] count {len(pred['spks'])}/{gt['human_total']} "
                  f"({'✓' if r['count']['correct'] else '✗'}) "
                  f"switch R={sw['recall']} P={sw['precision']} (±{PRIMARY_TOL_MS}ms) "
                  f"attribution={att_s} "
                  f"mapping={r['attribution']['mapping']}", flush=True)

    out = os.path.join(HERE, "outputs", "speaker_benchmark_eval.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"tolerances_ms": TOLERANCES_MS, "primary_tol_ms": PRIMARY_TOL_MS,
                   "results": results}, f, ensure_ascii=False, indent=2)
    print(f"-> {out}", flush=True)


if __name__ == "__main__":
    main()
