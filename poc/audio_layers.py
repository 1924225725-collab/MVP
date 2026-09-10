"""Audio Signal 分层验证 PoC (audio_layers.py)

目的：验证「相对基线 + 分层」是否比旧版「绝对 RMS/ZCR」更可靠地定位
      audio_anomaly，并用同一批人工标注的 25 个 y/n 点做 A/B 对比。

三层概念（本文件只实现 L0/L1/L2 的信号侧，不做 highlight 判断）：
  L0 预处理    : 帧级 RMS / ZCR
  L1 anomaly   : 纯信号异常（相对 60s 能量基线突增 + 合理时长窗），
                 "这里有动静" —— 只产 evidence，不下高光结论
  L2 粗归类    : 叠加 speech 证据(说话中/非说话) + 时长/能量形态，
                 给低置信启发式类型候选(short_pulse 碰撞 / sustained 高能 / burst 情绪)
  highlight    : 本文件不判断。audio 只当 evidence，由 ASR/Event/未来 Vision 裁决。

核心改进 vs 旧版(audio_hotspot_detect.py)：
  1. 能量基线 = 60s 局部窗口的百分位，而非绝对阈值 0.10
     → 直播间 BGM/底噪高时不会所有帧都过线
  2. 突增 = 对比更长基线(8s 平均/中位)，而非只前 2s
     → 抑制说话起伏本身触发的误报
  3. speech 只作辅助 evidence(说话中 laughter/情绪更可信)，不硬过滤
  4. 时长窗 0.3~4s(笑声/尖叫/碰撞的自然长度)

不改主流程 / A1 / A2 / A3 / 评分 / prompt / UI。独立 poc 脚本。
"""
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
WAV = BASE / "t2.wav"
TRANSCRIPT = BASE.parent / "transcripts" / "测试视频2.txt"
OUT_ANOMALY = BASE / "audio_layers_anomaly.json"
OUT_SPEECH = BASE / "audio_layers_speech.json"

SR = 16000
FRAME = 0.1          # 100ms 帧

# ---- L1 参数：相对基线 ----
BASE_WIN = 60.0      # 能量基线窗口 60s
BASE_PCT = 0.85      # 基线取窗口能量 p85（环境活跃水平）
BURST_RATIO = 2.0    # 帧能量 > 基线 * 2.0 视为偏强
BURST_LONG_RATIO = 1.8  # 相对 8s 中位再要求一个突增
LONG_WIN = 8.0       # 长窗
EV_MIN = 0.3         # 事件最短
EV_MAX = 4.0         # 事件最长


def load_wav(path):
    with wave.open(str(path), "rb") as w:
        raw = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return raw


def calc_feats(raw):
    """100ms 帧 RMS + ZCR（与旧版一致，便于公平对比）"""
    fl = int(SR * FRAME)
    n = len(raw) // fl
    seg = raw[: n * fl].reshape(n, fl)
    rms = np.sqrt(np.mean(seg ** 2, axis=1))
    signs = seg[:, 1:] * seg[:, :-1]
    zcr = np.mean(signs < 0, axis=1)
    return rms, zcr


def parse_transcript(path):
    """返回 [(start,end,text)] 有人声段。用于 speech 证据(该时间有没有主播说话)"""
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
        if m.group(3).strip():
            segs.append((ts2s(m.group(1)), ts2s(m.group(2))))
    return segs


def speech_evidence(segs, dur):
    """把有人声段标记为 speech 帧(1)，非说话段为 0。返回帧级数组。"""
    n = int(dur / FRAME)
    sp = np.zeros(n, dtype=int)
    for s, e in segs:
        i0, i1 = int(s / FRAME), int(e / FRAME)
        sp[i0:i1] = 1
    return sp


def running_percentile(rms, win_frames, pct):
    """滑动窗口百分位基线。向量化: 用 pandas 不可用, 用 cumsum 近似不行(百分位)。
    改为: 均匀采样窗口中心, 对每帧用 np.percentile 太慢。
    折中: 用 np.convolve 近似(均值) 太不敏感; 用 np.lib.stride_tricks 滑窗太吃内存。
    方案: 每 0.5s 一个锚点算窗口 p85, 中间帧线性插值(直播环境平缓,足够)。"""
    n = len(rms)
    step = max(1, int(0.5 / FRAME))       # 每 0.5s 一个锚点
    half = win_frames // 2
    anchors = []
    # 为避免超吃内存, 直接在锚点上滑窗 percentile
    idxs = list(range(0, n, step))
    vals = np.empty(len(idxs))
    for k, ci in enumerate(idxs):
        lo, hi = max(0, ci - half), min(n, ci + half)
        vals[k] = float(np.percentile(rms[lo:hi], pct * 100))
    # 插值回每帧
    full = np.interp(np.arange(n), np.array(idxs, dtype=float), vals)
    return full


def main():
    raw = load_wav(WAV)
    dur = len(raw) / SR
    print(f"读 WAV: {dur:.0f}s")
    segs = parse_transcript(TRANSCRIPT)
    rms, zcr = calc_feats(raw)
    n = len(rms)
    sp = speech_evidence(segs, dur)
    times = np.arange(n) * FRAME

    # ---- L1: 相对基线 anomaly 检测 ----
    win_base = int(BASE_WIN / FRAME)
    long_win = int(LONG_WIN / FRAME)
    base85 = running_percentile(rms, win_base, BASE_PCT)
    # 8s 滚动中位(突增参照): 用 np.convolve 求每帧前8s均值太慢, 用 running_percentile 近似(50%)
    base8 = running_percentile(rms, long_win, 0.5)

    # 帧级 anomaly 判定: 能量 > 基线p85*ratio(相对环境)  且  能量 > 前8s中位*ratio(突发)
    above_base = rms > np.maximum(base85, 1e-4) * BURST_RATIO
    burst_long = rms > np.maximum(base8, 1e-4) * BURST_LONG_RATIO
    flags = np.where(above_base & burst_long, 1, 0)

    # 时长窗: 合并相邻 flagged 帧成事件(0.3~4s)
    anomalies = []
    i = 0
    while i < n:
        if flags[i] == 0:
            i += 1
            continue
        j = i
        while j < n and flags[j] == 1:
            j += 1
        d = (j - i) * FRAME
        if EV_MIN <= d <= EV_MAX:
            pk = i + int(np.argmax(rms[i:j]))
            anomalies.append({
                "start": round(times[i], 2), "end": round(times[j - 1] + FRAME, 2),
                "dur": round(d, 2),
                "peak_energy": round(float(rms[pk]), 4),
                "peak_zcr": round(float(np.max(zcr[i:j])), 4),
                "above_env": round(float(rms[pk] / base85[pk]), 2),  # 相对环境基线倍数
                "speech": int(sp[pk]),   # 峰值帧是否在说话段
                # 粗形态启发式(低置信, 只当 evidence): 
                #   short_pulse(短而尖,<0.8s,像碰撞/拍桌) / sustained(持续高能,像BGM高潮/大笑) / burst(其他突增)
            })
            d2 = anomalies[-1]["dur"]
            if d2 < 0.8:
                anomalies[-1]["kind_guess"] = "short_pulse"
            elif anomalies[-1]["peak_energy"] > np.maximum(base85[pk], 1e-4) * 3.5:
                anomalies[-1]["kind_guess"] = "sustained"
            else:
                anomalies[-1]["kind_guess"] = "burst"
        i = j

    # ---- speech evidence 输出 ----
    speech_stats = {"speech_frames": int(sp.sum()), "total_frames": n,
                    "speech_pct": round(float(sp.mean()) * 100, 1)}

    print(f"\n=== L1 anomaly 汇总 ===")
    print(f"anomaly 总数: {len(anomalies)}  (旧版 541)")
    from collections import Counter
    print("kind_guess 分布:", dict(Counter(a["kind_guess"] for a in anomalies)))
    print(f"speech 覆盖: {speech_stats['speech_pct']}% (说话中/非说话)")

    # 保存
    json.dump(anomalies, open(OUT_ANOMALY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(speech_stats, open(OUT_SPEECH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"已保存: {OUT_ANOMALY.name} / {OUT_SPEECH.name}")


if __name__ == "__main__":
    main()
