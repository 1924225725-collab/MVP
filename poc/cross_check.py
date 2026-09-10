"""Audio PoC: 高置信热点 与 A3 已确认高光 + 文本稿 的三方对照
判断"音频强文本弱"热点里，多少是当前文本系统真漏掉的候选。
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
    hot = json.load(open("poc/audio_hotspots.json", encoding="utf-8"))
    d = json.load(open("highlights_v2.json", encoding="utf-8"))
    events = d["highlights"] + d["rejected"]

    # 高置信 + 文本弱的候选
    cand = [h for h in hot if h["kind"] in ("strong_anomaly", "high_freq_burst")
            and h["text_tag"] == "文本弱"]
    cand.sort(key=lambda x: -x["peak_energy"])
    print(f"高置信+文本弱 候选: {len(cand)} 个")

    # 判断每个是否落在任一 AI 事件(A/B/C/D)区间内
    in_ev = 0
    outside = []
    for h in cand:
        cx = (h["start"] + h["end"]) / 2
        hit = None
        for e in events:
            es, ee = ts2s(e["start_time"]), ts2s(e["end_time"])
            if es <= cx <= ee:
                hit = e
                break
        if hit:
            in_ev += 1
        else:
            outside.append((h, hit))

    print(f"  落在 AI 已识别事件区间内: {in_ev} (系统已见, 但文本弱)")
    print(f"  落在 AI 事件区间外: {len(outside)} (文本系统可能完全没抓到 -> 候选漏检高光)")
    print()

    print(f"=== 事件区间外的高置信候选 Top40 (按能量) ===")
    for h, _ in outside[:40]:
        print(f"  {fmt(h['start'])}-{fmt(h['end'])} ({h['dur']}s) E={h['peak_energy']:.3f} "
              f"ZCR={h['peak_zcr']:.2f} kind={h['kind']} 文本den={h['text_density']}")
    print()
    print(f"总: 高置信{len([h for h in hot if h['kind']=='strong_anomaly'])}, "
          f"高置信+文本弱{len(cand)}, 其中事件区间外{len(outside)}")


if __name__ == "__main__":
    main()
