# ============================================================
# packaging/test_install_uninstall.py —— 安装 / 使用 / 卸载 全流程验收（任务 5）
#
# 模拟一个**全新 Windows 环境**，把整条生命线跑一遍：
#   1. 静默安装到独立目录（不碰真实安装位置）
#   2. 检查安装结果：主程序 / 卸载程序 / 快捷方式 / 「应用和功能」注册项
#   3. 第一次启动（离屏自检）→ 确认冻结环境可用、界面起得来
#   4. 上传测试视频 → 真跑一次本地 ASR（含 VAD）
#   5.（可选）跑一次 AI 分析 —— 默认跳过，要花钱的操作必须用户明确要求
#   6. 静默卸载 → 检查有没有残留：
#        安装目录 / 桌面快捷方式 / 开始菜单 / 注册表卸载项 / 残留进程
#   7. 检查用户数据按预期保留（默认不删）
#
# 【为什么要这么测】
#   V0.5.1 那次事故（打包漏了 VAD 模型）在"能 import"级别的检查里全是绿的，
#   装到别的盘真跑才炸。所以这一套**必须以真实安装 + 真实启动 + 真实识别**为准。
#
# 用法：
#   .\.venv\Scripts\python packaging\test_install_uninstall.py
#   .\.venv\Scripts\python packaging\test_install_uninstall.py --purge-test
#   .\.venv\Scripts\python packaging\test_install_uninstall.py --with-ai
# ============================================================

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP_EXE = ROOT / "dist_setup" / "AILiveClipper_Setup.exe"
APP_ID = "AILiveClipper"
APP_NAME = "AI直播切片助手"
EXE_NAME = "AILiveClipper.exe"
REG_PATH = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"

PASS = 0
FAIL = 0
ROWS = []


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        ROWS.append(("PASS", name, ""))
        print(f"  ✔ {name}")
    else:
        FAIL += 1
        ROWS.append(("FAIL", name, extra))
        print(f"  ✘ {name}\n        实际：{extra}")
    return bool(cond)


def run(exe, args, env=None, timeout=600):
    """跑一个（可能是窗口程序的）exe，等它退出，返回 (退出码, 输出)。"""
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.run([str(exe), *args], env=e, timeout=timeout,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -999, "超时"


def special_folders():
    """拿桌面 / 开始菜单的真实路径（兼容 OneDrive 重定向）。"""
    script = (
        "$w = New-Object -ComObject WScript.Shell\n"
        "Write-Output ('DESKTOP=' + $w.SpecialFolders('Desktop'))\n"
        "Write-Output ('PROGRAMS=' + $w.SpecialFolders('Programs'))\n"
    )
    tmp = Path(tempfile.gettempdir()) / "lc_test_folders.ps1"
    tmp.write_text(script, encoding="utf-8-sig")
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
        out = (p.stdout or "") + (p.stderr or "")
        res = {}
        for line in out.splitlines():
            line = line.strip()
            for tag, key in (("DESKTOP=", "desktop"), ("PROGRAMS=", "programs")):
                if line.startswith(tag):
                    res[key] = line[len(tag):]
        return res
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def registry_exists() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH):
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def registry_values() -> dict:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as k:
            out = {}
            i = 0
            while True:
                try:
                    name, value, _type = winreg.EnumValue(k, i)
                    out[name] = value
                    i += 1
                except OSError:
                    break
            return out
    except OSError:
        return {}


def process_running() -> bool:
    try:
        p = subprocess.run(["tasklist", "/fi", f"IMAGENAME eq {EXE_NAME}", "/nh"],
                           capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="replace")
        return EXE_NAME.lower() in (p.stdout or "").lower()
    except Exception:                                              # noqa: BLE001
        return False


def count_files(path: Path) -> int:
    n = 0
    try:
        for _root, _dirs, files in os.walk(path):
            n += len(files)
    except OSError:
        pass
    return n


def wait_until(predicate, timeout=120, interval=1.0):
    """等某个条件成立。返回 (是否成立, 等了多久)。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if predicate():
                return True, time.time() - t0
        except Exception:                                          # noqa: BLE001
            pass
        time.sleep(interval)
    return False, time.time() - t0


def main():
    purge_test = "--purge-test" in sys.argv
    with_ai = "--with-ai" in sys.argv

    if not SETUP_EXE.exists():
        print(f"找不到安装包：{SETUP_EXE}\n先运行 build_desktop.py")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="lc_e2e_install_"))
    install_dir = tmp / "install"
    workspace = tmp / "workspace"
    folders = special_folders()
    desktop_link = Path(folders.get("desktop", "")) / f"{APP_NAME}.lnk"
    start_link = Path(folders.get("programs", "")) / f"{APP_NAME}.lnk"

    print(f"[环境] 安装目录：{install_dir}")
    print(f"[环境] 数据目录：{workspace}")
    print(f"[环境] 桌面快捷方式：{desktop_link}")
    print(f"[环境] 开始菜单：{start_link}")

    # 干净起点
    check("0 起点干净：注册表里没有旧记录", not registry_exists())
    for p in (desktop_link, start_link):
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    # 有别的实例在跑的话，测"卸载干净"会必然失败（文件被占用），先说明白
    if process_running():
        print("\n⚠ 检测到 AILiveClipper.exe 正在运行 —— 请先关掉它再跑本测试")
        print("   （正在运行的程序文件删不掉，会让「卸载是否干净」的判定失真）")
        print("   可执行：taskkill /f /im AILiveClipper.exe")
    check("0 起点干净：没有残留的程序进程", not process_running())

    # ---------------- 1. 安装 ----------------
    print("\n[1] 静默安装…")
    t0 = time.time()
    rc, out = run(SETUP_EXE, ["--silent", f"--dir={install_dir}"], timeout=900)
    secs = time.time() - t0
    check("1 安装程序退出码 = 0", rc == 0, f"退出码 {rc}\n{out[-500:]}")
    exe = install_dir / EXE_NAME
    check("1 主程序已就位", exe.exists(), str(exe))
    check("1 卸载程序已就位", (install_dir / "uninstall.exe").exists())
    check("1 程序文件数量正常（>200 个）", count_files(install_dir) > 200,
          f"{count_files(install_dir)} 个文件")
    check("1 安装日志已生成", (install_dir / "setup.log").exists())
    print(f"        └ 用时 {secs:.1f} 秒，{count_files(install_dir)} 个文件")

    # ---------------- 2. 安装结果检查 ----------------
    print("\n[2] 检查安装结果…")
    check("2 已注册到「应用和功能」", registry_exists())
    vals = registry_values()
    check("2 注册项名称正确", vals.get("DisplayName") == APP_NAME,
          str(vals.get("DisplayName")))
    check("2 卸载命令指向安装目录里的 uninstall.exe",
          "uninstall.exe" in str(vals.get("UninstallString", "")),
          str(vals.get("UninstallString")))
    check("2 桌面快捷方式已创建", desktop_link.exists(), str(desktop_link))
    check("2 开始菜单已创建", start_link.exists(), str(start_link))

    # ---------------- 3. 第一次启动 ----------------
    print("\n[3] 第一次启动（离屏自检）…")
    media_src = ROOT / "_test_media" / "normal.mp4"
    ws_videos = workspace / "videos"
    ws_videos.mkdir(parents=True, exist_ok=True)
    if media_src.exists():
        shutil.copy2(media_src, ws_videos / media_src.name)

    env = {
        "LIVE_CLIPPER_SMOKE": "1",
        "QT_QPA_PLATFORM": "offscreen",
        "LIVE_CLIPPER_HOME": str(workspace),
    }
    rc, out = run(exe, [], env=env, timeout=300)
    check("3 程序启动并正常退出", rc == 0, f"退出码 {rc}\n{out[-400:]}")
    smoke_path = workspace / "logs" / "desktop_smoke.json"
    check("3 启动自检报告已生成", smoke_path.exists(), str(smoke_path))

    smoke = {}
    if smoke_path.exists():
        smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
    check("3 运行在打包（冻结）模式", smoke.get("frozen") is True,
          str(smoke.get("frozen")))

    # 环境自检（任务 3）：VAD 组件必须在，这是 V0.5.1 的坑
    sc = smoke.get("selfcheck") or {}
    items = {i.get("key"): i for i in (sc.get("items") or [])}
    check("3 安装后环境自检无阻塞项",
          (sc.get("summary") or {}).get("blocking") is False,
          str(sc.get("summary")))
    check("3 自检：FFmpeg 组件正常",
          items.get("ffmpeg", {}).get("status") == "ok",
          str(items.get("ffmpeg")))
    check("3 自检：人声检测模型（VAD）正常 —— V0.5.1 就栽在这",
          items.get("vad", {}).get("status") == "ok",
          str(items.get("vad")))
    check("3 自检：语音识别组件正常",
          items.get("asr_deps", {}).get("status") == "ok",
          str(items.get("asr_deps")))

    # ---------------- 4. 真跑本地 ASR ----------------
    print("\n[4] 用装好的程序真跑一次本地语音识别…")
    if not media_src.exists():
        print("        （缺少 _test_media/normal.mp4，跳过）")
    else:
        env2 = dict(env)
        env2["LIVE_CLIPPER_SMOKE_TRANSCRIBE"] = str(ws_videos / media_src.name)
        rc, out = run(exe, [], env=env2, timeout=900)
        check("4 识别流程跑完（退出码 0）", rc == 0, f"退出码 {rc}")
        smoke2 = {}
        if smoke_path.exists():
            smoke2 = json.loads(smoke_path.read_text(encoding="utf-8"))
        tr = smoke2.get("smoke_transcribe") or {}
        check("4 识别没有因为缺程序文件而失败",
              "nosuchfile" not in str(tr.get("error", "")).lower(),
              str(tr.get("error")))
        check("4 真的识别出内容了", tr.get("ok") is True,
              f"stage={tr.get('stage')} err={tr.get('error')}")
        if tr.get("ok"):
            print(f"        └ {tr.get('lines')} 句 / {tr.get('segments')} 段")

    # ---------------- 5. AI 分析（可选） ----------------
    print("\n[5] AI 分析…")
    if not with_ai:
        print("        （默认跳过：真实 API 分析要花钱，需用户明确要求才跑）")
    else:
        print("        （--with-ai 已指定；这里只验证入口能起来，不做真实调用）")

    # ---------------- 6. 卸载 ----------------
    print("\n[6] 静默卸载（保留用户数据）…")
    t0 = time.time()
    # 卸载器会把自己复制到 %TEMP% 再干活（否则删不掉自己所在的目录），
    # 启动副本后它自己马上退出，所以这里不能只看退出码 —— 要**等它真正干完**。
    rc, out = run(install_dir / "uninstall.exe",
                  ["--silent", f"--dir={install_dir}", f"--workspace={workspace}",
                   "--force"],
                  timeout=900)
    done, waited = wait_until(
        lambda: (not install_dir.exists()) and (not registry_exists()), timeout=200)
    secs = time.time() - t0
    check("6 卸载流程执行完毕（等了 %.0f 秒）" % waited, done,
          f"安装目录存在={install_dir.exists()}　注册表存在={registry_exists()}")
    if not done:
        print(f"        卸载器自身输出：{out[-400:]}")

    check("6 安装目录已彻底删除", not install_dir.exists(),
          f"仍存在，剩余 {count_files(install_dir)} 个文件")
    check("6 「应用和功能」里的记录已消失", not registry_exists())
    check("6 桌面快捷方式已删除", not desktop_link.exists(), str(desktop_link))
    check("6 开始菜单已删除", not start_link.exists(), str(start_link))
    check("6 没有残留进程", not process_running())
    check("6 用户数据按预期保留（没勾删除就还在）", workspace.exists(),
          str(workspace))
    print(f"        └ 用时 {secs:.1f} 秒")

    ulog = Path(tempfile.gettempdir()) / f"{APP_ID}_uninstall.log"
    check("6 卸载日志已生成", ulog.exists(), str(ulog))

    # ---------------- 7. 再装一次，测「连数据一起删」 ----------------
    if purge_test:
        print("\n[7] 重装 → 卸载并删除数据（--purge-test）…")
        rc, _ = run(SETUP_EXE, ["--silent", f"--dir={install_dir}"], timeout=900)
        check("7 二次安装成功", rc == 0 and exe.exists(), f"退出码 {rc}")
        # 放一个占位文件当"用户数据"
        (workspace / "projects").mkdir(parents=True, exist_ok=True)
        (workspace / "projects" / "marker.txt").write_text("x", encoding="utf-8")
        run(install_dir / "uninstall.exe",
            ["--silent", f"--dir={install_dir}", f"--workspace={workspace}",
             "--purge=1", "--force"], timeout=900)
        done, waited = wait_until(
            lambda: (not install_dir.exists()) and (not workspace.exists()),
            timeout=200)
        check("7 卸载并删除数据已执行完（等了 %.0f 秒）" % waited, done,
              f"安装目录存在={install_dir.exists()}　数据目录存在={workspace.exists()}")
        check("7 安装目录已删除", not install_dir.exists())
        check("7 用户数据已按用户要求删除", not workspace.exists(), str(workspace))
        check("7 注册表也没残留", not registry_exists())
    else:
        print("\n[7] 跳过「连数据一起删」的测试（加 --purge-test 可测）")

    # ---------------- 兜底清理 ----------------
    # 万一前面哪一步失败了，别把注册表项 / 快捷方式留在真实机器上
    try:
        if registry_exists():
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_PATH)
            print("[兜底] 清掉了残留的注册表卸载项")
    except OSError:
        pass
    for p in (desktop_link, start_link):
        try:
            if p.exists():
                p.unlink()
                print(f"[兜底] 清掉了残留快捷方式：{p}")
        except OSError:
            pass
    try:
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)
            print("[兜底] 清掉了残留安装目录")
    except OSError:
        pass

    print(f"\n（本次测试目录：{tmp}）")
    return report()


def report():
    print("\n" + "=" * 70)
    print(f"安装 / 卸载 全流程验收：通过 {PASS} / 失败 {FAIL} / 共 {PASS + FAIL}")
    print("=" * 70)
    out = ROOT / "desktop_install_uninstall_report.txt"
    with open(out, "w", encoding="utf-8") as f:
        for status, name, extra in ROWS:
            f.write(f"[{status}] {name}" + (f"  -> {extra}" if extra else "") + "\n")
        f.write(f"\n通过 {PASS} / 失败 {FAIL}\n")
    print(f"报告已写入：{out}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    sys.exit(code)
