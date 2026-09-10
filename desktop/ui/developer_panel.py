# ============================================================
# desktop/ui/developer_panel.py —— 🔧 开发者 / 调试
#
# 这里**保留全部原始信息**（网页版 D-046 的约定延续到这里）：
#   - 路径布局（程序目录 vs 用户数据目录）
#   - 语音识别引擎 / 模型状态
#   - 分析元信息、成本、结构来源、漏检质检记录
#   - 运行日志、完整结果 JSON
#
# 普通用户不看这一页；出问题时它必须能说清"到底哪一层坏了"。
# ============================================================

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QPlainTextEdit, QPushButton, QScrollArea, QTabWidget, QVBoxLayout,
    QWidget,
)

from desktop.ui import widgets as W


class DeveloperPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._project = None
        self._log = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.addWidget(W.strong("开发者视图", size=14))
        bar.addStretch(1)
        copy_btn = QPushButton("复制结果 JSON")
        copy_btn.clicked.connect(self._copy_json)
        bar.addWidget(copy_btn)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(lambda: self.set_project(self._project, self._log))
        bar.addWidget(refresh)
        root.addLayout(bar)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.env_tab = _text_tab("环境")
        self.meta_tab = _text_tab("元信息")
        self.log_tab = _text_tab("运行日志")
        self.json_tab = _text_tab("完整结果")
        self.tabs.addTab(self.env_tab, "环境 / 路径")
        self.tabs.addTab(self.meta_tab, "元信息 / 成本")
        self.tabs.addTab(self.log_tab, "运行日志")
        self.tabs.addTab(self.json_tab, "完整结果 JSON")

    # ---------------- 对外 ----------------

    def set_project(self, project: dict, log_text: str = ""):
        self._project = project
        self._log = log_text or ""
        self._render()

    def append_log(self, line: str):
        self._log += str(line) + "\n"
        self._set(self.log_tab, self._log)

    # ---------------- 渲染 ----------------

    def _render(self):
        import app_paths

        # ---- 环境 ----
        lines = ["【路径布局】"]
        for k, v in app_paths.describe().items():
            lines.append(f"  {k:8}：{v}")

        lines.append("")
        lines.append("【语音识别引擎】")
        try:
            from asr import registry
            for p in registry.list_providers():
                flag = "可用" if p.get("available") else "不可用"
                mark = "（默认）" if p.get("default") else ""
                lines.append(f"  - {p.get('name')} [{p.get('id')}]{mark}"
                             f"　{flag}　{p.get('reason', '')}")
        except Exception as e:
            lines.append(f"  （读取失败：{e}）")

        lines.append("")
        lines.append("【本地模型】")
        try:
            from desktop.services.model_manager import ModelManager
            mgr = ModelManager()
            for st in mgr.list_status():
                lines.append(f"  - {st['name']} [{st['id']}]　"
                             f"{'已安装' if st['installed'] else '未安装'}"
                             f"　来源={st.get('source') or '-'}")
                if st.get("path"):
                    lines.append(f"      路径：{st['path']}")
            lines.append(f"  清单文件：{mgr.manifest_path()}")
        except Exception as e:
            lines.append(f"  （读取失败：{e}）")

        self._set(self.env_tab, "\n".join(lines))

        # ---- 元信息 ----
        p = self._project or {}
        a = p.get("analysis") or {}
        head = [
            "【当前项目】",
            f"  project_id  ：{p.get('project_id', '-')}",
            f"  视频        ：{(p.get('video') or {}).get('name', '-')}",
            f"  状态        ：{p.get('state', '-')}",
            f"  文字稿      ：{(p.get('transcript') or {}).get('path', '-')}",
            f"  创建 / 更新 ：{p.get('created_at', '-')} / {p.get('updated_at', '-')}",
        ]
        if not a:
            self._set(self.meta_tab, "\n".join(head + ["", "（还没有分析结果）"]))
        else:
            meta = a.get("meta") or {}
            cost = a.get("cost") or {}
            body = list(head) + ["", "【分析元信息】",
                                 json.dumps(meta, ensure_ascii=False, indent=2)]
            body += ["", "【成本】", json.dumps(cost, ensure_ascii=False, indent=2)]
            body += ["", f"【结构来源】{a.get('structure_source') or '-'}"]
            ch = (a.get("structure") or {}).get("chapters") or []
            body += [f"【结构规模】Chapter {len(ch)} 个 / "
                     f"Story {sum(len(c.get('stories') or []) for c in ch)} 个"]
            mc = meta.get("miss_check_chunks") or []
            if mc:
                body += ["", f"【漏检质检】判定可疑并重扫的区块：{mc}"]
            self._set(self.meta_tab, "\n".join(body))

        # ---- 日志 ----
        self._set(self.log_tab, self._log or "（本次还没有运行日志）")

        # ---- 完整 JSON ----
        if not a:
            self._set(self.json_tab, "（还没有分析结果）")
        else:
            slim = {k: v for k, v in a.items() if k != "_log"}
            self._set(self.json_tab, json.dumps(slim, ensure_ascii=False, indent=2))

    @staticmethod
    def _set(tab, text):
        tab.setPlainText(text)

    def _copy_json(self):
        a = (self._project or {}).get("analysis")
        if not a:
            return
        slim = {k: v for k, v in a.items() if k != "_log"}
        QGuiApplication.clipboard().setText(
            json.dumps(slim, ensure_ascii=False, indent=2))


def _text_tab(name: str) -> QPlainTextEdit:
    te = QPlainTextEdit()
    te.setReadOnly(True)
    te.setObjectName("Monospace")
    te.setPlaceholderText(f"{name}（暂无可显示内容）")
    return te
