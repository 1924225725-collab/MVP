# 验证「模型管理下载的模型，识别时必须用上」（模拟干净机器，用完即删）
import io
import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
WS = tempfile.mkdtemp(prefix="lc_link_")
os.environ["LIVE_CLIPPER_HOME"] = WS

from desktop.services.model_manager import ModelManager
from desktop.services import tasks

HERE = Path(__file__).resolve().parent


def find_hf_snapshot(model_id: str):
    """在本机 HF 缓存里找一份现成的模型（模拟'用户手动指定文件夹'的来源）。"""
    base = Path.home() / ".cache" / "huggingface" / "hub"
    for snap in (base / f"models--Systran--{model_id}" / "snapshots").glob("*"):
        if (snap / "model.bin").exists():
            return snap
    return None


def main():
    mid = "faster-whisper-small"
    mgr = ModelManager()

    # 模拟干净机器：工作区里没有模型 → 从本机 HF 缓存"手动指定文件夹"装进来
    # （等价于模型管理里的「使用本机已有模型/手动指定文件夹」）
    src = find_hf_snapshot(mid)
    if not (src and Path(src).is_dir() and (Path(src) / "model.bin").exists()):
        print(f"本机 HF 缓存里没有 {mid} 的完整模型（{src}），改用下载？跳过")
        return 2
    res = mgr.copy_into_workspace(mid, str(src))
    print(f"[1] 模型已放进工作区：{res}")

    path, source = mgr.resolve_local(mid)
    print(f"[2] resolve_local → {path}　source={source}")
    assert source == "workspace", f"应该优先用工作区模型，实际 source={source}"

    # 关键：识别时 stdout 应出现「语音识别模型：…（workspace）」
    buf = io.StringIO()
    media = HERE / "_test_media" / "normal.mp4"
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        r = tasks.transcribe_video(str(media))
    log = buf.getvalue()

    ok_line = "语音识别模型" in log and "workspace" in log
    print(f"[3] 识别用了工作区模型：{'是 ✅' if ok_line else '否 ❌'}")
    for ln in log.splitlines():
        if "语音识别" in ln or "模型" in ln:
            print("      日志>", ln.strip())

    print(f"[4] 识别结果：{r['lines']} 句 / 时长 {r['duration']}")
    if not ok_line or r["lines"] <= 0:
        print("❌ 修复未生效")
        return 1
    print("\n✅ 下载与识别已接通：模型管理装的模型，识别时直接离线使用")
    shutil.rmtree(WS, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
