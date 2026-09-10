# ============================================================
# desktop_app.py —— AI 直播切片助手 · Windows 桌面版入口
#
# 双击即用：不需要 Python / VS Code / 命令行 / 浏览器。
#
# 开发态运行：
#     .\.venv\Scripts\python desktop_app.py
# 打包后：
#     AI直播切片助手.exe（由 installer/ 打包脚本产出）
#
# 【启动顺序很重要】
#   1. 先把「用户数据目录」定下来（app_paths.ensure_workspace）
#   2. 再导入界面（界面导入链会连带导入 analysis / pipeline / asr，
#      这些模块在导入时就会用 app_paths 解析出最终路径）
# ============================================================

import os
import sys
import traceback
from pathlib import Path


# ---------------- 让 live_clipper 根目录可导入 ----------------

def _bootstrap_path():
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and meipass not in sys.path:
            sys.path.insert(0, meipass)
    return here


ROOT = _bootstrap_path()


def _crash_log(exc_text: str):
    """启动就崩的话，把原因写进日志文件（用户看不到控制台）。"""
    try:
        import app_paths
        log = app_paths.logs_dir() / "desktop_crash.log"
    except Exception:
        log = ROOT / "desktop_crash.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        import datetime
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.datetime.now().isoformat(timespec='seconds')} =====\n")
            f.write(exc_text)
    except Exception:
        pass
    return log


def main() -> int:
    import app_paths

    app_paths.ensure_workspace()

    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError as e:
        _crash_log(f"PySide6 导入失败：{e}\n{traceback.format_exc()}")
        return 2

    # 高 DPI：Qt6 默认已经开启缩放，这里只把缩放取整策略定下来，
    # 免得 125% / 150% 缩放下界面出现半像素模糊。
    try:
        from PySide6.QtGui import QGuiApplication
        policy = getattr(Qt, "HighDpiScaleFactorRoundingPolicy", None)
        if policy is not None:
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
                policy.PassThrough)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(app_paths.APP_DISPLAY_NAME)
    app.setOrganizationName(app_paths.APP_NAME)
    app.setFont(QFont("Microsoft YaHei UI", 9))

    from desktop import theme
    app.setStyleSheet(theme.QSS)

    try:
        from desktop.ui import MainWindow
        win = MainWindow()
    except Exception as e:
        log = _crash_log(f"界面初始化失败：{e}\n{traceback.format_exc()}")
        QMessageBox.critical(None, "启动失败",
                             f"程序启动失败：\n{e}\n\n日志已写入：\n{log}")
        return 3

    win.show()

    # 打包自检：设了 LIVE_CLIPPER_SMOKE=1 就在离屏模式跑一下，
    # 把"冻结环境到底能不能用"写进日志（打包后没控制台，只能落文件）。
    if os.environ.get("LIVE_CLIPPER_SMOKE"):
        _write_smoke_report(win)
        # 再真跑一次语音识别（可选，给验收用）：
        #   只 import 得进来不算数 —— faster_whisper 的 VAD 模型文件漏打包时，
        #   导入和构造都正常，只有真跑一次才会炸。
        media = os.environ.get("LIVE_CLIPPER_SMOKE_TRANSCRIBE", "").strip()
        if media and os.path.exists(media):
            _run_smoke_transcribe(media)
        QTimer.singleShot(600, app.quit)
        return app.exec()

    # 首次使用：本地模型没装就提醒一次（不挡路，用户可以选择稍后）
    QTimer.singleShot(600, lambda: _check_model_on_startup(win, QMessageBox))

    return app.exec()


def _run_smoke_transcribe(media: str):
    """自检时真跑一次本地语音识别，结果追加进同一个报告。

    这一步是**验收的关键**：打包漏文件时（比如 faster_whisper 的 VAD 模型
    silero_vad.onnx），import 和构造识别器都不会报错，只有真跑才炸。
    """
    import json
    import traceback

    import app_paths

    report_path = app_paths.logs_dir() / "desktop_smoke.json"
    try:
        base = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:                                               # noqa: BLE001
        base = {}

    entry = {"media": media}
    try:
        from desktop.services.tasks import transcribe_video
        res = transcribe_video(media)
        entry.update({
            "ok": True,
            "lines": res.get("lines"),
            "segments": res.get("segments"),
            "duration": res.get("duration"),
        })
    except Exception as e:                                          # noqa: BLE001
        stage = getattr(e, "stage", "")
        entry.update({
            "ok": False,
            "stage": stage,
            "error": f"{type(e).__name__}: {e}",
            "detail": (getattr(e, "detail", "") or "")[-1500:],
            "traceback": traceback.format_exc()[-1500:],
        })

    base["smoke_transcribe"] = entry
    try:
        report_path.write_text(json.dumps(base, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception:                                               # noqa: BLE001
        pass


def _write_smoke_report(win):
    """把打包环境的关键信息写出来，供安装包验收用。"""
    import json
    info = {"frozen": bool(getattr(sys, "frozen", False))}
    try:
        import app_paths
        info["paths"] = app_paths.describe()
    except Exception as e:                                          # noqa: BLE001
        info["paths"] = f"失败：{e}"
    try:
        import pipeline
        info["ffmpeg"] = pipeline.find_ffmpeg()
    except Exception as e:                                          # noqa: BLE001
        info["ffmpeg"] = f"失败：{type(e).__name__}: {e}"
    try:
        import asr
        # 只构造识别器，不加载模型（自检要快，不能真去读 464MB）
        info["asr_create"] = type(asr.create_recognizer()).__name__
    except Exception as e:                                          # noqa: BLE001
        info["asr_create"] = f"失败：{type(e).__name__}: {e}"
    try:
        from asr import registry
        info["providers"] = [
            {"id": p.get("id"), "available": p.get("available"), "reason": p.get("reason")}
            for p in registry.list_providers()
        ]
    except Exception as e:                                          # noqa: BLE001
        info["providers"] = f"失败：{e}"
    try:
        from desktop.services.model_manager import ModelManager
        info["models"] = [{"id": s["id"], "installed": s["installed"]}
                          for s in ModelManager().list_status()]
    except Exception as e:                                          # noqa: BLE001
        info["models"] = f"失败：{e}"
    try:
        info["tabs"] = [win.tabs.tabText(i) for i in range(win.tabs.count())]
        info["window"] = win.windowTitle()
    except Exception as e:                                          # noqa: BLE001
        info["tabs"] = f"失败：{e}"
    try:
        import analysis
        info["analysis_import"] = "OK"
    except Exception as e:                                          # noqa: BLE001
        info["analysis_import"] = f"失败：{type(e).__name__}: {e}"

    try:
        out = app_paths.logs_dir() / "desktop_smoke.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _check_model_on_startup(win, QMessageBox):
    try:
        from desktop.services.model_manager import ModelManager
        from desktop.services.settings_store import SettingsStore

        settings = SettingsStore().load()
        mgr = ModelManager()
        model_id = settings.get("asr_model_id") or mgr.default_model_id()
        if not model_id or mgr.is_installed(model_id):
            return
        ans = QMessageBox.question(
            win, "还差一个语音识别模型",
            "本机还没有语音识别模型（第一次使用需要装一次，约几百 MB，之后完全离线）。\n\n"
            f"准备好了吗？现在打开「模型管理」下载：{model_id}\n"
            "（如果以前跑过网页版，模型可能已经在缓存里，点「使用本机已有模型」即可）")
        if ans == QMessageBox.Yes:
            win.open_models()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        _crash_log(traceback.format_exc())
        raise
