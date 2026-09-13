# -*- coding: utf-8 -*-
"""parse_human_gt.py —— 解析人工 AAA 标注 → 说话人填表（turn sheet）+ 结构化摘要

用户标注约定（2026-09-12 确认）：
  - 在内容文字里插入 3 个以上连续 A = 这个位置发生了说话人切换
  - 说话人栏（human_spk_XX、human_spk_YY）= 该时间段里出现过的所有人（共现式，不代表谁切给谁）
  - 切换到了谁暂未标注 → 由 turn sheet 逐行补填

解析输入：fixtures/speaker_ground_truth_<key>.txt（人工已填）
输出：
  fixtures/speaker_turn_sheet_<key>.txt   逐行填表（每行末尾填一个数字）
  outputs/scan/human_gt_parse_<key>.json  结构化摘要（子轮次 + 估算切换点 + 疑点标记）
"""

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
SCAN_DIR = os.path.join(HERE, "outputs", "scan")

BLOCK_RE = re.compile(r"^# 段(\d+) 模型判：.*?（([\d.]+)s–([\d.]+)s） —— 内容：(.*)$")
SENT_RE = re.compile(r"^#\s*([\d.]+)\s*[-–]\s*([\d.]+)\s+spk-\d+\s+(.*)$")
PEOPLE_RE = re.compile(r"[hH]?uman_spk_(\d+)")
TOTAL_RE = re.compile(r"^总人数\s*(\d+|TODO)\s*$", re.M)
TOTAL_COMMENT_RE = re.compile(r"# 把下面的\s*(\S+)\s*改成数字")
SPLIT_RE = re.compile(r"A{3,}")


def parse_annotated(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    anchors = []          # {kind, seg, start_ms, end_ms, content}
    people_by_seg = {}    # 段号 -> [1,2,3]（来自说话人栏，按"最近段注释"归属）
    for ln in lines:
        m = BLOCK_RE.match(ln)
        if m:
            anchors.append({"kind": "block", "seg": int(m.group(1)),
                            "start_ms": int(float(m.group(2)) * 1000),
                            "end_ms": int(float(m.group(3)) * 1000),
                            "content": m.group(4)})
            continue
        m = SENT_RE.match(ln)
        if m:
            anchors.append({"kind": "sentence", "seg": None,
                            "start_ms": int(float(m.group(1))),
                            "end_ms": int(float(m.group(2))),
                            "content": m.group(3)})
            continue
        # 非注释数据行：<start><end><说话人栏>（容忍缺空格/缺字母，如 "85620human_spk_01"、"uman_spk_01"）
        if ln and not ln.startswith("#") and not ln.startswith("总人数"):
            people = sorted({int(x) for x in PEOPLE_RE.findall(ln.lower())})
            if people and anchors:
                last_seg = anchors[-1]["seg"]
                if last_seg is not None:
                    people_by_seg[last_seg] = people
    total_m = TOTAL_RE.search("\n".join(lines))
    total = int(total_m.group(1)) if total_m and total_m.group(1) != "TODO" else None
    total_comment = TOTAL_COMMENT_RE.search("\n".join(lines))
    comment_hint = total_comment.group(1) if total_comment else None
    return anchors, people_by_seg, total, comment_hint


def choose_anchors(anchors):
    """段级注释和逐句参考是同一区域的两种粒度——哪级带了 AAA 标注就用哪级。"""
    sent_has = any(SPLIT_RE.search(a["content"]) for a in anchors if a["kind"] == "sentence")
    block_has = any(SPLIT_RE.search(a["content"]) for a in anchors if a["kind"] == "block")
    if sent_has:
        return [a for a in anchors if a["kind"] == "sentence"], "sentence"
    if block_has:
        return [a for a in anchors if a["kind"] == "block"], "block"
    return anchors, "all"


def split_turns(anchor):
    """按 A{3,} 拆子轮次；返回 (subturns, a_run_flags)。时间 = 按字符位置线性插值的估算。"""
    content = anchor["content"]
    dur = max(1, anchor["end_ms"] - anchor["start_ms"])
    parts = SPLIT_RE.split(content)
    runs = SPLIT_RE.findall(content)
    flags = [f"A×{len(r)}" for r in runs if len(r) != 3]
    # 计算每个子轮次在原文里的字符区间 → 估算时间
    est, pos = [], 0
    for p in parts:
        start_char, end_char = pos, pos + len(p)
        pos = end_char + 3  # 跳过 AAA
        est.append((anchor["start_ms"] + dur * start_char / max(1, len(content)),
                    anchor["start_ms"] + dur * end_char / max(1, len(content))))
    subturns = []
    for p, (s, e) in zip(parts, est):
        t = p.strip()
        if not t:
            continue
        subturns.append({"text": t,
                         "est_start_ms": int(s), "est_end_ms": int(e)})
    return subturns, flags


def main():
    jobs = [
        ("t2_2630_2685", "benchmark_t2_2630_2685.wav", 54730),
        ("t2_0274_0360", "benchmark_t2_0274_0360.wav", 85640),
    ]
    for key, wav, dur in jobs:
        path = os.path.join(FIXTURES, f"speaker_ground_truth_{key}.txt")
        anchors, people_by_seg, total, comment_hint = parse_annotated(path)
        chosen, level = choose_anchors(anchors)
        whole_people = sorted({p for v in people_by_seg.values() for p in v})
        all_turns, all_flags = [], []
        for a in chosen:
            subs, flags = split_turns(a)
            all_flags += flags
            for s in subs:
                all_turns.append({"seg": a["seg"], "kind": a["kind"],
                                  "anchor": [a["start_ms"], a["end_ms"]],
                                  "people_in_seg": people_by_seg.get(a["seg"],
                                                                     whole_people if level == "sentence" else []),
                                  **s})
        # ── turn sheet ──
        ls = []
        ls.append(f"# 说话人填表 —— {wav}（{dur / 1000:.1f} 秒）")
        ls.append("# 来源：你标注的 AAA 切换点，已自动拆成下面 %d 行" % len(all_turns))
        ls.append("#")
        ls.append("# 填法（很简单）：每行【说话人=】后面写一个数字（1 / 2 / 3）。")
        ls.append("#   ★ 同一个真人从头到尾用同一个数字 ★")
        ls.append("#   这一行是两个人同时说的：写 12 / 23 这种；听不清：写 ?，# 后补一句原因")
        ls.append("#   行拆分不对（AAA 位置不对/多打了 A）：不用改行，# 后写\"第 N 行应该是…\"")
        ls.append("#   时间是按文字位置估算的，仅供对照音频定位，不用改")
        ls.append("#")
        # 先按 seg 分组，再统一编号（组头显示该组真实覆盖的时间范围）
        groups = []
        for t in all_turns:
            if groups and groups[-1][0] == t["seg"]:
                groups[-1][1].append(t)
            else:
                groups.append((t["seg"], [t]))
        idx = 0
        for seg, ts in groups:
            ppl_set = ts[0]["people_in_seg"]
            ppl = "、".join(f"human_spk_{p:02d}" for p in ppl_set) or "（你标了哪些人？）"
            span = f"{ts[0]['anchor'][0] / 1000:.1f}–{ts[-1]['anchor'][1] / 1000:.1f}s"
            label = f"段{seg}" if seg is not None else "逐句"
            ls.append(f"# ── {label} {span}（你标了这里有：{ppl}）──")
            for t in ts:
                idx += 1
                est = f"{t['est_start_ms'] / 1000:.1f}–{t['est_end_ms'] / 1000:.1f}s"
                ls.append(f"{idx:02d} [约{est}] 说话人=__  {t['text']}")
        ls.append("#")
        ls.append("# 填完这表，说话人身份就齐了——我会把它合回 speaker_ground_truth json")
        if all_flags:
            ls.append("#")
            ls.append("# 【疑点】这几处你打的 A 不是 3 个：" + "；".join(all_flags)
                      + " ← 都按 1 次切换处理了，如果不对请说明")
        if total is None:
            ls.append("# 【待确认】总人数这行还是 TODO"
                      + ("（你在注释里写了 " + comment_hint + "，是听到了 " + comment_hint + " 个人吗？）"
                         if comment_hint and comment_hint != "TODO" else "——请补一个数字"))
        else:
            ls.append(f"# 总人数（你填的）：{total}")
        sheet_path = os.path.join(FIXTURES, f"speaker_turn_sheet_{key}.txt")
        with open(sheet_path, "w", encoding="utf-8") as f:
            f.write("\n".join(ls) + "\n")

        # ── 结构化摘要 ──
        n_markers = len(SPLIT_RE.findall(" ".join(a["content"] for a in chosen)))
        summary = {
            "key": key, "wav": f"fixtures/{wav}", "duration_ms": dur,
            "anchor_level": level,
            "total_human_speakers": total,
            "total_comment_hint": comment_hint,
            "people_by_seg": {str(k): v for k, v in people_by_seg.items()},
            "anchors": len(chosen),
            "aaa_switch_markers": n_markers,
            "subturns": len(all_turns),
            "a_run_flags": all_flags,
            "turns": all_turns,
            "_note": "est_* 均为按字符位置线性插值的估算，正式切换点以人工复核为准",
        }
        out = os.path.join(SCAN_DIR, f"human_gt_parse_{key}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"[{key}] level={level} anchors={len(chosen)} aaa_markers={n_markers} "
              f"subturns={len(all_turns)} total={total} "
              f"flags={all_flags or '无'} -> {sheet_path}")


if __name__ == "__main__":
    main()
