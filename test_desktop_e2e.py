# ============================================================
# test_desktop_e2e.py —— 桌面版端到端实测（**本地，不联网、不调 AI**）
#
# 验证「从选一个视频到拿到文字稿」这条链路在桌面版服务层里真的跑得通，
# 并且出错时**还是分层的**（延续 V0.4.5 / D-046 的要求）。
#
# 覆盖：
#   1. 视频探测（时长 / 有无音轨）
#   2. 导入到工作区
#   3. 本地 ASR 出稿（真的跑 faster-whisper）
#   4. 项目落盘 + 读回（project_id 校验、状态机）
#   5. 面板拿到项目后显示正确（有稿无分析 → 空态；视频信息页显示稿信息）
#   6. 两个项目互不污染（文字稿路径、行数各自独立）
#   7. 四种错误仍分层：文件不存在 / 损坏 / 无音轨 / 静音
#
# 用法：
#   .\.venv\Scripts\python test_desktop_e2e.py             # 用短片（快）
#   .\.venv\Scripts\python test_desktop_e2e.py --long       # 用完整 6 分钟视频（慢，约 90 秒）
# ============================================================

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

_TMP = Path(tempfile.mkdtemp(prefix="lc_e2e_"))
os.environ["LIVE_CLIPPER_HOME"] = str(_TMP)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS = 0
FAIL = 0
ROWS = []


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        ROWS.append(("PASS", name, ""))
    else:
        FAIL += 1
        ROWS.append(("FAIL", name, extra))
    print(f"  {'✔' if cond else '✘'} {name}" + (f"\n        实际：{extra}" if not cond and extra else ""))


def main():
    use_long = "--long" in sys.argv
    media = HERE / "_test_media"
    src = media / ("full_6min.mp4" if use_long else "normal.mp4")
    print(f"[环境] 工作区 = {_TMP}")
    print(f"[环境] 测试视频 = {src.name}（{src.stat().st_size/1024/1024:.1f} MB）")

    import app_paths
    app_paths.ensure_workspace()

    if not src.exists():
        check("0 测试视频存在", False, f"缺少 {src}（先跑 test_v045_asr_errors.py 生成 _test_media/）")
        return report()

    # ---------------- 1. 探测 ----------------
    from desktop.services.tasks import probe_video
    try:
        info = probe_video(src)
        check("1 视频探测成功",
              info.get("readable") and info.get("has_audio"), str(info))
        check("1 探测出时长", bool(info.get("duration")), str(info.get("duration")))
    except Exception as e:
        check("1 视频探测成功", False, f"{type(e).__name__}: {e}")
        return report()

    # ---------------- 2. 导入 ----------------
    from desktop.services.tasks import import_video
    ws_path = import_video(src)
    check("2 视频已导入工作区", ws_path.startswith(str(_TMP)) and Path(ws_path).exists(),
          ws_path)
    check("2 导入后文件名一致", Path(ws_path).name == src.name, ws_path)

    # ---------------- 3. 本地 ASR ----------------
    from desktop.services.tasks import transcribe_video
    t0 = time.time()
    try:
        res = transcribe_video(ws_path)
    except Exception as e:
        check("3 本地 ASR 出稿", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        return report()
    secs = time.time() - t0
    check("3 本地 ASR 出稿成功", int(res.get("lines", 0)) > 0,
          f"lines={res.get('lines')} segments={res.get('segments')}")
    check("3 文字稿落在工作区", str(res.get("transcript", "")).startswith(str(_TMP)),
          str(res.get("transcript")))
    print(f"         └ {res.get('lines')} 句 / {secs:.1f} 秒")

    # ---------------- 4. 项目落盘 ----------------
    from desktop.services import ProjectStore
    store = ProjectStore()
    proj = store.create(video_name=src.name, video_path=ws_path)
    proj["video"]["duration"] = res.get("duration", "")
    store.save(ProjectStore.mark_transcribed(proj, res["transcript"], res["lines"]))
    back = store.load(proj["project_id"])
    check("4 项目能读回来", back is not None)
    check("4 状态 = transcribed", (back or {}).get("state") == "transcribed",
          str((back or {}).get("state")))
    check("4 文字稿路径与行数已记录",
          (back or {}).get("transcript", {}).get("lines") == res["lines"])

    # ---------------- 5. 界面拿到这个项目 ----------------
    from PySide6.QtWidgets import QApplication
    from desktop import theme
    from desktop.ui import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.QSS)
    win = MainWindow()
    win.show()
    win.load_project(proj["project_id"])
    app.processEvents()

    check("5 顶栏显示当前视频名", src.name in win.video_title.text(), win.video_title.text())
    check("5 状态徽章 = 已出文字稿", "已出文字稿" in win.state_chip.text(),
          win.state_chip.text())
    ptxt = _dump(win.panel_project)
    check("5 视频信息页显示文字稿句数",
          str(res["lines"]) in ptxt, ptxt[:200])
    check("5 还没有分析 → 推荐页显示空态",
          "还没有分析结果" in win.panel_recommended._empty.text(),
          win.panel_recommended._empty.text())
    check("5 还没有分析 → 结构页显示空态",
          "还没有分析结果" in win.panel_structure.empty.text())
    check("5 有文字稿 → 「开始分析」按钮可用", win.btn_analyze.isEnabled())

    # ---------------- 6. 两个项目互不污染 ----------------
    src2 = media / "no_audio.mp4"
    if src2.exists():
        p2 = store.create(video_name=src2.name, video_path=str(src2))
        tr2 = str(_TMP / "transcripts" / "第二个项目的稿.txt")
        Path(tr2).parent.mkdir(parents=True, exist_ok=True)
        Path(tr2).write_text("[00:00 - 00:10] 这是第二个项目的台词\n", encoding="utf-8")
        store.save(ProjectStore.mark_transcribed(p2, tr2, 7))
        win.load_project(p2["project_id"])
        app.processEvents()
        t2 = _dump(win.panel_project)
        # 用**文字稿路径**做指纹（行数这种小数字在编号、时长里到处都是，容易误判）
        check("6 切到第二个项目后不再出现第一个的文字稿",
              str(res["transcript"]) not in t2, t2[:300])
        check("6 第二个项目显示自己的文字稿", "第二个项目的稿" in t2, t2[:300])
        check("6 顶栏换成第二个视频", src2.name in win.video_title.text(),
              win.video_title.text())
        win.load_project(proj["project_id"])
        app.processEvents()
        check("6 切回第一个项目，内容回来了",
              str(res["transcript"]) in _dump(win.panel_project))

    # ---------------- 7. 错误仍然分层 ----------------
    # 注意：探测（probe_video）只"如实报告"（readable / has_audio），不抛错；
    # 真正分层抛错的是**开始识别**（transcribe_video）。所以这里用后者验证，
    # 顺带也验证探测能把"有没有音轨"报出来。
    from desktop.services.tasks import probe_video as _probe
    from errors import ProcessError

    try:
        _probe(media / "no_audio.mp4")
        check("7 探测能报出「没有音轨」",
              _probe(media / "no_audio.mp4").get("has_audio") is False,
              str(_probe(media / "no_audio.mp4")))
    except ProcessError as e:
        check("7 探测能报出「没有音轨」", False, f"探测就抛错了：{e.stage} {e.message}")

    expects = [
        ("文件不存在", str(_TMP / "不存在.mp4"), "media_unreadable"),
        ("视频损坏", str(media / "broken.mp4"), "media_unreadable"),
        ("没有音轨", str(media / "no_audio.mp4"), "no_audio_track"),
    ]
    for label, path, want_stage in expects:
        if label != "文件不存在" and not Path(path).exists():
            check(f"7 {label} → {want_stage}", False, f"缺少测试文件 {path}")
            continue
        try:
            transcribe_video(path)
            check(f"7 {label} → {want_stage}", False, "竟然没报错")
        except ProcessError as e:
            check(f"7 {label} → {want_stage}", e.stage == want_stage,
                  f"实际 stage={e.stage}：{e.message}")
        except Exception as e:
            check(f"7 {label} → {want_stage}", False, f"{type(e).__name__}: {e}")

    # 静音视频：能探测但识别不出内容
    silent = media / "silent.mp4"
    if silent.exists():
        try:
            probe_video(silent)
            try:
                transcribe_video(str(silent))
                check("7 静音视频 → asr_empty", False, "识别通过了（本该报没内容）")
            except ProcessError as e:
                check("7 静音视频 → asr_empty", e.stage == "asr_empty",
                      f"实际 stage={e.stage}：{e.message}")
        except Exception as e:
            check("7 静音视频 → asr_empty", False, f"探测阶段就失败：{e}")

    win.close()
    return report()


def _dump(widget):
    from PySide6.QtWidgets import QLabel, QPlainTextEdit
    parts = []
    for lb in widget.findChildren(QLabel):
        parts.append(lb.text() or "")
    for te in widget.findChildren(QPlainTextEdit):
        parts.append(te.toPlainText() or "")
    return "\n".join(parts)


def report():
    print("\n" + "=" * 66)
    print(f"桌面版端到端实测：通过 {PASS} / 失败 {FAIL} / 共 {PASS + FAIL}")
    print("=" * 66)
    out = HERE / "desktop_e2e_report.txt"
    with open(out, "w", encoding="utf-8") as f:
        for status, name, extra in ROWS:
            f.write(f"[{status}] {name}" + (f"  -> {extra}" if extra else "") + "\n")
        f.write(f"\n通过 {PASS} / 失败 {FAIL}\n")
    print(f"报告已写入：{out}")
    print(f"（临时工作区：{_TMP}，保留以便查看真实产物）")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit:
        raise                       # main() 里主动退出，不要当成异常
    except BaseException:
        traceback.print_exc()
        code = 1
    sys.exit(code)
