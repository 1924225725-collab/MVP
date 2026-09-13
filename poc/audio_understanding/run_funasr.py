# run_funasr.py —— Audio Understanding PoC runner（设计文档 §7 P1）
#
# 输入：音频/视频文件（非 wav 自动用 ffmpeg 转 16k mono PCM wav）
# 输出：<out>.audio_understanding.v1.json（schema 见 schema.py）
#       + 性能/环境信息（load 时间、推理时间、RTF、CPU/GPU、模型 revision）
#       + --dump-raw：额外落一份 sentence_info 原始结构样本供审计
#
# 组合：SenseVoiceSmall(ASR+情绪+事件) + FSMN-VAD(切分) + CAM++(说话人)
# 独立环境运行：.venv-audio-poc（不 import 生产代码，不污染主 venv）。
#
# 运行：
#   .venv-audio-poc/Scripts/python run_funasr.py --input fixtures/clip_51min_000_090.wav --dump-raw

import argparse
import ctypes
import glob
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import normalize  # noqa: E402
import schema  # noqa: E402

ASR_MODEL_ID = "iic/SenseVoiceSmall"
VAD_MODEL_ID = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
SPK_MODEL_ID = "iic/speech_campplus_sv_zh-cn_16k-common"

# 这些事件 token 属于"语音本身"，不算音频事件，不进 audio_events（其余真实 token 都收）
NON_EVENT_LABELS = {"speech"}


def log(msg):
    print(f"[poc] {msg}", flush=True)


def find_ffmpeg(explicit=None):
    """顺序：--ffmpeg 参数 → PATH → 项目 venv 的 imageio_ffmpeg binaries。"""
    if explicit and os.path.isfile(explicit):
        return explicit
    which = shutil.which("ffmpeg")
    if which:
        return which
    pattern = os.path.join(
        os.path.dirname(HERE), "..", ".venv", "Lib", "site-packages",
        "imageio_ffmpeg", "binaries", "ffmpeg-*.exe")
    hits = sorted(glob.glob(os.path.abspath(pattern)))
    return hits[0] if hits else None


def ensure_wav(input_path, ffmpeg):
    """非 16k mono wav 输入 → 用 ffmpeg 转出临时 wav（覆盖到 fixtures/_converted）。"""
    if input_path.lower().endswith(".wav"):
        return input_path, None
    if not ffmpeg:
        raise SystemExit("[poc] 需要 ffmpeg 转码该输入格式（--ffmpeg 指定路径）")
    out_dir = os.path.join(HERE, "fixtures", "_converted")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, os.path.splitext(os.path.basename(input_path))[0] + ".wav")
    cmd = [ffmpeg, "-y", "-i", input_path, "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", out]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.isfile(out):
        raise SystemExit(f"[poc] ffmpeg 转码失败:\n{r.stderr[-800:]}")
    return out, out


def wav_duration_seconds(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate())


def system_info():
    info = {
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
    }
    try:
        info["ram_gb"] = round(ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory() / 1024 ** 3, 1)
    except Exception:
        pass
    return info


def resolve_revision(model_id):
    """best-effort 读取 modelscope 缓存中的实际 revision；读不到如实写 not-cached。

    实测新版 modelscope 缓存布局：
      ~/.cache/modelscope/models/<org>--<name>/snapshots/<revision>/
    """
    home = os.environ.get("MODELSCOPE_CACHE",
                          os.path.join(os.path.expanduser("~"), ".cache", "modelscope"))
    org, name = model_id.split("/")
    roots = [
        os.path.join(home, "models", f"{org}--{name}"),
        os.path.join(home, "hub", "models", *model_id.split("/")),
        os.path.join(home, "models", *model_id.split("/")),
    ]
    for root in roots:
        snap = os.path.join(root, "snapshots")
        if os.path.isdir(snap):
            revs = sorted(os.listdir(snap))
            if revs:
                return f"snapshots/{revs[-1]} (auto)"
            return "cached(no revision marker)"
    return "not-cached"


def build_model(device):
    from funasr import AutoModel  # noqa: 延迟导入，性能统计准确
    t0 = time.perf_counter()
    model = AutoModel(
        model=ASR_MODEL_ID,
        vad_model=VAD_MODEL_ID,
        vad_kwargs={"max_single_segment_time": 15000},  # utterance 基本单位 2~10s（设计文档 §5.4），30s 一句太粗
        spk_model=SPK_MODEL_ID,
        device=device,
        disable_update=True,
        disable_pbar=True,
    )
    return model, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default=None, help="输出 json 路径（默认 outputs/<name>.audio_understanding.v1.json）")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--dump-raw", action="store_true", help="额外保存 sentence_info 原始样本")
    ap.add_argument("--project-id", default="poc")
    args = ap.parse_args()

    sys_info = system_info()
    log(f"环境: {sys_info['platform']} | CPU {sys_info['cpu_count']} 核 | python {sys_info['python']}")

    wav_path, converted = ensure_wav(os.path.abspath(args.input), find_ffmpeg())
    audio_seconds = wav_duration_seconds(wav_path)
    log(f"输入: {wav_path} ({audio_seconds:.1f}s @16k mono)")

    import torch
    import funasr
    cuda = torch.cuda.is_available()
    log(f"funasr {funasr.__version__} | torch {torch.__version__} | cuda可用: {cuda}")

    model, load_seconds = build_model(args.device)
    log(f"模型加载(含缺失模型下载)耗时 {load_seconds:.1f}s")

    t0 = time.perf_counter()
    res = model.generate(input=wav_path, cache={}, batch_size_s=60, hotword="")
    infer_seconds = time.perf_counter() - t0
    rtf = infer_seconds / audio_seconds if audio_seconds else None
    log(f"推理耗时 {infer_seconds:.1f}s | RTF {rtf:.3f}" if rtf else "推理完成")

    result = res[0] if res else {}
    sentences = result.get("sentence_info") or []
    if args.dump_raw:
        raw_path = os.path.join(HERE, "outputs", "raw_probe.json")
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump({
                "top_keys": sorted(result.keys()),
                "text_head": (result.get("text") or "")[:400],
                "sentence_info_count": len(sentences),
                "sentence_info_sample": sentences[:3],
            }, f, ensure_ascii=False, indent=2, default=str)
        log(f"原始结构样本 → {raw_path}")

    # ---------- 组装 sidecar ----------
    engines = {
        "asr": {"id": ASR_MODEL_ID, "revision": resolve_revision(ASR_MODEL_ID),
                "runtime": f"funasr {funasr.__version__} / torch {torch.__version__}"},
        "vad": {"id": VAD_MODEL_ID, "revision": resolve_revision(VAD_MODEL_ID)},
        "diarization": {"id": SPK_MODEL_ID, "revision": resolve_revision(SPK_MODEL_ID)},
    }
    doc = schema.new_document(
        project_id=args.project_id,
        source_media=os.path.basename(args.input),
        duration_ms=int(audio_seconds * 1000),
        engines=engines,
    )
    doc["meta"]["performance"] = {
        "load_seconds": round(load_seconds, 2),
        "infer_seconds": round(infer_seconds, 2),
        "audio_seconds": round(audio_seconds, 2),
        "rtf": round(rtf, 4) if rtf else None,
        "device": args.device,
        "cuda_available": cuda,
        "system": sys_info,
    }

    for s in sentences:
        parsed = normalize.parse_rich_text(s.get("text", ""))
        text = parsed["clean_text"]
        if not text:
            continue
        start_ms = int(s.get("start") or 0)
        end_ms = int(s.get("end") or 0)
        spk = s.get("spk")
        sid = None
        if spk is not None:
            sid = schema.add_speaker(doc, int(spk))
        affect = None
        if parsed["emotion_raw"]:
            affect = {
                "label": normalize.normalize_emotion(parsed["emotion_raw"]),
                "raw_label": parsed["emotion_raw"],
                "source": "sensevoice",
                "confidence": None,
            }
        utt = schema.add_utterance(
            doc, start_ms, end_ms, text, speaker_id=sid, language=parsed["language"],
            affect=affect,
            paralinguistic_tags=[normalize.normalize_event(t) for t in parsed["events_raw"]
                                 if normalize.normalize_event(t) not in NON_EVENT_LABELS],
        )
        if parsed["unknown_tokens"]:
            doc["warnings"].append(f"{utt['utterance_id']}: 未知 token {parsed['unknown_tokens']}")
        for raw in parsed["events_raw"]:
            label = normalize.normalize_event(raw)
            if label in NON_EVENT_LABELS:
                continue
            schema.add_audio_event(doc, start_ms, end_ms, label, raw,
                                   linked_utterance_ids=[utt["utterance_id"]],
                                   speaker_ids=[sid] if sid else [])

    # speaker_turns：相邻同 spk 的 utterance 合并；与相邻 turn 重叠则标 overlap
    prev = None
    for u in doc["utterances"]:
        sid = u.get("speaker_id")
        if sid is None:
            prev = None
            continue
        if prev and prev["speaker_ids"] == [sid] and u["start_ms"] - prev["end_ms"] < 800:
            prev["end_ms"] = max(prev["end_ms"], u["end_ms"])
        else:
            if prev and u["start_ms"] < prev["end_ms"]:
                prev["overlap"] = True
            schema.add_speaker_turn(doc, u["start_ms"], u["end_ms"], [sid])
            prev = doc["speaker_turns"][-1]

    errors = schema.validate_document(doc)
    if errors:
        print("[poc] sidecar 校验失败，不写出：", *errors, sep="\n  - ")
        sys.exit(2)

    out_path = args.out or os.path.join(
        HERE, "outputs", os.path.splitext(os.path.basename(args.input))[0] + ".audio_understanding.v1.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    log(f"sidecar → {out_path}")

    # 顺手写 legacy 投影候选稿（不碰生产 transcripts/）
    import legacy_projection as projection
    cand_path = os.path.splitext(out_path)[0] + ".transcript_candidate.txt"
    projection.write_transcript_candidate(doc, cand_path)
    log(f"legacy 投影(候选, 不接入) → {cand_path}")

    n_emo = sum(1 for u in doc["utterances"] if u["affect"])
    log(f"汇总: 句 {len(doc['utterances'])} | 事件 {len(doc['audio_events'])} | "
        f"情绪标注 {n_emo}/{len(doc['utterances'])} | 说话人 {len(doc['speakers'])} | "
        f"话轮 {len(doc['speaker_turns'])} | 警告 {len(doc['warnings'])}")


if __name__ == "__main__":
    main()
