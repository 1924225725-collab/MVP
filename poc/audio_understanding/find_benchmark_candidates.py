# -*- coding: utf-8 -*-
"""find_benchmark_candidates.py —— 清晰双人 Speaker Benchmark 候选搜索（PoC，不接生产）

目标：在现有素材里找「30~90 秒 / 恰好 2 个真人说话人 / 清楚轮流说话 / 少 overlap /
BGM 弱或没有 / 边界容易人工确认」的候选短片段，作为 CAM++ 简单条件下能力上限的 benchmark 素材。

铁律：
  - 模型预测只是候选筛选与参考，一律不算 Ground Truth；正式 benchmark 等 GT 人工确认后才跑。
  - 本脚本不改生产代码、不动 CAM++、不调参数（配置与 ab_experiment.py 的 A 组完全一致）。

扫描配置（= A 组，保留富 token 以便统计 <|BGM|>）：
  SenseVoiceSmall + fsmn-vad(max_single_segment_time=15000) + CAM++(spk)，无 punc，cpu，batch_size_s=60

用法：
  .venv-audio-poc/Scripts/python find_benchmark_candidates.py                # 全量扫描
  .venv-audio-poc/Scripts/python find_benchmark_candidates.py --only t2_51min  # 只扫一个源

输出（outputs/scan/）：
  <name>.wav             统一 16k mono pcm_s16le（重复运行直接复用）
  <name>.sentences.json  句子流（start/end/text/spk）+ 计时
  candidates.json        全部候选汇总（含窗口结构、切换点、评分）
"""

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))  # live_clipper/
SCAN_DIR = os.path.join(HERE, "outputs", "scan")

ASR_MODEL_ID = "iic/SenseVoiceSmall"
VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
SPK_MODEL_ID = "iic/speech_campplus_sv_zh-cn_16k-common"
VAD_KWARGS = {"max_single_segment_time": 15000}

FFMPEG_CANDIDATES = [
    os.path.join(
        ROOT,
        ".venv",
        "Lib",
        "site-packages",
        "imageio_ffmpeg",
        "binaries",
        "ffmpeg-win-x86_64-v7.1.exe",
    ),
]

SOURCES = [
    {"name": "full6min",    "path": os.path.join(ROOT, "videos", "测试视频.mp4")},
    {"name": "t2_51min",    "path": os.path.join(ROOT, "poc", "t2.wav")},
    {"name": "video4_23min","path": os.path.join(ROOT, "videos", "测试视频4.mp4")},
    {"name": "top25_judge", "path": os.path.join(ROOT, "poc", "AUDIO_top25_judge.mp3")},
    {"name": "normal30s",   "path": os.path.join(ROOT, "_test_media", "normal.mp4")},
]

# ── 候选筛选参数 ──────────────────────────────────────────────
MIN_SPAN_S = 30.0        # 窗口最短跨度
MAX_SPAN_S = 90.0        # 窗口最长跨度
MIN_SWITCHES = 2         # 至少 2 次说话人切换（A→B→A）
BGM_TOKEN = "<|BGM|>"
MIN_SPK_SHARE = 0.15     # 每个说话人的发声占比下限
MIN_SPK_VOICED_MS = 4000 # 每个说话人最短发声时长
MAX_OVERLAP_KEEP = 0.40  # 同源去重：与已保留候选重叠超 40% 则丢弃
TOP_PER_SOURCE = 5


def find_ffmpeg():
    for p in FFMPEG_CANDIDATES:
        if os.path.exists(p):
            return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError("找不到 ffmpeg（imageio_ffmpeg 也不可用）")


def wav_format_ok(path):
    """是否已是 16k mono 16bit wav。"""
    import wave
    try:
        with wave.open(path, "rb") as w:
            return (w.getnchannels() == 1 and w.getframerate() == 16000
                    and w.getsampwidth() == 2)
    except Exception:
        return False


def wav_seconds(path):
    import wave
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def ensure_wav(src, name):
    """统一转 16k mono pcm_s16le；已是目标格式直接用；转换结果复用。"""
    if src.lower().endswith(".wav") and wav_format_ok(src):
        return src, 0.0
    dst = os.path.join(SCAN_DIR, name + ".wav")
    if os.path.exists(dst) and wav_format_ok(dst):
        return dst, 0.0  # 复用上次转换
    t0 = time.perf_counter()
    cmd = [find_ffmpeg(), "-y", "-i", src, "-ar", "16000", "-ac", "1",
           "-c:a", "pcm_s16le", dst]
    subprocess.run(cmd, check=True, capture_output=True)
    return dst, time.perf_counter() - t0


def scan_source(model, name, src_path):
    """推理一个源 → 句子流落盘 → 滑窗候选。"""
    t0 = time.perf_counter()
    wav, convert_s = ensure_wav(src_path, name)
    dur_s = wav_seconds(wav)
    res = model.generate(input=wav, cache={}, batch_size_s=60, hotword="")
    infer_s = time.perf_counter() - t0
    result = res[0] if res else {}
    raw = result.get("sentence_info") or []
    sents = [{"start": int(s.get("start", 0)), "end": int(s.get("end", 0)),
              "text": s.get("text", ""), "spk": s.get("spk")} for s in raw]

    payload = {
        "name": name, "source_path": src_path, "wav_path": wav,
        "audio_seconds": round(dur_s, 2),
        "timing": {"convert_seconds": round(convert_s, 2),
                   "infer_seconds": round(infer_s, 2),
                   "rtf": round(infer_s / dur_s, 4) if dur_s else None},
        "config": {"asr": ASR_MODEL_ID, "vad": VAD_MODEL_ID, "spk": SPK_MODEL_ID,
                   "punc": None, "vad_kwargs": VAD_KWARGS, "device": "cpu",
                   "batch_size_s": 60},
        "sentence_count": len(sents),
        "sentence_info": sents,
    }
    sent_path = os.path.join(SCAN_DIR, name + ".sentences.json")
    with open(sent_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    cands = search_windows(sents)
    return {"name": name, "source_path": src_path, "wav_path": wav,
            "audio_seconds": round(dur_s, 2), "sentence_count": len(sents),
            "infer_seconds": round(infer_s, 2), "candidates": cands}, sent_path


def search_windows(sents):
    """滑窗搜索候选窗口。窗口 = 句子流里首句 start 到末句 end。"""
    pool = [s for s in sents if s.get("spk") is not None and s["end"] > s["start"]]
    pool.sort(key=lambda s: s["start"])
    n = len(pool)
    found = []
    for i in range(n):
        for j in range(i, n):
            span_ms = pool[j]["end"] - pool[i]["start"]
            if span_ms > MAX_SPAN_S * 1000:
                break
            if span_ms < MIN_SPAN_S * 1000:
                continue
            win = pool[i:j + 1]
            order = [s["spk"] for s in win]
            spk_set = set(order)
            if len(spk_set) != 2:
                continue
            text_all = "".join(s["text"] or "" for s in win)
            if text_all.count(BGM_TOKEN) != 0:
                continue
            switch_idx = [k for k in range(1, len(win)) if order[k] != order[k - 1]]
            if len(switch_idx) < MIN_SWITCHES:
                continue
            voiced = {}
            for s in win:
                voiced[s["spk"]] = voiced.get(s["spk"], 0) + (s["end"] - s["start"])
            total_voiced = sum(voiced.values())
            if total_voiced <= 0:
                continue
            if any(ms / total_voiced < MIN_SPK_SHARE or ms < MIN_SPK_VOICED_MS
                   for ms in voiced.values()):
                continue
            # 同说话人连续段（run）：切换点 = 新说话人首句 start
            runs, run_start = [], 0
            for k in switch_idx:
                runs.append({"spk": win[run_start]["spk"],
                             "start_ms": win[run_start]["start"],
                             "end_ms": win[k - 1]["end"]})
                run_start = k
            runs.append({"spk": win[run_start]["spk"],
                         "start_ms": win[run_start]["start"],
                         "end_ms": win[-1]["end"]})
            min_run_s = min((r["end_ms"] - r["start_ms"]) / 1000.0 for r in runs)
            span_s = span_ms / 1000.0
            voiced_ratio = total_voiced / span_ms
            # 模式串：第一个说话人=A，第二个=B
            mapping = {}
            pattern = []
            for sp in order:
                if sp not in mapping:
                    mapping[sp] = "AB"[len(mapping)]
                pattern.append(mapping[sp])
            # 评分：最短发言段越长越好；切换次数（≤6 计满）越多越像轮流；发声占比越高越干净
            score = (min_run_s * 1.0 + min(6, len(switch_idx)) * 2.0
                     + voiced_ratio * 10.0)
            found.append({
                "start_ms": win[0]["start"], "end_ms": win[-1]["end"],
                "span_s": round(span_s, 2),
                "speakers": sorted(spk_set),
                "switches": len(switch_idx),
                "switch_points_ms": [win[k]["start"] for k in switch_idx],
                "pattern": "".join(pattern),
                "runs": runs,
                "min_run_s": round(min_run_s, 2),
                "voiced_ratio": round(voiced_ratio, 3),
                "per_spk_voiced_ms": {str(k): v for k, v in voiced.items()},
                "sentence_count": len(win),
                "score": round(score, 2),
                "sentence_index_range": [i, j],
            })
    found.sort(key=lambda c: (-c["score"], abs(c["span_s"] - 60)))
    kept = []
    for c in found:
        ok = True
        for k in kept:
            ov = min(c["end_ms"], k["end_ms"]) - max(c["start_ms"], k["start_ms"])
            if ov > MAX_OVERLAP_KEEP * (c["end_ms"] - c["start_ms"]):
                ok = False
                break
        if ok:
            kept.append(c)
        if len(kept) >= TOP_PER_SOURCE:
            break
    return kept


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None,
                    help="只扫描指定 name 的源（默认全部）")
    args = ap.parse_args()
    os.makedirs(SCAN_DIR, exist_ok=True)

    missing = [s["name"] for s in SOURCES if not os.path.exists(s["path"])]
    if missing:
        print(f"[warn] 以下源不存在，跳过: {missing}", flush=True)
    todo = [s for s in SOURCES if os.path.exists(s["path"])
            and (args.only is None or s["name"] == args.only)]
    if not todo:
        print("没有可扫描的源", flush=True)
        return

    t0 = time.perf_counter()
    from funasr import AutoModel
    model = AutoModel(
        model=ASR_MODEL_ID,
        vad_model=VAD_MODEL_ID,
        vad_kwargs=dict(VAD_KWARGS),
        spk_model=SPK_MODEL_ID,
        device="cpu",
        disable_update=True,
        disable_pbar=True,
    )
    print(f"model init {time.perf_counter() - t0:.1f}s", flush=True)

    all_results = []
    for src in todo:
        t0 = time.perf_counter()
        print(f"[scan] {src['name']} <- {src['path']}", flush=True)
        try:
            r, sent_path = scan_source(model, src["name"], src["path"])
        except Exception as e:
            print(f"[scan] {src['name']} 失败: {type(e).__name__}: {e}", flush=True)
            all_results.append({"name": src["name"], "error": f"{type(e).__name__}: {e}"})
            continue
        print(f"[scan] {src['name']} {r['audio_seconds']}s sentences={r['sentence_count']} "
              f"infer={r['infer_seconds']}s candidates={len(r['candidates'])} "
              f"({time.perf_counter() - t0:.1f}s)", flush=True)
        for c in r["candidates"]:
            print(f"   cand {c['start_ms'] / 1000:.1f}-{c['end_ms'] / 1000:.1f}s "
                  f"span={c['span_s']}s pattern={c['pattern']} switches={c['switches']} "
                  f"min_run={c['min_run_s']}s score={c['score']}", flush=True)
        all_results.append(r)

    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "候选窗口由模型输出筛选而来，仅供人工核对，不构成 Ground Truth",
        "filters": {"min_span_s": MIN_SPAN_S, "max_span_s": MAX_SPAN_S,
                    "min_switches": MIN_SWITCHES, "bgm_token_must_be_zero": True,
                    "min_spk_share": MIN_SPK_SHARE,
                    "min_spk_voiced_ms": MIN_SPK_VOICED_MS,
                    "max_overlap_keep": MAX_OVERLAP_KEEP,
                    "top_per_source": TOP_PER_SOURCE},
        "sources": all_results,
    }
    out_path = os.path.join(SCAN_DIR, "candidates.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    total_c = sum(len(r.get("candidates", [])) for r in all_results)
    print(f"[done] sources={len(all_results)} candidates={total_c} -> {out_path}",
          flush=True)


if __name__ == "__main__":
    main()
