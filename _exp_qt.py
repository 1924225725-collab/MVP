# 临时复现：用 Qt 信号（和模型管理对话框完全一样的方式）当下载进度回调（用完即删）
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LIVE_CLIPPER_HOME"] = tempfile.mkdtemp(prefix="lc_qt_")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Signal

app = QApplication([])

from desktop.services.model_manager import ModelManager


class _ProgressBridge(QWidget := __import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget):
    """和 desktop/ui/dialogs.py 里一模一样的桥。"""
    tick = Signal(int, int, str, str)


files = {
    "config.json": b'{"model_type": "whisper"}',
    "model.bin": b"B" * (2 * 1024 * 1024),
    "tokenizer.json": b"{}",
    "vocabulary.txt": "v".encode(),
}


class _Srv(ThreadingHTTPServer):
    def __init__(self):
        self._files = files
        super().__init__(("127.0.0.1", 0), _H)
        self.port = self.server_address[1]


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        name = os.path.basename(self.path.split("?")[0])
        data = self.server._files.get(name)
        if data is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


srv = _Srv()
threading.Thread(target=srv.serve_forever, daemon=True).start()

tmp = Path(tempfile.mkdtemp(prefix="lc_qt_reg_"))
manifest = tmp / "models_registry.json"
manifest.write_text(json.dumps({
    "manifest_version": 1,
    "models": [{
        "id": "qt-test", "kind": "asr-local", "engine": "faster-whisper",
        "name": "Qt测试", "repo_id": "r/t", "revision": "main",
        "base_url": f"http://127.0.0.1:{srv.port}/repo/resolve/main",
        "files": list(files), "primary_file": "model.bin",
        "min_primary_bytes": 1024, "sha256": "",
    }],
}, ensure_ascii=False), encoding="utf-8")

mgr = ModelManager(registry_path=str(manifest), models_root=str(tmp / "models"),
                   hf_cache_dirs=[])

bridge = _ProgressBridge()
got = []
bridge.tick.connect(lambda *a: got.append(a))

def cb(done, total, fname, phase):
    # 和 dialogs._install 里一模一样的转发
    bridge.tick.emit(done, total, fname, phase)

print("开始（Qt 信号做进度回调）…", flush=True)
try:
    res = mgr.install("qt-test", progress=cb)
    print(f"成功：{res['downloaded_bytes']} 字节，进度事件 {len(got)} 条", flush=True)
    print("✅ 桌面 UI 的调用方式没有问题", flush=True)
except Exception as e:                                          # noqa: BLE001
    print(f"✘ 复现了！{type(e).__name__}: {getattr(e, 'message', e)}", flush=True)
    print(getattr(e, "detail", "")[:400], flush=True)
