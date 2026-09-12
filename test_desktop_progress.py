# ============================================================
# test_desktop_progress.py —— 进度显示系统验收（V0.5.2）
#
# 重点验证**百分比是真的**，不是假动画：
#   ASR 事件里的 percent，必须等于 detail 里"已处理时间 / 总时长"算出来的值。
#
# 覆盖：
#   1. 六个阶段定义齐全，事件结构完整
#   2. 节流：高频事件不会淹没界面，但换阶段 / 100% 一定发
#   3. 兼容旧回调（只吃一个字符串的函数）
#   4. AI 阶段日志翻译（海选/复审有真百分比，其余是里程碑）
#   5. **真跑一次本地 ASR**，逐条核对进度事件的真实性
#   6. 界面进度组件能离屏渲染
#
# 用法：
#   .\.venv\Scripts\python test_desktop_progress.py
#   .\.venv\Scripts\python test_desktop_progress.py --long   # 用 6 分钟视频（约 90 秒）
# ============================================================

import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

_TMP = Path(tempfile.mkdtemp(prefix="lc_prog_"))
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
        print(f"  ✔ {name}")
    else:
        FAIL += 1
        ROWS.append(("FAIL", name, extra))
        print(f"  ✘ {name}\n        实际：{extra}")


def main():
    use_long = "--long" in sys.argv
    import app_paths
    app_paths.ensure_workspace()

    # ---------------- 1. 阶段定义 ----------------
    import stages
    check("1 六个处理阶段齐全（读取视频/提取音频/VAD/语音识别/AI分析/生成结果）",
          len(stages.STAGE_ORDER) == 6
          and stages.STAGE_ORDER[0] == stages.STAGE_VIDEO_READ
          and stages.STAGE_ORDER[-1] == stages.STAGE_FINALIZE,
          str(stages.STAGE_ORDER))
    check("1 每个阶段都有中文标题和进行中说明",
          all(stages.STAGE_TITLES.get(s) and stages.STAGE_RUNNING_TEXT.get(s)
              for s in stages.STAGE_ORDER),
          str(stages.STAGE_TITLES))
    ev = stages.make_event(stages.STAGE_ASR, 45.2, "23:10 / 51:00")
    check("1 事件字段完整（stage/title/percent/detail/index/total_steps）",
          set(ev) >= {"stage", "title", "percent", "detail", "index", "total_steps"},
          str(sorted(ev)))
    check("1 语音识别是第 4 步", ev["index"] == 4 and ev["total_steps"] == 6, str(ev["index"]))
    check("1 百分比被夹在 0~100", 
          stages.make_event("x", 150)["percent"] == 100.0
          and stages.make_event("x", -5)["percent"] == 0.0)
    check("1 时间格式化正确",
          stages.fmt_clock(1390) == "23:10" and stages.fmt_clock(3661) == "1:01:01",
          f"{stages.fmt_clock(1390)} / {stages.fmt_clock(3661)}")

    # ---------------- 2. 节流 ----------------
    # min_dt 设大 → 单独验证"按百分比变化节流"这一支
    # （min_dt=0 的语义是"不按时间节流"，那样永远发，测不出节流）
    got = []
    sink = stages.ProgressSink(lambda e: got.append(e), structured=True,
                               min_dt=10.0, min_dpct=0.5)
    sink(stages.STAGE_ASR, 10.0, "a")
    sink(stages.STAGE_ASR, 10.1, "b")     # 变化太小 → 丢
    sink(stages.STAGE_ASR, 10.2, "c")     # 变化太小 → 丢
    sink(stages.STAGE_ASR, 50.0, "d")     # 变化够大 → 发
    check("2 高频小变化被节流丢掉", len(got) == 2, f"收到 {len(got)} 条")
    sink(stages.STAGE_VAD, None, "换阶段")  # 换阶段 → 必发
    check("2 换阶段一定发（用户要看到阶段变化）", len(got) == 3, f"收到 {len(got)} 条")
    got.clear()
    sink(stages.STAGE_ASR, 100.0, "完成", force=True)
    check("2 完成事件一定发", len(got) == 1 and got[0]["percent"] == 100.0, str(got))

    # ---------------- 3. 旧回调兼容 ----------------
    old = []

    def legacy(msg):
        old.append(msg)

    s2 = stages.ProgressSink(legacy)
    s2(stages.STAGE_ASR, 45.2, "23:10 / 51:00")
    check("3 只吃字符串的旧回调自动降级成一句话",
          len(old) == 1 and isinstance(old[0], str) and "45%" in old[0]
          and "23:10" in old[0],
          str(old))

    # ---------------- 4. AI 阶段日志翻译 ----------------
    from desktop.services.ai_progress import AiProgressTracker
    seen = []
    tr = AiProgressTracker(
        stages.ProgressSink(lambda e: seen.append(e), structured=True))
    tr.feed("[分区] 时长 51:39，共 12 个区块（直播类型：娱乐聊天）")
    tr.feed("[预算] 预计约 18000 token（标准模式预算 20000）")
    tr.feed("[海选] 区块 1/12：00:00 - 04:00")
    p1 = seen[-1]["percent"]
    tr.feed("[海选] 区块 12/12：47:00 - 51:39")
    p12 = seen[-1]["percent"]
    # 第 12/12 个区块是"正在扫最后一个" → 已完成 11/12，不谎报扫完
    check("4 海选进度按真实区块数推进",
          p1 is not None and p12 is not None and p1 < p12 and abs(p12 - 54.0) < 0.01,
          f"{p1} → {p12}")
    check("4 海选详情写明第几个区块",
          "区块 12/12" in seen[-1]["detail"], seen[-1]["detail"])
    tr.feed("[质检] 检查 12 个区块有没有漏掉的爆点…")
    check("4 质检阶段推进到里程碑", seen[-1]["percent"] >= 58, str(seen[-1]["percent"]))
    tr.feed("[事件聚合] 15 个候选 → 13 个事件")
    tr.feed("[复审] 共 13 个事件，分批复审…")
    tr.feed("[复审] 批次 1/3（5 个事件）…")
    q1 = seen[-1]["percent"]
    tr.feed("[复审] 批次 3/3（3 个事件）…")
    q3 = seen[-1]["percent"]
    check("4 复审进度按真实批次数推进", q1 < q3, f"{q1} → {q3}")
    tr.feed("[结构] 为本场视频生成 Chapter / Story …")
    tr.feed("[报告] 整场分析报告已生成")
    tr.finish()
    check("4 结束点到达 100%", seen[-1]["percent"] == 100.0, str(seen[-1]["percent"]))
    check("4 进度单调不倒退",
          all(a["percent"] <= b["percent"] for a, b in zip(seen, seen[1:])
              if a["percent"] is not None and b["percent"] is not None),
          str([e["percent"] for e in seen]))
    check("4 所有事件都属于 AI 阶段",
          all(e["stage"] == stages.STAGE_AI for e in seen), "")

    # ---------------- 5. 真跑一次本地 ASR，核对进度真实性 ----------------
    media = HERE / "_test_media" / ("full_6min.mp4" if use_long else "normal.mp4")
    if not media.exists():
        print(f"\n[5] 跳过真跑验证（缺少 {media}）")
    else:
        print(f"\n[5] 真跑本地 ASR 核对进度真实性（{media.name}）…")
        from desktop.services.tasks import transcribe_video
        events = []
        res = transcribe_video(str(media), progress=lambda e: events.append(e))
        stages_seen = [e["stage"] for e in events]
        check("5 上报了「读取视频」阶段", stages.STAGE_VIDEO_READ in stages_seen, str(stages_seen))
        check("5 上报了「提取音频」阶段", stages.STAGE_AUDIO_EXTRACT in stages_seen)
        check("5 上报了「VAD 人声检测」阶段", stages.STAGE_VAD in stages_seen)
        check("5 上报了「语音识别」阶段", stages.STAGE_ASR in stages_seen)
        check("5 阶段按顺序出现（VAD 在语音识别之前）",
              stages_seen.index(stages.STAGE_VAD) < stages_seen.index(stages.STAGE_ASR),
              str(stages_seen))

        asr_evs = [e for e in events if e["stage"] == stages.STAGE_ASR
                   and e["percent"] is not None]
        check("5 语音识别有多个真实进度点", len(asr_evs) >= 2, f"{len(asr_evs)} 个")
        check("5 语音识别最终到 100%", asr_evs and asr_evs[-1]["percent"] == 100.0,
              str(asr_evs[-1]["percent"] if asr_evs else None))
        check("5 语音识别百分比单调递增",
              all(a["percent"] <= b["percent"] for a, b in zip(asr_evs, asr_evs[1:])),
              str([round(e["percent"], 1) for e in asr_evs]))

        # ← 关键：percent 必须等于 detail 里"已处理 / 总时长"算出来的比例
        bad = []
        for e in asr_evs[:-1]:                       # 最后一条是收尾，不带时间
            m = re.search(r"(\d+):(\d+) / (\d+):(\d+)", e["detail"] or "")
            if not m:
                continue
            dm, ds, tm, ts = (int(x) for x in m.groups())
            done, total = dm * 60 + ds, tm * 60 + ts
            if total <= 0:
                continue
            expect = done / total * 100.0
            if abs(expect - e["percent"]) > 1.0:
                bad.append(f"detail={e['detail']} percent={e['percent']:.1f} 应为 {expect:.1f}")
        check("5 百分比与「已处理时间/总时长」完全对应（不是假动画）", not bad,
              "；".join(bad[:3]))

        # VAD 阶段不该编百分比
        vad_evs = [e for e in events if e["stage"] == stages.STAGE_VAD]
        check("5 VAD 阶段如实报「进行中」（不编百分比）",
              all(e["percent"] is None for e in vad_evs), str(vad_evs))
        print(f"         └ 共 {len(events)} 个进度事件，识别 {res['lines']} 句 / "
              f"{res['duration']}")

    # ---------------- 6. 界面组件 ----------------
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from desktop.ui.progress_view import ProgressView
    pv = ProgressView()
    pv.start()
    check("6 开始时进度条是「不确定」模式（不是假百分比）",
          pv.bar.minimum() == 0 and pv.bar.maximum() == 0,
          f"{pv.bar.minimum()}~{pv.bar.maximum()}")
    pv.update_event(stages.make_event(stages.STAGE_ASR, 45.2, "23:10 / 51:00　已识别 312 句"))
    check("6 有真实百分比时显示百分比", pv.percent.text() == "45%", pv.percent.text())
    check("6 进度条切到确定模式", pv.bar.maximum() == 100 and pv.bar.value() == 45,
          f"{pv.bar.value()}/{pv.bar.maximum()}")
    check("6 详情行显示已处理时间", "23:10 / 51:00" in pv.detail.text(), pv.detail.text())
    check("6 当前阶段被高亮、之前的阶段标成已完成",
          "3b7ddd" in pv._stage_labels[stages.STAGE_ASR].styleSheet()
          and "2f9e63" in pv._stage_labels[stages.STAGE_VAD].styleSheet(),
          pv._stage_labels[stages.STAGE_ASR].styleSheet())
    pv.update_event(stages.make_event(stages.STAGE_VAD, None, "正在检测哪里有人说话…"))
    check("6 无百分比的阶段不显示数字、进度条回到不确定模式",
          pv.percent.text() == "" and pv.bar.maximum() == 0, pv.percent.text())
    pv.finish("分析完成")
    check("6 完成后进度条满格", pv.bar.value() == 100 and pv.percent.text() == "100%",
          f"{pv.bar.value()} {pv.percent.text()}")

    print(f"\n（临时工作区：{_TMP}）")
    return report()


def report():
    print("\n" + "=" * 66)
    print(f"进度显示系统验收：通过 {PASS} / 失败 {FAIL} / 共 {PASS + FAIL}")
    print("=" * 66)
    out = HERE / "desktop_progress_report.txt"
    with open(out, "w", encoding="utf-8") as f:
        for status, name, extra in ROWS:
            f.write(f"[{status}] {name}" + (f"  -> {extra}" if extra else "") + "\n")
        f.write(f"\n通过 {PASS} / 失败 {FAIL}\n")
    print(f"报告已写入：{out}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        code = 1
    sys.exit(code)
