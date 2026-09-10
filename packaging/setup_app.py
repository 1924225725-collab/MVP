# ============================================================
# packaging/setup_app.py —— 安装程序（最终产出：AI直播切片助手_Setup.exe）
#
# 【一次双击就装完】标准 Windows 安装流程：
#   欢迎 → 选安装位置 → 拷贝文件 → 建快捷方式 → 注册到「应用和功能」 → 完成
#
# 【为什么不需要管理员】默认装到 %LOCALAPPDATA%\Programs\，
#   注册表只写 HKCU —— 全程不触发 UAC，用户点两下就装好。
#
# 【模型不打包】语音识别模型几百 MB 且可换，**不随安装包分发**；
#   程序首次运行时会检测并引导下载到用户数据目录（见 models_registry.json）。
#
# 【载荷形态】payload.zip（LZMA 压缩）在构建时塞进 exe，
#   安装时解压到目标目录 —— 比直接内嵌上万个散文件小得多、也快得多。
# ============================================================

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
import zipfile
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

APP_NAME = "AI直播切片助手"
APP_ID = "AILiveClipper"
APP_VERSION = "0.5.0"
APP_EXE = "AILiveClipper.exe"
PUBLISHER = "AI 直播切片助手"
REG_PATH = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"

PAYLOAD_DIR_NAME = "AILiveClipper"          # payload.zip 解压后的顶层目录名


def _meipass() -> str:
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def payload_zip() -> str:
    return os.path.join(_meipass(), "payload.zip")


def default_install_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"),
                                                          "AppData", "Local")
    return os.path.join(base, "Programs", APP_ID)


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def app_is_running() -> bool:
    try:
        p = subprocess.run(["tasklist", "/fi", f"IMAGENAME eq {APP_EXE}", "/nh"],
                           capture_output=True, text=True, timeout=15,
                           encoding="utf-8", errors="replace",
                           creationflags=_no_window())
        return APP_EXE.lower() in (p.stdout or "").lower()
    except Exception:                                              # noqa: BLE001
        return False


# ---------------- 注册表 / 快捷方式 ----------------

def write_registry(install_dir: str, size_kb: int):
    import winreg
    exe = os.path.join(install_dir, APP_EXE)
    unins = os.path.join(install_dir, "uninstall.exe")
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PATH)
    vals = {
        "DisplayName": APP_NAME,
        "DisplayVersion": APP_VERSION,
        "Publisher": PUBLISHER,
        "InstallLocation": install_dir,
        "DisplayIcon": f"{exe},0",
        "UninstallString": f'"{unins}"',
        "QuietUninstallString": f'"{unins}"',
        "InstallDate": datetime.now().strftime("%Y%m%d"),
        "EstimatedSize": int(size_kb),
    }
    with key:
        for k, v in vals.items():
            winreg.SetValueEx(key, k, 0,
                              winreg.REG_DWORD if k == "EstimatedSize" else winreg.REG_SZ,
                              v)
        for k in ("NoModify", "NoRepair"):
            winreg.SetValueEx(key, k, 0, winreg.REG_DWORD, 1)


def make_shortcuts(install_dir: str, desktop: bool, start_menu: bool) -> dict:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from shortcuts import create_shortcut, special_folders
    except ImportError:
        return {"desktop": (False, "缺少 shortcuts 模块"),
                "start_menu": (False, "缺少 shortcuts 模块")}
    exe = os.path.join(install_dir, APP_EXE)
    folders = special_folders()
    res = {"desktop": (False, "未勾选"), "start_menu": (False, "未勾选")}
    if desktop and folders.get("desktop"):
        res["desktop"] = create_shortcut(
            os.path.join(folders["desktop"], f"{APP_NAME}.lnk"), exe, install_dir,
            description=APP_NAME)
    if start_menu and folders.get("programs"):
        res["start_menu"] = create_shortcut(
            os.path.join(folders["programs"], f"{APP_NAME}.lnk"), exe, install_dir,
            description=APP_NAME)
    return res


# ---------------- 解压（带进度） ----------------

def extract_payload(target: str, on_progress):
    """把 payload.zip 解到 target。on_progress(done, total, name)。"""
    src = payload_zip()
    if not os.path.exists(src):
        raise FileNotFoundError(f"安装载荷缺失：{src}")
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        total = len(names)
        for i, name in enumerate(names, 1):
            z.extract(name, target)
            if i % 5 == 0 or i == total:
                on_progress(i, total, os.path.basename(name))
    return target


def flatten_if_wrapped(target: str):
    """如果解压出来外面多套了一层 AILiveClipper/，把它提上来。"""
    inner = os.path.join(target, PAYLOAD_DIR_NAME)
    if os.path.isdir(inner) and not os.path.exists(os.path.join(target, APP_EXE)):
        for item in os.listdir(inner):
            shutil.move(os.path.join(inner, item), os.path.join(target, item))
        os.rmdir(inner)


# ---------------- 界面 ----------------

class Setup(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} 安装程序")
        self.geometry("620x420")
        self.resizable(False, False)
        self.target = tk.StringVar(value=default_install_dir())
        self.with_desktop = tk.BooleanVar(value=True)
        self.with_start = tk.BooleanVar(value=True)
        self.with_launch = tk.BooleanVar(value=True)
        self._build_welcome()

    # ---- 第 1 屏 ----
    def _build_welcome(self):
        self._clear()
        pad = {"padx": 22, "pady": 6}
        tk.Label(self, text=f"安装 {APP_NAME}", font=("Microsoft YaHei UI", 15, "bold")
                 ).pack(anchor="w", **pad)
        tk.Label(self, justify="left", font=("Microsoft YaHei UI", 9), wraplength=560,
                 text=(f"版本 {APP_VERSION}　·　本地语音识别 + AI 内容理解\n\n"
                       "装好后：桌面会出现快捷方式，双击即用，不需要 Python、"
                       "不需要命令行、不需要浏览器。\n"
                       "语音识别完全在本机完成，视频不会上传。")
                 ).pack(anchor="w", **pad)

        box = tk.LabelFrame(self, text="安装位置", font=("Microsoft YaHei UI", 9),
                            padx=10, pady=8)
        box.pack(fill="x", padx=22, pady=8)
        row = tk.Frame(box)
        row.pack(fill="x")
        tk.Entry(row, textvariable=self.target, font=("Microsoft YaHei UI", 9)
                 ).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self._browse).pack(side="left", padx=6)
        tk.Label(box, fg="#6b7686", font=("Microsoft YaHei UI", 8), justify="left",
                 text="默认装在当前用户目录下，不需要管理员权限；"
                      "你的项目和模型数据不放在这里，卸载程序不会删。"
                 ).pack(anchor="w", pady=(6, 0))

        opt = tk.LabelFrame(self, text="快捷方式", font=("Microsoft YaHei UI", 9),
                            padx=10, pady=6)
        opt.pack(fill="x", padx=22)
        tk.Checkbutton(opt, variable=self.with_desktop, text="创建桌面快捷方式",
                       font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        tk.Checkbutton(opt, variable=self.with_start, text="创建开始菜单快捷方式",
                       font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        btns = tk.Frame(self)
        btns.pack(side="bottom", fill="x", padx=22, pady=16)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="开始安装", command=self._start).pack(side="right", padx=8)

    def _browse(self):
        d = filedialog.askdirectory(title="选择安装位置",
                                    initialdir=os.path.dirname(self.target.get()))
        if d:
            self.target.set(os.path.join(d, APP_ID))

    # ---- 第 2 屏 ----
    def _start(self):
        target = self.target.get().strip()
        if not target:
            messagebox.showwarning("请选择安装位置", "安装位置不能为空。")
            return
        if app_is_running():
            messagebox.showwarning(
                "程序正在运行",
                f"{APP_NAME} 现在正在运行。\n请先关掉它再安装。")
            return
        low = target.lower().replace("/", "\\")
        if "\\program files" in low and not _is_admin():
            if not messagebox.askyesno(
                    "这里需要管理员权限",
                    "Program Files 需要管理员权限才能写入，当前不是管理员。\n\n"
                    "建议改回默认位置（当前用户目录）。\n仍要继续吗？"):
                return
        if os.path.isdir(target) and os.listdir(target):
            if not messagebox.askyesno(
                    "目录已有内容",
                    f"{target}\n\n这个目录不是空的，同名文件会被覆盖。继续吗？"):
                return
        self._build_progress()
        self.after(120, lambda: self._install(target))

    def _build_progress(self):
        self._clear()
        pad = {"padx": 22, "pady": 6}
        tk.Label(self, text="正在安装…", font=("Microsoft YaHei UI", 15, "bold")
                 ).pack(anchor="w", **pad)
        self.step_label = tk.Label(self, font=("Microsoft YaHei UI", 9),
                                   text="准备解压程序文件…", anchor="w", justify="left",
                                   wraplength=560)
        self.step_label.pack(anchor="w", fill="x", **pad)
        self.bar = ttk.Progressbar(self, orient="horizontal", length=560, mode="determinate")
        self.bar.pack(padx=22, pady=6)
        self.detail = tk.Label(self, fg="#6b7686", font=("Microsoft YaHei UI", 8),
                               text="", anchor="w")
        self.detail.pack(anchor="w", fill="x", padx=22)

    # ---- 实际安装 ----
    def _install(self, target):
        try:
            def on_progress(done, total, name):
                self.bar["maximum"] = total
                self.bar["value"] = done
                self.detail.config(text=f"{done}/{total}　{name}")
                self.update_idletasks()

            self.step_label.config(text="正在解压程序文件…")
            extract_payload(target, on_progress)
            flatten_if_wrapped(target)

            self.step_label.config(text="正在创建快捷方式…")
            self.update_idletasks()
            sc = make_shortcuts(target, self.with_desktop.get(), self.with_start.get())

            self.step_label.config(text="正在注册到「应用和功能」…")
            self.update_idletasks()
            size_kb = _dir_size_kb(target)
            write_registry(target, size_kb)

            # 安装信息（程序里的开发者视图会读它）
            try:
                with open(os.path.join(target, "install_info.json"), "w",
                          encoding="utf-8") as f:
                    json.dump({
                        "app": APP_NAME, "app_id": APP_ID, "version": APP_VERSION,
                        "installed_at": datetime.now().isoformat(timespec="seconds"),
                        "install_dir": target,
                        "shortcuts": {k: list(v) for k, v in sc.items()},
                    }, f, ensure_ascii=False, indent=2)
            except OSError:
                pass

            self._build_done(target, sc)
        except Exception as e:                                     # noqa: BLE001
            messagebox.showerror("安装失败", f"{type(e).__name__}: {e}\n\n"
                                            f"目标目录：{target}")
            self.destroy()

    # ---- 第 3 屏 ----
    def _build_done(self, target, sc):
        self._clear()
        pad = {"padx": 22, "pady": 6}
        tk.Label(self, text="安装完成", font=("Microsoft YaHei UI", 15, "bold")
                 ).pack(anchor="w", **pad)
        lines = [f"程序已装到：{target}", ""]
        lines.append("桌面快捷方式：" + ("已创建" if sc["desktop"][0] else
                                        ("未创建（" + sc["desktop"][1] + "）"
                                         if self.with_desktop.get() else "未勾选")))
        lines.append("开始菜单：" + ("已创建" if sc["start_menu"][0] else
                                    ("未创建（" + sc["start_menu"][1] + "）"
                                     if self.with_start.get() else "未勾选")))
        lines += ["", "首次启动会提示下载语音识别模型（约 464 MB，只需一次，之后完全离线）。"]
        tk.Label(self, justify="left", font=("Microsoft YaHei UI", 9), wraplength=560,
                 text="\n".join(lines)).pack(anchor="w", **pad)

        tk.Checkbutton(self, variable=self.with_launch, text=f"立即启动 {APP_NAME}",
                       font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=22, pady=8)

        btns = tk.Frame(self)
        btns.pack(side="bottom", fill="x", padx=22, pady=16)
        ttk.Button(btns, text="完成", command=lambda: self._finish(target)
                   ).pack(side="right")

    def _finish(self, target):
        if self.with_launch.get():
            exe = os.path.join(target, APP_EXE)
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe], cwd=target, creationflags=_no_window())
                except Exception:                                  # noqa: BLE001
                    pass
        self.destroy()

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()


def _is_admin() -> bool:
    try:
        return bool(ctypes_is_admin())
    except Exception:                                              # noqa: BLE001
        return False


def ctypes_is_admin() -> bool:
    import ctypes
    return ctypes.windll.shell32.IsUserAnAdmin() != 0


def _dir_size_kb(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total // 1024


def _setup_selftest() -> int:
    """无界面自检：确认安装载荷确实被塞进了 exe，且能解出主程序。

    给自动化验收用（GUI 没法在无人值守环境里点）：
        AILiveClipper_Setup.exe --selftest
    结果写到 %TEMP%\\lc_setup_selftest.json，退出码 0 = 通过。
    """
    info = {"argv": sys.argv[1:], "frozen": bool(getattr(sys, "frozen", False))}
    try:
        info["payload_zip"] = payload_zip()
        info["payload_mb"] = round(os.path.getsize(payload_zip()) / 1024 / 1024, 1)
        with zipfile.ZipFile(payload_zip()) as z:
            names = z.namelist()
            bad = z.testzip()
        info["payload_entries"] = len(names)
        info["has_exe"] = any(n.replace("\\", "/").endswith(APP_EXE) for n in names)
        info["has_uninstall"] = any(n.replace("\\", "/").endswith("uninstall.exe")
                                    for n in names)
        info["has_ffmpeg"] = any("imageio_ffmpeg/binaries/ffmpeg-" in n.replace("\\", "/")
                                 for n in names)
        info["zip_integrity"] = "OK" if bad is None else f"损坏条目：{bad}"
        info["default_install_dir"] = default_install_dir()
        info["payload_top"] = sorted({n.split("/")[0] for n in names})[:5]
    except Exception as e:                                          # noqa: BLE001
        info["error"] = f"{type(e).__name__}: {e}"

    ok = (not info.get("error") and info.get("has_exe")
          and info.get("zip_integrity") == "OK")
    info["result"] = "PASS" if ok else "FAIL"
    out = os.path.join(tempfile.gettempdir(), "lc_setup_selftest.json")
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_setup_selftest())
    Setup().mainloop()
