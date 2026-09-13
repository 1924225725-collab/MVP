# CLEANUP_REPORT_FINAL —— 工程化整理勘察报告

> **状态：仅勘察，未删除、未移动、未修改任何文件。**
> 生成时间：2026-09-13 03:10
> 勘察范围：`<workspace>\`（项目根 = `live_clipper\`）
> 下一步：等待用户确认后再执行任何删除

> **2026-09-13 复核：**第 1 阶段的依赖清单、结构文档和忽略规则已落地；
> 本轮仅补正文档路径与低风险配置，仍未执行任何删除。

---

## 1. 当前项目大小

| 层级 | 大小 |
|---|---|
| **整个 workspace**（`<workspace>\`） | **4.2 GB** |
| └ `.workbuddy` + `.workbuddy-ai`（工具元数据） | 156 KB |
| └ `live_clipper\`（项目本体） | 约 4.2 GB |

**结论：4.2 GB 里约 2.7 GB 是三个虚拟环境，属于「可重建资产」而非项目内容。**

### 体积构成总览

| 分类 | 占用 | 占比 |
|---|---|---|
| 虚拟环境（3 个） | **2.70 GB** | 64% |
| 打包产物（dist / dist_setup / packaging / build） | **1.03 GB** | 25% |
| 测试视频素材（videos / audio） | 360 MB | 9% |
| PoC 实验（poc，含 95M 中间 wav） | 167 MB | 4% |
| 测试媒体（_test_media） | 31 MB | <1% |
| 源码 + 文档 + 词库 | 约 4.5 MB | <1% |

> 真正的「项目代码与文档」不到 5 MB —— 其余全是可重建或素材。

---

## 2. 最大占用目录

按大小降序：

| # | 路径 | 大小 | 文件数 | 性质 |
|---|---|---|---|---|
| 1 | `.venv-audio-poc/` | **1.40 GB** | — | PoC 虚拟环境（可重建） |
| 2 | `.venv/` | **847 MB** | — | 主虚拟环境（可重建） |
| 3 | `.venv-pyannote-poc/` | **450 MB** | — | PoC 虚拟环境（可重建） |
| 4 | `dist/` | **423 MB** | 337 | PyInstaller 打包产物（可重建） |
| 5 | `videos/` | **346 MB** | 4 | **测试视频素材（唯一副本）** |
| 6 | `packaging/build/` | **294 MB** | — | 打包中间产物（可重建） |
| 7 | `dist_setup/` | **276 MB** | 2 | 安装包产物（可重建） |
| 8 | `poc/` | **167 MB** | 121 | PoC 实验（含 `t2.wav` 95M 中间产物） |
| 9 | `build/` | **35 MB** | 16 | PyInstaller 中间产物（可重建） |
| 10 | `_test_media/` | **31 MB** | 5 | 验收临时媒体（可重建） |
| 11 | `audio/` | **14 MB** | 4 | ASR 抽取的音频（可从 videos 重建） |

### `poc/` 内部拆解（167 MB）

| 路径 | 大小 | 说明 |
|---|---|---|
| `poc/t2.wav` | **95 MB** | 单文件中间音频产物 |
| `poc/audio_understanding/` | **67 MB** | 见下方拆解 |
| `poc/audio_clips/` | 3.8 MB | 切分音频片段 |
| `poc/AUDIO_top25_judge.mp3` | 876 KB | 试听素材 |
| 其余脚本 + JSON 结果 | 约 500 KB | **有保留价值** |

`poc/audio_understanding/` 内部：

| 路径 | 大小 | 性质 |
|---|---|---|
| `outputs/scan/video4_23min.wav` | 42.7 MB | 中间音频（可重建） |
| `outputs/scan/full6min.wav` | 11.8 MB | 中间音频（可重建） |
| `outputs/scan/top25_judge.wav` | 3.4 MB | 中间音频（可重建） |
| `fixtures/*.wav`（3 个） | 6.0 MB | **评测基准音频（有价值）** |
| `fixtures/*.json / *.txt`（GT 标注） | 约 100 KB | **人工标注真值（不可重建！）** |
| `*.py`（11 个脚本） | 约 100 KB | **源码（有价值）** |

---

## 3. 可以安全删除的文件列表

> 判定标准：**① 可无损重建；② 有官方源可重新下载；③ 无唯一数据**。
> 以下文件**本次未删除**，仅列出。

### A 类 —— 虚拟环境（最大收益，2.70 GB）

| 路径 | 大小 | 依据 |
|---|---|---|
| `.venv-audio-poc/` | 1.40 GB | 已被 `.gitignore` 忽略（`git check-ignore` 确认）；PoC 专用环境，`requirements` 可重建 |
| `.venv-pyannote-poc/` | 450 MB | 同上 |
| `.venv/` | 847 MB | 已被 `.gitignore` 明确忽略；主环境，可用 requirements.txt 重建 |

⚠️ **删除前请注意**：重建主环境需重新下载 faster-whisper / torch 等大包，
且模型文件（`models/`）也需重新下载。若网络受限，建议**保留 `.venv/`**，只删两个 PoC 环境（净省 1.85 GB）。

### B 类 —— 打包产物（约 1.03 GB）

| 路径 | 大小 | 依据 |
|---|---|---|
| `dist/` | 423 MB | PyInstaller 输出，`.gitignore` 已忽略；`packaging/live_clipper.spec` 可重新打包 |
| `packaging/build/` | 294 MB | 打包中间产物，`.gitignore` 已忽略 |
| `dist_setup/` | 276 MB | 安装包输出，`.gitignore` 已忽略 |
| `build/` | 35 MB | PyInstaller 中间产物，`.gitignore` 已忽略 |

⚠️ 若要**验证安装包/卸载器功能**，`dist_setup/` 里的安装包是验证依据；
如需保留一份可换机器测试，可只留最新的 `dist_setup/AILiveClipper_Setup.exe`。

### C 类 —— PoC 中间音频（约 154 MB）

| 路径 | 大小 | 依据 |
|---|---|---|
| `poc/t2.wav` | 95 MB | 中间产物，`.gitignore` 第 38 行已忽略；源视频在 `videos/` |
| `poc/audio_understanding/outputs/scan/video4_23min.wav` | 42.7 MB | 扫描中间产物（**未被忽略，是 gitignore 缺口**） |
| `poc/audio_understanding/outputs/scan/full6min.wav` | 11.8 MB | 同上 |
| `poc/audio_understanding/outputs/scan/top25_judge.wav` | 3.4 MB | 同上 |

### D 类 —— 可重建的测试媒体（约 45 MB）

| 路径 | 大小 | 依据 |
|---|---|---|
| `_test_media/` | 31 MB | 验收临时媒体，`.gitignore` 已忽略 |
| `audio/*.mp3`（3 个） | 14 MB | 从 `videos/*.mp4` 用 ffmpeg 抽取即可重建 |

### E 类 —— 明确的临时/残留文件（约 10 KB）

| 路径 | 大小 | 依据 |
|---|---|---|
| `test_write.txt` | 0 B | **本次权限测试残留的空文件，应删** |
| `_exp_link.py` | 2.7 KB | 文件头自述「模拟干净机器，**用完即删**」 |
| `_exp_qt.py` | 3.1 KB | 文件头自述「临时复现…**用完即删**」 |

### F 类 —— 构建日志（约 59 KB）

| 路径 | 依据 |
|---|---|
| `build_app.log` / `build_full.log` / `build_setup.log` | `.gitignore` 的 `build_*.log` 已覆盖；打包日志无长期价值 |
| `streamlit.log` | `.gitignore` 已忽略；网页版运行日志 |
| `__pycache__/` | `.gitignore` 已忽略 |

### 可删除总量

| 方案 | 释放空间 | 说明 |
|---|---|---|
| **保守**（仅 E + F + C） | 约 **154 MB** | 零风险，纯临时产物 |
| **推荐**（保守 + B + D + 两个 PoC venv） | 约 **3.05 GB** | 保留主 venv 与测试视频 |
| **激进**（全部 A~F） | 约 **3.90 GB** | 主环境也需重建，模型需重新下载 |

---

## 4. 风险文件列表

> **这些文件不要删。** 删除后不可无损恢复，或会导致功能不可用。

### 🔴 高危 —— 唯一数据，删了不可恢复

| 路径 | 大小 | 风险说明 |
|---|---|---|
| `poc/audio_understanding/fixtures/*.json` / `*.txt` | 约 100 KB | **人工标注的说话人真值（GT）**。这是评测的基准答案，**无法从任何源重建**，删了所有 benchmark 对比全部失效 |
| `poc/audio_understanding/fixtures/*.wav` | 6.0 MB | 评测用基准音频切片，与上面的 GT 严格配对 |
| `correction/dictionary/raw_sources/` | 约 100 KB | **用户词库原始快照**（热词/人物/影视），来自 `C:\...\词语库`，曾用 md5 校验 |
| `videos/*.mp4`（3 个） | 346 MB | **测试视频唯一副本**。删了无法再跑完整流程（重录成本高） |
| `transcripts/*.txt`（3 个） | 468 KB | 真实 ASR 文字稿，含 `峰哥/风哥` 等真实错误样本 |
| `api_key.txt` | 35 B | 含密钥；**不应删除，但必须确保已被 gitignore**（已确认） |
| `.env`（若存在） | — | 密钥文件，`.gitignore` 已覆盖 |

### 🟠 中危 —— 源码/配置，改动或删除会破坏功能

| 路径 | 说明 |
|---|---|
| `asr/`、`analysis/`、`correction/`、`speaker/` | **核心业务代码，本期严禁改动** |
| `pipeline.py`、`stages.py`、`config.py`、`app_paths.py`、`errors.py` | 核心模块 |
| `ui.py`、`desktop_app.py`、`desktop/` | 界面层 |
| `packaging/*.spec`、`setup_app.py`、`uninstaller.py` | 打包/安装脚本，删了无法重新打包 |
| `models_registry.json`、`custom_dictionary.json`、`user_lexicon.txt` | 配置与词库 |
| `poc/audio_understanding/*.py`、`poc/*.py` | PoC 源码，实验结论的载体 |
| `docs/`（34 个文档，2.2 MB） | **决策记录（DECISIONS.md 57KB）与开发日志，项目记忆** |
| `CODEX_HANDOFF.md`、`AGENT_HANDOFF.md`、`CURRENT_STATE.md`、`README.md`、`TUTORIAL.md` | 交接文档 |

### 🟡 低危但需留意

| 路径 | 说明 |
|---|---|
| `*.json` 运行结果（`highlights_v2.json` 44KB、`v044_two_videos.json` 71KB、`feedback.json`） | 历史运行结果，gitignore 已覆盖，可留作对比 |
| `structures/` | 结构缓存，删掉会重新现算（有性能成本，无数据损失） |
| `logs/`、`projects/`、`outputs/` | 运行时数据目录，**注意用户数据可能在 `%LOCALAPPDATA%\AILiveClipper\`** |
| `outputs/speaker/` | 上轮 speaker benchmark 产物 |

### ⚠️ 一个必须提醒的 gitignore 缺口

| 问题 | 详情 |
|---|---|
| `poc/audio_understanding/outputs/` | **未被 `.gitignore` 覆盖**。里面 57 MB 的中间 `.wav` 会被误提交进仓库 |
| 建议 | 在 `.gitignore` 补一条 `poc/**/outputs/`（本报告第二步允许修改 `.gitignore`） |

> 另：`.venv-audio-poc/` 与 `.venv-pyannote-poc/` 虽被 `git check-ignore` 判定为忽略，
> 但 `.gitignore` 里**没有显式规则**（是靠 `.venv/` 前缀匹配意外命中）。
> 建议显式补上两条，避免以后误提交。

---

## 5. 建议执行顺序

**分阶段、每阶段可回滚、每阶段后验证。严格遵循「先只读、后低风险」原则。**

### 第 0 阶段 —— 开工前（本报告已完成）

- [x] 只读勘察，产出本报告
- [x] **未删除、未移动、未修改任何文件**

### 第 1 阶段 —— 低风险写入（本报告第二步将执行）

允许且仅允许以下四件事：

| # | 动作 | 说明 |
|---|---|---|
| 1 | 新建 `requirements.txt` | 运行时直接依赖（已从代码 import + pip list 核实） |
| 2 | 新建 `requirements-dev.txt` | 开发/打包依赖 |
| 3 | 更新 `.gitignore` | **只增不删**，补两个 venv 与 PoC outputs 缺口 |
| 4 | 新建 `PROJECT_STRUCTURE.md` | 记录真实目录结构与各目录职责 |

**禁止**：删除任何文件、移动核心代码、修改 `asr/` `analysis/` `correction/` `speaker/` `pipeline.py`。

**验证**：`git status` 应只显示新增/修改的这 4 个文件。

### 第 2 阶段 —— 清理临时残留（需单独确认）

- 删 E 类（`test_write.txt`、`_exp_link.py`、`_exp_qt.py`）
- 删 F 类（`build_*.log`、`streamlit.log`、`__pycache__/`）
- **预计释放约 200 KB，零风险**

### 第 3 阶段 —— 清理 PoC 中间音频（需单独确认）

- 删 C 类（`poc/t2.wav` + `outputs/scan/*.wav`）
- **保留 `fixtures/` 与所有脚本/JSON**
- **预计释放约 154 MB**

### 第 4 阶段 —— 清理打包产物（需单独确认）

- 删 B 类（`dist/`、`dist_setup/`、`packaging/build/`、`build/`）
- **建议先确认最新安装包是否已备份**
- **预计释放约 1.03 GB**

### 第 5 阶段 —— 清理虚拟环境（需单独确认，建议最后做）

- 先删两个 PoC 环境（`.venv-audio-poc/`、`.venv-pyannote-poc/`）→ 释放 1.85 GB
- `.venv/` 视网络情况决定是否保留
- **删后必须验证**：`.venv/Scripts/python.exe -m pytest` 或跑一次最小流程

### 回滚方案

| 阶段 | 回滚方式 |
|---|---|
| 第 1 阶段 | `git checkout -- .gitignore`；删除新增 md/txt |
| 第 2~4 阶段 | 从回收站恢复（建议用回收站删除，不用 `rm -rf`） |
| 第 5 阶段 | 重新 `python -m venv .venv && pip install -r requirements.txt` |

---

## 6. 关键结论摘要

1. **4.2 GB 中 2.70 GB（64%）是三个虚拟环境** —— 这是体积的主要来源，不是代码膨胀。
2. **真正有价值的代码+文档不到 5 MB**，却和 4 GB 的产物混在一起。
3. **最危险的文件是 `poc/audio_understanding/fixtures/`** —— 人工标注真值，删了不可恢复。
4. **`videos/` 346 MB 是测试素材的唯一副本**，属于「占空间但必须留」。
5. **发现 1 个 gitignore 缺口**：`poc/**/outputs/` 未被忽略，有误提交风险。
6. **零风险可立即释放约 154 MB**（临时文件 + 日志 + PoC 中间音频）。

---

*本报告仅为勘察结果，未执行任何删除操作。等待用户确认后进入第 1 阶段。*
