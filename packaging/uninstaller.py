# ============================================================
# packaging/uninstaller.py —— 卸载程序（被安装器放进安装目录）
#
# 打包成 uninstall.exe，注册到「应用和功能」里。
#
# 【做得干净也做得讲理】
#   程序文件   → 删
#   快捷方式   → 删
#   注册表项   → 删
#   用户数据   → **默认保留**（视频/文字稿/分析结果都在 %LOCALAPPDATA%\AILiveClipper）
#                想一起删，要在界面上主动勾选（不可逆，二次确认）
# ============================================================

import ctypes
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

APP_NAME = "AI直播切片助手"
APP_ID = "AILiveClipper"
REG_PATH = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}"

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False)
                                     else __file__))
INSTALL_DIR = HERE
WORKSPACE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), APP_ID)


# ---------------- 具体清理动作 ----------------

def remove_shortcuts():
    """删快捷方式（复用安装器里那套 PowerShell 逻辑，独立一份，卸载器可单独打包）。"""
    import tempfile
    script = (
        "$w = New-Object -ComObject WScript.Shell\n"
        f"$p = Join-Path $w.SpecialFolders('Desktop') '{APP_NAME}.lnk'\n"
        "if (Test-Path $p) { Remove-Item $p -Force }\n"
        f"$dir = Join-Path $w.SpecialFolders('Programs') '{APP_NAME}'\n"
        "if (Test-Path $dir) { Remove-Item -LiteralPath $dir -Force -Recurse }\n"
        "Write-Output 'DONE'\n"
    )
    tmp = os.path.join(tempfile.gettempdir(), "lc_uninstall_shortcuts.ps1")
    try:
        with open(tmp, "w", encoding="utf-8-sig") as f:
            f.write(script)
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-File", tmp],
                       capture_output=True, timeout=60,
                       creationflags=_no_window())
    except Exception:
        pass
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def remove_registry():
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REG_PATH)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def remove_workspace():
    if os.path.isdir(WORKSPACE_DIR):
        shutil.rmtree(WORKSPACE_DIR, ignore_errors=True)
    return not os.path.isdir(WORKSPACE_DIR)


def schedule_self_delete():
    """安排：本进程退出后，把安装目录整个删掉。"""
    cmd = f'ping -n 3 127.0.0.1 >nul & rmdir /s /q "{INSTALL_DIR}"'
    subprocess.Popen(["cmd", "/c", cmd], creationflags=_no_window() | 0x00000008)
    # 0x00000008 = DETACHED_PROCESS


def _no_window():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


# ---------------- 界面 ----------------

class Uninstaller(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"卸载 {APP_NAME}")
        self.geometry("520x330")
        self.resizable(False, False)
        self._build()

    def _build(self):
        pad = {"padx": 20, "pady": 6}
        tk.Label(self, text=f"卸载 {APP_NAME}",
                 font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w", **pad)
        tk.Label(self, justify="left", wraplength=470, font=("Microsoft YaHei UI", 9),
                 text=(
                     "将从本机移除程序文件、桌面与开始菜单快捷方式。\n\n"
                     f"程序目录：{INSTALL_DIR}\n\n"
                     "你的项目数据（视频、文字稿、分析结果、模型）保存在：\n"
                     f"{WORKSPACE_DIR}\n"
                     "默认会**保留**，方便以后重装继续用。"
                 )).pack(anchor="w", **pad)

        self.purge = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self, variable=self.purge, font=("Microsoft YaHei UI", 9),
            text="同时删除我的项目数据（视频 / 文字稿 / 分析结果 / 已下载模型）",
        ).pack(anchor="w", padx=20, pady=(10, 2))
        tk.Label(self, fg="#c0392b", font=("Microsoft YaHei UI", 8),
                 text="注意：勾选后数据不可恢复。").pack(anchor="w", padx=44)

        btns = tk.Frame(self)
        btns.pack(side="bottom", fill="x", padx=20, pady=16)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="开始卸载", command=self._do).pack(side="right", padx=8)

    def _do(self):
        purge = bool(self.purge.get())
        if purge and not messagebox.askyesno(
                "确认删除数据",
                "将要删除：\n" + WORKSPACE_DIR +
                "\n\n视频、文字稿、分析结果、模型都会消失，且无法恢复。\n确定吗？"):
            return

        notes = []
        remove_shortcuts()
        notes.append("已删除快捷方式")
        if remove_registry():
            notes.append("已清理注册表")
        if purge:
            notes.append("已删除项目数据" if remove_workspace() else "项目数据删除不完整")
        else:
            notes.append("已保留项目数据")

        schedule_self_delete()
        messagebox.showinfo("卸载完成",
                            APP_NAME + " 已卸载。\n\n" + "\n".join(notes) +
                            "\n\n程序目录会在几秒后自动清理干净。")
        self.destroy()


if __name__ == "__main__":
    try:
        Uninstaller().mainloop()
    except Exception:
        # 界面起不来也别把卸载卡死
        remove_shortcuts()
        remove_registry()
        schedule_self_delete()
