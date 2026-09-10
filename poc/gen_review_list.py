"""生成人工复核清单: 高置信 + 文本弱 + A3事件外 的 Top 候选
这些是最可能"音频强、文本系统漏掉"的高光, 需人工对照原视频判断是否真是笑点/尖叫等。
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
    ev_ranges = [(ts2s(e["start_time"]), ts2s(e["end_time"]), e["grade"], e["event_id"]) for e in events]

    # 高置信 + 文本弱
    cand = [h for h in hot if h["kind"] in ("strong_anomaly", "high_freq_burst") and h["text_tag"] == "文本弱"]
    # 排除落在 A 事件区间内的
    outside = []
    for h in cand:
        cx = (h["start"] + h["end"]) / 2
        if not any(es <= cx <= ee for es, ee, *_ in ev_ranges):
            outside.append(h)
    # 按"文本den低优先 + 能量高"排序, 文本den=0/极低的排前面(更像纯音频事件)
    outside.sort(key=lambda x: (x["text_density"], -x["peak_energy"]))

    print("人工复核清单: 高置信音频异常 + 文本弱 + 不在AI已识别事件内")
    print(f"共 {len(outside)} 个, 下面列出前25个(文本den最低/能量最高的优先):\n")
    for i, h in enumerate(outside[:25], 1):
        print(f"{i:2}. {fmt(h['start'])}-{fmt(h['end'])} ({h['dur']}s) "
              f"E={h['peak_energy']:.3f} ZCR={h['peak_zcr']:.2f} "
              f"kind={h['kind']} ASR词数={h['text_density']}")
    print()
    print("请对照原视频 videos/测试视频2.mp4 的时间点, 判断:")
    print("  - 这段是不是笑声/尖叫/惊呼/反应爆发?  y=是 n=否")
    print("  - 如果是, 有没有娱乐价值/值得剪?")
    print("(降级版无法区分真笑声vsBGM鼓点/环境音, 需人工听)")


if __name__ == "__main__":
    main()
