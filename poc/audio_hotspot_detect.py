"""Audio PoC 降级版：本地 numpy 检测"音频异常热点"（不判断是不是笑声，只找异常）

不改任何主流程/A1/A2/A3/prompt/评分/UI。独立脚本，输出存 poc/ 供人工复核。

信号：
  - 短时 RMS 能量（音量）
  - ZCR 过零率（高频/噪声/笑声指示）
  - 突发能量变化（相对前窗）
  - 高能量 + 高 ZCR（"音频异常"，疑似笑声/尖叫/惊呼/干呕的声学特征）

输出每个热点：start/end / 能量 / ZCR / 异常类型候选 / 与 ASR 文本区是否重合
  - 重合 = 该时间段文字稿里有台词(ASR 抓到话)
  - 不重合(文本弱/空) 而音频强 = "音频强文本弱"候选
"""
import wave
import json
import sys
import numpy as np
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
WAV = BASE / "t2.wav"
TRANSCRIPT = BASE.parent / "transcripts" / "测试视频2.txt"
OUT_JSON = BASE / "audio_hotspots.json"
OUT_CSV = BASE / "audio_hotspots_hr.csv"

SR = 16000
FRAME = 0.1          # 100ms 帧
# 能量阈值
ENERGY_ABS_MIN = 0.10     # 绝对能量下限(排除极静音噪声)
ENERGY_BURST_RATIO = 2.5  # 相对前 2s 中位突增
# ZCR: 16k 下语音 ~0.02-0.08, 笑声/尖叫/噪声更高
ZCR_HIGH = 0.20           # 高 ZCR 阈值(疑似高频爆发)
# 事件最小/最大时长
EV_MIN = 0.3
EV_MAX = 4.0


def load_wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getsampwidth() == 2
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return raw


def calc_feats(raw):
    """滑窗(100ms,hop100ms)算 RMS 和 ZCR"""
    fl = int(SR * FRAME)
    n = len(raw) // fl
    seg = raw[: n * fl].reshape(n, fl)
    rms = np.sqrt(np.mean(seg ** 2, axis=1))
    # ZCR: 符号变化次数 / 采样数
    signs = seg[:, 1:] * seg[:, :-1]
    zcr = np.mean(signs < 0, axis=1)
    return rms, zcr


def fmt(sec):
    sec = int(sec)
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"


def parse_transcript(path):
    """解析文字稿: 返回 [(start_sec,end_sec,text)], 用于"该时间有没有文本"判断"""
    import re
    segs = []
    if not Path(path).exists():
        return segs
    pat = re.compile(r"\[(\d+:\d{2}(?::\d{2})?)\s*-\s*(\d+:\d{2}(?::\d{2})?)\]\s*(.*)")
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        def ts2s(t):
            p = t.split(":")
            return int(p[0]) * 60 + int(p[1]) if len(p) == 2 else int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
        s, e = ts2s(m.group(1)), ts2s(m.group(2))
        if m.group(3).strip():
            segs.append((s, e, m.group(3).strip()))
    return segs


def has_text(segs, lo, hi):
    """该时间段是否有 ASR 文本"""
    for s, e, _ in segs:
        if s < hi and e > lo:
            return True
    return False


def text_density(segs, lo, hi):
    """该时间段 ASR 文本长度(近似活跃度)"""
    n = 0
    for s, e, t in segs:
        if s < hi and e > lo:
            n += len(t)
    return n


def cluster_and_mark(rms, zcr, times):
    """检测热点并给类型候选"""
    hotspots = []
    lookback = int(2.0 / FRAME)
    n = len(rms)

    # 逐帧打标: 高能量 且 (突增 或 高ZCR)
    flags = np.zeros(n, dtype=int)  # 1=burst, 2=highzcr_highE, 3=both
    for i in range(n):
        if rms[i] < ENERGY_ABS_MIN:
            continue
        prev = rms[max(0, i - lookback): i]
        med = float(np.median(prev)) if prev.size else 0
        is_burst = med > 1e-4 and rms[i] / med > ENERGY_BURST_RATIO
        is_hz = zcr[i] >= ZCR_HIGH and rms[i] >= ENERGY_ABS_MIN
        if is_burst and is_hz:
            flags[i] = 3
        elif is_hz:
            flags[i] = 2
        elif is_burst:
            flags[i] = 1

    # 相邻同 flag 合并成事件
    i = 0
    while i < n:
        if flags[i] == 0:
            i += 1
            continue
        j = i
        while j < n and flags[j] != 0:
            j += 1
        dur = (j - i) * FRAME
        if EV_MIN <= dur <= EV_MAX:
            fmax = int(flags[i:j].max())
            pk_i = i + int(np.argmax(rms[i:j]))
            hotspots.append({
                "start": round(times[i], 2),
                "end": round(times[j - 1] + FRAME, 2),
                "dur": round(dur, 2),
                "peak_energy": round(float(rms[pk_i]), 4),
                "mean_energy": round(float(np.mean(rms[i:j])), 4),
                "peak_zcr": round(float(np.max(zcr[i:j])), 4),
                "flag": fmax,  # 1=burst, 2=highZCR+highE, 3=both(最强)
                "kind": {1: "energy_burst", 2: "high_freq_burst", 3: "strong_anomaly"}[fmax],
            })
        i = j
    return hotspots


def main():
    print(f"读 WAV: {WAV.name}")
    raw = load_wav(WAV)
    print(f"时长 {len(raw)/SR:.0f}s")
    segs = parse_transcript(TRANSCRIPT)
    print(f"ASR 文本段数: {len(segs)}")

    rms, zcr = calc_feats(raw)
    times = np.arange(len(rms)) * FRAME
    print(f"帧数 {len(rms)}")

    hotspots = cluster_and_mark(rms, zcr, times)
    print(f"\n== 音频异常热点(去重后) 共 {len(hotspots)} ==")

    # 与文本对照打标签
    stats = Counter()
    rows = []
    for h in hotspots:
        lo, hi = h["start"], h["end"]
        # 文本弱=该段几乎没有 ASR 词; 文本强=词多
        density = text_density(segs, lo, hi)
        has_txt = has_text(segs, lo, hi)
        if density <= 8:
            text_tag = "文本弱"
        elif density <= 30:
            text_tag = "文本中"
        else:
            text_tag = "文本强"
        h["text_density"] = density
        h["text_tag"] = text_tag
        # 标签类型
        if h["kind"] == "strong_anomaly":
            stats["strong_anomaly"] += 1
        if text_tag == "文本弱" and h["kind"] in ("strong_anomaly", "high_freq_burst"):
            stats["audio_strong_text_weak"] += 1
        if text_tag == "文本弱":
            stats["text_weak"] += 1
        rows.append(h)

    # 高置信异常 = strong_anomaly(高能+高ZCR+突发)
    high_conf = [h for h in hotspots if h["kind"] == "strong_anomaly"]
    print(f"\n=== 汇总 ===")
    print(f"热点总数: {len(hotspots)}")
    print(f"  其中 strong_anomaly(高能+高ZCR+突发, 最疑似笑声/尖叫): {len(high_conf)}")
    print(f"  其中 high_freq_burst(高能+高ZCR): {sum(1 for h in hotspots if h['kind']=='high_freq_burst')}")
    print(f"  其中 energy_burst(纯能量突发): {sum(1 for h in hotspots if h['kind']=='energy_burst')}")
    print(f"  文本弱(该段ASR几乎没抓到话): {stats['text_weak']}")
    print(f"  音频强+文本弱(疑似漏检高光候选): {stats['audio_strong_text_weak']}")

    print(f"\n=== 高置信异常热点 Top30(strong_anomaly 按 peak_energy) ===")
    cnt = 0
    for h in sorted(high_conf, key=lambda x: -x["peak_energy"]):
        if cnt >= 30:
            break
        cnt += 1
        print(f"  {fmt(h['start'])}-{fmt(h['end'])} ({h['dur']}s) E={h['peak_energy']:.3f} "
              f"ZCR={h['peak_zcr']:.2f} 文本[{h['text_tag']}] den={h['text_density']}")

    # 保存
    json.dump(hotspots, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(OUT_CSV, "w", encoding="utf-8") as f:
        f.write("start,end,dur,peak_energy,peak_zcr,kind,text_density,text_tag\n")
        for h in rows:
            f.write(f"{h['start']},{h['end']},{h['dur']},{h['peak_energy']},{h['peak_zcr']},{h['kind']},{h['text_density']},{h['text_tag']}\n")
    print(f"\n已保存原始检测: {OUT_JSON.name}")
    print(f"已保存人工复核表: {OUT_CSV.name}")


if __name__ == "__main__":
    main()
