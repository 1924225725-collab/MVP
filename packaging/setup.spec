# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# packaging/setup.spec —— 安装程序（最终交付：一个 Setup.exe）
#
# 载荷 = packaging/build/payload.zip（由 build_desktop.py 先打好），
# 里面就是 dist/AILiveClipper 整个目录。
#
# exe 名用 ASCII（AILiveClipper_Setup），构建脚本再复制一份中文名的
# 「AI直播切片助手_Setup.exe」作为对用户交付的文件名。
# ============================================================

import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
PAYLOAD = ROOT / "packaging" / "build" / "payload.zip"

if not PAYLOAD.exists():
    raise SystemExit(f"[setup.spec] 找不到安装载荷：{PAYLOAD}\n"
                     f"请先运行 build_desktop.py（会先生成 payload.zip）")

a = Analysis(
    [str(ROOT / "packaging" / "setup_app.py")],
    pathex=[str(ROOT), str(ROOT / "packaging")],
    binaries=[],
    datas=[(str(PAYLOAD), ".")],
    hiddenimports=["shortcuts"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy", "PIL", "requests", "streamlit", "faster_whisper",
        "ctranslate2", "tokenizers", "onnxruntime", "av", "PySide6",
        "matplotlib", "pandas", "scipy", "huggingface_hub",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AILiveClipper_Setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
