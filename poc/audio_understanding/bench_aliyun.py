# -*- coding: utf-8 -*-
"""bench_aliyun.py —— 阿里云 speaker provider 在已有 benchmark 上的真实效果验证

【定位】PoC 验证脚本，独立于生产流程。只读 fixtures，只写 outputs。
        不改生产 pipeline / UI / DeepSeek / ASR。

【它做什么】
  1. 读 fixtures/benchmark_t2_*.wav 两个片段
  2. 通过 speaker/aliyun.py 调用阿里云录音文件识别（需公网音频 URL）
  3. 落盘：原始 API 返回 + 标准 speaker JSON
  4. 用与 CAM++ 完全相同的协议评估（复用 eval_speaker_benchmark.py）
  5. 生成对比报告

【硬前提（缺一不可）】
  A. 环境变量：ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET / ALIYUN_APP_KEY
  B. 音频可公网访问：阿里云只吃 URL，不吃本地文件
     - 传 --audio-url-base <前缀> ：脚本按 <前缀>/<文件名> 拼 URL
     - 或传 --oss-upload 打开内置 OSS 上传（需 oss2 + OSS 相关环境变量）

【用法】
  # 离线自检（不联网，验证脚本自身与协议一致性）
  python bench_aliyun.py --dry-run

  # 真实调用（音频已在公网）
  python bench_aliyun.py --audio-url-base https://your-bucket.oss-cn-shanghai.aliyuncs.com/bench

  # 真实调用（先用 OSS 上传本地 fixture）
  python bench_aliyun.py --oss-upload
"""

import argparse
import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # live_clipper/
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

FIXTURES = os.path.join(HERE, "fixtures")
BENCH_DIR = os.path.join(HERE, "outputs", "bench_aliyun")   # 供 eval 复用
OUT_ROOT = os.path.join(ROOT, "outputs", "speaker", "aliyun")  # 用户指定输出
RAW_DIR = os.path.join(OUT_ROOT, "raw")
UNI_DIR = os.path.join(OUT_ROOT, "unified")

KEYS = ["t2_0274_0360", "t2_2630_2685"]
WAV = {k: os.path.join(FIXTURES, f"benchmark_{k}.wav") for k in KEYS}

# GT 速查（来自 fixtures/speaker_ground_truth_t2_*.json，硬编码仅用于报告标题）
GT_SUMMARY = {
    "t2_0274_0360": {"speakers": 2, "switches": 5, "label": "简单题"},
    "t2_2630_2685": {"speakers": 3, "switches": 14, "label": "难题"},
}


def _ensure_dirs():
    for d in (BENCH_DIR, OUT_ROOT, RAW_DIR, UNI_DIR):
        os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------
# 可选：内置 OSS 上传（仅 --oss-upload 时启用；不改变模块本身）
# ---------------------------------------------------------------

def _oss_upload_factory():
    """返回一个 本地路径 -> 公网URL 的函数；依赖 OSS 环境变量。

    环境变量：OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / OSS_ENDPOINT / OSS_BUCKET
    （省着用：也可以用 ALIYUN_* 作为回退）
    """
    try:
        import oss2  # noqa: F401
    except ImportError:
        raise SystemExit(
            "  [错误] --oss-upload 需要 oss2：pip install oss2\n"
            "        或改用 --audio-url-base 传入你已有的公网前缀。")

    ak = (os.environ.get("OSS_ACCESS_KEY_ID") or os.environ.get("ALIYUN_ACCESS_KEY_ID") or "").strip()
    sk = (os.environ.get("OSS_ACCESS_KEY_SECRET") or os.environ.get("ALIYUN_ACCESS_KEY_SECRET") or "").strip()
    endpoint = (os.environ.get("OSS_ENDPOINT") or "").strip()
    bucket_name = (os.environ.get("OSS_BUCKET") or "").strip()
    if not (ak and sk and endpoint and bucket_name):
        raise SystemExit(
            "  [错误] --oss-upload 需要 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET / "
            "OSS_ENDPOINT / OSS_BUCKET")

    import oss2
    auth = oss2.Auth(ak, sk)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)

    def upload(local_path: str) -> str:
        key = f"bench/{os.path.basename(local_path)}"
        bucket.put_object_from_file(key, local_path)
        host = endpoint.replace("https://", "").replace("http://", "").rstrip("/")
        return f"https://{bucket_name}.{host}/{key}"

    return upload


# ---------------------------------------------------------------
# 核心：对单个 fixture 跑阿里云
# ---------------------------------------------------------------

def run_one(key, provider, audio_url, poll_interval, poll_timeout):
    """调用阿里云，返回 (raw_response, unified_list, timing, error_or_None)。"""
    from speaker import AliyunError

    raw_out = {}
    t0 = time.monotonic()
    err = None
    turns, uni = [], []
    try:
        turns = provider.diarize(audio_url, raw_out=raw_out,
                                 poll_interval=poll_interval, poll_timeout=poll_timeout)
        from speaker import to_unified
        uni = to_unified(turns)
    except AliyunError as e:
        err = str(e)
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    elapsed = round(time.monotonic() - t0, 2)

    raw_response = raw_out.get("response")

    # 落盘：原始返回
    with open(os.path.join(RAW_DIR, f"{key}.raw.json"), "w", encoding="utf-8") as f:
        json.dump({"fixture": key, "audio_url": audio_url,
                   "elapsed_s": elapsed, "error": err,
                   "response": raw_response}, f, ensure_ascii=False, indent=2)

    # 落盘：标准 speaker JSON（统一格式）
    with open(os.path.join(UNI_DIR, f"{key}.speaker.json"), "w", encoding="utf-8") as f:
        json.dump(uni, f, ensure_ascii=False, indent=2)

    # 落盘：给 eval_speaker_benchmark 用的格式（它读 outputs/bench/<key>.<cfg>.json）
    spk_segments = [{"start": int(round(u["start"] * 1000)),
                     "end": int(round(u["end"] * 1000)),
                     "spk": u["speaker"]} for u in uni]
    bench_payload = {
        "segments": spk_segments,
        "timing": {"elapsed_s": elapsed},
        "meta": {"provider": "aliyun", "audio_url": audio_url, "error": err},
    }
    with open(os.path.join(BENCH_DIR, f"{key}.aliyun.json"), "w", encoding="utf-8") as f:
        json.dump(bench_payload, f, ensure_ascii=False, indent=2)

    return raw_response, uni, {"elapsed_s": elapsed}, err


# ---------------------------------------------------------------
# 报告
# ---------------------------------------------------------------

def write_report(per_key, eval_results, meta, out_path):
    lines = []
    A = lines.append
    A("# 阿里云智能语音 —— Speaker Diarization Benchmark 报告")
    A("")
    A(f"日期：{meta['date']} ｜ Provider：`aliyun`（录音文件识别 OpenAPI 2018-08-17）"
      f" ｜ Region：{meta['region']}")
    A(f"音频：`poc/audio_understanding/fixtures/benchmark_t2_*.wav`"
      f" ｜ 评估协议：与 CAM++ 完全一致（主容差 ±1500ms）")
    A("")
    A("> 本报告为 PoC 独立验证，未改生产 pipeline / UI / DeepSeek / ASR。")
    A("")

    # 运行状态
    any_err = any(v.get("error") for v in per_key.values())
    if any_err:
        A("## 0. 运行状态")
        A("")
        A("| fixture | 状态 | 说明 |")
        A("|---|---|---|")
        for k in KEYS:
            v = per_key[k]
            st = "❌ 失败" if v.get("error") else "✅ 成功"
            A(f"| {k} | {st} | {v.get('error') or '调用成功'} |")
        A("")
        A("**注意：因存在失败，下方指标不足以作为路线判定依据。**")
        A("")

    A("## 1. 结果总表（主容差 ±1.5s）")
    A("")
    A("| fixture | 难度 | 句子/段数 | 人数（预测/真实） | 切换 R | 切换 P | Attribution | 判读 |")
    A("|---|---|---|---|---|---|---|---|")
    for k in KEYS:
        g = GT_SUMMARY[k]
        r = eval_results.get(f"{k}/aliyun")
        if not r:
            A(f"| {k} | {g['label']} | — | — | — | — | — | 无数据 |")
            continue
        cnt = r["count"]
        sw = r["switch"]["1500"]
        att = r["attribution"]["accuracy"]
        att_s = f"{att*100:.1f}%" if att is not None else "N/A"
        verdict = "人数对 ✓" if cnt["correct"] else f"人数错 ✗"
        A(f"| {k} | {g['label']} | {r['pred']['segment_count']} | "
          f"**{cnt['pred']} / {cnt['human']}** | {sw['recall']} | {sw['precision']} | "
          f"{att_s} | {verdict} |")
    A("")

    A("## 2. 容差敏感性（R / P）")
    A("")
    A("| fixture | ±1.0s | ±1.5s | ±2.0s |")
    A("|---|---|---|---|")
    for k in KEYS:
        r = eval_results.get(f"{k}/aliyun")
        if not r:
            continue
        cells = [f"{r['switch'][t]['recall']} / {r['switch'][t]['precision']}"
                 for t in ("1000", "1500", "2000")]
        A(f"| {k} | " + " | ".join(cells) + " |")
    A("")

    A("## 3. 与 GT 对比（逐切换点）")
    A("")
    for k in KEYS:
        r = eval_results.get(f"{k}/aliyun")
        if not r:
            continue
        g = GT_SUMMARY[k]
        A(f"### {k}（GT：{g['speakers']} 人 / {g['switches']} 次切换）")
        A("")
        A(f"- 预测簇数：**{r['pred']['cluster_count']}**")
        A(f"- 预测切换点数：**{r['pred']['pred_switch_count']}** "
          f"（GT {r['gt']['human_switch_count']}）")
        A(f"- 预测切换点(ms)：{r['pred']['pred_switches_ms']}")
        A(f"- 人工切换点(ms)：{r['gt']['human_switches_ms']}")
        A(f"- 最佳簇→人映射：{r['attribution']['mapping']}")
        A("")
    A("")

    A("## 4. 原始产物")
    A("")
    A(f"- 原始 API 返回：`outputs/speaker/aliyun/raw/<key>.raw.json`")
    A(f"- 标准 speaker JSON：`outputs/speaker/aliyun/unified/<key>.speaker.json`")
    A(f"- 评估明细：`outputs/speaker/aliyun/benchmark_eval.json`")
    A("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_path


# ---------------------------------------------------------------
# main
# ---------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="离线自检：不联网，用假数据走通全流程")
    ap.add_argument("--audio-url-base", default="",
                    help="公网音频前缀，脚本拼 <base>/benchmark_t2_xxx.wav")
    ap.add_argument("--oss-upload", action="store_true",
                    help="用 OSS 上传本地 fixture 后调用（需 oss2 + OSS 环境变量）")
    ap.add_argument("--poll-interval", type=int, default=5)
    ap.add_argument("--poll-timeout", type=int, default=1800)
    ap.add_argument("--keys", default=",".join(KEYS),
                    help="逗号分隔的 fixture key（默认两个）")
    args = ap.parse_args()

    _ensure_dirs()
    keys = [k.strip() for k in args.keys.split(",") if k.strip()]

    print("=" * 66)
    print("阿里云 Speaker Diarization Benchmark（PoC）")
    print("=" * 66)

    if args.dry_run:
        print("\n[DRY-RUN] 离线自检模式：不联网，用假数据验证全流程与协议一致性")
        return _dry_run(keys)

    # ---- 真实调用分支 ----
    from speaker import AliyunSpeakerProvider, AliyunError
    from speaker import config as spk_config

    missing = spk_config.aliyun_describe_missing()
    if missing:
        print("\n[阻塞] 缺少环境变量：" + ", ".join(missing))
        print("       请先 export ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET / ALIYUN_APP_KEY")
        return 2

    upload_fn = None
    url_base = args.audio_url_base.rstrip("/")
    if args.oss_upload:
        print("\n[OSS] 启用内置上传...")
        upload_fn = _oss_upload_factory()
    elif not url_base:
        print("\n[阻塞] 需要一个公网音频地址：")
        print("       --audio-url-base https://your-bucket.oss-cn-shanghai.aliyuncs.com/bench")
        print("       或 --oss-upload（需 oss2 + OSS_* 环境变量）")
        print("       阿里云录音文件识别只吃公网 URL，不吃本地文件。")
        return 2

    provider = AliyunSpeakerProvider(upload_fn=upload_fn)
    ok, why = provider.is_available()
    print(f"\n[provider] available={ok} ({why})")
    if not ok:
        return 2

    per_key = {}
    for k in keys:
        if k not in WAV or not os.path.exists(WAV[k]):
            print(f"  [跳过] 找不到 fixture：{WAV.get(k)}")
            continue
        if upload_fn is not None:
            audio_url = upload_fn(WAV[k])
        else:
            audio_url = f"{url_base}/{os.path.basename(WAV[k])}"
        print(f"\n[{k}] 调用中... URL={audio_url}")
        _, uni, timing, err = run_one(k, provider, audio_url,
                                      args.poll_interval, args.poll_timeout)
        per_key[k] = {"error": err, "n_turns": len(uni),
                      "n_speakers": len({u['speaker'] for u in uni}),
                      "elapsed_s": timing["elapsed_s"]}
        if err:
            print(f"  [失败] {err}")
        else:
            print(f"  [成功] {len(uni)} 段 / "
                  f"{len({u['speaker'] for u in uni})} 位说话人 / {timing['elapsed_s']}s")

    return _finalize(keys, per_key, args)


def _finalize(keys, per_key, args):
    """跑评估 + 写报告（dry-run 与真实共用）。"""
    from eval_speaker_benchmark import (PRIMARY_TOL_MS, TOLERANCES_MS,  # noqa: E402
                                        attribution, load_gt, match_switches)

    eval_results = {}
    for k in keys:
        bench_fp = os.path.join(BENCH_DIR, f"{k}.aliyun.json")
        if not os.path.exists(bench_fp):
            continue
        gt = load_gt(k)
        with open(bench_fp, encoding="utf-8") as f:
            d = json.load(f)
        pool = [s for s in d["segments"] if s["end"] > s["start"]]
        pool.sort(key=lambda s: (s["start"], s["end"]))
        switches = [pool[i]["start"] for i in range(1, len(pool))
                    if pool[i]["spk"] != pool[i - 1]["spk"]]
        spks = sorted({s["spk"] for s in pool})
        # overlap 剔除（与 pyannote 协议一致）
        bounds = sorted({s["start"] for s in pool} | {s["end"] for s in pool})
        clean, overlap_ms = [], 0
        for a, b in zip(bounds, bounds[1:]):
            active = [s for s in pool if s["start"] <= a and s["end"] >= b]
            if not active:
                continue
            if len({s["spk"] for s in active}) == 1:
                clean.append({"start": a, "end": b, "spk": active[0]["spk"]})
            else:
                overlap_ms += b - a

        r = {
            "gt": {"human_total": gt["human_total"],
                   "human_switch_count": len(gt["switches"]),
                   "human_switches_ms": [round(s["t_ms"]) for s in gt["switches"]]},
            "pred": {"cluster_count": len(spks), "segment_count": len(pool),
                     "pred_switch_count": len(switches), "pred_switches_ms": switches,
                     "overlap_excluded_ms": overlap_ms},
            "count": {"pred": len(spks), "human": gt["human_total"],
                      "correct": len(spks) == gt["human_total"]},
            "switch": {},
            "attribution": attribution(clean, gt["labels"], gt["human_spks"], spks),
        }
        for tol in TOLERANCES_MS:
            matched = match_switches(switches, [s["t_ms"] for s in gt["switches"]], tol)
            tp = len(matched)
            r["switch"][str(tol)] = {
                "recall": round(tp / len(gt["switches"]), 3) if gt["switches"] else None,
                "precision": round(tp / len(switches), 3) if switches else None,
                "tp": tp,
            }
        eval_results[f"{k}/aliyun"] = r
        sw = r["switch"][str(PRIMARY_TOL_MS)]
        att = r["attribution"]["accuracy"]
        print(f"[{k}/aliyun] count {len(spks)}/{gt['human_total']} "
              f"({'OK' if r['count']['correct'] else 'X'}) "
              f"switch R={sw['recall']} P={sw['precision']} (±{PRIMARY_TOL_MS}ms) "
              f"attribution={(f'{att*100:.1f}%' if att is not None else 'N/A')}")

    with open(os.path.join(OUT_ROOT, "benchmark_eval.json"), "w", encoding="utf-8") as f:
        json.dump({"tolerances_ms": TOLERANCES_MS, "primary_tol_ms": PRIMARY_TOL_MS,
                   "results": eval_results}, f, ensure_ascii=False, indent=2)

    from speaker import config as spk_config
    meta = {"date": datetime.date.today().isoformat(),
            "region": spk_config.get_aliyun_region()}
    out_md = os.path.join(ROOT, "outputs", "speaker",
                          "aliyun_benchmark_report.md")
    write_report(per_key, eval_results, meta, out_md)
    print(f"\n-> 报告：{out_md}")
    print(f"-> 评估：{os.path.join(OUT_ROOT, 'benchmark_eval.json')}")
    print(f"-> 原始：{RAW_DIR}")
    print(f"-> 统一：{UNI_DIR}")
    return 0


def _dry_run(keys):
    """用合成的假数据走通全流程，验证脚本 + 协议一致（不联网）。"""
    fake = {
        "t2_0274_0360": [
            (0, 38000, "spk_0"), (39200, 41100, "spk_1"), (41900, 81200, "spk_0"),
            (81200, 82600, "spk_1"), (83000, 83500, "spk_0"), (83900, 85600, "spk_1"),
        ],
        "t2_2630_2685": [
            (0, 8200, "spk_0"), (8200, 9000, "spk_1"), (9700, 14800, "spk_0"),
            (15000, 25200, "spk_1"), (25200, 27700, "spk_0"), (27700, 29581, "spk_2"),
            (29581, 31400, "spk_0"), (31400, 33400, "spk_1"), (33400, 45000, "spk_0"),
            (45000, 46100, "spk_1"), (46100, 46900, "spk_0"), (46900, 51200, "spk_1"),
            (51200, 52300, "spk_2"), (52300, 54700, "spk_0"),
        ],
    }
    per_key = {}
    for k in keys:
        uni = [{"start": s / 1000.0, "end": e / 1000.0, "speaker": spk}
               for s, e, spk in fake.get(k, [])]
        with open(os.path.join(UNI_DIR, f"{k}.speaker.json"), "w", encoding="utf-8") as f:
            json.dump(uni, f, ensure_ascii=False, indent=2)
        with open(os.path.join(RAW_DIR, f"{k}.raw.json"), "w", encoding="utf-8") as f:
            json.dump({"fixture": k, "dry_run": True, "response": None}, f,
                      ensure_ascii=False, indent=2)
        segs = [{"start": int(u["start"] * 1000), "end": int(u["end"] * 1000),
                 "spk": u["speaker"]} for u in uni]
        with open(os.path.join(BENCH_DIR, f"{k}.aliyun.json"), "w", encoding="utf-8") as f:
            json.dump({"segments": segs, "timing": {"elapsed_s": 0.0},
                       "meta": {"dry_run": True}}, f, ensure_ascii=False, indent=2)
        per_key[k] = {"error": None, "n_turns": len(uni),
                      "n_speakers": len({u["speaker"] for u in uni}), "elapsed_s": 0.0}
        print(f"  [dry] {k}: {len(uni)} 段 / {len({u['speaker'] for u in uni})} 人")
    print("\n[dry-run] 走通评估 + 报告生成...")
    rc = _finalize(keys, per_key, None)
    print("\n[dry-run] 完成。真实效果需配好凭据 + 公网 URL 后重跑。")
    return rc


if __name__ == "__main__":
    sys.exit(main())
