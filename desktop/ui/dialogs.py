# ============================================================
# desktop/ui/dialogs.py —— 新建分析 / 设置 / 模型管理
#
# 注意：Token 三模式只展示人话描述，**不露 token 数字**（沿用网页版约定）。
# ============================================================

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

import config
from desktop import theme
from desktop.ui import widgets as W

LIVE_TYPES = list(config.LIVE_TYPE_WEIGHTS.keys())
TOKEN_MODES = list(config.TOKEN_MODES.keys())
QUANTITY_MODES = list(config.QUANTITY_MODES)


# ============================================================
# 新建分析：展示视频信息 + 三设置
# ============================================================

class AnalysisOptionsDialog(QDialog):
    """视频已经探测好了，这里只收「怎么分析」。"""

    def __init__(self, video_info: dict, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("开始分析")
        self.setMinimumWidth(520)
        self._video_info = dict(video_info or {})

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # ---- 视频信息 ----
        box, lay = W.card()
        lay.addWidget(W.strong(self._video_info.get("name", ""), size=14))
        meta = (
            f"时长 {self._video_info.get('duration') or '未知'}"
            f"　·　{'有音轨' if self._video_info.get('has_audio') else '无音轨'}"
            f"　·　{_fmt_size(self._video_info.get('size_bytes'))}"
        )
        lay.addWidget(W.muted(meta))
        lay.addWidget(W.muted(self._video_info.get("path", ""), size=11))
        root.addWidget(box)

        # ---- 设置 ----
        form = QFormLayout()
        form.setSpacing(10)

        self.live_type = QComboBox()
        self.live_type.addItems(LIVE_TYPES)
        self.live_type.setCurrentText(settings.get("live_type") or config.LIVE_TYPE_DEFAULT)
        self.live_type.setToolTip("不同直播类型的看点不一样，选对了判断更准")
        form.addRow("直播类型", self.live_type)

        self.token_mode = QComboBox()
        for name in TOKEN_MODES:
            desc = config.TOKEN_MODES[name].get("desc", "")
            self.token_mode.addItem(f"{name}　—　{desc}", name)
        idx = TOKEN_MODES.index(settings.get("token_mode")
                                if settings.get("token_mode") in TOKEN_MODES else "标准")
        self.token_mode.setCurrentIndex(idx)
        form.addRow("分析模式", self.token_mode)

        self.quantity_mode = QComboBox()
        self.quantity_mode.addItems(QUANTITY_MODES)
        self.quantity_mode.setCurrentText(
            settings.get("quantity_mode") or config.QUANTITY_MODE_DEFAULT)
        self.quantity_mode.currentTextChanged.connect(self._on_qty_changed)
        form.addRow("输出数量", self.quantity_mode)

        self.custom_count = QSpinBox()
        self.custom_count.setRange(1, 100)
        self.custom_count.setValue(int(settings.get("custom_count") or config.DEFAULT_CUSTOM_COUNT))
        form.addRow("自定义条数", self.custom_count)

        root.addLayout(form)
        self._on_qty_changed(self.quantity_mode.currentText())

        hint = W.muted("分析会调用 AI，按量计费；运行前会先给出预估花费。", size=11)
        root.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("开始分析")
        bb.button(QDialogButtonBox.Ok).setObjectName("AccentButton")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def _on_qty_changed(self, text):
        self.custom_count.setEnabled(text == "自定义数量")

    def options(self) -> dict:
        return {
            "live_type": self.live_type.currentText(),
            "token_mode": self.token_mode.currentData(),
            "quantity_mode": self.quantity_mode.currentText(),
            "custom_count": int(self.custom_count.value()),
        }


def _fmt_size(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "大小未知"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


# ============================================================
# 设置
# ============================================================

class SettingsDialog(QDialog):
    def __init__(self, settings: dict, providers: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.api_key = QLineEdit(settings.get("api_key") or "")
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("sk-…　（用于 AI 分析，留空则不能分析）")
        show = QCheckBox("显示")
        show.toggled.connect(
            lambda on: self.api_key.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password))
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.api_key, 1)
        rl.addWidget(show)
        form.addRow("DeepSeek 钥匙", row)

        self.provider = QComboBox()
        for p in providers:
            label = f"{p.get('name')}"
            if not p.get("available"):
                label += "（暂不可用）"
            self.provider.addItem(label, p.get("id"))
        cur = settings.get("asr_provider") or "local-faster-whisper"
        for i in range(self.provider.count()):
            if self.provider.itemData(i) == cur:
                self.provider.setCurrentIndex(i)
                break
        form.addRow("语音识别引擎", self.provider)

        root.addLayout(form)

        note = W.muted(
            "语音识别在本机完成（免费、不上传视频）；AI 分析需要联网并消耗钥匙额度。",
            size=11, wrap=True)
        root.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("保存")
        bb.button(QDialogButtonBox.Ok).setObjectName("AccentButton")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

    def values(self) -> dict:
        return {
            "api_key": self.api_key.text().strip(),
            "asr_provider": self.provider.currentData(),
        }


# ============================================================
# 模型管理（Model Registry 的界面）
# ============================================================

class ModelManagerDialog(QDialog):
    """列出可用模型 → 检测状态 → 一键安装（进度/失败/重试）。"""

    def __init__(self, manager, settings: dict, parent=None, on_changed=None):
        super().__init__(parent)
        self.setWindowTitle("本地语音识别模型")
        self.setMinimumWidth(660)
        self.setMinimumHeight(460)
        self._mgr = manager
        self._settings = settings
        self._on_changed = on_changed
        self._worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        root.addWidget(W.strong("模型装在哪、装没装、能不能用", size=14))
        root.addWidget(W.muted(
            "模型放在用户数据目录（不在安装目录里），升级或卸载程序都不会丢。"
            "首次使用需要下载一次，之后完全离线。", size=11, wrap=True))

        self.list_host = QVBoxLayout()
        self.list_host.setSpacing(8)
        root.addLayout(self.list_host)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status = W.muted("")
        root.addWidget(self.status)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("重新检测")
        self.refresh_btn.clicked.connect(self.refresh)
        self.adopt_btn = QPushButton("使用本机已有模型")
        self.adopt_btn.setToolTip("如果以前跑过网页版，模型可能已经在缓存里，点这里直接登记，不用重新下载")
        self.adopt_btn.clicked.connect(self._adopt)
        self.folder_btn = QPushButton("手动指定模型文件夹…")
        self.folder_btn.clicked.connect(self._pick_folder)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.adopt_btn)
        btn_row.addWidget(self.folder_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("关闭")
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        root.addWidget(bb)

        self.refresh()

    # ---------- 列表 ----------

    def refresh(self):
        while self.list_host.count():
            item = self.list_host.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        try:
            statuses = self._mgr.list_status()
        except Exception as e:
            self.status.setText(f"模型清单读取失败：{e}")
            return
        cur = self._settings.get("asr_model_id") or ""
        for st in statuses:
            self.list_host.addWidget(self._row(st, is_current=(st["id"] == cur)))

    def _row(self, st: dict, is_current: bool) -> QWidget:
        box, lay = W.card(theme.OK_COLOR if st["installed"] else None)
        top = QHBoxLayout()
        title = st["name"]
        if st.get("recommended"):
            title += "　（推荐）"
        top.addWidget(W.strong(title, size=13))
        top.addStretch(1)
        if st["installed"]:
            src = {"workspace": "已安装", "hf_cache": "沿用缓存"}.get(st["source"], "已安装")
            top.addWidget(W.chip(src, bg=theme.OK_COLOR))
        else:
            top.addWidget(W.chip("未安装", bg="#8a94a6"))
        lay.addLayout(top)

        desc = st.get("description") or ""
        if desc:
            lay.addWidget(W.muted(desc, wrap=True))
        bits = []
        if st.get("size_hint"):
            bits.append(f"体积约 {st['size_hint']}")
        if st.get("actual_bytes"):
            bits.append(f"实际 {_fmt_size(st['actual_bytes'])}")
        if st.get("path"):
            bits.append(f"位置 {st['path']}")
        if bits:
            lay.addWidget(W.muted("　·　".join(bits), size=11, wrap=True))

        btns = QHBoxLayout()
        if st["installed"]:
            use = QPushButton("设为当前模型" if not is_current else "当前使用中")
            use.setEnabled(not is_current)
            use.clicked.connect(lambda _=False, mid=st["id"]: self._set_current(mid))
            btns.addWidget(use)

            chk = QPushButton("完整性校验")
            chk.clicked.connect(lambda _=False, mid=st["id"]: self._verify(mid))
            btns.addWidget(chk)

            if st["source"] == "workspace":
                rm = QPushButton("卸载")
                rm.clicked.connect(lambda _=False, mid=st["id"]: self._remove(mid))
                btns.addWidget(rm)
        else:
            inst = QPushButton("一键安装")
            inst.setObjectName("AccentButton")
            inst.clicked.connect(lambda _=False, mid=st["id"]: self._install(mid))
            btns.addWidget(inst)
        btns.addStretch(1)
        lay.addLayout(btns)
        return box

    # ---------- 动作 ----------

    def _set_current(self, model_id: str):
        self._settings["asr_model_id"] = model_id
        if self._on_changed:
            self._on_changed(self._settings)
        self.status.setText(f"已把「{model_id}」设为当前使用的模型")
        self.refresh()

    def _verify(self, model_id: str):
        try:
            ok, msg = self._mgr.verify(model_id, deep=True)
        except Exception as e:
            self.status.setText(f"校验出错：{e}")
            return
        self.status.setText(("✔ " if ok else "✘ ") + msg)

    def _remove(self, model_id: str):
        if QMessageBox.question(self, "卸载模型",
                                f"确定要删除已下载的「{model_id}」吗？\n"
                                f"（不会动 HuggingFace 缓存和你的原始文件夹）"
                                ) != QMessageBox.Yes:
            return
        self._mgr.remove(model_id)
        self.status.setText(f"已卸载 {model_id}")
        self.refresh()

    def _adopt(self):
        cur = self._settings.get("asr_model_id") or self._mgr.default_model_id()
        try:
            res = self._mgr.adopt_from_hf_cache(cur)
        except Exception as e:
            self.status.setText(f"本机缓存里没找到可用模型：{e}")
            return
        self.status.setText(f"已登记本机已有模型（{cur}）：{res.get('path')}")
        self.refresh()

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "选择模型文件夹（含 model.bin）")
        if not d:
            return
        cur = self._settings.get("asr_model_id") or self._mgr.default_model_id()
        try:
            self._mgr.copy_into_workspace(cur, d)
        except Exception as e:
            QMessageBox.warning(self, "无法使用该文件夹", str(e))
            return
        self.status.setText(f"已把 {cur} 复制到工作区")
        self.refresh()

    def _install(self, model_id: str):
        from desktop.workers import TaskWorker
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.refresh_btn.setEnabled(False)

        def job(progress=None):
            def cb(done, total, fname, phase):
                # cb 在子线程里跑，这里只发信号不碰控件。
                # ⚠️ 必须写 `progress_changed.tick.emit(...)`（显式指定信号名）：
                #    PySide6 里 `progress_changed.emit(...)` 不指定信号名时
                #    不会路由到自定义信号，会直接 TypeError —— 这个坑让
                #    「一键安装模型」在进度回调第一次触发时就崩掉。
                self.progress_changed.tick.emit(done, total, fname, phase)
            return self._mgr.install(model_id, progress=cb)

        self.progress_changed = _ProgressBridge()
        self.progress_changed.tick.connect(self._on_tick)
        self._worker = TaskWorker(job, self)
        self._worker.progressChanged.connect(self.status.setText)
        self._worker.succeeded.connect(lambda r: self._install_done(model_id, r))
        self._worker.failed.connect(lambda e: self._install_failed(e))
        self._worker.start()

    def _on_tick(self, done, total, fname, phase):
        if total:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(done * 100 / total))
            self.status.setText(f"{phase}：{fname}　{_fmt_size(done)} / {_fmt_size(total)}")
        else:
            self.progress.setRange(0, 0)
            self.status.setText(f"{phase}：{fname}　{_fmt_size(done)}")

    def _install_done(self, model_id, result):
        self.progress.setVisible(False)
        self.refresh_btn.setEnabled(True)
        if result.get("already"):
            self.status.setText("本机已有该模型，无需重复下载")
        else:
            self.status.setText(f"安装完成：{result.get('path')}")
            self._settings["asr_model_id"] = model_id
            if self._on_changed:
                self._on_changed(self._settings)
        self.refresh()

    def _install_failed(self, exc):
        self.progress.setVisible(False)
        self.refresh_btn.setEnabled(True)
        detail = getattr(exc, "detail", "") or ""
        msg = getattr(exc, "message", None) or str(exc)
        self.status.setText(f"✘ 安装失败：{msg}")
        QMessageBox.warning(self, "模型安装失败", f"{msg}\n\n{detail}")


class _ProgressBridge(QWidget):
    """把子线程里的下载回调安全地转到主线程（跨线程发信号是 Qt 推荐做法）。"""
    tick = Signal(int, int, str, str)
