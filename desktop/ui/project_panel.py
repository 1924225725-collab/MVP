# ============================================================
# desktop/ui/project_panel.py —— 📺 视频 / 项目信息
#
# 【数据来源铁律】这一屏所有数字都来自**当前这个项目自己**的
#   project["video"] / project["transcript"] / project["analysis"]，
#   绝不使用任何固定样例、也不读别的项目。
# ============================================================

import os
import subprocess
import sys

from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from desktop.ui import widgets as W

_STATE_TEXT = {
    "created": ("只有视频", "#8a94a6"),
    "transcribed": ("已出文字稿", "#d9822b"),
    "analyzed": ("已完成分析", "#2f9e63"),
    "failed": ("上次失败", "#d9534f"),
}


class ProjectPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self.host = QVBoxLayout()
        self.host.setSpacing(10)
        root.addLayout(self.host)
        root.addStretch(1)

        self._project = None

    # ---------------- 对外 ----------------

    def set_project(self, project: dict):
        self._project = project
        self._render()

    # ---------------- 渲染 ----------------

    def _clear(self):
        while self.host.count():
            item = self.host.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _render(self):
        self._clear()
        p = self._project
        if not p:
            self.host.addWidget(W.muted("还没有选择项目。点左上角「新建分析」开始。"))
            return

        video = p.get("video") or {}
        analysis = p.get("analysis") or {}
        meta = (analysis.get("meta") or {}) if analysis else {}
        structure = (analysis.get("structure") or {}) if analysis else {}
        stats = structure.get("stats") or {}
        highlights = (analysis.get("highlights") or []) if analysis else []
        recs = [h for h in highlights if h.get("recommended")]
        cost = (analysis.get("cost") or {}) if analysis else {}
        transcript = p.get("transcript") or {}

        # ---- 视频 ----
        box, lay = W.card()
        lay.addWidget(W.strong(video.get("name") or "（未命名视频）", size=15))
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        rows = [
            ("时长", video.get("duration") or meta.get("duration") or "未知"),
            ("文件大小", _fmt_size(video.get("size_bytes"))),
            ("项目编号", p.get("project_id", "")),
            ("创建时间", _fmt_time(p.get("created_at"))),
            ("最后更新", _fmt_time(p.get("updated_at"))),
            ("视频路径", video.get("path") or "—"),
        ]
        for i, (k, v) in enumerate(rows):
            grid.addWidget(W.muted(k, size=12), i, 0)
            val = W.selectable(str(v))
            if k.endswith("路径"):
                val.setObjectName("Monospace")
            grid.addWidget(val, i, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        btns = QHBoxLayout()
        open_dir = QPushButton("打开视频所在文件夹")
        open_dir.setEnabled(bool(video.get("path")))
        open_dir.clicked.connect(lambda: _open_folder(video.get("path")))
        btns.addWidget(open_dir)
        open_tr = QPushButton("打开文字稿")
        open_tr.setEnabled(bool(transcript.get("path")))
        open_tr.clicked.connect(lambda: _open_path(transcript.get("path")))
        btns.addWidget(open_tr)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.host.addWidget(box)

        # ---- 文字稿 ----
        box, lay = W.card()
        lay.addWidget(W.strong("语音识别（本地完成，免费离线）", size=13))
        if transcript.get("path"):
            lay.addWidget(W.muted(
                f"{transcript.get('lines', 0)} 句　·　"
                f"来源 {_source_text(transcript.get('source'))}", wrap=True))
            lay.addWidget(W.muted(transcript.get("path", ""), size=11))
        else:
            lay.addWidget(W.muted("还没有文字稿。"))
        self.host.addWidget(box)

        # ---- 分析概览 ----
        box, lay = W.card()
        lay.addWidget(W.strong("分析概览", size=13))
        if analysis:
            g = QGridLayout()
            g.setHorizontalSpacing(18)
            g.setVerticalSpacing(6)
            items = [
                ("直播类型", meta.get("live_type", "—")),
                ("分析模式", meta.get("token_mode", "—")),
                ("输出数量", meta.get("quantity_mode", "—")),
                ("分析时长", meta.get("duration", "—")),
                ("内容区块", str(meta.get("chunk_count", "—"))),
                ("Chapter 数", str(stats.get("chapter_count", len(structure.get("chapters") or [])))),
                ("Story 数", str(stats.get("story_count", "—"))),
                ("候选片段", str(len(highlights))),
                ("推荐剪辑", str(len(recs))),
                ("AI 花费", f"¥{cost.get('cost_yuan', 0):.4f}" if cost else "—"),
            ]
            for i, (k, v) in enumerate(items):
                g.addWidget(W.muted(k, size=12), i // 2, (i % 2) * 2)
                g.addWidget(W.selectable(str(v)), i // 2, (i % 2) * 2 + 1)
            g.setColumnStretch(1, 1)
            g.setColumnStretch(3, 1)
            lay.addLayout(g)
            if int(meta.get("degrade_level") or 0) >= 2:
                lay.addWidget(W.muted(
                    "提示：本场内容较多，已按预算自动调整扫描密度。想更细可以改用「精细」模式重跑。",
                    size=11, wrap=True))
        else:
            lay.addWidget(W.muted("还没有分析结果。点「开始分析」跑一次。"))
        self.host.addWidget(box)

        # ---- 上次失败 ----
        err = p.get("error")
        if err:
            box, lay = W.card("#d9534f")
            lay.addWidget(W.strong(f"上次失败：{err.get('message', '')}", size=13))
            lay.addWidget(W.muted(f"出错位置：{err.get('stage', '')}　·　{err.get('at', '')}",
                                  size=11))
            if err.get("detail"):
                tb = QPlainTextEdit(err["detail"])
                tb.setReadOnly(True)
                tb.setObjectName("Monospace")
                tb.setFixedHeight(120)
                lay.addWidget(tb)
            self.host.addWidget(box)


# ---------------- 小工具 ----------------

def _fmt_size(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "—"


def _fmt_time(s):
    return str(s or "").replace("T", " ")[:19] or "—"


def _source_text(source):
    return {"asr": "本地识别", "manual": "手工导入", "corrected": "纠错后"}.get(source, source or "—")


def _open_folder(path):
    if not path or not os.path.exists(path):
        return
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def _open_path(path):
    if not path or not os.path.exists(path):
        return
    if sys.platform.startswith("win"):
        os.startfile(path)                                  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", path])
