# ============================================================
# desktop/services/project_store.py —— 项目存储（桌面版）
#
# 【核心约束】（延续 V0.4.4 的数据绑定要求）
#   每个视频 = 一个独立项目 = 一份独立分析结果。
#   连续分析多个视频时，彼此绝不共用 / 回退 / 污染。
#   项目结果落在 工作区/projects/<项目ID>/project.json，
#   里面同时记录「这份结果属于哪个视频」，读取时校验，杜绝串场。
# ============================================================

import json
import re
from datetime import datetime
from pathlib import Path

import app_paths

_STATE_CREATED = "created"          # 只有视频
_STATE_TRANSCRIBED = "transcribed"  # 有文字稿
_STATE_ANALYZED = "analyzed"        # 有分析结果
_STATE_FAILED = "failed"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug(name: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(name)).strip("_.")
    return s[:40] or "project"


class ProjectStore:
    """项目读写。root 默认取工作区的 projects/ 目录。"""

    def __init__(self, root=None):
        self.root = Path(root) if root else app_paths.projects_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------- 路径 ----------------

    def dir_of(self, project_id: str) -> Path:
        return self.root / project_id

    def file_of(self, project_id: str) -> Path:
        return self.dir_of(project_id) / "project.json"

    def new_id(self, video_name: str = "") -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{stamp}_{_slug(Path(str(video_name)).stem)}"

    # ---------------- 创建 / 保存 / 读取 ----------------

    def create(self, video_name: str = "", video_path: str = "",
               project_id: str = None) -> dict:
        pid = project_id or self.new_id(video_name)
        proj = {
            "project_id": pid,
            "created_at": _now(),
            "updated_at": _now(),
            "state": _STATE_CREATED,
            "video": {
                "name": video_name or "",
                "path": str(video_path or ""),
                "size_bytes": None,
                "duration": "",
            },
            "transcript": {"path": "", "lines": 0, "source": ""},
            "settings": {},
            "analysis": None,
            "error": None,
        }
        self.save(proj)
        return proj

    def save(self, project: dict) -> Path:
        project["updated_at"] = _now()
        path = self.file_of(project["project_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(project, ensure_ascii=False, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(path)          # 原子写：避免中途崩溃留下半个 JSON
        return path

    def load(self, project_id: str):
        path = self.file_of(project_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        # 完整性校验：结果必须属于它自己的项目（防串场）
        if data.get("project_id") != project_id:
            return None
        return data

    def delete(self, project_id: str) -> bool:
        import shutil
        d = self.dir_of(project_id)
        if not d.exists():
            return False
        shutil.rmtree(d, ignore_errors=True)
        return True

    def list(self) -> list:
        """列出全部项目摘要，最近更新的排前面。"""
        out = []
        for d in self.root.iterdir():
            if not d.is_dir():
                continue
            data = self.load(d.name)
            if not data:
                continue
            analysis = data.get("analysis") or {}
            structure = (analysis.get("structure") or {}) if analysis else {}
            chapters = structure.get("chapters") or []
            stats = structure.get("stats") or {}
            story_count = stats.get("story_count")
            if story_count is None:
                story_count = sum(len(c.get("stories") or []) for c in chapters)
            highlights = (analysis.get("highlights") or []) if analysis else []
            recs = [h for h in highlights if h.get("recommended")]
            out.append({
                "project_id": data.get("project_id", d.name),
                "video_name": (data.get("video") or {}).get("name") or d.name,
                "state": data.get("state", ""),
                "updated_at": data.get("updated_at", ""),
                "duration": (data.get("video") or {}).get("duration", ""),
                "chapter_count": len(chapters),
                "story_count": int(story_count or 0),
                "recommend_count": len(recs),
            })
        out.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return out

    # ---------------- 状态更新小工具 ----------------

    @staticmethod
    def mark_transcribed(project: dict, transcript_path, lines: int, source: str = "asr"):
        project["transcript"] = {
            "path": str(transcript_path), "lines": int(lines), "source": source,
        }
        project["state"] = _STATE_TRANSCRIBED
        project["error"] = None
        return project

    @staticmethod
    def mark_analyzed(project: dict, analysis: dict, settings: dict):
        project["analysis"] = analysis
        project["settings"] = dict(settings or {})
        project["state"] = _STATE_ANALYZED
        project["error"] = None
        return project

    @staticmethod
    def mark_failed(project: dict, stage: str, message: str, detail: str = ""):
        project["state"] = _STATE_FAILED
        project["error"] = {"stage": stage, "message": message,
                            "detail": detail, "at": _now()}
        return project
