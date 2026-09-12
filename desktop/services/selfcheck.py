# ============================================================
# desktop/services/selfcheck.py —— 软件环境自检（V0.5.2）
#
# 【为什么需要】
#   用户遇到问题时，最怕看到一句「视频处理失败」——因为那等于什么都没说。
#   实际情况往往是这几类之一，而且**处理办法完全不同**：
#     1. 视频问题   （文件损坏 / 没有音轨）      → 换个视频
#     2. 程序组件问题（缺依赖文件 / 打包遗漏）    → 重装程序
#     3. 模型问题   （模型没装 / 模型文件损坏）   → 一键安装 / 校验修复
#     4. 权限问题   （目录写不进去 / 删不掉）     → 换个位置 / 用管理员
#
#   这个模块在启动时把环境摸一遍，把结论**分好类**摆出来，
#   每一条都写清楚"哪儿坏了 + 该怎么办"。
#
# 【检查项】
#   ffmpeg       音视频处理组件（提取音频要用）
#   wasm         语音识别依赖（faster-whisper / ctranslate2 / tokenizers / onnxruntime）
#   vad          人声检测模型（silero_vad onnx）—— V0.5.1 就是这里被漏打包过
#   model        本地模型装没装、能不能用
#   config       配置与资源文件（模型清单、词库、钥匙）
#   storage      工作区读写权限
# ============================================================

import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ---------------- 问题分类（界面按这个分组显示） ----------------

CAT_VIDEO = "video"            # 视频问题
CAT_COMPONENT = "component"    # 程序组件问题
CAT_MODEL = "model"            # 模型问题
CAT_PERMISSION = "permission"  # 权限问题
CAT_CONFIG = "config"          # 配置问题

CATEGORY_TITLES = {
    CAT_VIDEO: "视频问题",
    CAT_COMPONENT: "程序组件问题",
    CAT_MODEL: "模型问题",
    CAT_PERMISSION: "权限问题",
    CAT_CONFIG: "配置问题",
}

# ---------------- 检查结果 ----------------

STATUS_OK = "ok"
STATUS_WARN = "warn"      # 不阻塞使用，但功能会受限（比如没装模型 → 不能识别）
STATUS_FAIL = "fail"      # 阻塞：现在就跑不了


@dataclass
class CheckItem:
    key: str                      # 检查项 id
    name: str                     # 显示名
    status: str                   # ok / warn / fail
    category: str = ""            # 出问题时的分类
    detail: str = ""              # 技术细节（开发者视图）
    fix: str = ""                 # 用户该怎么办（普通人能看懂的一句话）
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def blocking(self) -> bool:
        return self.status == STATUS_FAIL

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------- 出错 stage → 问题分类 ----------------

def category_of_stage(stage: str) -> str:
    """把 ProcessError 的 stage 归类到四个大类（界面据此给建议）。"""
    from errors import (
        STAGE_ASR_EMPTY, STAGE_ASR_INFERENCE, STAGE_AUDIO_EXTRACT,
        STAGE_CONFIG, STAGE_DEPENDENCY, STAGE_FFMPEG, STAGE_MEDIA_UNREADABLE,
        STAGE_MODEL_LOAD, STAGE_MODEL_MISSING, STAGE_NO_AUDIO, STAGE_PERMISSION,
    )
    return {
        STAGE_MEDIA_UNREADABLE: CAT_VIDEO,
        STAGE_NO_AUDIO: CAT_VIDEO,
        STAGE_AUDIO_EXTRACT: CAT_VIDEO,
        STAGE_ASR_EMPTY: CAT_VIDEO,
        STAGE_FFMPEG: CAT_COMPONENT,
        STAGE_DEPENDENCY: CAT_COMPONENT,
        STAGE_ASR_INFERENCE: CAT_COMPONENT,
        STAGE_MODEL_MISSING: CAT_MODEL,
        STAGE_MODEL_LOAD: CAT_MODEL,
        STAGE_PERMISSION: CAT_PERMISSION,
        STAGE_CONFIG: CAT_CONFIG,
    }.get(str(stage or ""), CAT_COMPONENT)


# ---------------- 单项检查 ----------------

def check_ffmpeg() -> CheckItem:
    """音视频处理组件：ffmpeg（提取音频靠它）。"""
    item = CheckItem("ffmpeg", "FFmpeg 音视频处理组件", STATUS_OK)
    try:
        import pipeline
        exe = pipeline.find_ffmpeg()
    except Exception as e:                                   # noqa: BLE001
        item.status = STATUS_FAIL
        item.category = CAT_COMPONENT
        item.detail = f"{type(e).__name__}: {e}"
        item.fix = ("程序自带的音视频组件不完整（可能是安装没完成或被杀毒软件删了）。"
                    "请重新安装本程序。")
        return item
    if not exe or not os.path.exists(exe):
        item.status = STATUS_FAIL
        item.category = CAT_COMPONENT
        item.detail = f"找不到 ffmpeg：{exe}"
        item.fix = "程序自带的音视频组件不完整，请重新安装本程序。"
        return item
    item.detail = exe
    item.extra = {"path": exe, "size_mb": round(os.path.getsize(exe) / 1024 / 1024, 1)}
    return item


def check_asr_deps() -> CheckItem:
    """语音识别依赖组件（faster-whisper 及其推理库）。"""
    item = CheckItem("asr_deps", "语音识别组件（faster-whisper）", STATUS_OK)
    missing = []
    for mod, label in (("faster_whisper", "faster-whisper"),
                       ("ctranslate2", "ctranslate2 推理引擎"),
                       ("tokenizers", "tokenizers 分词"),
                       ("onnxruntime", "onnxruntime 运行时")):
        try:
            __import__(mod)
        except Exception as e:                               # noqa: BLE001
            missing.append(f"{label}（{type(e).__name__}）")
    if missing:
        item.status = STATUS_FAIL
        item.category = CAT_COMPONENT
        item.detail = "缺少：" + "、".join(missing)
        item.fix = "程序组件不完整，请重新安装本程序。"
    else:
        item.detail = "4 个组件齐全"
    return item


def check_vad() -> CheckItem:
    """人声检测模型（silero_vad onnx）。

    ⚠️ V0.5.1 的真实事故：这个文件是 faster_whisper 包里唯一的非 .py 文件，
    打包时漏了 → 开发态永远正常，装到别的盘一识别就崩。
    所以必须**单独检查**它，而不是只 import 一下包就算数。
    """
    item = CheckItem("vad", "人声检测模型（VAD）", STATUS_OK)
    try:
        import faster_whisper
        assets = Path(faster_whisper.__file__).resolve().parent / "assets"
    except Exception as e:                                   # noqa: BLE001
        item.status = STATUS_FAIL
        item.category = CAT_COMPONENT
        item.detail = f"无法定位 faster_whisper 包：{e}"
        item.fix = "程序组件不完整，请重新安装本程序。"
        return item

    files = sorted(p.name for p in assets.glob("*.onnx")) if assets.is_dir() else []
    if not files:
        item.status = STATUS_FAIL
        item.category = CAT_COMPONENT
        item.detail = f"目录里没有任何 .onnx 模型：{assets}"
        item.fix = ("程序缺少人声检测模型（安装包没装全，常见于被杀毒软件拦截）。"
                    "请重新安装本程序。")
        return item
    item.detail = f"{assets}　→　{', '.join(files)}"
    item.extra = {"files": files, "dir": str(assets)}
    return item


def check_model(model_id: str = "") -> CheckItem:
    """本地语音识别模型：装没装、能不能直接用。"""
    item = CheckItem("model", "本地语音识别模型", STATUS_OK)
    try:
        from desktop.services.model_manager import ModelManager
        mgr = ModelManager()
        mid = model_id or mgr.default_model_id()
        item.extra["model_id"] = mid
        if not mid:
            item.status = STATUS_FAIL
            item.category = CAT_MODEL
            item.detail = "模型清单是空的"
            item.fix = "程序自带的模型清单读不到，请重新安装本程序。"
            return item
        path, source = mgr.resolve_local(mid)
        if not path:
            item.status = STATUS_WARN
            item.category = CAT_MODEL
            item.detail = f"{mid} 尚未安装"
            item.fix = ("还没有下载语音识别模型。点「模型管理」→「一键安装」即可"
                        "（只需一次，之后完全离线）。")
            return item
        ok, msg = mgr.verify(mid)
        if not ok:
            item.status = STATUS_WARN
            item.category = CAT_MODEL
            item.detail = f"{mid}：{msg}"
            item.fix = ("模型文件不完整或已损坏。请在「模型管理」里点「完整性校验」，"
                        "或卸载后重新安装该模型。")
            return item
        item.detail = f"{mid}　来源={source}　{msg}"
        item.extra.update({"source": source, "path": str(path)})
    except Exception as e:                                   # noqa: BLE001
        item.status = STATUS_WARN
        item.category = CAT_MODEL
        item.detail = f"{type(e).__name__}: {e}"
        item.fix = ("读取模型清单失败，请在「模型管理」里检查。"
                    "若反复失败，重新安装本程序。")
    return item


def check_config() -> CheckItem:
    """配置与资源文件：模型清单、自定义词库、API 钥匙。"""
    problems = []
    notes = []
    try:
        import app_paths
        manifest = app_paths.program_root() / "models_registry.json"
        if not manifest.exists():
            problems.append("模型清单 models_registry.json 丢失")
        else:
            try:
                json.loads(manifest.read_text(encoding="utf-8"))
                notes.append("模型清单 OK")
            except (OSError, json.JSONDecodeError) as e:
                problems.append(f"模型清单格式坏了（{e}）")
    except Exception as e:                                   # noqa: BLE001
        problems.append(f"读取程序目录失败（{e}）")

    # 自定义词库（用户自己改坏的也提醒一下，但不阻塞）
    try:
        import app_paths
        dic = app_paths.workspace_root() / "custom_dictionary.json"
        if dic.exists():
            try:
                json.loads(dic.read_text(encoding="utf-8"))
                notes.append("自定义词库 OK")
            except (OSError, json.JSONDecodeError):
                problems.append("自定义词库 JSON 格式有误（不影响识别，纠错会跳过）")
    except Exception:                                        # noqa: BLE001
        pass

    # AI 分析的钥匙（没有就不能做分析，但识别照常）
    has_key = False
    try:
        import app_paths
        key_file = app_paths.api_key_file()
        has_key = bool(os.environ.get("DEEPSEEK_API_KEY")) or (
            key_file.exists() and key_file.read_text(encoding="utf-8").strip())
    except Exception:                                        # noqa: BLE001
        pass

    item = CheckItem("config", "配置文件", STATUS_OK)
    item.detail = "；".join(notes + problems) or "—"
    if problems:
        item.status = STATUS_WARN
        item.category = CAT_CONFIG
        item.fix = "配置文件有问题：" + "；".join(problems)
    if not has_key:
        # 没钥匙只影响"AI 分析"，不影响本地识别 → 用 warn 而不是 fail
        item.status = STATUS_WARN if item.status == STATUS_OK else item.status
        item.category = item.category or CAT_CONFIG
        item.fix = (item.fix + "　" if item.fix else "") + \
            "还没有填 DeepSeek 钥匙（本地识别不受影响，但 AI 分析不能用）。" \
            "可在「设置」里填一次。"
    item.extra["has_api_key"] = has_key
    return item


def check_storage() -> CheckItem:
    """工作区读写权限（能不能建目录、写文件、删文件）。"""
    item = CheckItem("storage", "数据目录读写权限", STATUS_OK)
    try:
        import app_paths
        root = app_paths.ensure_workspace()
    except Exception as e:                                   # noqa: BLE001
        item.status = STATUS_FAIL
        item.category = CAT_PERMISSION
        item.detail = f"无法创建工作区目录：{type(e).__name__}: {e}"
        item.fix = ("数据目录建不出来（可能是权限不足或磁盘满了）。"
                    "请检查磁盘空间，或换一个有写入权限的位置。")
        return item

    probe = Path(root) / f".selfcheck_{int(time.time())}.tmp"
    try:
        probe.write_text("ok", encoding="utf-8")
        if probe.read_text(encoding="utf-8") != "ok":
            raise OSError("写进去读出来不一致")
    except Exception as e:                                   # noqa: BLE001
        item.status = STATUS_FAIL
        item.category = CAT_PERMISSION
        item.detail = f"{root}：{type(e).__name__}: {e}"
        item.fix = (f"数据目录写不进去（{root}）。"
                    "可能是杀毒软件拦截或权限不足，请换一个位置或联系管理员。")
        return item
    finally:
        # 探针文件一定要清掉（以前失败路径会留个垃圾文件在用户目录里）
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
    item.detail = f"{root}　可读写"
    item.extra["workspace"] = str(root)
    return item


# ---------------- 总入口 ----------------

CHECK_ORDER = ("ffmpeg", "asr_deps", "vad", "model", "config", "storage")


def run_all(model_id: str = "", on_item=None) -> list:
    """跑一遍全部检查，返回 CheckItem 列表。

    on_item(item) 可选：每查完一项回调一次（界面可以边查边显示）。
    """
    checks = {
        "ffmpeg": lambda: check_ffmpeg(),
        "asr_deps": lambda: check_asr_deps(),
        "vad": lambda: check_vad(),
        "model": lambda: check_model(model_id),
        "config": lambda: check_config(),
        "storage": lambda: check_storage(),
    }
    items = []
    for key in CHECK_ORDER:
        try:
            item = checks[key]()
        except Exception as e:                               # noqa: BLE001
            item = CheckItem(key, key, STATUS_FAIL, CAT_COMPONENT,
                             f"自检本身出错：{type(e).__name__}: {e}",
                             "请把「开发者视图」里的信息反馈给开发者。")
        items.append(item)
        if on_item:
            try:
                on_item(item)
            except Exception:                                # noqa: BLE001
                pass
    return items


def summarize(items: list) -> dict:
    """统计结果：有几项 ok / 警告 / 失败，有没有阻塞项。"""
    fails = [i for i in items if i.status == STATUS_FAIL]
    warns = [i for i in items if i.status == STATUS_WARN]
    oks = [i for i in items if i.status == STATUS_OK]
    return {
        "total": len(items),
        "ok": len(oks),
        "warn": len(warns),
        "fail": len(fails),
        "blocking": bool(fails),
        "headline": (f"{len(fails)} 项有问题，程序可能无法正常识别" if fails
                     else (f"环境正常，{len(warns)} 项提示" if warns
                           else "环境正常，可以开始使用")),
        "problems": [i.to_dict() for i in (fails + warns)],
    }


def report_text(items: list) -> str:
    """给「开发者视图」看的完整文字报告。"""
    icon = {STATUS_OK: "✔", STATUS_WARN: "!", STATUS_FAIL: "✘"}
    lines = ["【环境自检】"]
    for it in items:
        cat = f"　[{CATEGORY_TITLES.get(it.category, it.category)}]" if it.category else ""
        lines.append(f"  {icon.get(it.status, '?')} {it.name}{cat}")
        if it.detail:
            lines.append(f"      {it.detail}")
        if it.fix and it.status != STATUS_OK:
            lines.append(f"      → {it.fix}")
    s = summarize(items)
    lines.append("")
    lines.append(f"  小结：{s['headline']}")
    return "\n".join(lines)
