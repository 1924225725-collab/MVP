# ============================================================
# app_paths.py —— 统一的「程序目录 / 用户数据目录」解析（桌面化 V0.5 新增）
#
# 【为什么需要】
#   以前所有路径都以「项目根目录」为基准（各模块自己写 BASE_DIR = __file__/..）。
#   打包成桌面软件后：
#     - 程序装在 Program Files（**不可写**，升级会覆盖）
#     - 用户视频 / 文稿 / 分析结果 / 模型必须放在可写且升级不丢的地方
#   所以把「路径从哪来」集中到这一个文件，业务模块只问它要目录。
#
# 【行为约定】（关键：默认行为与改造前完全一致）
#   1. 设置了环境变量 LIVE_CLIPPER_HOME  → 用它作为用户数据根目录
#   2. 打包运行（PyInstaller frozen）    → %LOCALAPPDATA%\AILiveClipper
#   3. 其他（开发态、跑测试、跑网页版）  → 项目根目录（= 改造前行为）
#
#   因此：现有 main.py / ui.py / 全部 test_*.py 行为不变，无需改动。
#
# 【目录布局】（工作区内，与开发态布局保持一致，便于迁移）
#   api_key.txt / custom_dictionary.json / user_lexicon.txt / feedback.json
#   videos/  audio/  transcripts/  structures/  projects/  models/  logs/  temp/
# ============================================================

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "AILiveClipper"                 # 英文名（目录名用，避免中文路径问题）
APP_DISPLAY_NAME = "AI直播切片助手"          # 显示名
ENV_HOME = "LIVE_CLIPPER_HOME"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包出来的程序里。"""
    return bool(getattr(sys, "frozen", False))


def program_root() -> Path:
    """程序目录（**只读**）：打包内置资源、模板文件。

    - 打包态：PyInstaller 解包目录（_MEIPASS）或 exe 所在目录
    - 开发态：项目根目录
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def workspace_root() -> Path:
    """用户数据根目录（可写）：视频、文稿、结构缓存、分析结果、模型、日志。"""
    env = os.environ.get(ENV_HOME, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path(__file__).resolve().parent      # 开发态：项目根（保持既有行为）


def set_workspace(path) -> Path:
    """切换用户数据根目录（桌面版启动时调用；测试也可用）。

    设置后新的目录常量会在**下一次导入**时生效——桌面版在导入业务模块前调用。
    """
    p = Path(path).expanduser().resolve()
    os.environ[ENV_HOME] = str(p)
    ensure_workspace()
    return p


# ---------------- 各子目录 ----------------

def videos_dir() -> Path:
    return workspace_root() / "videos"


def audio_dir() -> Path:
    return workspace_root() / "audio"


def transcripts_dir() -> Path:
    return workspace_root() / "transcripts"


def structures_dir() -> Path:
    return workspace_root() / "structures"


def projects_dir() -> Path:
    """每个视频一份项目结果（桌面版新增）。"""
    return workspace_root() / "projects"


def models_dir() -> Path:
    """本地 ASR 模型目录（**不放 Program Files**）。"""
    return workspace_root() / "models"


def logs_dir() -> Path:
    return workspace_root() / "logs"


def temp_dir() -> Path:
    return workspace_root() / "temp"


def api_key_file() -> Path:
    return workspace_root() / "api_key.txt"


def settings_file() -> Path:
    return workspace_root() / "settings.json"


ALL_SUBDIRS = ("videos", "audio", "transcripts", "structures",
               "projects", "models", "logs", "temp")

# 首次运行时从程序目录复制到工作区的模板文件（存在就跳过，不覆盖用户数据）
SEED_FILES = ("custom_dictionary.json", "user_lexicon.txt")


def ensure_workspace() -> Path:
    """确保工作区目录结构存在；首次运行释放模板文件。返回工作区根目录。"""
    root = workspace_root()
    for name in ALL_SUBDIRS:
        try:
            (root / name).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    # 模板文件：程序目录里有、工作区里没有 → 复制一份（绝不覆盖已有用户数据）
    prog = program_root()
    for fname in SEED_FILES:
        dst = root / fname
        src = prog / fname
        if dst.exists() or not src.exists() or src.resolve() == dst.resolve():
            continue
        try:
            shutil.copyfile(src, dst)
        except OSError:
            pass
    return root


def describe() -> dict:
    """当前路径布局（开发者视图显示用）。"""
    return {
        "程序目录": str(program_root()),
        "用户数据目录": str(workspace_root()),
        "打包运行": is_frozen(),
        "环境变量": os.environ.get(ENV_HOME, ""),
        "视频": str(videos_dir()),
        "文字稿": str(transcripts_dir()),
        "结构缓存": str(structures_dir()),
        "项目结果": str(projects_dir()),
        "模型": str(models_dir()),
        "日志": str(logs_dir()),
    }
