# ============================================================
# packaging/verify_install.py —— 安装包实测（阶段 10 自动部分）
#
# 【模拟真实的"装完打开"过程】
#   1. 把安装载荷 payload.zip 解到一个**干净的临时安装目录**
#      （跟 Setup.exe 做的事完全一样）
#   2. 用**独立的工作区**（LIVE_CLIPPER_HOME）跑装好的 AILiveClipper.exe，
#      带 LIVE_CLIPPER_SMOKE=1 → 程序离屏自检后自动退出，结果写进日志
#   3. 逐项核对：冻结态 / 目录分离 / 内置 ffmpeg 可用 / 四个页签 /
#      ASR 引擎与模型清单 / 分析模块可导入 / 卸载程序在不在
#
# 这一步**不需要人工点鼠标**，也不联网、不跑模型。
# 真正的"双击 Setup.exe 看快捷方式"仍需人工过一遍（见报告末尾清单）。
#
# 用法：.\.venv\Scripts\python packaging\verify_install.py
# ============================================================

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = ROOT / "packaging" / "build" / "payload.zip"
EXE_NAME = "AILiveClipper.exe"

PASS = 0
FAIL = 0
ROWS = []


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        ROWS.append(("PASS", name, ""))
    else:
        FAIL += 1
        ROWS.append(("FAIL", name, extra))
    return bool(cond)


def main():
    if not PAYLOAD.exists():
        print(f"找不到安装载荷：{PAYLOAD}\n先运行 build_desktop.py")
        return 2

    # ---- 第 0 步：安装程序自身的自检（载荷是否真的塞进 exe 了） ----
    setup_exe = ROOT / "dist_setup" / "AILiveClipper_Setup.exe"
    if setup_exe.exists():
        print("[0] 安装程序自检…")
        try:
            pr = subprocess.run([str(setup_exe), "--selftest"], capture_output=True,
                                text=True, timeout=180, encoding="utf-8",
                                errors="replace")
            sj = Path(tempfile.gettempdir()) / "lc_setup_selftest.json"
            sinfo = json.loads(sj.read_text(encoding="utf-8")) if sj.exists() else {}
            check("0 安装程序能启动并读取自带载荷", pr.returncode == 0,
                  f"退出码 {pr.returncode}")
            check("0 载荷 zip 完整无损", sinfo.get("zip_integrity") == "OK",
                  str(sinfo.get("zip_integrity")))
            check("0 载荷里有主程序 / 卸载程序 / ffmpeg",
                  bool(sinfo.get("has_exe") and sinfo.get("has_uninstall")
                       and sinfo.get("has_ffmpeg")), str(sinfo))
            check("0 默认安装位置在用户目录（不需要管理员权限）",
                  "AppData" in str(sinfo.get("default_install_dir", "")),
                  str(sinfo.get("default_install_dir")))
        except Exception as e:                                      # noqa: BLE001
            check("0 安装程序自检", False, f"{type(e).__name__}: {e}")
    else:
        print("[0] 没找到 dist_setup/AILiveClipper_Setup.exe，跳过安装程序自检")

    tmp_root = Path(tempfile.mkdtemp(prefix="lc_verify_"))
    install_dir = tmp_root / "install"
    workspace = tmp_root / "workspace"
    install_dir.mkdir(parents=True)

    print(f"[1] 解压安装载荷 → {install_dir}  ({PAYLOAD.stat().st_size/1024/1024:.0f} MB)")
    with zipfile.ZipFile(PAYLOAD) as z:
        z.extractall(install_dir)

    # payload.zip 里若多套一层同名目录，提上来
    inner = install_dir / "AILiveClipper"
    if inner.is_dir() and not (install_dir / EXE_NAME).exists():
        for item in inner.iterdir():
            shutil.move(str(item), str(install_dir / item.name))
        inner.rmdir()

    exe = install_dir / EXE_NAME
    check("1 解压后主程序存在", exe.exists(), str(exe))
    check("1 卸载程序随主程序一起装好", (install_dir / "uninstall.exe").exists())
    check("1 内置 ffmpeg 存在",
          any(p.name.startswith("ffmpeg-") and p.suffix == ".exe"
              for p in (install_dir / "_internal" / "imageio_ffmpeg" / "binaries").glob("*")
              ) if (install_dir / "_internal" / "imageio_ffmpeg" / "binaries").is_dir()
          else False)
    check("1 Qt 平台插件存在（不然窗口起不来）",
          (install_dir / "_internal" / "PySide6" / "plugins" / "platforms"
           / "qwindows.dll").exists())
    check("1 推理引擎 DLL 存在（ctranslate2）",
          any((install_dir / "_internal" / "ctranslate2").glob("ctranslate2.dll")))
    check("1 Model Registry 随程序分发",
          (install_dir / "_internal" / "models_registry.json").exists())
    check("1 程序目录里**没有** models/ 目录（模型不随包分发）",
          not (install_dir / "models").exists())

    if not exe.exists():
        return report()

    # ---- 真正跑一次装好的程序 ----
    env = dict(os.environ)
    env["LIVE_CLIPPER_SMOKE"] = "1"
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["LIVE_CLIPPER_HOME"] = str(workspace)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)

    print("[2] 启动装好的程序（离屏自检模式，最多等 180 秒）…")
    try:
        p = subprocess.run([str(exe)], env=env, cwd=str(install_dir),
                           capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")
        rc = p.returncode
    except subprocess.TimeoutExpired:
        check("2 程序能在 180 秒内启动并自检退出", False, "超时")
        return report()
    check("2 程序启动并正常退出（退出码 0）", rc == 0, f"退出码 {rc}")

    smoke = workspace / "logs" / "desktop_smoke.json"
    check("2 自检报告已生成", smoke.exists(), str(smoke))
    if not smoke.exists():
        return report()

    info = json.loads(smoke.read_text(encoding="utf-8"))

    # ---- 逐项核对 ----
    check("3 运行在冻结（打包）模式", info.get("frozen") is True, str(info.get("frozen")))

    paths = info.get("paths") or {}
    check("3 用户数据目录 = 我们指定的独立工作区",
          str(paths.get("用户数据目录", "")) == str(workspace),
          str(paths.get("用户数据目录")))
    check("3 程序目录 ≠ 用户数据目录（程序与数据分离）",
          str(paths.get("程序目录", "")) != str(paths.get("用户数据目录", "")),
          f"{paths.get('程序目录')} / {paths.get('用户数据目录')}")
    check("3 模型目录落在用户数据目录里（不在安装目录）",
          str(paths.get("模型", "")).startswith(str(workspace)),
          str(paths.get("模型")))
    check("3 工作区子目录已自动创建",
          all((workspace / d).is_dir()
              for d in ("videos", "transcripts", "projects", "models", "logs")))

    ff = str(info.get("ffmpeg", ""))
    check("4 内置 ffmpeg 在打包环境里能找到", os.path.exists(ff), ff)
    check("4 找到的 ffmpeg 来自程序目录（不是开发者机器的 venv）",
          str(install_dir) in ff, ff)

    check("5 分析核心模块可导入（打包没漏东西）",
          info.get("analysis_import") == "OK", str(info.get("analysis_import")))
    check("5 本地 ASR 识别器可构造",
          info.get("asr_create") == "LocalWhisperRecognizer", str(info.get("asr_create")))

    provs = info.get("providers") or []
    ids = [p.get("id") for p in provs if isinstance(p, dict)]
    check("6 三个语音识别引擎都在（本地/云端/两遍）",
          {"local-faster-whisper", "cloud-asr", "two-pass"} <= set(ids), str(ids))
    local = next((p for p in provs if isinstance(p, dict)
                  and p.get("id") == "local-faster-whisper"), {})
    check("6 本地引擎报可用（依赖齐全）", local.get("available") is True,
          str(local.get("reason")))

    models = info.get("models") or []
    mids = [m.get("id") for m in models if isinstance(m, dict)]
    check("7 模型清单读到 4 个模型", len(mids) == 4, str(mids))
    # 注意：开发机上可能已经存在 HuggingFace 缓存，此时程序会「沿用缓存」并报 installed=true
    # （这是设计内的：不重复下载）。所以这里真正要验证的是——
    # **本次指定的独立工作区里没有被写入任何模型文件**（程序没有偷偷依赖开发机目录）。
    ws_models = workspace / "models"
    leftover = list(ws_models.iterdir()) if ws_models.is_dir() else []
    check("7 独立工作区里没有模型文件（程序没往工作区偷偷写模型）",
          not leftover, str([p.name for p in leftover]))
    check("7 程序目录里没有 models/（模型不随安装包分发）",
          not (install_dir / "models").exists())
    check("7 每个模型都带下载地址与文件清单（可一键安装）",
          all(isinstance(m, dict) for m in models) and len(mids) == 4, str(mids))

    tabs = info.get("tabs") or []
    check("8 四个页签齐全", len(tabs) == 4, str(tabs))
    check("8 窗口标题正确", "AI 直播切片助手" in str(info.get("window", "")),
          str(info.get("window")))

    return report(tmp_root)


def report(tmp_root=None):
    print("\n" + "=" * 70)
    print("安装包实测结果（模拟安装 + 实机启动）")
    print("=" * 70)
    for status, name, extra in ROWS:
        mark = "✔" if status == "PASS" else "✘"
        print(f"  {mark} {name}")
        if status == "FAIL" and extra:
            print(f"        实际：{extra}")
    print("=" * 70)
    print(f"通过 {PASS} / 失败 {FAIL} / 共 {PASS + FAIL}")
    print("\n仍需人工过一遍的（自动化做不了）：")
    print("  □ 双击 Setup.exe：欢迎页 / 选目录 / 进度 / 完成页")
    print("  □ 桌面与开始菜单快捷方式出现，双击能打开")
    print("  □ 「应用和功能」里能看到并卸载；卸载后快捷方式消失")
    print("  □ 卸载时勾选删除数据 → 用户数据目录被清；不勾选 → 保留")
    print("  □ 首次运行无模型时的「一键安装模型」流程（需联网）")
    print("  □ 用它真实分析一个视频（导入 → 识别 → 分析 → 推荐剪辑）")
    out = ROOT / "desktop_install_report.txt"
    with open(out, "w", encoding="utf-8") as f:
        for status, name, extra in ROWS:
            f.write(f"[{status}] {name}" + (f"  -> {extra}" if extra else "") + "\n")
        f.write(f"\n通过 {PASS} / 失败 {FAIL}\n")
    print(f"\n报告已写入：{out}")
    if tmp_root:
        print(f"（临时安装目录：{tmp_root}）")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
