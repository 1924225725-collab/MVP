# ============================================================
# desktop/ui/main_window.py —— 主窗口
#
# 布局：
#   左侧边栏（项目列表 / 新建分析 / 设置 / 模型管理）
#   右侧内容区（📺 视频信息 · ⭐ 推荐剪辑 · 🧭 内容结构 · 🔧 开发者视图）
#
# 【关键约束】
#   1. 界面只调 desktop/services/*，不直接碰 analysis / pipeline / asr。
#   2. 每个项目的数据都从 ProjectStore 按 project_id 读取，
#      切项目即刻重绘；**不存在"上一个视频的结果留在界面上"**。
#   3. 所有耗时任务在后台线程跑，界面不假死。
# ============================================================

import os
import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

import app_paths
from errors import ProcessError, STAGE_MEDIA_UNREADABLE, STAGE_NO_AUDIO
from desktop import APP_TITLE, APP_VERSION, theme
from desktop.services import ProjectStore, SettingsStore
from desktop.services.tasks import (
    analyze_transcript, probe_video, transcribe_video, wrap_error,
)
from desktop.ui import widgets as W
from desktop.ui.dialogs import AnalysisOptionsDialog, ModelManagerDialog, SettingsDialog
from desktop.ui.developer_panel import DeveloperPanel
from desktop.ui.error_text import error_ui
from desktop.ui.project_panel import ProjectPanel
from desktop.ui.recommended_panel import RecommendedPanel
from desktop.ui.structure_panel import StructurePanel
from desktop.workers import TaskWorker

_VIDEO_FILTER = "视频文件 (*.mp4 *.mkv *.mov *.flv *.avi *.ts *.m4v *.wmv);;所有文件 (*)"

_STATE_TEXT = {
    "created": ("只有视频", "#8a94a6"),
    "transcribed": ("已出文字稿", "#d9822b"),
    "analyzed": ("已完成分析", "#2f9e63"),
    "failed": ("上次失败", "#d9534f"),
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE}  v{APP_VERSION}")
        self.resize(1280, 840)

        app_paths.ensure_workspace()
        self.store = ProjectStore()
        self.settings = SettingsStore()
        self.project = None            # 当前项目 dict
        self.worker = None             # 当前后台任务
        self.analysis_log = ""         # 本次运行的日志（只在内存，不写进 project.json）

        self._build_ui()
        self.refresh_projects()

    # ============================================================
    # 界面搭建
    # ============================================================

    def _build_ui(self):
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content(), 1)
        self.setCentralWidget(central)

    # ---------- 左侧边栏 ----------

    def _build_sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(258)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(6)

        title = QLabel(APP_TITLE)
        title.setObjectName("AppTitle")
        lay.addWidget(title)
        sub = QLabel(f"v{APP_VERSION}　本地识别 · AI 理解内容")
        sub.setObjectName("AppSubtitle")
        lay.addWidget(sub)

        self.btn_new = QPushButton("＋  新建分析")
        self.btn_new.setObjectName("PrimaryButton")
        self.btn_new.clicked.connect(self.new_analysis)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(16, 4, 16, 6)
        wl.addWidget(self.btn_new)
        lay.addWidget(wrap)

        lb = QLabel("项目")
        lb.setObjectName("SidebarHint")
        lay.addWidget(lb)

        self.project_list = QListWidget()
        self.project_list.setObjectName("ProjectList")
        self.project_list.currentItemChanged.connect(self._on_project_clicked)
        lay.addWidget(self.project_list, 1)

        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(16, 6, 16, 6)
        bl.setSpacing(6)

        self.btn_analyze = QPushButton("开始分析（用当前的文字稿）")
        self.btn_analyze.setObjectName("SidebarButton")
        self.btn_analyze.clicked.connect(self.run_analysis)
        bl.addWidget(self.btn_analyze)

        self.btn_retranscribe = QPushButton("重新语音识别")
        self.btn_retranscribe.setObjectName("SidebarButton")
        self.btn_retranscribe.clicked.connect(self.re_transcribe)
        bl.addWidget(self.btn_retranscribe)

        row = QHBoxLayout()
        self.btn_models = QPushButton("模型管理")
        self.btn_models.setObjectName("SidebarButton")
        self.btn_models.clicked.connect(self.open_models)
        row.addWidget(self.btn_models)
        self.btn_settings = QPushButton("设置")
        self.btn_settings.setObjectName("SidebarButton")
        self.btn_settings.clicked.connect(self.open_settings)
        row.addWidget(self.btn_settings)
        bl.addLayout(row)
        lay.addWidget(bottom)
        return side

    # ---------- 右侧内容 ----------

    def _build_content(self) -> QWidget:
        area = QWidget()
        area.setObjectName("ContentArea")
        lay = QVBoxLayout(area)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # --- 顶栏 ---
        top = QWidget()
        top.setObjectName("TopBar")
        tl = QVBoxLayout(top)
        tl.setContentsMargins(20, 12, 20, 10)
        tl.setSpacing(4)

        head = QHBoxLayout()
        self.video_title = QLabel("未选择项目")
        self.video_title.setObjectName("VideoTitle")
        head.addWidget(self.video_title)
        head.addStretch(1)
        self.state_chip = QLabel("")
        self.state_chip.setObjectName("StateChip")
        self.state_chip.setVisible(False)
        head.addWidget(self.state_chip)
        tl.addLayout(head)

        self.video_meta = QLabel("")
        self.video_meta.setObjectName("VideoMeta")
        tl.addWidget(self.video_meta)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        tl.addWidget(self.progress)

        lay.addWidget(top)

        # --- 选项卡 ---
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 12, 20, 16)
        bl.setSpacing(8)

        self.tabs = QTabWidget()
        self.panel_project = ProjectPanel()
        self.panel_recommended = RecommendedPanel()
        self.panel_structure = StructurePanel()
        self.panel_developer = DeveloperPanel()

        self.tabs.addTab(self.panel_recommended, "⭐  推荐剪辑")
        self.tabs.addTab(self.panel_structure, "🧭  直播内容结构")
        self.tabs.addTab(self.panel_project, "📺  视频信息")
        self.tabs.addTab(self.panel_developer, "🔧  开发者视图")
        bl.addWidget(self.tabs, 1)
        lay.addWidget(body, 1)
        return area

    # ============================================================
    # 项目列表
    # ============================================================

    def refresh_projects(self, keep_id: str = None):
        keep_id = keep_id or (self.project or {}).get("project_id")
        self.project_list.blockSignals(True)
        self.project_list.clear()
        rows = self.store.list()
        for r in rows:
            label = (f"{r['video_name']}\n"
                     f"{r['duration'] or '—'}　·　"
                     f"{r['chapter_count']} 章 / {r['story_count']} 段　·　"
                     f"⭐{r['recommend_count']}　·　{r['updated_at'].replace('T', ' ')[5:16]}")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, r["project_id"])
            state_txt, _ = _STATE_TEXT.get(r["state"], (r["state"], ""))
            item.setToolTip(f"{r['video_name']}\n状态：{state_txt}\n{r['project_id']}")
            self.project_list.addItem(item)
        self.project_list.blockSignals(False)

        if keep_id:
            for i in range(self.project_list.count()):
                if self.project_list.item(i).data(Qt.UserRole) == keep_id:
                    self.project_list.setCurrentRow(i)
                    return
        if self.project_list.count() and not self.project:
            self.project_list.setCurrentRow(0)
        elif not self.project_list.count():
            # 一个项目都没有 → 各面板进入"空"态（而不是留着上一次的内容）
            self.project = None
            self._render_current()

    def _on_project_clicked(self, cur, _prev):
        if not cur:
            return
        pid = cur.data(Qt.UserRole)
        self.load_project(pid)

    def load_project(self, project_id: str):
        proj = self.store.load(project_id)
        if proj is None:
            QMessageBox.warning(self, "读取失败",
                                f"项目 {project_id} 的文件读取不了或已损坏。")
            self.refresh_projects()
            return
        self.project = proj
        self.analysis_log = ""
        self._render_current()

    def _render_current(self):
        p = self.project
        if not p:
            # 空状态：四个面板全部回到"还没有结果"，绝不留上一个项目的痕迹
            self.video_title.setText("未选择项目")
            self.video_meta.setText("点左上角「＋ 新建分析」开始，或从左侧选一个已有项目")
            self.state_chip.setVisible(False)
            self._update_buttons()
            self.panel_project.set_project(None)
            self.panel_recommended.set_project(None)
            self.panel_structure.set_project(None)
            self.panel_developer.set_project(None, "")
            return
        video = p.get("video") or {}
        self.video_title.setText(video.get("name") or "（未命名视频）")
        state_txt, _ = _STATE_TEXT.get(p.get("state"), (p.get("state"), ""))
        analysis = p.get("analysis") or {}
        meta = (analysis.get("meta") or {}) if analysis else {}
        bits = [state_txt, p.get("project_id", "")]
        if meta.get("duration") or video.get("duration"):
            bits.insert(1, f"时长 {meta.get('duration') or video.get('duration')}")
        if meta.get("live_type"):
            bits.append(meta["live_type"])
        self.video_meta.setText("　·　".join(b for b in bits if b))
        self._update_state_chip(p.get("state"))
        self._update_buttons()

        self.panel_project.set_project(p)
        self.panel_recommended.set_project(p)
        self.panel_structure.set_project(p)
        self.panel_developer.set_project(p, self.analysis_log)

    def _update_state_chip(self, state):
        text, color = _STATE_TEXT.get(state, ("", "#8a94a6"))
        if not text:
            self.state_chip.setVisible(False)
            return
        self.state_chip.setVisible(True)
        self.state_chip.setText(text)
        self.state_chip.setStyleSheet(
            f"background:{color}22; color:{color}; border:1px solid {color}55;"
            f"border-radius:10px; padding:3px 10px; font-size:11px; font-weight:600;")

    def _update_buttons(self):
        p = self.project or {}
        busy = self._busy()
        has_video = bool((p.get("video") or {}).get("path"))
        has_transcript = bool((p.get("transcript") or {}).get("path"))
        self.btn_new.setEnabled(not busy)
        self.btn_analyze.setEnabled(not busy and has_transcript)
        self.btn_retranscribe.setEnabled(not busy and has_video)
        self.btn_models.setEnabled(not busy)
        self.btn_settings.setEnabled(not busy)

    def _busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    # ============================================================
    # 后台任务骨架
    # ============================================================

    def _run_task(self, fn, on_done, on_fail=None, status=""):
        if self._busy():
            QMessageBox.information(self, "正在忙",
                                    "上一个任务还没结束，请等它跑完。")
            return
        self._set_progress(True, status)
        self._update_buttons()
        self.worker = TaskWorker(fn, self)
        self.worker.progressChanged.connect(self._on_progress)
        self.worker.succeeded.connect(lambda r: self._on_task_done(r, on_done))
        self.worker.failed.connect(lambda e: self._on_task_fail(e, on_fail))
        self.worker.start()

    def _on_progress(self, msg: str):
        self.progress.setFormat(f"{msg}  %p%")
        self.panel_developer.append_log(f"[进度] {msg}")

    def _on_task_done(self, result, on_done):
        self._set_progress(False)
        # 先把 worker 收掉再执行回调：回调里可能立刻发起下一个任务
        # （识别完成 → 马上开始分析），不能因为"上一个线程还没完全退出"被拦住。
        self.worker = None
        self._update_buttons()
        if not on_done:
            return
        try:
            on_done(result)
        except BaseException:
            tb = traceback.format_exc()
            self.panel_developer.append_log(f"[回调异常]\n{tb}")
            QMessageBox.warning(self, "处理结果时出错",
                                "任务本身跑完了，但结果处理时出错。\n"
                                "详细信息见「开发者视图 → 运行日志」。")

    def _on_task_fail(self, exc, on_fail):
        self._set_progress(False)
        err = wrap_error(exc)
        self.panel_developer.append_log(
            f"[错误] stage={err.stage}\n{err.message}\n{err.detail}")
        if self.project:
            ProjectStore.mark_failed(self.project, err.stage, err.message, err.detail)
            self.store.save(self.project)
        self._update_state_chip("failed")
        self.worker = None
        self._update_buttons()
        if on_fail:
            on_fail(err)
        else:
            self._show_error(err)

    def _set_progress(self, on: bool, text: str = ""):
        self.progress.setVisible(on)
        self.progress.setRange(0, 0)
        self.progress.setFormat(text or "处理中…")

    def _show_error(self, err):
        title, desc, action = error_ui(getattr(err, "stage", ""))
        # 分类文案讲"该怎么做"，具体 message 讲"到底哪儿坏了"——两个都给用户看，
        # 否则只会看到一句"缺少依赖组件"，不知道缺的到底是什么。
        msg = str(getattr(err, "message", "") or "")
        if msg and msg not in desc:
            desc = f"{desc}\n\n具体原因：{msg}"
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Warning)
        box.setText(f"{title}\n\n{desc}")
        if getattr(err, "detail", ""):
            box.setDetailedText(err.detail)
        if action == "models":
            box.addButton("打开模型管理", QMessageBox.AcceptRole)
        elif action == "settings":
            box.addButton("打开设置", QMessageBox.AcceptRole)
        box.addButton("知道了", QMessageBox.RejectRole)
        box.exec()
        if action == "models":
            self.open_models()
        elif action == "settings":
            self.open_settings()

    # ============================================================
    # 新建分析
    # ============================================================

    def new_analysis(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择直播录像", "", _VIDEO_FILTER)
        if not path:
            return

        def job(progress=None):
            if progress:
                progress("正在检查视频…")
            return probe_video(path)

        self._run_task(job, lambda info: self._after_probe(path, info),
                       status="检查视频…")

    def _after_probe(self, path, info):
        # 探测阶段就能看出问题的话**立刻说**，别让用户填完设置才开始跑才发现
        # 「这个视频根本没有声音」（V0.4.5 / D-046 的分层原则延续到这里）。
        if not info.get("has_audio"):
            self._show_error(ProcessError(
                STAGE_NO_AUDIO,
                f"未检测到音轨：{info.get('name') or path}",
                f"文件：{info.get('path') or path}\n"
                f"视频能正常打开，但里面没有声音轨道（常见于无声录屏、或音轨被剥离的文件）。"))
            return
        if not info.get("readable"):
            self._show_error(ProcessError(
                STAGE_MEDIA_UNREADABLE,
                f"媒体文件无法读取：{info.get('name') or path}",
                f"文件：{info.get('path') or path}"))
            return

        dlg = AnalysisOptionsDialog(info, self.settings.load(), self)
        if dlg.exec() != AnalysisOptionsDialog.Accepted:
            return
        opts = dlg.options()
        self.settings.set(**opts)

        if not self.settings.api_key():
            QMessageBox.information(
                self, "还差一步",
                "AI 分析需要 DeepSeek 钥匙（Key）。\n"
                "先在这里填一次，之后会记住；本地语音识别不需要钥匙。")
            self.open_settings()
            return

        proj = self.store.create(video_name=info.get("name") or os.path.basename(path),
                                 video_path=info.get("path") or path)
        proj["video"]["size_bytes"] = info.get("size_bytes")
        proj["video"]["duration"] = info.get("duration")
        self.store.save(proj)
        self.project = proj
        self.refresh_projects(keep_id=proj["project_id"])
        self._render_current()

        self._transcribe_then_analyze(proj, opts, src_path=path)

    def _transcribe_then_analyze(self, proj, opts, src_path=None):
        video_path = src_path or (proj.get("video") or {}).get("path")

        def job(progress=None):
            progress("正在导入视频…")
            from desktop.services.tasks import import_video
            ws_path = import_video(video_path)
            progress("正在提取音频并识别（本地，不上传）…")
            res = transcribe_video(ws_path, progress=progress)
            res["_workspace_path"] = ws_path
            return res

        self._run_task(job,
                       lambda res: self._after_transcribe(proj, res, opts),
                       status="语音识别中…")

    def _after_transcribe(self, proj, res, opts):
        proj["video"]["path"] = res.get("_workspace_path") or proj["video"].get("path")
        if res.get("duration"):
            proj["video"]["duration"] = res["duration"]
        if res.get("dictionary_hits"):
            self.panel_developer.append_log(f"[纠错词库] 命中 {res['dictionary_hits']} 处")
        ProjectStore.mark_transcribed(proj, res["transcript"], res["lines"])
        self.store.save(proj)
        self.project = proj
        self.refresh_projects(keep_id=proj["project_id"])
        self._render_current()
        self._start_analysis(proj, opts)

    # ============================================================
    # 分析
    # ============================================================

    def run_analysis(self):
        proj = self.project
        if not proj or not (proj.get("transcript") or {}).get("path"):
            QMessageBox.information(self, "还没有文字稿",
                                    "这个项目还没有文字稿，先做一次语音识别。")
            return
        info = {
            "name": (proj.get("video") or {}).get("name", ""),
            "duration": (proj.get("video") or {}).get("duration", ""),
            "has_audio": True,
            "path": (proj.get("video") or {}).get("path", ""),
            "size_bytes": (proj.get("video") or {}).get("size_bytes"),
        }
        dlg = AnalysisOptionsDialog(info, proj.get("settings") or self.settings.load(), self)
        if dlg.exec() != AnalysisOptionsDialog.Accepted:
            return
        opts = dlg.options()
        self.settings.set(**opts)
        if not self.settings.api_key():
            QMessageBox.information(self, "还差一步", "AI 分析需要 DeepSeek 钥匙。")
            self.open_settings()
            return
        self._start_analysis(proj, opts)

    def _start_analysis(self, proj, opts):
        transcript = (proj.get("transcript") or {}).get("path")
        if not transcript:
            QMessageBox.warning(self, "缺少文字稿", "找不到文字稿文件。")
            return

        # 预估花费（沿用网页版 D-015 的预算预估）
        est = self._estimate(transcript, opts)

        def job(progress=None):
            return analyze_transcript(
                transcript,
                live_type=opts["live_type"],
                token_mode=opts["token_mode"],
                quantity_mode=opts["quantity_mode"],
                custom_count=opts["custom_count"],
                progress=progress,
            )

        self.analysis_log = f"[设置] {opts}\n{est}\n"
        self._run_task(job, lambda res: self._after_analysis(proj, res, opts),
                       status="AI 分析中…")

    def _estimate(self, transcript, opts) -> str:
        try:
            from analysis import budget, chunker, event_scanner, transcript_parser
            segs = transcript_parser.parse_transcript_file(transcript)
            if not segs:
                return ""
            duration = transcript_parser.total_duration(segs)
            buckets = event_scanner.scan(segs, opts["live_type"])
            chunks = chunker.build_chunks(buckets, segs)
            max_cand = 3
            try:
                max_cand = config.TOKEN_MODES[opts["token_mode"]]["max_candidates_per_chunk"]
            except Exception:
                pass
            est = budget.estimate_total(chunks, max_cand)
            return (f"[预估] 约 {est} token；"
                    f"时长 {chunker.format_time(duration)}，{len(chunks)} 个区块")
        except Exception as e:
            return f"[预估] 跳过（{e}）"

    def _after_analysis(self, proj, result, opts):
        log = result.pop("_log", "") if isinstance(result, dict) else ""
        self.analysis_log = (self.analysis_log or "") + "\n" + log
        ProjectStore.mark_analyzed(proj, result, opts)
        self.store.save(proj)
        self.project = proj
        self.refresh_projects(keep_id=proj["project_id"])
        self._render_current()

        recs = [h for h in (result.get("highlights") or []) if h.get("recommended")]
        cost = (result.get("cost") or {}).get("cost_yuan", 0)
        self.tabs.setCurrentWidget(self.panel_recommended)
        QMessageBox.information(
            self, "分析完成",
            f"推荐剪辑 {len(recs)} 条，全部候选 {len(result.get('highlights') or [])} 条。\n"
            f"本次 AI 花费 ¥{float(cost):.4f}。")

    # ============================================================
    # 重新识别
    # ============================================================

    def re_transcribe(self):
        proj = self.project
        video = (proj or {}).get("video") or {}
        if not video.get("path") or not os.path.exists(video["path"]):
            QMessageBox.warning(self, "找不到视频文件",
                                "视频文件不存在（可能被移动或删除了）。")
            return
        if QMessageBox.question(
                self, "重新语音识别",
                "会用当前的语音识别引擎重跑一遍，覆盖已有的文字稿。\n"
                "已有的分析结果不会自动更新（识别完可以再点「开始分析」）。\n\n继续吗？"
        ) != QMessageBox.Yes:
            return

        def job(progress=None):
            return transcribe_video(video["path"], progress=progress)

        self._run_task(job, lambda res: self._after_retranscribe(proj, res),
                       status="语音识别中…")

    def _after_retranscribe(self, proj, res):
        ProjectStore.mark_transcribed(proj, res["transcript"], res["lines"])
        self.store.save(proj)
        self.project = proj
        self.refresh_projects(keep_id=proj["project_id"])
        self._render_current()
        QMessageBox.information(self, "识别完成",
                                f"共 {res['lines']} 句。可以点「开始分析」了。")

    # ============================================================
    # 设置 / 模型
    # ============================================================

    def open_settings(self):
        try:
            from asr import registry
            providers = registry.list_providers()
        except Exception as e:
            providers = [{"id": "local-faster-whisper",
                          "name": "本地语音识别（faster-whisper）",
                          "available": False, "reason": str(e)}]
        dlg = SettingsDialog(self.settings.load(), providers, self)
        if dlg.exec() == SettingsDialog.Accepted:
            values = dlg.values()
            values["asr_provider"] = values.get("asr_provider") or "local-faster-whisper"
            self.settings.set(**values)
            self.panel_developer.set_project(self.project, self.analysis_log)

    def open_models(self):
        from desktop.services.model_manager import ModelManager
        mgr = ModelManager()
        settings = self.settings.load()
        dlg = ModelManagerDialog(mgr, settings, self,
                                 on_changed=lambda s: self.settings.save(s))
        dlg.exec()
        self.panel_developer.set_project(self.project, self.analysis_log)

    # ============================================================
    # 退出
    # ============================================================

    def closeEvent(self, event):
        if self._busy():
            if QMessageBox.question(self, "任务还在跑",
                                    "后台任务还没结束，确定要退出吗？"
                                    ) != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.cancel()
            self.worker.wait(3000)
        event.accept()
