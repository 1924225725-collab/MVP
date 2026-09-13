"""P1 启动状态判定与面向 Setup UI 的结构化环境检测。

这里只编排现有自检能力，不修改或执行视频分析、ASR 推理与 AI 调用。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import app_paths
from desktop.services import selfcheck
from desktop.services.project_store import ProjectStore
from desktop.services.setup_state import SetupStateStore


STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

SOURCE_SETUP_STATE = "setup_state"
SOURCE_PROJECTS = "projects"
SOURCE_CONFIG = "config"
SOURCE_NEW_USER = "new_user"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(frozen=True)
class StartupDecision:
    """启动时是否需要进入首次引导。"""

    needs_setup: bool
    source: str
    reason: str
    completion: str = ""
    project_count: int = 0
    config_sources: tuple[str, ...] = ()
    state_error: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["config_sources"] = list(self.config_sources)
        return data


@dataclass(frozen=True)
class InitializationItem:
    """初始化卡片可直接消费的稳定数据结构。"""

    key: str
    title: str
    activity: str
    status: str
    summary: str
    detail: str = ""
    fix: str = ""
    blocking: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class InitializationReport:
    items: tuple[InitializationItem, ...]
    checked_at: str

    @property
    def blocking(self) -> bool:
        return any(item.blocking for item in self.items)

    def summarize(self) -> dict:
        ok = sum(item.status == STATUS_OK for item in self.items)
        warn = sum(item.status == STATUS_WARN for item in self.items)
        fail = sum(item.status == STATUS_FAIL for item in self.items)
        return {
            "status": "blocked" if self.blocking else (
                "attention" if warn or fail else "ready"),
            "total": len(self.items),
            "ok": ok,
            "warn": warn,
            "fail": fail,
            "blocking": self.blocking,
            "checked_at": self.checked_at,
        }

    def to_dict(self) -> dict:
        return {
            "items": [item.to_dict() for item in self.items],
            "summary": self.summarize(),
        }


def _valid_settings_history(path: Path) -> bool:
    """有效 settings.json 即代表用户曾保存配置，包括纯本地配置。"""
    if not path.is_file():
        return False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(raw, dict):
        return False
    known = {
        "api_key", "live_type", "token_mode", "quantity_mode",
        "custom_count", "asr_provider", "asr_model_id", "work_mode",
    }
    return any(key in raw for key in known)


def _has_model_history(root: Path) -> bool:
    if not root.is_dir():
        return False
    try:
        return any(path.is_file() for path in root.rglob("*"))
    except OSError:
        return False


def detect_startup_state(
    *,
    setup_store: SetupStateStore | None = None,
    project_store: ProjectStore | None = None,
    settings_path: Path | None = None,
    api_key_path: Path | None = None,
    models_root: Path | None = None,
) -> StartupDecision:
    """按 setup_state → 项目 → 配置 → 新用户的顺序判定。

    API Key 只是“已有配置”的一个正向证据；缺少 API Key 从不单独导致
    新用户判定，本地模式用户不会因此重复进入引导。
    """
    setup_store = setup_store or SetupStateStore()
    state = setup_store.load()
    state_error = setup_store.last_error

    # 最高优先级：有效状态文件明确决定是否继续/跳过引导。
    if state is not None:
        completed = bool(state.get("completed"))
        completion = str(state.get("completion") or "pending")
        return StartupDecision(
            needs_setup=not completed,
            source=SOURCE_SETUP_STATE,
            reason=("首次引导已记录" if completed else "首次引导尚未完成"),
            completion=completion,
            state_error=state_error,
        )

    # 第二优先级：任何有效项目都说明这不是新用户。
    project_store = project_store or ProjectStore()
    try:
        project_count = len(project_store.list())
    except Exception:  # 损坏项目或目录错误不应让启动判定崩溃
        project_count = 0
    if project_count:
        return StartupDecision(
            needs_setup=False,
            source=SOURCE_PROJECTS,
            reason="检测到已有项目历史",
            project_count=project_count,
            state_error=state_error,
        )

    # 第三优先级：设置、密钥或已下载模型均视为既有配置历史。
    settings_path = Path(settings_path or app_paths.settings_file())
    api_key_path = Path(api_key_path or app_paths.api_key_file())
    models_root = Path(models_root or app_paths.models_dir())
    sources = []
    if _valid_settings_history(settings_path):
        sources.append("settings")
    try:
        if api_key_path.is_file() and api_key_path.read_text(
                encoding="utf-8").strip():
            sources.append("api_key")
    except (OSError, UnicodeError):
        pass
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        sources.append("environment_api_key")
    if _has_model_history(models_root):
        sources.append("local_model")
    if sources:
        return StartupDecision(
            needs_setup=False,
            source=SOURCE_CONFIG,
            reason="检测到已有配置历史",
            config_sources=tuple(sources),
            state_error=state_error,
        )

    return StartupDecision(
        needs_setup=True,
        source=SOURCE_NEW_USER,
        reason="未检测到首次状态、项目或配置历史",
        state_error=state_error,
    )


def _from_selfcheck(
    item,
    *,
    key: str,
    title: str,
    activity: str,
    ok_summary: str,
    warn_summary: str,
    fail_summary: str,
) -> InitializationItem:
    status = item.status if item.status in {
        STATUS_OK, STATUS_WARN, STATUS_FAIL} else STATUS_FAIL
    summary = {
        STATUS_OK: ok_summary,
        STATUS_WARN: warn_summary,
        STATUS_FAIL: fail_summary,
    }[status]
    return InitializationItem(
        key=key,
        title=title,
        activity=activity,
        status=status,
        summary=summary,
        detail=str(item.detail or ""),
        fix=str(item.fix or ""),
        blocking=bool(item.blocking),
        extra=dict(item.extra or {}),
    )


def check_ffmpeg() -> InitializationItem:
    raw = selfcheck.check_ffmpeg()
    return _from_selfcheck(
        raw,
        key="ffmpeg",
        title="Media Engine",
        activity="Checking Media Engine...",
        ok_summary="FFmpeg 已就绪",
        warn_summary="FFmpeg 需要注意",
        fail_summary="媒体引擎不可用",
    )


def check_python_runtime() -> InitializationItem:
    try:
        import PySide6

        version = sys.version_info
        supported = version >= (3, 10)
        frozen = bool(getattr(sys, "frozen", False))
        return InitializationItem(
            key="python",
            title="Application Runtime",
            activity="Checking Application Runtime...",
            status=STATUS_OK if supported else STATUS_WARN,
            summary=("应用运行环境已就绪" if supported else
                     "运行环境版本较旧"),
            detail=(f"Python {version.major}.{version.minor}.{version.micro} · "
                    f"PySide6 {PySide6.__version__} · "
                    f"{'embedded' if frozen else 'development'}"),
            fix=("建议使用 Python 3.10 或更高版本。" if not supported else ""),
            blocking=False,
            extra={"embedded": frozen, "python": sys.version.split()[0]},
        )
    except Exception as exc:
        return InitializationItem(
            key="python",
            title="Application Runtime",
            activity="Checking Application Runtime...",
            status=STATUS_FAIL,
            summary="应用运行环境不完整",
            detail=f"{type(exc).__name__}: {exc}",
            fix="请重新安装 AI Live Clipper。",
            blocking=True,
        )


def check_local_asr() -> InitializationItem:
    deps = selfcheck.check_asr_deps()
    vad = selfcheck.check_vad()
    raws = (deps, vad)
    if any(item.status == STATUS_FAIL for item in raws):
        status = STATUS_FAIL
    elif any(item.status == STATUS_WARN for item in raws):
        status = STATUS_WARN
    else:
        status = STATUS_OK
    detail = "；".join(filter(None, (deps.detail, vad.detail)))
    fixes = "　".join(filter(None, (deps.fix, vad.fix)))
    return InitializationItem(
        key="local_asr",
        title="Local AI Engine",
        activity="Checking Local AI Engine...",
        status=status,
        summary={
            STATUS_OK: "本地语音能力已就绪",
            STATUS_WARN: "本地语音能力需要配置",
            STATUS_FAIL: "本地语音组件不可用",
        }[status],
        detail=detail,
        fix=fixes,
        blocking=any(item.blocking for item in raws),
    )


def check_model_directory(model_id: str = "") -> InitializationItem:
    raw = selfcheck.check_model(model_id)
    item = _from_selfcheck(
        raw,
        key="model",
        title="AI Model Library",
        activity="Checking AI Model Library...",
        ok_summary="本地模型已就绪",
        warn_summary="尚未准备本地模型",
        fail_summary="模型目录不可用",
    )
    extra = dict(item.extra)
    extra.setdefault("models_root", str(app_paths.models_dir()))
    return InitializationItem(
        **{**item.to_dict(), "extra": extra},
    )


def check_api_configuration() -> InitializationItem:
    configured = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
    source = "environment" if configured else ""
    if not configured:
        try:
            path = app_paths.api_key_file()
            configured = path.is_file() and bool(
                path.read_text(encoding="utf-8").strip())
            source = "workspace" if configured else ""
        except (OSError, UnicodeError):
            configured = False
    return InitializationItem(
        key="api",
        title="Cloud AI Service",
        activity="Checking AI Service...",
        status=STATUS_OK if configured else STATUS_WARN,
        summary=("云端增强能力已配置" if configured else
                 "云端增强尚未配置"),
        detail=("API凭据可用" if configured else
                "本地模式无需 API 配置"),
        fix=("可在引导中配置，或稍后在设置中完成。" if not configured else ""),
        blocking=False,
        extra={"configured": configured, "source": source},
    )


def check_video_processing(ffmpeg_item: InitializationItem) -> InitializationItem:
    storage = selfcheck.check_storage()
    if ffmpeg_item.status == STATUS_FAIL:
        return InitializationItem(
            key="video",
            title="Video Pipeline",
            activity="Preparing Video Pipeline...",
            status=STATUS_FAIL,
            summary="视频处理能力不可用",
            detail=ffmpeg_item.detail,
            fix=ffmpeg_item.fix,
            blocking=True,
        )
    if storage.status == STATUS_FAIL:
        return _from_selfcheck(
            storage,
            key="video",
            title="Video Pipeline",
            activity="Preparing Video Pipeline...",
            ok_summary="视频处理能力已就绪",
            warn_summary="视频处理能力需要注意",
            fail_summary="创作空间不可写",
        )

    executable = ffmpeg_item.detail
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        probe = subprocess.run(
            [executable, "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=flags,
            check=False,
        )
        if probe.returncode != 0:
            raise RuntimeError(f"FFmpeg exited with {probe.returncode}")
    except Exception as exc:
        return InitializationItem(
            key="video",
            title="Video Pipeline",
            activity="Preparing Video Pipeline...",
            status=STATUS_FAIL,
            summary="视频处理引擎无法启动",
            detail=f"{type(exc).__name__}: {exc}",
            fix="请重新安装应用，或检查安全软件是否隔离了 FFmpeg。",
            blocking=True,
        )
    return InitializationItem(
        key="video",
        title="Video Pipeline",
        activity="Preparing Video Pipeline...",
        status=STATUS_OK,
        summary="视频处理能力已就绪",
        detail=str(storage.detail or ""),
        blocking=False,
    )


def run_initialization(
    model_id: str = "",
    on_item: Callable[[InitializationItem], None] | None = None,
) -> InitializationReport:
    """依次执行六项轻量检测，并可逐项推送给未来的卡片 UI。"""
    items: list[InitializationItem] = []

    def emit(item: InitializationItem):
        items.append(item)
        if on_item:
            try:
                on_item(item)
            except Exception:
                # 展示层回调不能破坏初始化本身。
                pass

    checks: tuple[tuple[str, str, str, Callable[[], InitializationItem]], ...] = (
        ("ffmpeg", "Media Engine", "Checking Media Engine...", check_ffmpeg),
        ("python", "Application Runtime", "Checking Application Runtime...",
         check_python_runtime),
        ("local_asr", "Local AI Engine", "Checking Local AI Engine...",
         check_local_asr),
        ("model", "AI Model Library", "Checking AI Model Library...",
         lambda: check_model_directory(model_id)),
        ("api", "Cloud AI Service", "Checking AI Service...",
         check_api_configuration),
    )
    for key, title, activity, check in checks:
        try:
            emit(check())
        except Exception as exc:
            emit(InitializationItem(
                key=key,
                title=title,
                activity=activity,
                status=STATUS_FAIL,
                summary="检测过程出现异常",
                detail=f"{type(exc).__name__}: {exc}",
                fix="请重试；如果问题持续，请提交诊断信息。",
                blocking=True,
            ))

    try:
        emit(check_video_processing(items[0]))
    except Exception as exc:
        emit(InitializationItem(
            key="video",
            title="Video Pipeline",
            activity="Preparing Video Pipeline...",
            status=STATUS_FAIL,
            summary="视频处理检测失败",
            detail=f"{type(exc).__name__}: {exc}",
            fix="请重试；如果问题持续，请重新安装应用。",
            blocking=True,
        ))
    return InitializationReport(tuple(items), _now())
