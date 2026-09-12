# ============================================================
# desktop/services/model_manager.py —— Model Registry / 模型管理
#
# 【职责】
#   1. 读模型清单（models_registry.json）—— 下载地址、文件、校验规则集中管理，
#      **不散落在业务代码里**
#   2. 检测本地是否已安装（工作区 models/ 或已有的 HuggingFace 缓存）
#   3. 一键下载安装（进度 / 失败提示 / 可重试 / 断点续传 / 完整性校验）
#   4. 安装状态记录（installed.json）
#
# 【目录约定】（模型与程序分离，不塞 Program Files）
#   工作区/models/<模型ID>/            ← 安装到这里
#   %LOCALAPPDATA%\AILiveClipper\models\
#
# 【设计边界】
#   - 只管模型文件，不认识 faster-whisper（引擎细节留给 asr provider）
#   - 不自动删除用户已有文件；卸载由用户显式触发
# ============================================================

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

import app_paths
from errors import STAGE_MODEL_MISSING, STAGE_MODEL_LOAD, ProcessError

# 下载源：**镜像优先**。
# 直连 huggingface.co 在国内网络大概率超时（用户实测 ConnectTimeout），
# hf-mirror.com 是路径完全兼容的反向镜像，实测 0.7 秒可达。
# 官方地址仍然保留在兜底列表里（万一镜像挂了还能走官方）。
DEFAULT_MIRRORS = ["https://hf-mirror.com"]


class _DownloadFail(Exception):
    """单个下载源失败（用于自动换源重试，不直接抛给用户）。"""

    def __init__(self, message, detail=""):
        self.message = message
        self.detail = detail
        super().__init__(message)


def _split_origin_path(base_url: str):
    """'https://huggingface.co/Systran/xx/resolve/main' → (origin, '/Systran/xx/resolve/main')"""
    m = re.match(r"^(https?://[^/]+)(/.*)$", str(base_url).strip())
    if m:
        return m.group(1), m.group(2)
    return str(base_url).rstrip("/"), ""


def _source_urls(model: dict) -> list:
    """把清单里的 base_url 展开成「镜像优先、官方兜底」的候选下载源列表。"""
    base = str(model.get("base_url") or "").strip()
    if not base:
        return []
    origin, path = _split_origin_path(base)
    urls = []
    mirrors = list(model.get("mirrors") or []) or list(DEFAULT_MIRRORS)
    for m in mirrors:
        u = str(m).rstrip("/") + path
        if u not in urls:
            urls.append(u)
    if base.rstrip("/") not in urls:
        urls.append(base.rstrip("/"))
    return urls

_REGISTRY_NAME = "models_registry.json"


class ModelError(ProcessError):
    """模型相关错误（沿用 ProcessError 的 stage 语义）。"""


class ModelManager:
    def __init__(self, registry_path=None, models_root=None, hf_cache_dirs=None):
        self._registry_path = Path(registry_path) if registry_path else None
        self._models_root = Path(models_root) if models_root else app_paths.models_dir()
        self._hf_cache_dirs = [Path(p) for p in hf_cache_dirs] if hf_cache_dirs else None
        self._manifest_cache = None

    # ---------------- 清单 ----------------

    def manifest_path(self) -> Path:
        """工作区里有覆盖清单就用工作区的，否则用程序自带清单（便于日后热更新）。"""
        if self._registry_path:
            return self._registry_path
        ws = app_paths.workspace_root() / _REGISTRY_NAME
        if ws.exists():
            return ws
        return app_paths.program_root() / _REGISTRY_NAME

    def manifest(self) -> dict:
        if self._manifest_cache is None:
            path = self.manifest_path()
            try:
                self._manifest_cache = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise ModelError(STAGE_MODEL_LOAD,
                                 f"模型清单读不了：{path.name}",
                                 f"{type(e).__name__}: {e}\n路径：{path}")
        return self._manifest_cache

    def all_models(self) -> list:
        return list(self.manifest().get("models") or [])

    def get(self, model_id: str) -> dict:
        for m in self.all_models():
            if m.get("id") == model_id:
                return m
        raise ModelError(STAGE_MODEL_MISSING, f"清单里没有这个模型：{model_id}",
                         f"可用模型：{[m.get('id') for m in self.all_models()]}")

    def default_model_id(self) -> str:
        for m in self.all_models():
            if m.get("default"):
                return m["id"]
        models = self.all_models()
        return models[0]["id"] if models else ""

    # ---------------- 路径 ----------------

    def models_root(self) -> Path:
        return self._models_root

    def dir_of(self, model_id: str) -> Path:
        return self._models_root / model_id

    def marker_of(self, model_id: str) -> Path:
        return self.dir_of(model_id) / "installed.json"

    def hf_cache_dirs(self) -> list:
        if self._hf_cache_dirs is not None:
            return self._hf_cache_dirs
        dirs = []
        for env in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE"):
            v = os.environ.get(env)
            if v:
                dirs.append(Path(v))
        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            dirs.append(Path(hf_home) / "hub")
        dirs.append(Path.home() / ".cache" / "huggingface" / "hub")
        return dirs

    def hf_cache_dir_for(self, model: dict):
        """在 HuggingFace 缓存里找这个模型（用户以前跑过网页版就可能已经有）。"""
        folder = "models--" + str(model.get("repo_id", "")).replace("/", "--")
        for base in self.hf_cache_dirs():
            snapshots = base / folder / "snapshots"
            if not snapshots.is_dir():
                continue
            for snap in sorted(snapshots.iterdir(), reverse=True):
                if self._is_complete(model, snap):
                    return snap
        return None

    # ---------------- 检测 ----------------

    def _is_complete(self, model: dict, folder: Path) -> bool:
        """文件齐不齐 + 主文件大小是否合理（基本完整性校验）。"""
        if not folder or not folder.is_dir():
            return False
        for fname in model.get("files", []):
            if not (folder / fname).exists():
                return False
        primary = model.get("primary_file")
        if primary:
            p = folder / primary
            if not p.exists():
                return False
            min_bytes = int(model.get("min_primary_bytes") or 0)
            if p.stat().st_size < min_bytes:
                return False
        return True

    def resolve_local(self, model_id: str):
        """这个模型现在能不能直接用？返回 (路径, 来源) 或 (None, "")。

        来源： "workspace"（装在用户数据目录）/ "hf_cache"（沿用已有缓存）
        """
        model = self.get(model_id)
        ws = self.dir_of(model_id)
        if self._is_complete(model, ws):
            return ws, "workspace"
        cached = self.hf_cache_dir_for(model)
        if cached:
            return cached, "hf_cache"
        return None, ""

    def is_installed(self, model_id: str) -> bool:
        path, _ = self.resolve_local(model_id)
        return path is not None

    def status(self, model_id: str) -> dict:
        """给界面用的完整状态。"""
        model = self.get(model_id)
        path, source = self.resolve_local(model_id)
        installed = path is not None
        size = None
        if installed:
            try:
                size = sum((path / f).stat().st_size for f in model.get("files", [])
                           if (path / f).exists())
            except OSError:
                size = None
        marker = {}
        if self.marker_of(model_id).exists():
            try:
                marker = json.loads(self.marker_of(model_id).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                marker = {}
        return {
            "id": model_id,
            "name": model.get("name", model_id),
            "description": model.get("description", ""),
            "size_hint": model.get("size_hint", ""),
            "recommended": bool(model.get("recommended")),
            "installed": installed,
            "source": source,
            "path": str(path) if path else "",
            "actual_bytes": size,
            "verified_at": marker.get("verified_at", ""),
            "installed_at": marker.get("installed_at", ""),
        }

    def list_status(self) -> list:
        return [self.status(m["id"]) for m in self.all_models()]

    # ---------------- 校验 ----------------

    @staticmethod
    def _sha256(path: Path, chunk=1024 * 1024) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()

    def verify(self, model_id: str, deep: bool = False):
        """校验已安装模型。返回 (ok, 说明)。

        deep=True 时对主文件做 sha256（较慢），用于用户手动触发的「完整性校验」。
        """
        model = self.get(model_id)
        path, source = self.resolve_local(model_id)
        if not path:
            return False, "未安装"
        for fname in model.get("files", []):
            if not (path / fname).exists():
                return False, f"缺少文件：{fname}"
        primary = model.get("primary_file")
        if primary:
            size = (path / primary).stat().st_size
            min_bytes = int(model.get("min_primary_bytes") or 0)
            if size < min_bytes:
                return False, (f"{primary} 大小异常（{size} 字节 < 期望 {min_bytes} 字节），"
                               f"可能下载不完整")
        if deep and primary:
            digest = self._sha256(path / primary)
            # 期望值优先看清单里写死的 sha256（官方发布的，最可信），
            # 清单里没写就看安装时自己记下来的（下载后算出来的）。
            expect = (model.get("sha256") or "").strip()
            if not expect:
                marker = {}
                if self.marker_of(model_id).exists():
                    try:
                        marker = json.loads(self.marker_of(model_id).read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        marker = {}
                expect = (marker.get("sha256") or {}).get(primary) or ""
            if expect and expect != digest:
                return False, f"{primary} 校验值不匹配（文件可能损坏）"
            return True, f"校验通过（{primary} sha256={digest[:16]}…）"
        return True, "文件齐全，大小正常"

    # ---------------- 安装 ----------------

    def install(self, model_id: str, progress=None, is_cancelled=None) -> dict:
        """下载并安装模型。已安装则直接返回（**不重复下载**）。

        progress(done_bytes, total_bytes, filename, phase)
        返回 {"path", "source", "downloaded_bytes", "already": bool}
        """
        model = self.get(model_id)
        existing, source = self.resolve_local(model_id)
        if existing:
            return {"path": str(existing), "source": source,
                    "downloaded_bytes": 0, "already": True}

        try:
            import requests
        except ImportError as e:
            raise ModelError("dependency", "缺少 requests 库，无法下载模型", str(e))

        target = self.dir_of(model_id)
        target.mkdir(parents=True, exist_ok=True)

        files = list(model.get("files") or [])
        sources = _source_urls(model)
        if not sources:
            raise ModelError(STAGE_MODEL_MISSING,
                             f"模型 {model_id} 的清单里没有下载地址",
                             "请在 models_registry.json 里补 base_url")

        # **多源回退**：镜像优先，官方兜底。
        # 直连 HuggingFace 在很多网络下不通（用户实测 ConnectTimeout），
        # 单源一旦失败整个安装就完了 —— 所以每个源都试一遍，全失败才报错。
        total_done = 0
        attempts = []
        used_source = ""
        for si, src in enumerate(sources, 1):
            try:
                total_done = self._download_from(
                    src, files, target, progress, is_cancelled, si, len(sources))
            except ModelError:
                raise                      # 用户取消 / 写盘失败：换源解决不了
            except _DownloadFail as e:
                attempts.append(f"源 {si}（{src}）→ {e.message}")
                continue                   # 换下一个源（.part 保留，可继续续传）
            used_source = src
            break
        else:
            raise ModelError(
                STAGE_MODEL_MISSING,
                f"模型 {model_id} 所有下载源都失败了",
                "\n".join(attempts)
                + f"\n\n可以稍后重试；或手动下载上面地址里的文件放到：{target}"
                + "\n（镜像地址通常国内可达；官方地址可能需要代理）")

        ok, msg = self.verify(model_id)
        if not ok:
            raise ModelError(STAGE_MODEL_LOAD, f"模型下载后校验未通过：{msg}",
                             f"目录：{target}")

        primary = model.get("primary_file")
        digest = self._sha256(target / primary) if primary and (target / primary).exists() else ""
        self.marker_of(model_id).write_text(json.dumps({
            "model_id": model_id,
            "source": "download",
            "source_url": used_source,
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "size_bytes": total_done,
            "sha256": {primary: digest} if digest else {},
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        return {"path": str(target), "source": "workspace",
                "downloaded_bytes": total_done, "already": False}

    def _download_from(self, base_url: str, files: list, target: Path,
                       progress, is_cancelled, source_index: int,
                       source_total: int) -> int:
        """从**单一源**把模型文件全部下完。网络/HTTP 问题抛 _DownloadFail（可换源重试）。

        用户取消（ModelError("cancelled")）与写盘失败（ModelError）直接上抛 ——
        换个下载源解决不了这两种问题。
        """
        import requests            # install() 里已确认可用，这里复用同一份

        total_done = 0
        for idx, fname in enumerate(files):
            if is_cancelled and is_cancelled():
                raise ModelError("cancelled", "用户取消了模型下载", "")
            url = f"{base_url.rstrip('/')}/{fname}"
            dst = target / fname
            part = target / (fname + ".part")
            done = part.stat().st_size if part.exists() else 0

            headers = {"Range": f"bytes={done}-"} if done else {}
            # 连接超时收紧到 10 秒：连不上的源早点放弃、早点换下一个
            try:
                resp = requests.get(url, stream=True, timeout=(10, 120),
                                    headers=headers)
            except Exception as e:
                raise _DownloadFail(f"{fname}（{type(e).__name__}）",
                                    f"{type(e).__name__}: {e}\n地址：{url}")
            if resp.status_code not in (200, 206):
                raise _DownloadFail(f"{fname}（HTTP {resp.status_code}）",
                                    f"地址：{url}")
            if resp.status_code == 200:
                done = 0                      # 服务器不支持断点续传，从头来
                part.unlink(missing_ok=True)

            remaining = resp.headers.get("Content-Length")
            try:
                remaining = int(remaining) if remaining is not None else 0
            except ValueError:
                remaining = 0
            file_total = done + remaining
            mode = "ab" if done else "wb"
            try:
                with open(part, mode) as f:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        if is_cancelled and is_cancelled():
                            raise ModelError("cancelled", "用户取消了模型下载", "")
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        total_done += len(chunk)
                        if progress:
                            phase = (f"下载 {idx + 1}/{len(files)}"
                                     f"　·　源 {source_index}/{source_total}")
                            progress(done, file_total, fname, phase)
            except ModelError:
                raise
            except Exception as e:
                raise ModelError(STAGE_MODEL_MISSING,
                                 f"写入模型文件失败：{fname}",
                                 f"{type(e).__name__}: {e}\n目标：{target}")
            part.replace(dst)
        return total_done

    def adopt_from_hf_cache(self, model_id: str) -> dict:
        """把已有的 HuggingFace 缓存登记为「已安装」（不重复下载）。

        用户之前跑过网页版时，模型往往已经躺在 HF 缓存里了。
        """
        model = self.get(model_id)
        cached = self.hf_cache_dir_for(model)
        if not cached:
            raise ModelError(STAGE_MODEL_MISSING,
                             "本机 HuggingFace 缓存里没有这个模型", "")
        marker = self.marker_of(model_id)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({
            "model_id": model_id,
            "source": "hf_cache",
            "hf_cache_path": str(cached),
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(cached), "source": "hf_cache", "already": True}

    def copy_into_workspace(self, model_id: str, src_dir, progress=None) -> dict:
        """把用户手动指定的模型文件夹拷进工作区（离线安装兜底）。"""
        model = self.get(model_id)
        src = Path(src_dir)
        if not self._is_complete(model, src):
            raise ModelError(STAGE_MODEL_LOAD,
                             "选中的文件夹不是完整模型",
                             f"需要这些文件：{model.get('files')}\n目录：{src}")
        dst = self.dir_of(model_id)
        dst.mkdir(parents=True, exist_ok=True)
        for i, fname in enumerate(model.get("files", [])):
            if progress:
                progress(i + 1, len(model.get("files", [])), fname, "复制")
            shutil.copy2(src / fname, dst / fname)
        self.marker_of(model_id).write_text(json.dumps({
            "model_id": model_id,
            "source": "manual_copy",
            "from": str(src),
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "verified_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(dst), "source": "workspace", "already": False}

    def remove(self, model_id: str) -> bool:
        """卸载：只删工作区里的副本，绝不动 HuggingFace 缓存或用户的原始文件夹。"""
        d = self.dir_of(model_id)
        if not d.exists():
            return False
        shutil.rmtree(d, ignore_errors=True)
        return True
