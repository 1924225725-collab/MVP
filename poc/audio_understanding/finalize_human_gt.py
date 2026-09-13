# -*- coding: utf-8 -*-
"""finalize_human_gt.py —— 把填好的 turn sheet 合入正式 speaker GT json

输入：
  fixtures/speaker_turn_sheet_<key>.txt   人工已填数字的填表
  outputs/scan/human_gt_parse_<key>.json  AAA 解析摘要（总人数等）
  outputs/scan/probe_<key>.json           模型预测（作为 _ai_reference 附在 GT 里）
输出：
  fixtures/speaker_ground_truth_<key>.json 覆盖为人工确认版（模板 → 正式 GT）

行解析规则：
  - 编号行：`NN [约x–ys] 说话人=N__ 文本` → 一个子轮次
  - 编号行下方紧跟的非注释续行（如 "1热吗"）= 人工把上一行又拆了一刀：
      数字 = 新子轮次说话人，文字 = 新子轮次文本，时间 = 上一行区间按字数比例分摊
  - 有未填行 → 不写 GT，报出缺哪些行
"""

import argparse
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
SCAN_DIR = os.path.join(HERE, "outputs", "scan")

ROW_RE = re.compile(r"^(\d{1,3})\s+\[约([^\]]+)\]\s*说话人\s*=\s*(.*)$")
CONT_RE = re.compile(r"^([0-9?]+)\s*(.+)$")
SHEET_TOTAL_RE = re.compile(r"总人数这行还是\s*(\d+)")
# "=1__ 文本" / "=_1_ 文本" / "=__ 文本" → 下划线与数字任意混排的说话人 token
SPK_TOKEN_RE = re.compile(r"[_\s]*([0-9?]*)[_\s]*(.*)$", re.S)


def parse_spk_token(after):
    m = SPK_TOKEN_RE.match(after)
    return m.group(1), m.group(2).strip()


def parse_est(s):
    a, b = s.replace("s", "").split("–")
    return int(float(a) * 1000), int(float(b) * 1000)


def parse_sheet(path):
    turns, missing = [], []
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for ln in lines:
        if not ln or ln.startswith("#") or ln.startswith("总人数"):
            continue
        m = ROW_RE.match(ln)
        if m:
            idx, est = int(m.group(1)), m.group(2)
            spk, text = parse_spk_token(m.group(3))
            a, b = parse_est(est)
            turns.append({"idx": idx, "est": [a, b], "spk": spk,
                          "text": text, "extra": False})
            if not spk:
                missing.append(idx)
            continue
        m = CONT_RE.match(ln)
        if m and turns:
            prev = turns[-1]
            spk, text = m.group(1), m.group(2).strip()
            a, b = prev["est"]
            ratio = len(prev["text"]) / max(1, len(prev["text"]) + len(text))
            cut = a + (b - a) * ratio
            prev["est"] = [a, int(cut)]
            turns.append({"idx": None, "est": [int(cut), b], "spk": spk,
                          "text": text, "extra": True})
    return turns, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    args = ap.parse_args()

    sheet = os.path.join(FIXTURES, f"speaker_turn_sheet_{args.key}.txt")
    parsej = os.path.join(SCAN_DIR, f"human_gt_parse_{args.key}.json")
    probe = os.path.join(SCAN_DIR, f"probe_{args.key}.json")
    gt_path = os.path.join(FIXTURES, f"speaker_ground_truth_{args.key}.json")

    turns, missing = parse_sheet(sheet)
    with open(parsej, encoding="utf-8") as f:
        meta = json.load(f)
    # 总人数：优先解析摘要里的"总人数 N"，否则认填表注释里"总人数这行还是 N"的人工回答
    total = meta.get("total_human_speakers")
    if total is None:
        with open(sheet, encoding="utf-8") as f:
            m = SHEET_TOTAL_RE.search(f.read())
        if m:
            total = int(m.group(1))
    if missing:
        print(f"[{args.key}] 未完成：{len(missing)} 行没填数字 → {missing}")
        print("GT 未写入。把表格填完再跑一次。")
        return

    # 顺序重排 idx；说话人 → human_spk_0N
    labels = []
    for i, t in enumerate(turns, 1):
        spk = ",".join(f"human_spk_{int(d):02d}" for d in t["spk"])
        note = "人工续行拆分" if t["extra"] else ""
        labels.append({"idx": i, "speaker": spk, "text": t["text"],
                       "est_start_ms": t["est"][0], "est_end_ms": t["est"][1],
                       "time_precision": "估算（按 AAA 字符位置线性插值，未经精听校时）",
                       "_note": note})

    ai_ref = {}
    if os.path.exists(probe):
        with open(probe, encoding="utf-8") as f:
            p = json.load(f)
        ai_ref = {"_note": "模型预测，仅供对照",
                  "predicted_runs": p["ai_reference"]["predicted_runs"],
                  "predicted_switch_points_ms": p["ai_reference"]["predicted_switch_points_ms"]}

    gt = {
        "_readme": [
            "人工 GT（正式版）。标注方法 = AAA 标注法：内容文字里插 ≥3 个 A = 说话人切换点；",
            "说话人身份由人工在 turn sheet 逐行填写（2026-09-12）。",
            "est_* 时间为估算值；边界精校时（如需计算边界误差指标）需人工精听复核。",
        ],
        "_source": meta["_source"] if "_source" in meta else
                   {"file": meta["wav"], "duration_ms": meta["duration_ms"]},
        "_filled_by": "human (AAA 标注法 + turn sheet, 2026-09-12)",
        "annotation_method": "AAA(≥3个A=切换点) + turn sheet 逐行填数字",
        "total_human_speakers": total,
        "labels": labels,
        "_ai_reference": ai_ref,
        "_unresolved": (["「就AAAA这」打了 4 个 A，按 1 次切换处理，人工未另作说明"]
                        if args.key == "t2_2630_2685" else []),
    }
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(gt, f, ensure_ascii=False, indent=2)

    seq = "→".join(l["speaker"].replace("human_spk_0", "") for l in labels)
    n_sw = sum(1 for a, b in zip(labels, labels[1:]) if a["speaker"] != b["speaker"])
    print(f"[{args.key}] GT 已写入: {gt_path}")
    print(f"  子轮次={len(labels)} 总人数={total} 实际切换={n_sw}")
    print(f"  人工序列: {seq}")


if __name__ == "__main__":
    main()
