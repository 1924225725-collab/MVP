# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# packaging/uninstaller.spec —— 卸载程序（小、单文件、无第三方依赖）
# 产物：packaging/build/uninstall.exe（会被放进安装目录）
# ============================================================

import os
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "uninstaller.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    name="uninstall",
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
