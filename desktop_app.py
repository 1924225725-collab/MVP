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


def _startup_log(msg: str):
    """启动日志（V0.5.2）。

    打包后没有控制台，启动慢/卡死时用户和开发者都拿不到线索，
    所以把关键节点和耗时写进 工作区/logs/desktop_startup.log。
    """
    try:
        import datetime

        import app_paths
        path = app_paths.logs_dir() / "desktop_startup.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        # 日志超过 512KB 就从头来，别无限长
        try:
            if path.exists() and path.stat().st_size > 512 * 1024:
                path.unlink()
        except OSError:
            pass
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:                                               # noqa: BLE001
        pass


def main() -> int:
    import time
    t_start = time.time()

    import app_paths

    app_paths.ensure_workspace()
    _startup_log("=" * 50)
    _startup_log(f"启动 AI直播切片助手　frozen={bool(getattr(sys, 'frozen', False))}")
    _startup_log(f"程序目录：{app_paths.program_root()}")
    _startup_log(f"用户数据：{app_paths.workspace_root()}")
    _startup_log(f"工作区就绪（{time.time() - t_start:.2f}s）")

    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError as e:
        _crash_log(f"PySide6 导入失败：{e}\n{traceback.format_exc()}")
        _startup_log(f"PySide6 导入失败：{e}")
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
    _startup_log(f"Qt 应用创建完成（{time.time() - t_start:.2f}s）")

    from desktop import theme
    app.setStyleSheet(theme.QSS)

    try:
        from desktop.ui import MainWindow
        win = MainWindow()
    except Exception as e:
        log = _crash_log(f"界面初始化失败：{e}\n{traceback.format_exc()}")
        _startup_log(f"主窗口构建失败：{e}")
        QMessageBox.critical(None, "启动失败",
                             f"程序启动失败：\n{e}\n\n日志已写入：\n{log}")
        return 3
    _startup_log(f"主窗口构建完成（{time.time() - t_start:.2f}s）")

    win.show()
    _startup_log(f"窗口已显示（{time.time() - t_start:.2f}s），进入事件循环")

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

    # 开机环境自检（V0.5.2）：
    #   界面**先显示出来**，检查放后台线程跑 —— 绝不让用户在启动时看到"无响应"。
    #   检查完只在真有问题时才弹窗（见 main_window.run_selfcheck 的 startup 分支）。
    QTimer.singleShot(600, lambda: win.run_selfcheck(startup=True))

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
        from desktop.services import selfcheck as _sc
        _items = _sc.run_all()
        info["selfcheck"] = {
            "summary": _sc.summarize(_items),
            "items": [{"key": i.key, "name": i.name, "status": i.status,
                       "category": i.category, "detail": i.detail} for i in _items],
        }
    except Exception as e:                                          # noqa: BLE001
        info["selfcheck"] = f"失败：{type(e).__name__}: {e}"

    try:
        out = app_paths.logs_dir() / "desktop_smoke.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _check_model_on_startup(win, QMessageBox):
    """（已由开机环境自检取代，保留这个函数仅为兼容旧调用。）

    现在启动流程走 win.run_selfcheck(startup=True)：
    自检在后台线程跑，把模型、组件、权限一次查完，有问题才弹窗。
    """
    return None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        _crash_log(traceback.format_exc())
        raise
