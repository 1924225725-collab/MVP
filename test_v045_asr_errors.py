# ============================================================
# test_v045_asr_errors.py —— 本地 ASR 错误处理链路验收（V0.4.5）
#
# 背景（用户报告的严重问题）：
#   网页版对**任何**上传视频都统一提示「视频处理失败，请换一个文件试试」。
#   根因：模型加载时联网校验被代理拦成 502，异常被统一 catch；
#   且「损坏 / 没音轨 / 模型没装」都被压成同一句，无法区分。
#
# 本测试覆盖用户要求的 4 种情况 + 另外 3 种（静音 / 模型加载失败 / 推理失败）：
#   1. 正常、有音轨的视频  → 必须真正走完本地 ASR（不再进失败分支）
#   2. 没有音轨的视频      → 未检测到音轨
#   3. 明显损坏的视频      → 媒体文件无法读取
#   4. 本地模型不存在      → 模型未安装
#   5. 有音轨但全静音      → 没有识别出内容
#   6. 模型存在但加载失败  → 模型加载失败（模拟）
#   7. 模型跑通但推理报错  → 语音识别推理失败（模拟）
#   最后：确认 7 种结果**互不相同**，且界面文案不再全部是同一句。
#
# 运行：.\.venv\Scripts\python test_v045_asr_errors.py
# 结果：v045_asr_report.txt
# ============================================================

import ast
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

import errors  # noqa: E402
import pipeline  # noqa: E402
from errors import ProcessError  # noqa: E402

MEDIA = BASE / "_test_media"
LINES = []
STAGES = {}


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    LINES.append(f"[{tag}] {name} —— {detail}")
    print(f"[{tag}] {name} —— {detail}")
    return ok


def expect_stage(label, fn, want_stage):
    """跑 fn，期望抛 ProcessError 且 stage == want_stage。"""
    try:
        fn()
    except ProcessError as e:
        STAGES[label] = e.stage
        return check(f"{label}", e.stage == want_stage,
                     f"stage={e.stage}" + ("" if e.stage == want_stage else f"（期望 {want_stage}）"))
    except BaseException as e:
        STAGES[label] = f"UNCAUGHT:{type(e).__name__}"
        return check(f"{label}", False, f"抛出了非 ProcessError：{type(e).__name__}: {e}")
    STAGES[label] = "NO_ERROR"
    return check(f"{label}", False, "没有报错（期望失败）")


print("=" * 72)
print("V0.4.5 验收：本地 ASR 错误处理链路（分层提示）")
print("=" * 72)

# ============================================================
# 1. 正常、有音轨的视频 —— 必须真正走完本地 ASR
# ============================================================
print("\n--- 1. 正常视频（有音轨）---")
normal = MEDIA / "normal.mp4"
try:
    res = pipeline.process_video(normal)
    STAGES["正常视频"] = "OK"
    check("1. 正常视频成功走完本地 ASR", bool(res and res["segments"]),
          f"识别 {len(res['segments'])} 句 → {Path(res['transcript']).name}")
    check("1b. 正常视频生成了音频文件", res["audio"].exists(),
          f"{Path(res['audio']).name}（{res['audio'].stat().st_size} 字节）")
except ProcessError as e:
    STAGES["正常视频"] = e.stage
    check("1. 正常视频成功走完本地 ASR", False, f"失败！stage={e.stage}: {e}")
    print(e.detail[:1500])

# ============================================================
# 2. 没有音轨的视频
# ============================================================
print("\n--- 2. 没有音轨的视频 ---")
expect_stage("2. 无音轨视频 → 未检测到音轨",
             lambda: pipeline.process_video(MEDIA / "no_audio.mp4"),
             errors.STAGE_NO_AUDIO)

# ============================================================
# 3. 明显损坏的视频
# ============================================================
print("\n--- 3. 损坏的视频 ---")
expect_stage("3. 损坏视频 → 媒体文件无法读取",
             lambda: pipeline.process_video(MEDIA / "broken.mp4"),
             errors.STAGE_MEDIA_UNREADABLE)

# ============================================================
# 4. 本地模型不存在（子进程 + 空模型缓存 + 强制离线）
# ============================================================
print("\n--- 4. 本地模型未安装 ---")
with tempfile.TemporaryDirectory() as empty_cache:
    code = (
        "import sys\n"
        f"sys.path.insert(0, r'{BASE}')\n"
        "from asr.local_whisper import LocalWhisperRecognizer\n"
        "from errors import ProcessError\n"
        "try:\n"
        "    LocalWhisperRecognizer('small')\n"
        "    print('STAGE=OK')\n"
        "except ProcessError as e:\n"
        "    print('STAGE=' + e.stage)\n"
        "except BaseException as e:\n"
        "    print('STAGE=UNCAUGHT:' + type(e).__name__)\n"
    )
    env = dict(os.environ)
    env.update({
        "HF_HOME": empty_cache,
        "HF_HUB_CACHE": empty_cache,
        "HUGGINGFACE_HUB_CACHE": empty_cache,
        "HF_HUB_OFFLINE": "1",
    })
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(BASE), env=env)
    out = (proc.stdout or "") + (proc.stderr or "")
    got = next((ln.split("=", 1)[1].strip() for ln in out.splitlines()
                if ln.startswith("STAGE=")), "NO_OUTPUT")
    STAGES["模型未安装"] = got
    check("4. 模型未安装 → 模型未安装", got == errors.STAGE_MODEL_MISSING,
          f"stage={got}" + ("" if got == errors.STAGE_MODEL_MISSING else "（期望 model_missing）"))
    if got != errors.STAGE_MODEL_MISSING:
        print(out[-1500:])

# ============================================================
# 5. 有音轨但全静音 → 没有识别出内容
# ============================================================
print("\n--- 5. 有音轨但全静音 ---")
expect_stage("5. 静音视频 → 没有识别出内容",
             lambda: pipeline.process_video(MEDIA / "silent.mp4"),
             errors.STAGE_ASR_EMPTY)

# ============================================================
# 6. 模型存在但加载失败（模拟：WhisperModel 构造即抛非"未缓存"错误）
# ============================================================
print("\n--- 6. 模型加载失败（模拟）---")


def _fake_faster_whisper(model_cls):
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = model_cls
    return mod


def _with_fake_model(model_cls, fn):
    old = sys.modules.get("faster_whisper")
    sys.modules["faster_whisper"] = _fake_faster_whisper(model_cls)
    try:
        return fn()
    finally:
        if old is not None:
            sys.modules["faster_whisper"] = old
        else:
            sys.modules.pop("faster_whisper", None)


def _new_recognizer():
    from asr.local_whisper import LocalWhisperRecognizer
    return LocalWhisperRecognizer("small")


def _load_fail():
    def boom(*a, **k):
        raise RuntimeError("simulated corrupt model file")
    _with_fake_model(boom, _new_recognizer)


expect_stage("6. 模型加载失败 → 模型加载失败", _load_fail, errors.STAGE_MODEL_LOAD)

# ============================================================
# 7. 模型跑通但推理报错（模拟）
# ============================================================
print("\n--- 7. ASR 推理失败（模拟）---")


class _InferBoom:
    def transcribe(self, *a, **k):
        raise RuntimeError("simulated inference failure")


expect_stage(
    "7. 推理失败 → 语音识别推理失败",
    lambda: pipeline.transcribe_audio(MEDIA / "normal.mp3", recognizer=_InferBoom()),
    errors.STAGE_ASR_INFERENCE,
)

# ============================================================
# 8. 探测层能区分正常 / 无音轨 / 损坏
# ============================================================
print("\n--- 8. probe_media 区分能力 ---")
p_ok = pipeline.probe_media(MEDIA / "normal.mp4")
p_no = pipeline.probe_media(MEDIA / "no_audio.mp4")
p_bad = pipeline.probe_media(MEDIA / "broken.mp4")
check("8. 正常视频：可读 + 有音轨", p_ok["readable"] and p_ok["has_audio"],
      f"readable={p_ok['readable']} has_audio={p_ok['has_audio']} duration={p_ok['duration']}")
check("8b. 无音轨视频：可读但无音轨", p_no["readable"] and not p_no["has_audio"],
      f"readable={p_no['readable']} has_audio={p_no['has_audio']}")
check("8c. 损坏视频：不可读", not p_bad["readable"],
      f"readable={p_bad['readable']} fatal={p_bad.get('fatal')}")

# ============================================================
# 9. 七种结果互不相同（核心诉求：不再全部同一句）
# ============================================================
print("\n--- 9. 各情况结果互不相同 ---")
distinct = sorted(set(STAGES.values()))
check("9. 各情况报错阶段互不相同", len(distinct) >= 7, f"{STAGES}")
check("9b. 正常视频不再进入任何失败分支", STAGES.get("正常视频") == "OK",
      f"正常视频 stage={STAGES.get('正常视频')}")

# ============================================================
# 10. UI 文案映射：每个 stage 都有独立文案，且不再有旧的统一提示
# ============================================================
print("\n--- 10. UI 错误文案映射 ---")
tree = ast.parse((BASE / "ui.py").read_text(encoding="utf-8"))
ui_map = None
for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "_ASR_ERROR_UI" for t in node.targets):
        ui_map = {}
        for k_node, v_node in zip(node.value.keys, node.value.values):
            ui_map[getattr(errors, k_node.id)] = ast.literal_eval(v_node)
        break

check("10. ui.py 里存在 _ASR_ERROR_UI 映射表", bool(ui_map), f"{len(ui_map or {})} 条")
if ui_map:
    need = [errors.STAGE_MEDIA_UNREADABLE, errors.STAGE_NO_AUDIO, errors.STAGE_AUDIO_EXTRACT,
            errors.STAGE_FFMPEG, errors.STAGE_DEPENDENCY, errors.STAGE_MODEL_MISSING,
            errors.STAGE_MODEL_LOAD, errors.STAGE_ASR_INFERENCE, errors.STAGE_ASR_EMPTY]
    missing = [s for s in need if s not in ui_map]
    check("10b. 所有 ASR 相关 stage 都有界面文案", not missing, f"缺少={missing or '无'}")

    titles = [ui_map[s][0] for s in need if s in ui_map]
    check("10c. 各 stage 的提示标题互不相同", len(set(titles)) == len(titles),
          f"{titles}")

    old_msg = "视频处理失败，请换一个文件试试"
    leaked = [s for s in need if s in ui_map and old_msg in ui_map[s][1]]
    check("10d. 旧的统一提示语已从各分层文案中移除", not leaked, f"残留={leaked or '无'}")

    dup = [s for s in ("media_unreadable", "no_audio_track")
           if s in ui_map and ui_map[s] == ui_map.get(errors.STAGE_AUDIO_EXTRACT)]
    check("10e. 「损坏」「没音轨」「提取失败」三者文案不重复", not dup, f"重复={dup or '无'}")

# ============================================================
# 清理测试产物（不污染 transcripts/ 列表）
# ============================================================
for stem in ("normal", "silent", "no_audio", "broken"):
    for p in (BASE / "transcripts" / f"{stem}.txt", BASE / "audio" / f"{stem}.mp3"):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
pipeline._recognizer_cache = None

print("\n" + "=" * 72)
total = len(LINES)
passed = sum(1 for l in LINES if l.startswith("[PASS]"))
print(f"结果：{passed}/{total} 通过" + ("" if passed == total else f"，{total - passed} 个失败"))
print("=" * 72)

(BASE / "v045_asr_report.txt").write_text(
    "V0.4.5 验收报告：本地 ASR 错误处理链路（分层提示）\n\n"
    + "各情况实际结果：\n"
    + "\n".join(f"  {k} → {v}" for k, v in STAGES.items())
    + "\n\n" + "\n".join(LINES)
    + f"\n\n结果：{passed}/{total} 通过\n",
    encoding="utf-8",
)
print(f"report saved: {BASE / 'v045_asr_report.txt'}")
