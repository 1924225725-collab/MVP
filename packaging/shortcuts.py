# ============================================================
# packaging/shortcuts.py —— 建 / 删快捷方式（安装器与卸载器共用）
#
# 【为什么用 PowerShell】Windows 的 .lnk 是二进制格式，纯 Python 写起来又长又脆。
#   WScript.Shell 能拿到"桌面 / 开始菜单"的**真实路径**（兼容 OneDrive 重定向），
#   所以路径一律问 SpecialFolders，不在 Python 里硬拼。
#
# 【中文怎么传才不坏】命令行参数容易被编码搞坏，所以：
#   - 把脚本写成 UTF-8 **带 BOM** 的临时 .ps1（Windows PowerShell 5.1 认 BOM）
#   - 路径/名称一律用单引号字符串（PowerShell 里 ' 用 '' 转义）
#   - 不用 here-string（here-string 的收尾符必须在行首，缩进会踩坑）
# ============================================================

import subprocess
import tempfile
from pathlib import Path

_PS_FLAGS = ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]


def _q(s) -> str:
    """PowerShell 单引号字符串（内部单引号翻倍）。"""
    return "'" + str(s).replace("'", "''") + "'"


def _run_ps(script: str):
    """把脚本写成带 BOM 的临时 ps1 再执行，返回 (ok, 输出)。"""
    tmp = Path(tempfile.gettempdir()) / "lc_shortcut_task.ps1"
    tmp.write_text(script, encoding="utf-8-sig")     # utf-8-sig = 带 BOM
    try:
        p = subprocess.run(["powershell", *_PS_FLAGS, str(tmp)],
                           capture_output=True, text=True, timeout=90,
                           encoding="utf-8", errors="replace")
        return p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    except Exception as e:                                        # noqa: BLE001
        return False, str(e)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def special_folders() -> dict:
    """拿桌面与开始菜单的真实路径（兼容 OneDrive / 重定向）。"""
    script = (
        "$w = New-Object -ComObject WScript.Shell\n"
        "Write-Output ('DESKTOP=' + $w.SpecialFolders('Desktop'))\n"
        "Write-Output ('PROGRAMS=' + $w.SpecialFolders('Programs'))\n"
    )
    _ok, msg = _run_ps(script)
    out = {}
    for line in msg.splitlines():
        line = line.strip()
        for tag, key in (("DESKTOP=", "desktop"), ("PROGRAMS=", "programs")):
            if line.startswith(tag):
                out[key] = line[len(tag):]
    return out


def create_shortcut(link_path: str, target_exe: str, workdir: str,
                    description: str = "", icon: str = "") -> tuple:
    """建一个 .lnk。返回 (ok, 说明)。"""
    icon = icon or target_exe
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "$w = New-Object -ComObject WScript.Shell\n"
        f"$s = $w.CreateShortcut({_q(link_path)})\n"
        f"$s.TargetPath = {_q(target_exe)}\n"
        f"$s.WorkingDirectory = {_q(workdir)}\n"
        f"$s.Description = {_q(description or '')}\n"
        f"$s.IconLocation = {_q(icon)} + ',0'\n"
        "$s.Save()\n"
        "if (Test-Path " + _q(link_path) + ") { Write-Output 'OK' } else { Write-Output 'MISSING' }\n"
    )
    ok, msg = _run_ps(script)
    good = ok and "OK" in msg
    return good, (msg.strip() or ("已创建 " + link_path if good else "未创建"))


def remove_shortcuts(name: str) -> list:
    """删掉桌面与开始菜单里的快捷方式，返回被删掉的路径。"""
    script = (
        "$w = New-Object -ComObject WScript.Shell\n"
        "$removed = @()\n"
        f"$p = Join-Path $w.SpecialFolders('Desktop') {_q(name + '.lnk')}\n"
        "if (Test-Path $p) { Remove-Item $p -Force; $removed += $p }\n"
        f"$dir = Join-Path $w.SpecialFolders('Programs') {_q(name)}\n"
        "if (Test-Path $dir) {\n"
        "  Get-ChildItem -LiteralPath $dir -Filter *.lnk | ForEach-Object {\n"
        "    Remove-Item -LiteralPath $_.FullName -Force; $removed += $_.FullName }\n"
        "  Remove-Item -LiteralPath $dir -Force -Recurse\n"
        "  $removed += $dir\n"
        "}\n"
        "$removed | ForEach-Object { Write-Output $_ }\n"
        "Write-Output 'DONE'\n"
    )
    _ok, msg = _run_ps(script)
    return [ln.strip() for ln in msg.splitlines()
            if ln.strip() and ln.strip() != "DONE"]
