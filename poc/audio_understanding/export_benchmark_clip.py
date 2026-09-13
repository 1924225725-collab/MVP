# -*- coding: utf-8 -*-
"""export_benchmark_clip.py —— 把候选窗口导出为 Speaker Benchmark fixture（PoC，不接生产）

做四件事（模型预测一律只是参考，不构成 Ground Truth）：
  1. 从 outputs/scan/<source>.wav 按样本精确剪切 [start_ms, end_ms]
     → fixtures/benchmark_<key>.wav（16k mono pcm_s16le）
  2. 在剪出的片段上重新跑一遍 A 配置推理（片段内重新聚类，边界比整段扫描更准）
  3. outputs/scan/probe_<key>.json：句子流 + 模型预测切换点 + sha256 + 来源溯源
  4. fixtures/speaker_ground_truth_<key>.txt / .json：待人工填写的 GT 模板
     （txt 沿用 speaker_ground_truth_000_090.txt 的填写约定）

用法：
  .venv-audio-poc/Scripts/python export_benchmark_clip.py \
      --source t2_51min --start_ms 123000 --end_ms 155000 --key t2_123_155
"""

import argparse
import hashlib
import json
import os
import re
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
SCAN_DIR = os.path.join(HERE, "outputs", "scan")

ASR_MODEL_ID = "iic/SenseVoiceSmall"
VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
SPK_MODEL_ID = "iic/speech_campplus_sv_zh-cn_16k-common"
VAD_KWARGS = {"max_single_segment_time": 15000}

TOKEN_RE = re.compile(r"<\|[^|]*\|>")


def strip_tokens(text):
    return TOKEN_RE.sub("", text or "").strip()


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cut_wav(src_wav, start_ms, end_ms, dst_wav):
    """wave 模块按帧剪切，样本级精确。"""
    with wave.open(src_wav, "rb") as w:
        assert w.getnchannels() == 1 and w.getframerate() == 16000 \
            and w.getsampwidth() == 2, "源 wav 必须是 16k mono 16bit"
        rate = w.getframerate()
        a = int(start_ms * rate / 1000)
        b = min(int(end_ms * rate / 1000), w.getnframes())
        w.setpos(a)
        frames = w.readframes(b - a)
    with wave.open(dst_wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return b - a, rate


def infer_clip(wav_path):
    """A 配置（与 ab_experiment.py / find_benchmark_candidates.py 完全一致）。"""
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
    t0 = time.perf_counter()
    res = model.generate(input=wav_path, cache={}, batch_size_s=60, hotword="")
    infer_s = time.perf_counter() - t0
    result = res[0] if res else {}
    sents = [{"start": int(s.get("start", 0)), "end": int(s.get("end", 0)),
              "text": s.get("text", ""), "spk": s.get("spk")}
             for s in (result.get("sentence_info") or [])]
    return sents, round(infer_s, 2)


def predicted_structure(sents):
    """从片段级句子流推出模型预测的 runs / 切换点（辅助参考）。"""
    pool = [s for s in sents if s.get("spk") is not None and s["end"] > s["start"]]
    pool.sort(key=lambda s: s["start"])
    runs, switches = [], []
    cur = None
    for s in pool:
        if cur is None or s["spk"] != cur["spk"]:
            if cur is not None:
                runs.append(cur)
            cur = {"spk": s["spk"], "start_ms": s["start"], "end_ms": s["end"],
                   "text_parts": [strip_tokens(s["text"])]}
            if runs or cur["start_ms"] > 0:
                switches.append(s["start"])
        else:
            cur["end_ms"] = s["end"]
            cur["text_parts"].append(strip_tokens(s["text"]))
    if cur is not None:
        runs.append(cur)
    for r in runs:
        r["text_hint"] = "/".join(t for t in r["text_parts"] if t)[:60]
        del r["text_parts"]
    # 段首即开始不算切换
    switches = [ms for ms in switches if ms > 0]
    return runs, switches


def fmt_ms(ms):
    return f"{ms / 1000:.1f}s"


def write_txt_template(path, key, wav_name, dur_ms, runs, sentences, source_desc):
    lines = []
    ap = lines.append
    ap(f"# speaker ground truth 标注 —— benchmark_{key}.wav（{dur_ms / 1000:.1f} 秒）")
    ap(f"# 来源：{source_desc}（16k mono wav）")
    ap("#")
    ap("# ══ 怎么填（很简单）══")
    ap("# 一行一个时间段：<开始> <结束> <说话人>    （# 号后面是备注，可写可不写）")
    ap("#")
    ap("#   时间怎么写都行：2110（毫秒）/ 2.1（秒）/ 0:02（分:秒）/ 0:02.1 都可以")
    ap("#   说话人命名：human_spk_01、human_spk_02、human_spk_03……")
    ap("#              ★ 同一个真人从头到尾必须用同一个名字 ★")
    ap("#   听不出来/拿不准：写 unsure，并在 # 后说明原因")
    ap("#")
    ap("# 注意：")
    ap("#   1. 下面各段的边界是\"模型预测值\"，仅供对照——请按你听到的真实切换点修改")
    ap("#   2. 除了这些段，如果你听到段内还有别的说话人切换，就再加行把那段拆开")
    ap("#   3. 最后回答\"总人数\"")
    ap("#")
    ap(f"# ══ 待确认的 {len(runs)} 段（把 TODO 改成 human_spk_XX）══")
    for i, r in enumerate(runs, 1):
        hint = f" —— 内容：{r['text_hint']}" if r.get("text_hint") else ""
        ap(f"# 段{i} 模型判：spk-{r['spk']:02d}（{fmt_ms(r['start_ms'])}–{fmt_ms(r['end_ms'])}）{hint}")
        ap(f"{r['start_ms']} {r['end_ms']} TODO      # 模型 spk-{r['spk']:02d}")
    ap("#")
    ap("# ══ 逐句参考（模型预测，仅供精确定位切换点；不用逐句填）══")
    for s in sentences:
        t = strip_tokens(s["text"])
        if not t:
            continue
        ap(f"# {s['start']:>6}–{s['end']:>6} spk-{s['spk']:02d}  {t[:50]}")
    ap("#")
    ap("# ══ 总人数 ══")
    ap("# 把下面的 TODO 改成数字（你听到的真人数量，不含 BGM/系统音）：")
    ap("总人数 TODO")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="扫描源 name（outputs/scan/<name>.wav）")
    ap.add_argument("--start_ms", required=True, type=int)
    ap.add_argument("--end_ms", required=True, type=int)
    ap.add_argument("--key", required=True, help="fixture 键名，如 t2_123_155")
    args = ap.parse_args()

    src_wav = os.path.join(SCAN_DIR, args.source + ".wav")
    if not os.path.exists(src_wav):
        # 扫描时若源本身已是 16k mono，则直接用了源文件——从 sentences.json 拿真实 wav 路径
        sent_json = os.path.join(SCAN_DIR, args.source + ".sentences.json")
        if os.path.exists(sent_json):
            with open(sent_json, encoding="utf-8") as f:
                src_wav = json.load(f).get("wav_path") or src_wav
    assert os.path.exists(src_wav), f"找不到 {src_wav}，先跑 find_benchmark_candidates.py"
    src_json = os.path.join(SCAN_DIR, args.source + ".sentences.json")
    os.makedirs(FIXTURES, exist_ok=True)

    wav_name = f"benchmark_{args.key}.wav"
    dst_wav = os.path.join(FIXTURES, wav_name)
    frames, rate = cut_wav(src_wav, args.start_ms, args.end_ms, dst_wav)
    dur_ms = int(frames / rate * 1000)
    print(f"[cut] {dst_wav}  {dur_ms}ms ({frames} frames @16k)", flush=True)

    sents, infer_s = infer_clip(dst_wav)
    runs, switches = predicted_structure(sents)
    print(f"[infer] sentences={len(sents)} runs={len(runs)} "
          f"switch_points={switches} infer={infer_s}s", flush=True)

    probe = {
        "key": args.key,
        "fixture_wav": f"fixtures/{wav_name}",
        "fixture_sha256": sha256_of(dst_wav),
        "duration_ms": dur_ms,
        "source": {"scan_source": args.source, "wav": src_wav,
                   "start_ms": args.start_ms, "end_ms": args.end_ms,
                   "origin_sentences_json": f"outputs/scan/{args.source}.sentences.json"},
        "config": {"asr": ASR_MODEL_ID, "vad": VAD_MODEL_ID, "spk": SPK_MODEL_ID,
                   "punc": None, "vad_kwargs": VAD_KWARGS, "device": "cpu",
                   "batch_size_s": 60},
        "timing": {"clip_infer_seconds": infer_s},
        "ai_reference": {
            "_note": "以下全部为模型预测，仅供人工标注对照，不构成 Ground Truth",
            "predicted_runs": runs,
            "predicted_switch_points_ms": switches,
        },
        "sentence_info": sents,
    }
    probe_path = os.path.join(SCAN_DIR, f"probe_{args.key}.json")
    with open(probe_path, "w", encoding="utf-8") as f:
        json.dump(probe, f, ensure_ascii=False, indent=2, default=str)

    src_desc = f"outputs/scan/{args.source}.wav 的 {args.start_ms}–{args.end_ms}ms"
    if os.path.exists(src_json):
        with open(src_json, encoding="utf-8") as f:
            origin = json.load(f).get("source_path")
        if origin:
            src_desc = f"{origin} {args.start_ms}–{args.end_ms}ms（{args.source}）"
    txt_path = os.path.join(FIXTURES, f"speaker_ground_truth_{args.key}.txt")
    write_txt_template(txt_path, args.key, wav_name, dur_ms, runs, sents, src_desc)

    gt = {
        "_readme": ["模板：speaker 栏全部为 TODO，待人工听写填写后此文件才是有效 GT。",
                    "标注请在同名 .txt 里按行填写（更顺手），填完可让人工转录回本 json。",
                    "模型预测仅供对照，不构成 Ground Truth。"],
        "_source": {"file": f"fixtures/{wav_name}", "origin": src_desc,
                    "duration_ms": dur_ms},
        "_ai_reference": {
            "predicted_switch_points_ms": switches,
            "note": "labels 的边界是模型预测值，仅供人工修改起点",
        },
        "_filled_by": "TODO",
        "labels": [{"start_ms": r["start_ms"], "end_ms": r["end_ms"],
                    "speaker": "TODO", "_note": f"模型 spk-{r['spk']:02d}；内容：{r.get('text_hint', '')}"}
                   for r in runs],
        "total_human_speakers": "TODO",
    }
    gt_path = os.path.join(FIXTURES, f"speaker_ground_truth_{args.key}.json")
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump(gt, f, ensure_ascii=False, indent=2, default=str)

    print(f"[done] probe={probe_path}\n       txt={txt_path}\n       json={gt_path}",
          flush=True)


if __name__ == "__main__":
    main()
