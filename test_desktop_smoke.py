# ============================================================
# test_desktop_smoke.py —— 桌面版骨架自测（离线，不联网、不跑 ASR、不调 AI）
#
# 目的：验证「界面骨架 + 数据绑定 + 防串场」这三件事。
#   1) 桌面版界面能建起来、四个页签都在
#   2) 每个面板显示的**确实是当前项目自己的数据**（不是固定样例、不串场）
#   3) 切项目后界面完全重绘，上一个视频的内容不留痕
#   4) 分层错误文案互不相同
#   5) 项目存储的完整性校验真的会拦下被改坏的文件
#
# 运行：.\.venv\Scripts\python test_desktop_smoke.py
# ============================================================

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# 必须在导入业务模块之前把工作区指到临时目录（隔离，不污染真实用户数据）
_TMP = Path(tempfile.mkdtemp(prefix="lc_desktop_test_"))
os.environ["LIVE_CLIPPER_HOME"] = str(_TMP)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS = 0
FAIL = 0
CASES = []


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        CASES.append(("PASS", name, ""))
    else:
        FAIL += 1
        CASES.append(("FAIL", name, extra))


# ------------------------------------------------------------
# 造一个"像真的一样"的分析结果（字段严格照 analysis 的输出 schema）
# ------------------------------------------------------------

def _event(eid, title, score, start, end, story_id, rec=False, tier="", etype="事件型",
           dur=45, rec_start="", rec_end="", rec_dur=None, reason=""):
    return {
        "clip_id": eid,
        "event_id": eid,
        "story_id": story_id,
        "title": title,
        "start_time": start,
        "end_time": end,
        "score": score,
        "grade": _grade(score),
        "highlight_type": etype,
        "reason": reason or f"{title} 值得一看",
        "why_cut": f"{title} 有反差和笑点",
        "risk": "开头两秒有点平",
        "negative_flags": [],
        "dims": {"hook": 8.0, "contrast": 7.5, "persona": 6.5,
                 "standalone": 7.0, "completeness": 8.5},
        "category": "名场面",
        "viral_probability": 0.6,
        "editing_advice": "",
        "confidence": 0.8,
        "ai_recommend": score >= 80,
        "recommended": rec,
        "recommend_tier": tier,
        "summary": f"{title}：完整讲了一遍经过",
        "duration": dur,
        "recommended_start": rec_start or start,
        "recommended_end": rec_end or end,
        "recommended_duration": rec_dur if rec_dur is not None else dur,
        "duration_reason": "把起承转合都包含进来",
    }


def _grade(score):
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _story(sid, title, start, end, events, reason="话题自然切换"):
    best = max((e["score"] for e in events), default=None)
    return {
        "story_id": sid, "raw_story_id": sid, "title": title,
        "summary": f"{title} 这一段的主要内容",
        "reason": reason,
        "start_time": start, "end_time": end,
        "start": _sec(start), "end": _sec(end),
        "score": best, "grade": _grade(best) if best else "",
        "best_event_id": "", "event_count": len(events), "events": events,
    }


def _chapter(cid, title, start, end, stories, summary="", boundary=""):
    scores = [s["score"] for s in stories if s.get("score") is not None]
    best = max(scores) if scores else None
    return {
        "chapter_id": cid, "title": title, "summary": summary,
        "boundary_reason": boundary,
        "start_time": start, "end_time": end,
        "start": _sec(start), "end": _sec(end),
        "score": best, "grade": _grade(best) if best else "",
        "story_count": len(stories),
        "event_count": sum(s["event_count"] for s in stories),
        "stories": stories,
    }


def _sec(ts):
    m, s = str(ts).split(":")[-2:]
    return int(m) * 60 + int(s)


def make_analysis(tag: str, chapter_titles, rec_count, duration="32:10"):
    """造一份分析结果。tag 用来保证两个项目的内容完全不同。"""
    events = []
    chapters = []
    n = 0
    for ci, ctitle in enumerate(chapter_titles, 1):
        stories = []
        for si in range(1, 2):
            evs = []
            for k in range(2):
                n += 1
                score = 95 - n * 6                 # 递减，保证排序稳定
                start = f"{n * 3:02d}:{n * 7 % 60:02d}"
                end = f"{n * 3:02d}:{(n * 7 + 40) % 60:02d}"
                evs.append(_event(
                    f"ev-{tag}-{n:03d}", f"{tag}-{ctitle}-事件{n}", score, start, end,
                    f"{ci:02d}-{si:02d}",
                    rec=(n <= rec_count), tier="A" if n <= rec_count else "",
                    dur=30 + n * 10, rec_dur=30 + n * 10,
                ))
            stories.append(_story(f"{ci:02d}-{si:02d}", f"{ctitle}-片段", "00:00", "10:00", evs))
        chapters.append(_chapter(f"ch-{ci:02d}", ctitle, "00:00", "10:00", stories,
                                 summary=f"{ctitle} 讲了一整件事",
                                 boundary="话题切换"))
    events = [e for c in chapters for s in c["stories"] for e in s["events"]]
    recs = [e for e in events if e["recommended"]]
    rejected = []
    for e in events:
        if not e["recommended"]:
            e2 = dict(e)
            e2["reject_reason"] = ["内容不错，但推荐数量已达目标（8 条）"]
            rejected.append(e2)
    return {
        "meta": {"transcript": f"{tag}.txt", "live_type": "娱乐聊天", "token_mode": "标准",
                 "quantity_mode": "自动精选", "custom_count": None, "duration": duration,
                 "chunk_count": len(chapters) + 3, "candidate_count": len(events),
                 "degrade_level": 0, "miss_check_chunks": []},
        "highlights": events,
        "rejected": rejected,
        "report": {"summary": f"{tag} 整场回顾", "best_spread_point": f"{tag} 最强点",
                   "overall": "本场内容密度中等", "why_not_more": "后段偏闲聊"},
        "structure": {
            "chapters": chapters,
            "stats": {"chapter_count": len(chapters),
                      "story_count": sum(len(c["stories"]) for c in chapters),
                      "stories_with_events": len(chapters),
                      "best_story_id": "01-01", "best_story_title": chapter_titles[0] + "-片段",
                      "best_story_score": 89},
            "source": "fresh",
        },
        "structure_source": "fresh",
        "cost": {"calls": 12, "input_tokens": 18000, "output_tokens": 3000,
                 "cost_yuan": 0.4123},
    }


# ------------------------------------------------------------
# 开始
# ------------------------------------------------------------

def main():
    print(f"[环境] 工作区 = {_TMP}")

    # ---- 1. 导入 ----
    try:
        import app_paths
        from desktop.services import ProjectStore, SettingsStore
        from desktop.services.model_manager import ModelManager
        from desktop.ui import widgets as W
        from desktop.ui.error_text import ERROR_UI, error_ui
        check("1 桌面模块导入无报错", True)
    except Exception:
        check("1 桌面模块导入无报错", False, traceback.format_exc())
        return report()

    # ---- 2. 工作区隔离 ----
    check("2 工作区指向临时目录（不污染真实数据）",
          str(app_paths.workspace_root()) == str(_TMP), str(app_paths.workspace_root()))
    app_paths.ensure_workspace()
    for name in ("videos", "transcripts", "projects", "models", "logs"):
        check(f"2 工作区子目录已建：{name}", (app_paths.workspace_root() / name).is_dir())

    # ---- 3. Qt 起来 ----
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    check("3 Qt 应用可创建（offscreen）", app is not None)

    from desktop.ui import MainWindow
    win = MainWindow()
    win.show()
    app.processEvents()
    check("4 主窗口创建成功", win is not None)
    check("4 四个选项卡齐全", win.tabs.count() == 4, f"实际 {win.tabs.count()}")
    tabs = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    check("4 选项卡顺序 = 推荐剪辑 / 内容结构 / 视频信息 / 开发者视图",
          tabs[0].endswith("推荐剪辑") and tabs[1].endswith("直播内容结构")
          and tabs[2].endswith("视频信息") and tabs[3].endswith("开发者视图"),
          str(tabs))

    # ---- 5. 空状态 ----
    check("5 无项目时推荐页给出空态提示", "还没有分析结果" in win.panel_recommended._empty.text(),
          win.panel_recommended._empty.text())
    check("5 无项目时结构页给出空态提示", "还没有分析结果" in win.panel_structure.empty.text())

    # ---- 6. 造两个项目 ----
    store = ProjectStore()
    pa = store.create("项目A_娱乐.mp4", str(_TMP / "videos" / "a.mp4"))
    store.save(ProjectStore.mark_transcribed(pa, _TMP / "transcripts" / "a.txt", 123))
    an_a = make_analysis("AAA", ["开场闲聊", "做饭翻车", "设备故障"], rec_count=3)
    store.save(ProjectStore.mark_analyzed(pa, an_a, {"live_type": "娱乐聊天"}))

    pb = store.create("项目B_游戏.mp4", str(_TMP / "videos" / "b.mp4"))
    store.save(ProjectStore.mark_transcribed(pb, _TMP / "transcripts" / "b.txt", 456))
    an_b = make_analysis("BBB", ["上分冲刺", "队友吵架", "赛后复盘", "彩蛋"], rec_count=2,
                         duration="1:12:40")
    store.save(ProjectStore.mark_analyzed(pb, an_b, {"live_type": "游戏竞技"}))

    check("6 项目列表能列出两个项目", len(store.list()) == 2, str(len(store.list())))
    win.refresh_projects()

    # ---- 7. 载入项目 A，逐项核对数据绑定 ----
    win.load_project(pa["project_id"])
    app.processEvents()

    recs_a = [h for h in an_a["highlights"] if h["recommended"]]
    check("7 推荐页条数 = 当前项目自己的 recommended 数",
          win.panel_recommended.summary.text().startswith(f"⭐ 推荐剪辑 {len(recs_a)} 条"),
          win.panel_recommended.summary.text())
    check("7 顶栏标题 = 当前视频名",
          "项目A_娱乐" in win.video_title.text(), win.video_title.text())
    check("7 视频信息页出现本项目 Chapter 数",
          "3" in _dump(win.panel_project), "未找到 Chapter 数")
    check("7 结构页摘要出现 Chapter 数量",
          "3 个 Chapter" in win.panel_structure.summary.text(),
          win.panel_structure.summary.text())
    check("7 结构页出现本项目自有 Chapter 标题：做饭翻车",
          "做饭翻车" in _dump(win.panel_structure))
    check("7 结构页出现本项目自有 Story：设备故障-片段",
          "设备故障-片段" in _dump(win.panel_structure))
    check("7 开发者视图含本项目 project_id",
          pa["project_id"] in _dump(win.panel_developer))
    check("7 开发者视图含本项目成本 ¥0.4123",
          "0.4123" in _dump(win.panel_developer))

    # A 的固有内容不应出现在别处
    dump_a = _dump(win.panel_structure) + _dump(win.panel_recommended)

    # ---- 8. 切到项目 B，验证完全重绘、无残留 ----
    win.load_project(pb["project_id"])
    app.processEvents()
    recs_b = [h for h in an_b["highlights"] if h["recommended"]]
    check("8 切项目后顶栏标题变为项目 B",
          "项目B_游戏" in win.video_title.text(), win.video_title.text())
    check("8 切项目后推荐条数变为项目 B 的",
          win.panel_recommended.summary.text().startswith(f"⭐ 推荐剪辑 {len(recs_b)} 条"),
          win.panel_recommended.summary.text())
    check("8 切项目后结构页变为 4 个 Chapter",
          "4 个 Chapter" in win.panel_structure.summary.text(),
          win.panel_structure.summary.text())
    check("8 切项目后出现项目 B 自有 Chapter：队友吵架",
          "队友吵架" in _dump(win.panel_structure))
    check("8 切项目后不再出现项目 A 的 Chapter：做饭翻车",
          "做饭翻车" not in _dump(win.panel_structure))
    check("8 切项目后不再出现项目 A 的章节",
          "设备故障-片段" not in _dump(win.panel_structure) + _dump(win.panel_recommended))
    check("8 切项目后开发者视图 project_id 已变",
          pb["project_id"] in _dump(win.panel_developer)
          and pa["project_id"] not in _dump(win.panel_developer))
    check("8 时长正确绑定到项目 B（1:12:40）",
          "1:12:40" in win.video_meta.text() or "1:12:40" in _dump(win.panel_project),
          win.video_meta.text())

    # ---- 9. 项目存储完整性校验 ----
    f = store.file_of(pa["project_id"])
    raw = json.loads(f.read_text(encoding="utf-8"))
    raw["project_id"] = "别的项目的ID"
    f.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    check("9 被改坏 project_id 的项目读不出来（防串场）",
          store.load(pa["project_id"]) is None)
    f.unlink()   # 清掉这条坏数据
    check("9 项目列表自动跳过损坏项目", len(store.list()) == 1, str(len(store.list())))

    # ---- 10. 等级字母不外露 ----
    check("10 soften 抹掉「B 级」字样",
          "级" not in W.soften("这段是 B 级内容，A级更值得剪"), W.soften("这段是 B 级内容，A级更值得剪"))
    check("10 展示档位不出现单个字母等级（S/A/B/C/D）",
          W.grade_badge("B") == "✨ 有看点" and W.grade_badge("S") == "🌟 高光内容",
          f'{W.grade_badge("B")} / {W.grade_badge("S")}')

    # ---- 11. 分层错误文案 ----
    stages = ["media_unreadable", "no_audio_track", "audio_extract", "ffmpeg_missing",
              "dependency", "model_missing", "model_load", "asr_inference",
              "asr_empty", "unknown"]
    titles = [error_ui(s)[0] for s in stages]
    check("11 10 种错误各有独立标题", len(set(titles)) == len(titles), str(titles))
    check("11 没有「视频处理失败，请换一个文件试试」这种万能句",
          not any("换一个文件试试" in t for t in titles))
    check("11 模型未安装 → 指向模型管理",
          error_ui("model_missing")[2] == "models")
    check("11 无音轨与文件损坏文案不同",
          error_ui("no_audio_track")[1] != error_ui("media_unreadable")[1])

    # ---- 12. 设置存储 ----
    ss = SettingsStore()
    ss.set(api_key="sk-test-123", live_type="游戏竞技", token_mode="精细")
    ss2 = SettingsStore()
    check("12 设置能持久化（重新读出来还在）",
          ss2.api_key() == "sk-test-123" and ss2.get("live_type") == "游戏竞技",
          str(ss2.load()))
    check("12 钥匙同时写入 api_key.txt（命令行/网页版也能用）",
          app_paths.api_key_file().read_text(encoding="utf-8").strip() == "sk-test-123")
    check("12 analysis_options 三个设置齐全",
          set(ss2.analysis_options()) == {"live_type", "token_mode", "quantity_mode",
                                          "custom_count"})

    # ---- 13. 模型清单可读、路径在工作区 ----
    mgr = ModelManager()
    sts = mgr.list_status()
    check("13 模型清单可读", len(sts) >= 1, str(len(sts)))
    check("13 默认模型 id 与清单里 default 一致",
          mgr.default_model_id() == "faster-whisper-small", mgr.default_model_id())
    check("13 模型目录在工作区（不在程序目录）",
          str(mgr.models_root()).startswith(str(_TMP)), str(mgr.models_root()))
    check("13 未安装时 resolve_local 返回空",
          mgr.resolve_local("faster-whisper-medium") == (None, ""),
          str(mgr.resolve_local("faster-whisper-medium")))
    check("13 清单 schema 齐备（id/name/base_url/files/校验字段）",
          all(m.get("id") and m.get("name") and m.get("base_url")
              and m.get("files") and "min_primary_bytes" in m and "sha256" in m
              for m in mgr.all_models()))
    try:
        mgr.get("不存在的模型")
        check("13 查不存在的模型会明确报错", False, "没有抛错")
    except Exception as e:
        check("13 查不存在的模型会明确报错", "清单里没有这个模型" in str(e), str(e))

    # ---- 14. 设置对话框 / 模型对话框能构造 ----
    from desktop.ui.dialogs import AnalysisOptionsDialog, ModelManagerDialog, SettingsDialog
    from asr import registry
    d1 = AnalysisOptionsDialog({"name": "x.mp4", "duration": "10:00", "has_audio": True},
                               {"live_type": "娱乐聊天"}, None)
    check("14 新建分析对话框可构造", d1.options()["live_type"] == "娱乐聊天")
    check("14 分析模式列表不露 token 数字",
          all("token" not in d1.token_mode.itemText(i).lower()
              for i in range(d1.token_mode.count())))
    d2 = SettingsDialog(ss.load(), registry.list_providers(), None)
    check("14 设置对话框列出语音识别引擎", d2.provider.count() >= 1, str(d2.provider.count()))
    d3 = ModelManagerDialog(mgr, ss.load(), None)
    check("14 模型管理对话框能列出模型", d3.list_host.count() >= 1, str(d3.list_host.count()))

    # ---- 15. 演示：真的对着一份结果渲染一遍（快照看得到） ----
    win.load_project(pb["project_id"])
    app.processEvents()
    snapshot = {
        "顶栏": f"{win.video_title.text()}　|　{win.video_meta.text()}",
        "推荐剪辑": win.panel_recommended.summary.text(),
        "内容结构": win.panel_structure.summary.text(),
    }
    check("15 得到可用界面快照", all(snapshot.values()), str(snapshot))

    win.close()
    return report(snapshot)


def _dump(widget) -> str:
    """把一个容器下所有 QLabel 的文字拼起来（用来断言界面上真的显示了什么）。"""
    from PySide6.QtWidgets import QLabel
    parts = []
    try:
        for lb in widget.findChildren(QLabel):
            parts.append(lb.text() or "")
        from PySide6.QtWidgets import QPlainTextEdit, QTextEdit
        for te in widget.findChildren(QPlainTextEdit):
            parts.append(te.toPlainText() or "")
        for te in widget.findChildren(QTextEdit):
            parts.append(te.toPlainText() or "")
    except Exception:
        pass
    return "\n".join(parts)


def report(snapshot=None):
    print("\n" + "=" * 66)
    print("桌面版骨架自测结果")
    print("=" * 66)
    for status, name, extra in CASES:
        mark = "✔" if status == "PASS" else "✘"
        line = f"  {mark} {name}"
        if status == "FAIL" and extra:
            line += f"\n        实际：{extra}"
        print(line)
    if snapshot:
        print("\n--- 界面快照 ---")
        for k, v in snapshot.items():
            print(f"  {k}：{v}")
    print("=" * 66)
    print(f"通过 {PASS} / 失败 {FAIL} / 共 {PASS + FAIL}")
    print(f"（临时工作区：{_TMP}）")
    out = HERE / "desktop_smoke_report.txt"
    with open(out, "w", encoding="utf-8") as f:
        for status, name, extra in CASES:
            f.write(f"[{status}] {name}" + (f"  -> {extra}" if extra else "") + "\n")
        f.write(f"\n通过 {PASS} / 失败 {FAIL}\n")
    print(f"报告已写入：{out}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaseException:
        traceback.print_exc()
        check("0 测试脚本自身不崩", False, traceback.format_exc())
        sys.exit(1)
