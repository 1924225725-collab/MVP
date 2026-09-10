"""PoC: 验证 pause_burst(停顿后爆发) 是否命中 A3 已确认的高光事件时间
对照 highlights_v2.json (A3 结果) 的 A/B 事件区间 vs pause_burst 热点
目的: 初步验证"能量信号与真高光相关", 决定 YamNet 是否值得跑
"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ts2s(t):
    p = t.split(":")
    if len(p) == 2:
        return int(p[0]) * 60 + int(p[1])
    if len(p) == 3:
        return int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
    return int(p[0])


def fmt(sec):
    s = int(sec)
    return f"{s//60:02d}:{s%60:02d}"


def main():
    hl = json.load(open("highlights_v2.json", encoding="utf-8"))
    hot = json.load(open("poc/energy_hotspots.json", encoding="utf-8"))
    pb = [x for x in hot if x["type"] == "pause_burst"]

    # A/B 高光事件区间(用户人工最可能认可的高光)
    events = [h for h in hl["highlights"] + hl["rejected"] if h["grade"] in ("A", "B", "C")]
    events.sort(key=lambda x: ts2s(x["end_time"]))

    print("=== pause_burst 是否落在 A/B/C 事件时间内 ===")
    hit = 0
    for x in sorted(pb, key=lambda v: -v["peak"])[:40]:  # 只看最强的40个
        xs, xe = x["start"], x["end"]
        in_ev = None
        for e in events:
            es, ee = ts2s(e["start_time"]), ts2s(e["end_time"])
            # 热点中心落在事件范围内, 或热点与事件重叠>50%
            cx = (xs + xe) / 2
            if es <= cx <= ee:
                in_ev = e
                break
        if in_ev:
            hit += 1
            mark = "HIT"
        else:
            mark = "miss"
        print(f"  [{mark}] pause@ {fmt(xs)} peak={x['peak']:.3f}"
              + (f"  -> {in_ev['grade']} {in_ev['event_id']} {in_ev['start_time']}-{in_ev['end_time']} {in_ev.get('title','')[:20]}"
                 if in_ev else ""))

    total = len([x for x in pb if x["peak"] >= 0.24])
    print(f"\n最强pause_burst(peak>=0.24) {total} 个中命中A/B/C事件: 需人工判断(上表前40)")
    print(f"注: 命中=停顿后爆发点落在某高光事件区间中心")


if __name__ == "__main__":
    main()
