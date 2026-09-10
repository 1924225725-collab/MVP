# ============================================================
# build_desktop.py —— 一键构建 Windows 桌面版安装包
#
# 产出（都在 dist_setup/）：
#     AI直播切片助手_Setup.exe     ← 交付给用户的唯一文件
#     AILiveClipper_Setup.exe      ← 同一个文件（ASCII 名，便于脚本/CI 使用）
#
# 构建顺序（每步都对应一个可以单独复跑的函数）：
#   1. 卸载程序  → packaging/build/uninstall.exe
#   2. 主程序    → dist/AILiveClipper/
#   3. 把卸载程序放进主程序目录
#   4. 打成安装载荷 packaging/build/payload.zip（LZMA）
#   5. 安装程序  → dist_setup/AILiveClipper_Setup.exe
#
# 用法：
#     .\.venv\Scripts\python build_desktop.py                # 全流程
#     .\.venv\Scripts\python build_desktop.py --skip-app     # 复用已有 dist/AILiveClipper
#     .\.venv\Scripts\python build_desktop.py --only-setup   # 只重打安装包
# ============================================================

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
PKG = ROOT / "packaging"
BUILD = PKG / "build"
DIST_APP = ROOT / "dist" / "AILiveClipper"
DIST_SETUP = ROOT / "dist_setup"
UNINSTALLER = BUILD / "uninstall.exe"
PAYLOAD_ZIP = BUILD / "payload.zip"


def log(msg):
    print(f"\n=== {msg} ===", flush=True)


def run_pyinstaller(spec: Path, distpath: Path, workpath: Path):
    # 先清掉这个 spec 自己的缓存目录：PyInstaller 收尾时会逐个文件删，
    # 遇到杀软/同步盘/文件保护常常失败（构建就断在半路）。整目录删一次最稳。
    spec_work = workpath / spec.stem
    if spec_work.exists():
        print(f"清理缓存：{spec_work}", flush=True)
        shutil.rmtree(spec_work, ignore_errors=True)
    cmd = [PY, "-m", "PyInstaller", "--noconfirm", "--distpath", str(distpath),
           "--workpath", str(workpath), str(spec)]
    print(" ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(ROOT))
    if p.returncode != 0:
        raise SystemExit(f"[构建失败] {spec.name}（退出码 {p.returncode}）")


# ---------------- 1. 卸载程序 ----------------

def build_uninstaller():
    log("1/5 构建卸载程序")
    run_pyinstaller(PKG / "uninstaller.spec", BUILD, BUILD / "pyi_uninstaller")
    if not UNINSTALLER.exists():
        raise SystemExit(f"卸载程序没生成：{UNINSTALLER}")
    print(f"OK  {UNINSTALLER}  ({UNINSTALLER.stat().st_size // 1024} KB)")


# ---------------- 2. 主程序 ----------------

def build_app():
    log("2/5 构建主程序（AILiveClipper，单目录）")
    # 先自己把上一次的产物清掉：PyInstaller 的 --noconfirm 会逐个文件删，
    # 在某些带文件保护的杀软/同步盘目录下会失败；一次整目录删除更稳。
    if DIST_APP.exists():
        print(f"清理旧产物：{DIST_APP}", flush=True)
        shutil.rmtree(DIST_APP, ignore_errors=True)
    run_pyinstaller(PKG / "live_clipper.spec", ROOT / "dist", ROOT / "build")
    if not (DIST_APP / "AILiveClipper.exe").exists():
        raise SystemExit(f"主程序没生成：{DIST_APP / 'AILiveClipper.exe'}")
    print(f"OK  {DIST_APP}  ({_dir_size_mb(DIST_APP):.0f} MB)")


# ---------------- 3. 合并 ----------------

def merge_uninstaller():
    log("3/5 把卸载程序放进安装目录")
    shutil.copy2(UNINSTALLER, DIST_APP / "uninstall.exe")
    print(f"OK  {DIST_APP / 'uninstall.exe'}")


# ---------------- 4. 载荷 ----------------

def make_payload():
    log("4/5 打包安装载荷（LZMA）")
    BUILD.mkdir(parents=True, exist_ok=True)
    if PAYLOAD_ZIP.exists():
        PAYLOAD_ZIP.unlink()
    files = [p for p in DIST_APP.rglob("*") if p.is_file()]
    t0 = time.time()
    with zipfile.ZipFile(PAYLOAD_ZIP, "w", zipfile.ZIP_LZMA) as z:
        for i, p in enumerate(files, 1):
            z.write(p, p.relative_to(DIST_APP.parent).as_posix())
            if i % 200 == 0:
                print(f"  {i}/{len(files)} …", flush=True)
    print(f"OK  {PAYLOAD_ZIP}  ({PAYLOAD_ZIP.stat().st_size / 1024 / 1024:.0f} MB, "
          f"{len(files)} 个文件, {time.time() - t0:.0f}s)")


# ---------------- 5. 安装程序 ----------------

def build_setup():
    log("5/5 构建安装程序（Setup.exe）")
    DIST_SETUP.mkdir(parents=True, exist_ok=True)
    run_pyinstaller(PKG / "setup.spec", DIST_SETUP, BUILD / "pyi_setup")
    ascii_name = DIST_SETUP / "AILiveClipper_Setup.exe"
    if not ascii_name.exists():
        raise SystemExit(f"安装程序没生成：{ascii_name}")
    cn_name = DIST_SETUP / "AI直播切片助手_Setup.exe"
    shutil.copy2(ascii_name, cn_name)
    print(f"OK  {cn_name}  ({cn_name.stat().st_size / 1024 / 1024:.0f} MB)")
    print(f"OK  {ascii_name}")


def _dir_size_mb(path: Path) -> float:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total / 1024 / 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-app", action="store_true",
                    help="复用已有的 dist/AILiveClipper（只重打载荷与安装包）")
    ap.add_argument("--only-setup", action="store_true",
                    help="等价于 --skip-app，且不重编卸载程序")
    ap.add_argument("--skip-payload", action="store_true",
                    help="复用已有的 packaging/build/payload.zip（改安装器界面时用，省几分钟）")
    args = ap.parse_args()

    t0 = time.time()
    if not args.only_setup:
        build_uninstaller()
    if not (args.skip_app or args.only_setup):
        build_app()
    if not DIST_APP.exists():
        raise SystemExit("dist/AILiveClipper 不存在，先跑一次完整构建")
    if not args.skip_payload:
        merge_uninstaller()
        make_payload()
    else:
        if not PAYLOAD_ZIP.exists():
            raise SystemExit(f"--skip-payload 但载荷不存在：{PAYLOAD_ZIP}")
        print(f"复用已有载荷：{PAYLOAD_ZIP}")
    build_setup()
    print(f"\n全部完成，用时 {time.time() - t0:.0f}s")
    print(f"交付文件：{DIST_SETUP / 'AI直播切片助手_Setup.exe'}")


if __name__ == "__main__":
    main()
