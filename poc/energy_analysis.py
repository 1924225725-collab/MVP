"""PoC 阶段1 - 音频能量/静音/突变分析
从 16kHz 单声道 WAV 算帧级能量, 标出:
  - 音量/能量突变点(短窗能量相对前窗突增)
  - 长静音后突然爆发
输出: 时间排序的能量热点 + 原始能量序列(供复核/后续YamNet引导)
不改任何主流程, 独立 PoC 脚本。
"""
import wave
import sys
import numpy as np
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WAV = Path(__file__).parent / "t2.wav"
OUT_JSON = Path(__file__).parent / "energy_hotspots.json"
OUT_RAW = Path(__file__).parent / "energy_curve.npy"

# 帧参数(秒)
FRAME = 0.1          # 每帧 100ms
HOP = 0.1            # 每 100ms 采一帧

# 突变阈值(相对)与绝对底
BURST_RATIO = 3.0    # 能量相对前 ~2s 中位跃升 >3x
BURST_ABS_MIN = 0.02 # 且绝对能量超过这个(避免极静音的噪声被当爆发)
SILENCE = 0.005      # 能量低于此算静音
PAUSE_MIN = 1.5      # 静音持续 >=1.5s 算"长停顿"
POST_PAUSE = 2.0     # 停顿结束后 2s 内若能量突增, 记为"停顿后爆发"


def load_wav(path):
    with wave.open(str(path), "rb") as w:
        nch, sw, sr, nf = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        assert sw == 2, "需要 16bit PCM"
        raw = np.frombuffer(w.readframes(nf), dtype=np.int16).astype(np.float32) / 32768.0
    return raw, sr


def frame_energy(raw, sr, frame=FRAME, hop=HOP):
    """滑窗算每帧 RMS 能量(0~1), 向量化。返回 (energies, times)"""
    fl = int(sr * frame)
    hl = int(sr * hop)
    # 非重叠 hop=frame 时可直接 reshape; 否则用步进索引。这里 hop=frame, 简化向量化
    if hop == frame:
        n_full = len(raw) // fl
        seg = raw[: n_full * fl].reshape(n_full, fl)
        energies = np.sqrt(np.mean(seg ** 2, axis=1))
        # 补最后一帧(不足 fl)
        tail = raw[n_full * fl:]
        if tail.size >= 16:  # 忽略极短尾巴
            energies = np.append(energies, float(np.sqrt(np.mean(tail ** 2))))
        times = np.arange(len(energies)) * hop
        return energies, times
    # hop<frame 的一般情况: 用 as_strided 近似(避免复杂内存), 落到循环(帧数少)
    n = (len(raw) - fl) // hl + 1
    energies = np.zeros(n)
    for i in range(n):
        seg = raw[i * hl: i * hl + fl]
        if seg.size:
            energies[i] = np.sqrt(np.mean(seg ** 2))
    times = np.arange(n) * hop
    return energies, times


def fmt(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main():
    print(f"读取 {WAV} ...")
    raw, sr = load_wav(WAV)
    print(f"采样率 {sr}, 时长 {len(raw)/sr:.0f}s")
    energies, times = frame_energy(raw, sr)
    print(f"帧数 {len(energies)}, 每帧 {FRAME}s")

    # ---------- 1. 能量突变点(相对前~2s中位能量跃升 >3x) ----------
    lookback = int(2.0 / HOP)  # 前2s的帧数
    hotspots = []
    for i in range(lookback, len(energies)):
        prev_win = energies[max(0, i - lookback): i]
        med = np.median(prev_win)
        cur = energies[i]
        if med > 0 and cur > BURST_ABS_MIN and cur / med > BURST_RATIO:
            # 去重: 连续多帧命中算一段
            if hotspots and abs(times[i] - hotspots[-1]["end"]) < 0.5:
                hotspots[-1]["end"] = times[i] + FRAME
                hotspots[-1]["peak"] = max(hotspots[-1]["peak"], float(cur))
            else:
                hotspots.append({"start": round(times[i], 2), "end": round(times[i] + FRAME, 2),
                                 "peak": float(cur), "type": "energy_burst"})

    # ---------- 2. 静音段(长停顿) ----------
    silent = energies < SILENCE
    pauses = []
    i = 0
    while i < len(silent):
        if silent[i]:
            j = i
            while j < len(silent) and silent[j]:
                j += 1
            dur = (j - i) * HOP
            if dur >= PAUSE_MIN:
                pauses.append((times[i], times[j - 1] + FRAME, dur))
            i = j
        else:
            i += 1

    # ---------- 3. 长停顿后突然爆发 ----------
    pause_burst = []
    for ps, pe, pd in pauses:
        # 停顿结束 pe 后 2s 内找能量峰
        idx_end = int(pe / HOP)
        idx_far = min(len(energies), int((pe + POST_PAUSE) / HOP))
        if idx_end < len(energies):
            win = energies[idx_end: idx_far]
            if win.size:
                pk = float(np.max(win))
                if pk > BURST_ABS_MIN:
                    pk_i = idx_end + int(np.argmax(win))
                    # 相对停顿内能量
                    pause_med = float(np.median(energies[max(0, int(ps/HOP)-3): int(pe/HOP)+1])) or 1e-6
                    if pk / max(pause_med, 1e-6) > BURST_RATIO:
                        pause_burst.append({"start": round(float(times[pk_i]), 2),
                                            "end": round(float(times[pk_i]) + FRAME, 2),
                                            "peak": pk, "pause_len": round(pd, 1),
                                            "type": "pause_burst"})

    print(f"\n=== 结果 ===")
    print(f"能量突变热点(>3x): {len(hotspots)}")
    print(f"长静音段(>={PAUSE_MIN}s): {len(pauses)}")
    print(f"停顿后爆发: {len(pause_burst)}")

    all_hot = hotspots + pause_burst
    all_hot.sort(key=lambda x: x["start"])

    print(f"\n总 Audio Hotspots(能量维度): {len(all_hot)}")
    for h in all_hot[:50]:
        print(f"  [{h['type']:12}] {fmt(h['start'])}-{fmt(h['end'])}  peak={h['peak']:.3f}"
              + (f"  停{pause_len}" if (pause_len := h.get('pause_len')) else ""))

    # 保存原始
    np.save(OUT_RAW, energies)  # 帧能量序列(供复核/画图/YamNet引导)
    import json
    json.dump(all_hot, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n已保存: {OUT_JSON}  ({len(all_hot)} hotspots)")
    print(f"已保存原始能量序列: {OUT_RAW}")


if __name__ == "__main__":
    main()
