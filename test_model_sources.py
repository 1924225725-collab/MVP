# ============================================================
# test_model_sources.py —— 模型下载「多源回退」验收
#
# 背景（用户实测）：直连 huggingface.co 在国内网络大概率超时
#   （ConnectTimeout），而 hf-mirror.com 这类路径完全兼容的镜像
#   实测 0.7 秒可达。所以下载必须**镜像优先、官方兜底、失败自动换源**。
#
# 本测试**不依赖外网**：
#   - 用本地 HTTP 服务器扮演"好源"
#   - 用一个必然连接失败的端口扮演"坏源"
#   - 验证：坏源失败后自动换到好源，模型装好且校验通过
#   （可选 --net：再真连一次镜像，验证真实链路）
# ============================================================

import json
import os
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PASS = 0
FAIL = 0
ROWS = []


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        ROWS.append(("PASS", name, ""))
        print(f"  ✔ {name}")
    else:
        FAIL += 1
        ROWS.append(("FAIL", name, extra))
        print(f"  ✘ {name}\n        实际：{extra}")


# ---------------- 本地"模型服务器" ----------------

class _FakeHub(ThreadingHTTPServer):
    def __init__(self, files: dict):
        self._files = files
        super().__init__(("127.0.0.1", 0), _Handler)
        self.port = self.server_address[1]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        name = os.path.basename(self.path.split("?")[0])
        data = self.server._files.get(name)
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):        # 静音
        pass


def main():
    import app_paths
    os.environ.setdefault("LIVE_CLIPPER_HOME", tempfile.mkdtemp(prefix="lc_src_"))
    import importlib
    importlib.reload(app_paths)
    app_paths.ensure_workspace()

    from desktop.services.model_manager import (
        ModelManager, _source_urls, DEFAULT_MIRRORS,
    )

    # ---------------- 1. 源展开顺序 ----------------
    model = {"base_url": "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main"}
    urls = _source_urls(model)
    check("1 镜像排在官方前面（国内网络镜像优先）",
          urls and urls[0].startswith("https://hf-mirror.com")
          and urls[-1].startswith("https://huggingface.co"), str(urls))
    check("1 镜像与官方的路径一致（hf-mirror 是路径兼容的反代）",
          all(u.endswith("/Systran/faster-whisper-tiny/resolve/main") for u in urls),
          str(urls))
    check("1 默认镜像清单可用", len(DEFAULT_MIRRORS) >= 1, str(DEFAULT_MIRRORS))
    urls2 = _source_urls({**model, "mirrors": ["https://my-mirror.example.com"]})
    check("1 清单里的 mirrors 字段可以覆盖默认镜像",
          urls2 and urls2[0].startswith("https://my-mirror.example.com"), str(urls2))

    # ---------------- 2. 多源回退（坏源 → 好源） ----------------
    files = {
        "config.json": b'{"model_type": "whisper"}',
        "model.bin": b"B" * (3 * 1024 * 1024),           # 3 MB
        "tokenizer.json": b'{"t": 1}',
        "vocabulary.txt": "词表".encode("utf-8"),
    }
    srv = _FakeHub(files)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    good = f"http://127.0.0.1:{srv.port}/repo/resolve/main"
    bad = "http://127.0.0.1:9/unreachable/resolve/main"   # 端口 9：连接必被拒

    tmp = Path(tempfile.mkdtemp(prefix="lc_src_model_"))
    manifest = tmp / "models_registry.json"
    manifest.write_text(json.dumps({
        "manifest_version": 1,
        "models": [{
            "id": "test-model", "kind": "asr-local", "engine": "faster-whisper",
            "name": "测试模型", "repo_id": "repo/test", "revision": "main",
            "base_url": bad,                       # ← 坏源排第一
            "mirrors": [f"http://127.0.0.1:{srv.port}"],   # ← 好源做镜像
            "files": list(files), "primary_file": "model.bin",
            "min_primary_bytes": 1024, "sha256": "",
        }],
    }, ensure_ascii=False), encoding="utf-8")

    mgr = ModelManager(registry_path=str(manifest),
                       models_root=str(tmp / "models"),
                       hf_cache_dirs=[])
    try:
        res = mgr.install("test-model")
        check("2 坏源失败后自动换到好源，安装成功", res.get("already") is False,
              str(res))
        marker = json.loads(mgr.marker_of("test-model").read_text(encoding="utf-8"))
        check("2 记录里写明了实际使用的下载源",
              str(marker.get("source_url", "")).startswith("http://127.0.0.1:"),
              str(marker.get("source_url")))
        ok, msg = mgr.verify("test-model")
        check("2 装好的模型通过完整性校验", ok, msg)
    except Exception as e:                                     # noqa: BLE001
        check("2 坏源失败后自动换到好源，安装成功", False,
              f"{type(e).__name__}: {getattr(e, 'message', e)}\n"
              f"{getattr(e, 'detail', '')[:400]}")

    # ---------------- 3. 全部源都失败时的报错 ----------------
    manifest.write_text(json.dumps({
        "manifest_version": 1,
        "models": [{
            "id": "test-model-2", "kind": "asr-local", "engine": "faster-whisper",
            "name": "测试模型2", "repo_id": "repo/test", "revision": "main",
            "base_url": bad, "files": ["model.bin"],
            "primary_file": "model.bin", "min_primary_bytes": 1, "sha256": "",
        }],
    }, ensure_ascii=False), encoding="utf-8")
    mgr2 = ModelManager(registry_path=str(manifest),
                        models_root=str(tmp / "models2"),
                        hf_cache_dirs=[])
    try:
        mgr2.install("test-model-2")
        check("3 所有源都失败时给出可读的汇总错误", False, "竟然成功了")
    except Exception as e:                                     # noqa: BLE001
        msg = str(getattr(e, "message", e))
        detail = str(getattr(e, "detail", ""))
        check("3 所有源都失败时给出可读的汇总错误",
              "所有下载源都失败" in msg and "源 1" in detail,
              f"{msg}\n{detail[:300]}")
        check("3 错误里包含手动放置的指引",
              "手动下载" in detail or "手动" in detail, detail[:300])

    srv.shutdown()

    # ---------------- 4.（可选）真连一次镜像 ----------------
    if "--net" in sys.argv:
        print("\n[4] 真连镜像下载（约 75 MB）…")
        os.environ["LIVE_CLIPPER_HOME"] = tempfile.mkdtemp(prefix="lc_net_")
        import importlib as _il
        _il.reload(app_paths)
        app_paths.ensure_workspace()
        from desktop.services.model_manager import ModelManager as MM
        try:
            res = MM().install("faster-whisper-tiny")
            check("4 镜像真实下载成功", res.get("already") is False, str(res))
            ok, msg = MM().verify("faster-whisper-tiny")
            check("4 下载后校验通过", ok, msg)
        except Exception as e:                                 # noqa: BLE001
            check("4 镜像真实下载成功", False,
                  f"{type(e).__name__}: {getattr(e, 'message', e)}\n"
                  f"{getattr(e, 'detail', '')[:300]}")
    else:
        print("\n[4] 跳过真实下载（加 --net 可真连镜像验证一次）")

    return report()


def report():
    print("\n" + "=" * 66)
    print(f"模型多源回退验收：通过 {PASS} / 失败 {FAIL} / 共 {PASS + FAIL}")
    print("=" * 66)
    out = HERE / "model_sources_report.txt"
    with open(out, "w", encoding="utf-8") as f:
        for status, name, extra in ROWS:
            f.write(f"[{status}] {name}" + (f"  -> {extra}" if extra else "") + "\n")
        f.write(f"\n通过 {PASS} / 失败 {FAIL}\n")
    print(f"报告已写入：{out}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        code = main()
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        code = 1
    sys.exit(code)
