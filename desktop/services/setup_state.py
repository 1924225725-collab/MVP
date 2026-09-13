"""首次启动 Setup Assistant 的独立状态存储。

该文件只记录引导生命周期，不保存 API Key 等敏感配置。默认位置为
``<workspace>/setup_state.json``，与用户数据一起升级保留。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Mapping

import app_paths


SCHEMA_VERSION = 1
VALID_COMPLETIONS = {"pending", "finished", "skipped", "legacy_detected"}
VALID_WORK_MODES = {"local", "cloud"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def defaults() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "completed": False,
        "completion": "pending",
        "completed_at": None,
        "work_mode": "local",
        "last_initialization": {},
        "updated_at": None,
    }


def _safe_initialization_summary(summary: Mapping | None) -> dict:
    """只保留首次引导需要的非敏感检测摘要。"""
    summary = summary or {}
    return {
        "status": str(summary.get("status") or "unknown"),
        "total": int(summary.get("total") or 0),
        "ok": int(summary.get("ok") or 0),
        "warn": int(summary.get("warn") or 0),
        "fail": int(summary.get("fail") or 0),
        "blocking": bool(summary.get("blocking")),
        "checked_at": str(summary.get("checked_at") or _now()),
    }


class SetupStateStore:
    """容错读取并原子保存首次引导状态。"""

    def __init__(self, path=None):
        self.path = (Path(path) if path else
                     app_paths.workspace_root() / "setup_state.json")
        self.last_error = ""

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict | None:
        """读取有效状态；文件缺失或损坏时返回 ``None``。

        调用方可通过 :attr:`last_error` 区分文件损坏与单纯不存在。
        未知 schema 不会被当成已完成，避免错误跳过未来版本引导。
        """
        self.last_error = ""
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.last_error = f"状态文件无法读取：{type(exc).__name__}"
            return None
        if not isinstance(raw, dict):
            self.last_error = "状态文件格式无效"
            return None
        if raw.get("schema_version") != SCHEMA_VERSION:
            self.last_error = "状态文件版本不兼容"
            return None
        if not isinstance(raw.get("completed"), bool):
            self.last_error = "状态文件缺少 completed"
            return None

        state = defaults()
        state.update(raw)
        if state.get("completion") not in VALID_COMPLETIONS:
            self.last_error = "状态文件 completion 无效"
            return None
        if state.get("work_mode") not in VALID_WORK_MODES:
            self.last_error = "状态文件 work_mode 无效"
            return None
        if not isinstance(state.get("last_initialization"), dict):
            state["last_initialization"] = {}
        return state

    def save(self, state: Mapping | None = None) -> Path:
        """规范化并原子写入状态。"""
        current = defaults()
        loaded = self.load()
        if loaded:
            current.update(loaded)
        if state:
            current.update(dict(state))

        current["schema_version"] = SCHEMA_VERSION
        current["completed"] = bool(current.get("completed"))
        completion = str(current.get("completion") or "pending")
        current["completion"] = (
            completion if completion in VALID_COMPLETIONS else "pending")
        mode = str(current.get("work_mode") or "local")
        current["work_mode"] = mode if mode in VALID_WORK_MODES else "local"
        if not isinstance(current.get("last_initialization"), dict):
            current["last_initialization"] = {}
        current["updated_at"] = _now()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            temp.write_text(
                json.dumps(current, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp.replace(self.path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return self.path

    def mark_completed(
        self,
        work_mode: str = "local",
        initialization_summary: Mapping | None = None,
    ) -> Path:
        """记录用户完成全部引导。"""
        now = _now()
        update = {
            "completed": True,
            "completion": "finished",
            "completed_at": now,
            "work_mode": work_mode,
        }
        if initialization_summary is not None:
            update["last_initialization"] = _safe_initialization_summary(
                initialization_summary)
        return self.save(update)

    def mark_skipped(
        self,
        work_mode: str = "local",
        initialization_summary: Mapping | None = None,
    ) -> Path:
        """记录“稍后设置”；下次启动应直接进入主界面。"""
        now = _now()
        update = {
            "completed": True,
            "completion": "skipped",
            "completed_at": now,
            "work_mode": work_mode,
        }
        if initialization_summary is not None:
            update["last_initialization"] = _safe_initialization_summary(
                initialization_summary)
        return self.save(update)

    def mark_legacy_detected(self, work_mode: str = "local") -> Path:
        """记录由已有项目/配置识别出的升级用户。"""
        now = _now()
        return self.save({
            "completed": True,
            "completion": "legacy_detected",
            "completed_at": now,
            "work_mode": work_mode,
        })

    def record_initialization(self, summary: Mapping) -> Path:
        """保存不含技术明细和密钥的最近检测摘要。"""
        return self.save({
            "last_initialization": _safe_initialization_summary(summary),
        })
