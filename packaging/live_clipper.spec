# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# packaging/live_clipper.spec —— 桌面版程序的 PyInstaller 配置
#
# 产物：dist/AILiveClipper/AILiveClipper.exe （单目录模式）
#   - 单目录（onedir）而不是单文件：启动快、模型/依赖加载稳，
#     安装器直接把整个目录复制到用户机即可。
#   - exe 名用英文（AILiveClipper），快捷方式显示名才是中文
#     —— 避免中文路径在不同编码环境下出问题。
#
# 【关键点】本地语音识别依赖一堆"非纯 Python"的东西，必须显式收进来，
#   否则打出来的包会在运行时报"缺模块"：
#     faster-whisper  → ctranslate2（推理引擎）/ tokenizers / onnxruntime（VAD）/ av（音频解码）
#     imageio-ffmpeg  → ffmpeg.exe（音视频提取）
#   模型本体**不打进安装包**（几百 MB，首次使用按需下载，见 models_registry.json）。
# ============================================================

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent          # packaging/ 的上一级 = 项目根

# ---------------- 数据文件（随程序分发，只读） ----------------

datas = [
    (str(ROOT / "models_registry.json"), "."),
]
for extra in ("custom_dictionary.json", "user_lexicon.txt"):
    p = ROOT / extra
    if p.exists():
        datas.append((str(p), "."))
# 模板 / 文档（可选，方便用户查阅）
for extra in ("TUTORIAL.md", "README.md"):
    p = ROOT / extra
    if p.exists():
        datas.append((str(p), "."))

# ---------------- 二进制库 ----------------

binaries = []
for pkg in ("ctranslate2", "tokenizers", "onnxruntime", "av"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception as e:                                  # noqa: BLE001
        print(f"[spec] collect_dynamic_libs({pkg}) 跳过：{e}")

# ffmpeg：imageio-ffmpeg 把可执行文件放在自己包目录的 binaries/ 下
try:
    import imageio_ffmpeg
    _ff = imageio_ffmpeg.get_ffmpeg_exe()
    binaries.append((_ff, "imageio_ffmpeg/binaries"))
    print(f"[spec] 已收进 ffmpeg：{_ff}")
except Exception as e:                                      # noqa: BLE001
    print(f"[spec] ffmpeg 收集失败（运行时会提示缺少组件）：{e}")

# ---------------- 隐式导入 ----------------

hiddenimports = [
    "huggingface_hub", "requests", "certifi", "charset_normalizer",
    "idna", "urllib3", "filelock", "tqdm", "regex", "safetensors",
]
for pkg in ("faster_whisper", "ctranslate2", "tokenizers", "imageio_ffmpeg"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception as e:                                  # noqa: BLE001
        print(f"[spec] collect_submodules({pkg}) 跳过：{e}")

# ---------------- 排除（瘦身） ----------------

excludes = [
    "streamlit", "altair", "pyarrow", "matplotlib", "pandas", "scipy",
    "IPython", "jupyter", "notebook", "pytest", "setuptools._distutils",
    "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.QtMultimedia", "PySide6.QtBluetooth", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtNetworkAuth",
]

block_cipher = None

a = Analysis(
    [str(ROOT / "desktop_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AILiveClipper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                       # UPX 可能损坏 Qt/ctranslate2 的 DLL，关掉更稳
    console=False,                   # 桌面程序：不弹黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AILiveClipper",
)
