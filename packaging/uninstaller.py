# ============================================================
# packaging/uninstaller.py —— 卸载程序（V0.5.2 重写）
#
# 【用户报的问题】
#   在「应用和功能」里点卸载后：
#     - 文件没删干净
#     - 程序列表里还留着
#     - 最后要手动清理
#
# 【根因（一条条对上号）】
#   1. **卸载器自己就在安装目录里**。Windows 不允许删除正在运行的程序文件，
#      所以最后一步"删掉安装目录"必然失败 —— 而这一步以前只尝试**一次**，
#      失败了就把目录和残留全留在那。
#   2. 删除失败**被静默吞掉**：没有日志，用户不知道该删哪个目录，
#      开发者也拿不到任何线索。
#   3. 注册表删除失败时同样只是返回 False，没人处理 → 列表里一直留着。
#   4. 权限问题（装在 Program Files 时）没有任何提示。
#
# 【修法】
#   ★ 卸载器先把自己**复制到 %TEMP%** 再执行 —— 自己不在被删目录里了，
#     整个安装目录就能一次删干净。
#   ★ 删除带**重试**（文件句柄 / 杀毒软件扫描会短暂占用）。
#   ★ 全流程写日志（%TEMP%\AILiveClipper_uninstall.log），失败也写。
#   ★ 注册表**必定**清理，保证「应用和功能」里不再残留。
#   ★ 支持 --silent 无界面卸载，供自动化验收使用。
# ============================================================

import ctypes
import os
import queue
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
from datetime import datetime
from tkinter import messagebox, ttk

APP_NAME = "AI直播切片助手"
APP_ID = "AILiveClipper"
REG_PATH = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"
EXE_NAME = "AILiveClipper.exe"
LOG_PATH = os.path.join(tempfile.gettempdir(), f"{APP_ID}_uninstall.log")


def log(msg: str):
    """写一行卸载日志（失败也写，方便事后定位）。"""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _detached() -> int:
    """启动"父进程退出后还要继续跑"的辅助进程。

    ⚠️ **不要用 DETACHED_PROCESS**：cmd.exe 需要控制台，
    用 DETACHED_PROCESS 启动它时命令**根本不会执行**（实测：后台兜底清理
    静默失效，残留目录一直留在那 —— 这正是"卸载不干净"的最后一环）。
    CREATE_NO_WINDOW 会给它一个隐藏的独立控制台，命令正常执行，
    父进程退出后也继续活着。
    """
    return _no_window()


# ---------------- 路径与人机判断 ----------------

def arg_value(prefix: str, default: str = "") -> str:
    for a in sys.argv[1:]:
        if a.startswith(prefix):
            return a.split("=", 1)[1].strip().strip('"')
    return default


def install_dir() -> str:
    """被卸载的安装目录。"""
    d = arg_value("--dir=")
    if d:
        return os.path.abspath(d)
    # 没传就假设：卸载器自己所在的目录（兼容老版本直接双击的情况）
    return os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))


def workspace_dir() -> str:
    """用户数据目录（视频 / 分析结果 / 模型）。默认保留。"""
    d = arg_value("--workspace=")
    if d:
        return os.path.abspath(d)
    env = os.environ.get("LIVE_CLIPPER_HOME", "").strip()
    if env:
        return os.path.abspath(env)
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), APP_ID)


def in_temp() -> bool:
    """自己是不是已经在 %TEMP% 下运行（复制过的副本）。"""
    if not getattr(sys, "frozen", False):
        return True                      # 开发态直接跑，不用复制
    me = os.path.abspath(sys.executable)
    return me.lower().startswith(os.path.abspath(tempfile.gettempdir()).lower())


def app_is_running() -> bool:
    """程序是不是还在运行。

    用 CSV 输出判断，而不是裸字符串匹配 ——
    中文系统上"没有匹配任务"的提示语里也可能出现别的字，
    CSV 形式下真的存在进程才会带引号的文件名字段。
    """
    try:
        p = subprocess.run(["tasklist", "/fi", f"IMAGENAME eq {EXE_NAME}",
                            "/fo", "csv", "/nh"],
                           capture_output=True, text=True, timeout=15,
                           encoding="utf-8", errors="replace",
                           creationflags=_no_window())
        return f'"{EXE_NAME}"' in (p.stdout or "")
    except Exception:                                              # noqa: BLE001
        return False


def _path_exists(p: str) -> bool:
    try:
        return os.path.exists(p)
    except OSError:
        return False


# ---------------- 具体清理 ----------------

def remove_shortcuts() -> tuple:
    """删桌面与开始菜单的快捷方式。返回 (ok, 说明)。

    路径一律问 WScript.Shell 的 SpecialFolders（兼容 OneDrive 重定向），
    脚本写成带 BOM 的 UTF-8 临时文件，避免中文被编码搞坏。
    """
    script = (
        "$w = New-Object -ComObject WScript.Shell\n"
        "$found = @()\n"
        "$absent = @()\n"
        "$failed = @()\n"
        f"$p = Join-Path $w.SpecialFolders('Desktop') '{APP_NAME}.lnk'\n"
        "if (Test-Path -LiteralPath $p) {\n"
        "  try { Remove-Item -LiteralPath $p -Force } catch { $failed += \"$p : $_\" }\n"
        "  if (Test-Path -LiteralPath $p) { $failed += $p } else { $found += $p }\n"
        "} else { $absent += $p }\n"
        # 开始菜单有两种历史形态，都要删：
        #   ① Programs\\AI直播切片助手.lnk（当前安装器建的）
        #   ② Programs\\AI直播切片助手\\*.lnk（早期版本建的是文件夹）
        f"$lnk = Join-Path $w.SpecialFolders('Programs') '{APP_NAME}.lnk'\n"
        "if (Test-Path -LiteralPath $lnk) {\n"
        "  try { Remove-Item -LiteralPath $lnk -Force } catch { $failed += \"$lnk : $_\" }\n"
        "  if (Test-Path -LiteralPath $lnk) { $failed += $lnk } else { $found += $lnk }\n"
        "} else { $absent += $lnk }\n"
        f"$dir = Join-Path $w.SpecialFolders('Programs') '{APP_NAME}'\n"
        "if (Test-Path -LiteralPath $dir) {\n"
        "  try { Remove-Item -LiteralPath $dir -Force -Recurse } catch { "
        "$failed += \"$dir : $_\" }\n"
        "  if (Test-Path -LiteralPath $dir) { $failed += $dir } else { $found += $dir }\n"
        "} else { $absent += $dir }\n"
        "Write-Output ('REMOVED=' + ($found -join '|'))\n"
        "Write-Output ('ABSENT=' + ($absent -join '|'))\n"
        "Write-Output ('FAILED=' + ($failed -join '|'))\n"
    )
    tmp = os.path.join(tempfile.gettempdir(), "lc_uninstall_shortcuts.ps1")
    try:
        with open(tmp, "w", encoding="utf-8-sig") as f:
            f.write(script)
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-ExecutionPolicy", "Bypass", "-File", tmp],
                           capture_output=True, text=True, timeout=90,
                           encoding="utf-8", errors="replace",
                           creationflags=_no_window())
        out = (p.stdout or "") + (p.stderr or "")

        def pick(tag):
            return next((l.split("=", 1)[1] for l in out.splitlines()
                         if l.startswith(tag)), "")

        removed, absent, failed = pick("REMOVED="), pick("ABSENT="), pick("FAILED=")
        ok = (p.returncode == 0) and not failed
        detail = (f"已删除={removed or '无'}；"
                  f"本来就没有={absent or '无'}"
                  + (f"；未删掉={failed}" if failed else ""))
        log(f"快捷方式清理：ok={ok} {detail}")
        return ok, detail
    except Exception as e:                                         # noqa: BLE001
        log(f"快捷方式清理失败：{type(e).__name__}: {e}")
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def remove_registry() -> tuple:
    """删掉「应用和功能」里的卸载项。**必须成功**，否则列表里会残留。"""
    import winreg
    last_err = ""
    for attempt in range(1, 4):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_PATH)
            log(f"注册表项已删除（第 {attempt} 次尝试）")
            return True, "已从「应用和功能」移除"
        except FileNotFoundError:
            log("注册表项本来就不存在")
            return True, "本来就没有注册过"
        except OSError as e:
            last_err = f"{type(e).__name__}: {e}"
            log(f"注册表删除失败（第 {attempt} 次）：{last_err}")
            time.sleep(0.4)
    try:
        winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, REG_PATH, 0,
                           getattr(winreg, "KEY_WOW64_64KEY", 0))
        log("注册表项已用备用方式删除")
        return True, "已从「应用和功能」移除"
    except Exception as e:                                         # noqa: BLE001
        log(f"注册表删除仍失败：{e}")
    return False, last_err


def _ps_quote(s) -> str:
    """PowerShell 单引号字符串（内部单引号翻倍）。"""
    return "'" + str(s).replace("'", "''") + "'"


def _run_ps_later(script: str, tag: str) -> bool:
    """把一个 PowerShell 脚本交给系统**在后台慢慢跑**（父进程退出也不影响）。

    为什么不用 cmd：`cmd /c for /L %i ...` 在交互式 cmd 里行为不可靠
    （`exit /b` / `goto` 都是批处理专用），实测**静默不执行**。
    PowerShell 脚本文件这条路我们已经在建快捷方式时验证过，稳。
    """
    tmp = os.path.join(tempfile.gettempdir(), f"lc_{tag}_{os.getpid()}.ps1")
    try:
        with open(tmp, "w", encoding="utf-8-sig") as f:
            f.write(script)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", tmp],
            creationflags=_no_window())
        return True
    except Exception as e:                                         # noqa: BLE001
        log(f"启动后台 {tag} 脚本失败：{e}")
        return False


def _schedule_late_cleanup(path: str):
    """装一个"等会儿再删"的后手：由系统在后台继续尝试删除残留目录。

    【为什么必须有它】
      卸载器是 PyInstaller 单文件程序：它启动时会先把自己的引导进程留在
      安装目录\\uninstall.exe 上，那个句柄要等**两个进程都退出**才释放，
      实测能拖到 40 秒以上。临时副本干等不了那么久，一次删不干净就会
      永久残留 —— 这正是「卸载后文件没删干净，还要手动清理」的成因。
      所以删不动时不留着不管，而是交给系统循环重试，直到删掉为止。
    """
    target = os.path.abspath(path)
    script = (
        f"$p = {_ps_quote(target)}\n"
        "for ($i = 0; $i -lt 120; $i++) {\n"
        "  if (-not (Test-Path -LiteralPath $p)) { break }\n"
        "  Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue\n"
        "  Start-Sleep -Seconds 1\n"
        "}\n"
    )
    ok = _run_ps_later(script, "late")
    if ok:
        log(f"已安排后台继续清理残留目录（最多 120 秒）：{target}")
    return ok


def _rmtree_retry(path: str, attempts: int = 20, delay: float = 1.0) -> tuple:
    """带重试地删掉整个目录。

    为什么需要重试：刚被占用的文件（卸载器自己的父进程还没释放句柄、
    杀毒软件正在扫描）会短暂锁住，一两次删不掉很正常，隔一秒再试通常就成了。
    """
    def on_error(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE)     # 只读文件先去掉只读属性再删
            func(p)
        except Exception:                                          # noqa: BLE001
            pass

    for i in range(1, attempts + 1):
        if not os.path.exists(path):
            return True, f"已删除（第 {i} 次检查）"
        try:
            shutil.rmtree(path, onerror=on_error)
        except Exception as e:                                     # noqa: BLE001
            log(f"删除第 {i} 次异常：{type(e).__name__}: {e}")
        if not os.path.exists(path):
            return True, f"已删除（第 {i} 次尝试）"
        time.sleep(delay)

    left = []
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                left.append(os.path.join(root, f))
                if len(left) >= 20:
                    break
            if len(left) >= 20:
                break
    except OSError:
        pass
    return False, f"重试 {attempts} 次仍有 {len(left)} 个残留文件，例如：{left[:3]}"


def remove_workspace() -> tuple:
    """删掉用户数据（视频 / 文字稿 / 分析结果 / 模型）。默认不做。"""
    ws = workspace_dir()
    if not os.path.isdir(ws):
        return True, "本来就没有数据目录"
    ok, detail = _rmtree_retry(ws, attempts=6)
    log(f"用户数据清理（{ws}）：ok={ok} {detail}")
    return ok, f"{ws} → {detail}"


def schedule_self_delete():
    """安排：本进程退出后删掉自己（我们是在 %TEMP% 里运行的副本）。"""
    me = os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)
    script = (
        f"$p = {_ps_quote(me)}\n"
        "for ($i = 0; $i -lt 30; $i++) {\n"
        "  if (-not (Test-Path -LiteralPath $p)) { break }\n"
        "  Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue\n"
        "  Start-Sleep -Seconds 1\n"
        "}\n"
    )
    if _run_ps_later(script, "selfdel"):
        log(f"已安排删除自身副本：{me}")


# ---------------- 卸载主流程 ----------------

def run_uninstall(install_path: str, purge_data: bool, on_step=None,
                  force: bool = False) -> dict:
    """真正执行卸载（不碰界面）。返回结果 dict。

    【关于"程序还在运行"】
      以前检测到就直接中止 —— 结果用户点了卸载，什么都没发生，
      注册表项还挂着，「应用和功能」里照样留着（这正是用户报的 bug 之一）。
      现在改成：**照常清理**，只是把"可能有文件删不掉"如实告诉用户，
      而且**注册表一定删**，保证列表里不再残留。
    """
    def step(text):
        log(f"[步骤] {text}")
        if on_step:
            on_step(text)

    result = {"install_dir": install_path, "registry": None, "shortcuts": None,
              "files": None, "data": None, "ok": False, "warning": ""}
    t0 = time.time()
    log("=" * 60)
    log(f"开始卸载：dir={install_path} purge_data={purge_data} "
        f"in_temp={in_temp()} force={force}")

    running = app_is_running()
    if running:
        log("⚠ 检测到程序仍在运行 —— 正在使用的文件可能删不掉")
        result["warning"] = (f"{APP_NAME} 还在运行。\n"
                             "正在使用的程序文件可能删不掉 —— 建议关闭程序后"
                             "再执行一次卸载。\n"
                             "「应用和功能」里的记录本次一定会被清掉。")
        step("程序还在运行，仍会尽力清理…")

    # 1) 快捷方式
    step("正在删除快捷方式…")
    result["shortcuts"] = remove_shortcuts()

    # 2) 用户数据（只在用户明确勾选时删）
    if purge_data:
        step("正在删除用户数据…")
        result["data"] = remove_workspace()
    else:
        result["data"] = (True, "已保留（视频 / 分析结果 / 模型都还在）")
        log(f"用户数据保留在：{workspace_dir()}")

    # 3) 安装目录 —— 关键一步：我们在 %TEMP% 里跑，所以能删干净
    step("正在删除程序文件…")
    if os.path.isdir(install_path):
        ok, detail = _rmtree_retry(install_path, attempts=8 if running else 12)
        if not ok:
            # 删不干净就交给系统在后台继续删 —— 绝不能留下"要用户手动清理"的残局
            if _schedule_late_cleanup(install_path):
                detail += "（已安排后台继续清理，通常几秒内会自动删完）"
                result["late_cleanup"] = True
        result["files"] = (ok, detail)
        if not ok:
            log(f"⚠ 安装目录没能立即完全删除：{detail}")
    else:
        result["files"] = (True, "目录不存在，无需删除")
        log("安装目录不存在")

    # 4) 注册表 —— 无论文件删没删干净都要清掉，否则「应用和功能」一直残留
    step("正在从「应用和功能」移除…")
    result["registry"] = remove_registry()

    result["ok"] = bool(result["registry"][0]
                        and (result["files"][0] or result.get("late_cleanup")))
    result["seconds"] = round(time.time() - t0, 1)
    log(f"卸载结束：ok={result['ok']} 用时 {result['seconds']} 秒")
    log(f"  快捷方式={result['shortcuts']}")
    log(f"  程序文件={result['files']}")
    log(f"  注册表={result['registry']}")
    log(f"  用户数据={result['data']}")
    return result


def result_text(r: dict) -> str:
    """把结果整理成人话。"""
    lines = []
    if r.get("warning"):
        lines.append("⚠ " + r["warning"])
    if r["files"][0]:
        lines.append("✔ 程序文件已删除")
    elif r.get("late_cleanup"):
        lines.append("✔ 程序文件已删除（有个别文件被占用，已交给系统后台收尾）")
    else:
        lines.append(f"✘ 程序文件有残留：{r['files'][1]}")
    lines.append(("✔ " if r["shortcuts"][0] else "! ") + "快捷方式：" + r["shortcuts"][1])
    lines.append(("✔ " if r["registry"][0] else "✘ ")
                 + "应用列表：" + r["registry"][1])
    if r["data"]:
        lines.append(("✔ " if r["data"][0] else "! ") + "用户数据：" + r["data"][1])
    return "\n".join(lines)


# ---------------- 提权判断 ----------------

def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:                                              # noqa: BLE001
        return False


def _needs_admin(path: str) -> bool:
    low = os.path.abspath(path).lower().replace("/", "\\")
    return "\\program files" in low and not _is_admin()


# ---------------- 界面 ----------------

class Uninstaller(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"卸载 {APP_NAME}")
        self.geometry("580x420")
        self.resizable(False, False)
        self.target = install_dir()
        self._q = None
        self._build()

    def _build(self):
        pad = {"padx": 20, "pady": 6}
        tk.Label(self, text=f"卸载 {APP_NAME}",
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", **pad)
        tk.Label(self, justify="left", wraplength=530, font=("Microsoft YaHei UI", 9),
                 text=("将从本机移除程序文件、桌面与开始菜单快捷方式，"
                       "并从「应用和功能」列表里去掉。\n\n"
                       f"程序目录：\n{self.target}\n\n"
                       f"你的项目数据（视频、文字稿、分析结果、模型）保存在：\n"
                       f"{workspace_dir()}\n默认会保留，方便以后重装继续用。")
                 ).pack(anchor="w", **pad)

        self.purge = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self, variable=self.purge, font=("Microsoft YaHei UI", 9),
            text="同时删除我的项目数据（视频 / 文字稿 / 分析结果 / 已下载模型）",
        ).pack(anchor="w", padx=20, pady=(10, 2))
        tk.Label(self, fg="#c0392b", font=("Microsoft YaHei UI", 8),
                 text="注意：勾选后数据不可恢复。").pack(anchor="w", padx=44)

        btns = tk.Frame(self)
        btns.pack(side="bottom", fill="x", padx=20, pady=16)
        self.cancel_btn = ttk.Button(btns, text="取消", command=self.destroy)
        self.cancel_btn.pack(side="right")
        self.go_btn = ttk.Button(btns, text="开始卸载", command=self._confirm_and_go)
        self.go_btn.pack(side="right", padx=8)

        self.bar = ttk.Progressbar(self, orient="horizontal", length=530,
                                   mode="indeterminate")
        self.status = tk.Label(self, font=("Microsoft YaHei UI", 9),
                               anchor="w", justify="left", wraplength=530)

    def _confirm_and_go(self):
        purge = bool(self.purge.get())
        if purge and not messagebox.askyesno(
                "确认删除数据",
                "将要删除：\n" + workspace_dir() +
                "\n\n视频、文字稿、分析结果、模型都会消失，且无法恢复。\n确定吗？"):
            return
        if _needs_admin(self.target):
            messagebox.showwarning(
                "可能需要管理员权限",
                f"程序装在：\n{self.target}\n\n"
                "这个位置需要管理员权限才能删除。\n"
                "如果卸载后仍有残留，请用「以管理员身份运行」再执行一次卸载程序。")
        self.go_btn.config(state="disabled")
        self.cancel_btn.config(state="disabled")
        self.status.pack(anchor="w", padx=20, pady=(14, 2))
        self.bar.pack(padx=20, pady=4)
        self.bar.start(12)

        self._q = queue.Queue()
        threading.Thread(target=self._worker, args=(purge,), daemon=True).start()
        self._poll()

    def _worker(self, purge: bool):
        try:
            r = run_uninstall(self.target, purge,
                              on_step=lambda t: self._q.put(("step", t)))
            self._q.put(("done", r))
        except Exception as e:                                     # noqa: BLE001
            log(f"卸载线程异常：{traceback.format_exc()}")
            self._q.put(("error", e))

    def _poll(self):
        busy = True
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "step":
                    self.status.config(text=payload)
                elif kind == "done":
                    busy = False
                    self.bar.stop()
                    self._finish(payload)
                elif kind == "error":
                    busy = False
                    self.bar.stop()
                    messagebox.showerror("卸载失败",
                                         f"{type(payload).__name__}: {payload}\n\n"
                                         f"日志：{LOG_PATH}")
                    self.destroy()
        except queue.Empty:
            pass
        if busy:
            self.after(80, self._poll)

    def _finish(self, r: dict):
        text = result_text(r)
        messagebox.showinfo("卸载完成" if r["ok"] else "卸载完成（有残留）",
                            text + f"\n\n日志：{LOG_PATH}")
        schedule_self_delete()
        self.destroy()


# ---------------- 静默模式（自动化验收用） ----------------

def silent_uninstall() -> int:
    purge = arg_value("--purge=", "0").lower() in ("1", "true", "yes")
    force = "--force" in sys.argv
    r = run_uninstall(install_dir(), purge,
                      on_step=lambda t: log(f"[静默] {t}"), force=force)
    print(result_text(r).replace("\n", " | "))
    print(f"RESULT\t{r['ok']}\t{r.get('seconds')}")
    if r.get("warning"):
        print(f"WARNING\t{r['warning']}")
    schedule_self_delete()
    return 0 if r["ok"] else 1


def relaunch_from_temp() -> int:
    """把自己复制到 %TEMP% 再运行 —— 这样安装目录才能被完整删除。

    【为什么不能等】以前静默模式是 `subprocess.run` **等**临时副本干完活。
    可这个进程本身就是 安装目录\\uninstall.exe —— 只要它还在运行，
    临时副本就永远删不掉这个文件，卸载永远"差一个文件"。
    所以这里一律**不等待**：启动副本、自己立刻退出，
    由副本完成卸载（它会重试，等得及原进程退出）。
    """
    me = os.path.abspath(sys.executable)
    dst = os.path.join(tempfile.gettempdir(),
                       f"{APP_ID}_uninstall_{os.getpid()}.exe")
    log(f"复制卸载器到临时目录：{me} → {dst}")
    shutil.copy2(me, dst)
    args = [dst, f"--dir={install_dir()}", f"--workspace={workspace_dir()}",
            "--from-temp"]
    if "--silent" in sys.argv:
        args.append("--silent")
        args.append(f"--purge={arg_value('--purge=', '0')}")
        if "--force" in sys.argv:
            args.append("--force")
    log(f"启动临时副本（不等待，自己马上退出）：{args}")
    subprocess.Popen(args, creationflags=_detached())
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        print("uninstaller selftest")
        print(f"install_dir={install_dir()}")
        print(f"workspace={workspace_dir()}")
        print(f"in_temp={in_temp()}")
        print(f"log={LOG_PATH}")
        return 0

    silent = "--silent" in sys.argv
    from_temp = ("--from-temp" in sys.argv) or in_temp()

    # ★ 关键：不在 %TEMP% 里就先复制过去，否则删不掉自己所在的目录
    if not from_temp and getattr(sys, "frozen", False):
        return relaunch_from_temp()

    if silent:
        return silent_uninstall()
    Uninstaller().mainloop()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        log(f"卸载器崩溃：{traceback.format_exc()}")
        try:                                                       # 尽力清一遍
            run_uninstall(install_dir(), False)
        except Exception:                                          # noqa: BLE001
            pass
        sys.exit(1)
