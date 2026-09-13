# eval_ab.py —— ct-punc A/B 结果 vs 人工 GT 的结构性对比（不猜 GT）
#
# 用法: .venv-audio-poc/Scripts/python eval_ab.py
# 输入: outputs/ab/{A,B}_run{1,2,3}.json + fixtures/speaker_ground_truth_000_090.json
# 输出: outputs/ab_eval.json（机器可读） + stdout 摘要（供报告引用）
#
# 评估原则（用户指令）：
#   - GT 与模型冲突时以 GT 为准，绝不把 GT 重释为"人工标错"。
#   - GT 是共现数组、无 sub-turn 边界 → 只做结构性对比（人数 / turn 结构 /
#     分段覆盖 / ID 时序一致性），不做边界级 DER，不做逐句归属判分。
#   - A 组文本带 SenseVoice rich token（<|zh|><|ANGRY|>…）：
#     标点检测 / 文本对比一律先剥 token，否则会把 token 竖线误判为标点。

import json
import os
import re
import statistics
import difflib

HERE = os.path.dirname(os.path.abspath(__file__))
AB = os.path.join(HERE, "outputs", "ab")
GT_PATH = os.path.join(HERE, "fixtures", "speaker_ground_truth_000_090.json")
OUT_PATH = os.path.join(HERE, "outputs", "ab_eval.json")

RUNS = [1, 2, 3]
GROUPS = ["A", "B"]

PUNCT_CHARS = set("，。！？、；：·…—,.!?;:\"'`“”‘’()（）[]【】<>《》|/\\~～@#￥%&*-_=+\u3000")
TOKEN_RE = re.compile(r"<\|[^|]*\|>")


def strip_tokens(text):
    """去掉 SenseVoice rich token（<|zh|><|ANGRY|>…），只留正文。"""
    return TOKEN_RE.sub("", text or "")


def strip_punct(text):
    return "".join(ch for ch in (text or "") if ch not in PUNCT_CHARS and not ch.isspace())


def norm_text(text):
    """去 rich token + 去标点/空白，用于内容级对比。"""
    return strip_punct(strip_tokens(text))


def has_punct(text):
    return any(ch in PUNCT_CHARS for ch in strip_tokens(text))


def overlap_ms(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


def load_run(group, n):
    with open(os.path.join(AB, f"{group}_run{n}.json"), encoding="utf-8") as f:
        return json.load(f)


def turns(sentences, gap_ms=800):
    """连续同 spk 合并为一个 turn；同 spk 且间隔<gap_ms 并入（同 run_funasr 规则）。"""
    ts = []
    for s in sentences:
        sid = s.get("spk")
        if ts and ts[-1]["spk"] == sid and s["start"] - ts[-1]["end"] < gap_ms:
            ts[-1]["end"] = max(ts[-1]["end"], s["end"])
            ts[-1]["n"] += 1
        else:
            ts.append({"spk": sid, "start": s["start"], "end": s["end"], "n": 1})
    return ts


def spk_runs(sentences):
    """不做 gap 合并的原始连续同 spk 段数。"""
    n = 0
    prev = object()
    for s in sentences:
        if s.get("spk") != prev:
            n += 1
            prev = s.get("spk")
    return n


def run_stats(j, gt):
    sents = j["raw"]["sentence_info"]
    timing = j["timing"]
    t = turns(sents)
    durs = [s["end"] - s["start"] for s in sents]
    spks = sorted({s.get("spk") for s in sents if s.get("spk") is not None})
    per_spk = {
        sid: {
            "n_sentences": sum(1 for s in sents if s.get("spk") == sid),
            "voiced_ms": sum(s["end"] - s["start"] for s in sents if s.get("spk") == sid),
        }
        for sid in spks
    }
    # GT 分段覆盖：每段内模型各 spk 的时间占比、turn 切换次数、落在 bgm 段的输出
    seg_cov = []
    for lab in gt["labels"]:
        s0, s1 = lab["start_ms"], lab["end_ms"]
        cov = {}
        for s in sents:
            ov = overlap_ms(s["start"], s["end"], s0, s1)
            if ov > 0:
                cov[s.get("spk")] = cov.get(s.get("spk"), 0) + ov
        sw = sum(1 for i in range(1, len(t))
                 if overlap_ms(t[i]["start"], t[i]["end"], s0, s1) > 0
                 and overlap_ms(t[i - 1]["start"], t[i - 1]["end"], s0, s1) > 0
                 and t[i]["spk"] != t[i - 1]["spk"])
        seg_cov.append({
            "seg": [s0, s1], "gt_label": lab["speaker"],
            "model_spk_ms": cov,
            "model_switches_inside": sw,
            "model_sentences_inside": sum(1 for s in sents if overlap_ms(s["start"], s["end"], s0, s1) > 0),
        })
    # 每个 GT 共现段内的"多数派 spk"→ ID 时序一致性 pattern
    pattern = []
    for lab in gt["labels"]:
        if not isinstance(lab["speaker"], list):
            continue
        best = None
        for sid in spks:
            ms = sum(overlap_ms(s["start"], s["end"], lab["start_ms"], lab["end_ms"])
                     for s in sents if s.get("spk") == sid)
            if best is None or ms > best[1]:
                best = (sid, ms)
        pattern.append(best[0] if best else None)
    return {
        "group": j["group"], "run": j["run"],
        "runtime": j["runtime"],
        "n_sentences": len(sents),
        "spk_ids": spks,
        "spk_count": len(spks),
        "per_spk": per_spk,
        "spk_runs_raw": spk_runs(sents),
        "turns_gap800": len(t),
        "sentence_ms": {"mean": round(statistics.mean(durs), 1) if durs else 0,
                        "median": round(statistics.median(durs), 1) if durs else 0,
                        "min": min(durs) if durs else 0, "max": max(durs) if durs else 0},
        "punct_sentence_ratio": round(sum(1 for s in sents if has_punct(s.get("text"))) / len(sents), 3) if sents else 0,
        "terminal_punct_ratio": round(sum(1 for s in sents if strip_tokens(s.get("text"))[-1:] in "。！？!?") / len(sents), 3) if sents else 0,
        "voiced_total_ms": sum(s["end"] - s["start"] for s in sents),
        "sent_with_rich_token": sum(1 for s in sents if "<|" in (s.get("text") or "")),
        "top_text_rich_tokens": "<|" in (j["raw"].get("text") or ""),
        "coverage": seg_cov,
        "majority_spk_pattern": pattern,
        "timing": timing,
    }


def text_of(j):
    return "".join(s.get("text") or "" for s in j["raw"]["sentence_info"])


def seq_signature(j):
    return [(s["start"], s["end"], s.get("spk")) for s in j["raw"]["sentence_info"]]


def main():
    with open(GT_PATH, encoding="utf-8") as f:
        gt = json.load(f)

    data = {(g, n): load_run(g, n) for g in GROUPS for n in RUNS}
    stats = {(g, n): run_stats(data[(g, n)], gt) for g in GROUPS for n in RUNS}

    ev = {"gt_summary": {
        "total_human_speakers": gt["total_human_speakers"],
        "labels": [{"seg": [l["start_ms"], l["end_ms"]], "speaker": l["speaker"]} for l in gt["labels"]],
        "has_sub_turn_boundaries": False,
        "note": "GT 为共现数组，无 sub-turn 边界 → 仅结构性对比",
    }, "runs": {f"{g}_run{n}": stats[(g, n)] for g in GROUPS for n in RUNS}}

    # ---- 组内稳定性（3 run 两两比）----
    stability = {}
    for g in GROUPS:
        s1, s2, s3 = (stats[(g, n)] for n in RUNS)
        d1, d2, d3 = (data[(g, n)] for n in RUNS)
        pair = {}
        for (na, a), (nb, b) in [(("run1", d1), ("run2", d2)), (("run2", d2), ("run3", d3)), (("run1", d1), ("run3", d3))]:
            ta, tb = norm_text(text_of(a)), norm_text(text_of(b))
            pair[f"{na}_vs_{nb}"] = {
                "same_sentence_count": len(a["raw"]["sentence_info"]) == len(b["raw"]["sentence_info"]),
                "same_seq_signature": seq_signature(a) == seq_signature(b),
                "same_stripped_text": ta == tb,
                "text_sim_ratio": round(difflib.SequenceMatcher(None, ta, tb).ratio(), 4),
            }
        stability[g] = {
            "n_sentences": [s1["n_sentences"], s2["n_sentences"], s3["n_sentences"]],
            "spk_ids": [s1["spk_ids"], s2["spk_ids"], s3["spk_ids"]],
            "majority_spk_pattern": [s1["majority_spk_pattern"], s2["majority_spk_pattern"], s3["majority_spk_pattern"]],
            "pairs": pair,
            "rtf": [s1["timing"]["rtf"], s2["timing"]["rtf"], s3["timing"]["rtf"]],
            "proc_total": [s1["timing"]["proc_total_seconds"], s2["timing"]["proc_total_seconds"], s3["timing"]["proc_total_seconds"]],
        }
    ev["stability"] = stability

    # ---- A vs B 文本对比（去 token + 去标点后）----
    ab_cmp = {}
    for n in RUNS:
        ta, tb = norm_text(text_of(data[("A", n)])), norm_text(text_of(data[("B", n)]))
        ab_cmp[f"run{n}"] = {
            "same_stripped_text": ta == tb,
            "sim_ratio": round(difflib.SequenceMatcher(None, ta, tb).ratio(), 4),
            "len_A": len(ta), "len_B": len(tb),
            "head_A": ta[:60], "head_B": tb[:60],
        }
    ev["A_vs_B_text"] = ab_cmp

    # ---- 切分统计对比（A vs B run1）----
    a1, b1 = stats[("A", 1)], stats[("B", 1)]
    ev["segmentation_A_vs_B"] = {
        "n_sentences": {"A": a1["n_sentences"], "B": b1["n_sentences"]},
        "sentence_ms_mean": {"A": a1["sentence_ms"]["mean"], "B": b1["sentence_ms"]["mean"]},
        "turns_gap800": {"A": a1["turns_gap800"], "B": b1["turns_gap800"]},
        "spk_runs_raw": {"A": a1["spk_runs_raw"], "B": b1["spk_runs_raw"]},
        "voiced_total_ms": {"A": a1["voiced_total_ms"], "B": b1["voiced_total_ms"]},
    }

    # ---- warm RTF / 冷启动 ----
    ev["timing_summary"] = {
        g: {
            "warm_rtf_mean": round(sum(stats[(g, n)]["timing"]["rtf"] for n in RUNS) / 3, 4),
            "warm_rtf_each": [stats[(g, n)]["timing"]["rtf"] for n in RUNS],
            "init_each": [stats[(g, n)]["timing"]["init_seconds"] for n in RUNS],
            "proc_total_each": [stats[(g, n)]["timing"]["proc_total_seconds"] for n in RUNS],
            "note": "每次运行都是全新进程（import→init→infer→output），proc_total 即冷启动总时长",
        } for g in GROUPS
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=2, default=str)

    # ---- stdout 摘要 ----
    for g in GROUPS:
        for n in RUNS:
            s = stats[(g, n)]
            t = s["timing"]
            print(f"[{g}{n}] sent={s['n_sentences']} spk={s['spk_ids']} turns(gap800)={s['turns_gap800']} "
                  f"spk_runs={s['spk_runs_raw']} mean_ms={s['sentence_ms']['mean']} punct={s['punct_sentence_ratio']} "
                  f"terminal={s['terminal_punct_ratio']} voiced={s['voiced_total_ms']} sent_tok={s['sent_with_rich_token']} "
                  f"pattern={s['majority_spk_pattern']} init={t['init_seconds']} infer={t['infer_seconds']} "
                  f"rtf={t['rtf']} proc_total={t['proc_total_seconds']}")
            for c in s["coverage"]:
                print(f"    seg{c['seg']} gt={c['gt_label']} model_spk_ms={c['model_spk_ms']} "
                      f"switches={c['model_switches_inside']} sents={c['model_sentences_inside']}")
    print("stability A:", json.dumps(stability["A"]["pairs"], ensure_ascii=False))
    print("stability B:", json.dumps(stability["B"]["pairs"], ensure_ascii=False))
    print("A_vs_B_text:", json.dumps(ab_cmp, ensure_ascii=False))
    print("timing:", json.dumps(ev["timing_summary"], ensure_ascii=False))
    print("saved ->", OUT_PATH)


if __name__ == "__main__":
    main()
