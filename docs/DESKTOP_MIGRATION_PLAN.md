# DESKTOP_MIGRATION_PLAN —— 桌面化迁移计划（V0.5 起）

> 阶段 1 产物：仓库审查 + 迁移边界。后续阶段按本文件推进，每阶段结束保持项目可运行。

## 一、当前仓库审查结论

### 1.1 入口层（会被桌面版替代，但保留）
| 文件 | 作用 | 桌面版处理 |
|---|---|---|
| `ui.py` | Streamlit 网页版（8501） | **保留**（开发/调试用），不作为最终用户 UI |
| `main.py` | CLI：视频→文稿 | **保留**，桌面版不复用它的交互 |
| `analyze_v2.py` | CLI：文稿→高光 | **保留**，桌面版走 service 层 |

### 1.2 核心分析层（`analysis/`）—— **零改造复用**
- 入口：`analyze_transcript_v2(transcript_path, live_type, token_mode, quantity_mode, custom_count, client, verbose)`
- 特征：**纯函数式**，输入文字稿路径，返回 `{meta, highlights, rejected, report, structure, structure_source, cost}`；唯一副作用是 `print` 日志（可用 `verbose=False` 关掉）
- 模块：transcript_parser / event_scanner / chunker / budget / prompt_builder / deepseek_client / event_cluster / dictionary / feedback / story_context / chapter_story
- ✅ **结论：Chapter / Story / Event / Highlight / 五维评分 / 推荐策略全部原样复用，一行算法都不改。**

### 1.3 ASR 层
- `asr/base.py`：已有 `BaseRecognizer`（雏形抽象）+ `Segment` 数据类
- `asr/local_whisper.py`：faster-whisper，**离线优先加载**（D-046）
- `asr/cloud_api.py`：空壳（`NotImplementedError`）
- `asr/__init__.py`：`create_recognizer()` 按 `config.ASR_BACKEND` 工厂
- `pipeline.py`：视频→音频（ffmpeg）→文稿，含 `check_video_readable` / `probe_media` / 分层 `ProcessError`
- ⚠️ **问题**：`pipeline.transcribe_audio` 直接调 `recognizer.transcribe`，业务层对「本地/云端」无显式 provider 概念
- 📋 **阶段 8 处理**：升级为 Provider 抽象（LocalASR / CloudASR），**不改识别逻辑本身**

### 1.4 配置与路径（**唯一需要最小改造的地方**）
`config.py` 全是常量；路径相关项都是**相对文件名**，各模块以「项目根目录」为基准解析：

| 位置 | 用途 |
|---|---|
| `pipeline.VIDEO_DIR / AUDIO_DIR / TRANSCRIPT_DIR` | 视频 / 音频 / 文字稿 |
| `analysis/chapter_story.cache_dir()` | 结构缓存 `structures/` |
| `analysis/feedback.py` | `feedback.json` |
| `analysis/dictionary.py` | `custom_dictionary.json` |
| `analysis/event_scanner.py` | `user_lexicon.txt` |
| `analysis/deepseek_client.py` | `api_key.txt` |
| `ui.py` | `api_key.txt` |

⚠️ **桌面版不能把用户视频/结果写进 Program Files**（无写权限、升级会丢数据）。
🔧 **改造方式**：新增 `app_paths.py` 统一解析「工作区根目录」，上述模块改为从它取路径。
**默认值保持「项目根目录」**，因此现有网页版与全部测试行为不变。

### 1.5 FFmpeg
- 由 `imageio-ffmpeg` 提供，位置：`.venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe`
- 📦 打包时必须随程序带上（PyInstaller 会把 imageio_ffmpeg 的二进制一起收进 `_internal/`）

### 1.6 模型（**当前硬依赖开发机缓存**）
- 位置：`C:\Users\admin\.cache\huggingface\hub\models--Systran--faster-whisper-small`
- ⚠️ 用户机器上不存在 → 必须支持检测 + 一键安装
- 📋 **阶段 6/7 处理**：Model Registry + 下载安装（进度/失败/重试/完整性校验）

### 1.7 测试结构
| 测试 | 覆盖 | 桌面版是否受影响 |
|---|---|---|
| `test_v040_step1~7.py` | 分析层回归（23/21/24/17/11/24/20） | ❌ 不受影响（不碰 analysis） |
| `test_ui_selftest.py` | Streamlit 界面 15/15 | ❌ 不受影响（ui.py 保留） |
| `test_v045_asr_errors.py` | ASR 分层错误 18/18 | ⚠️ 阶段 8 抽象后需回归 |

---

## 二、迁移边界（明确写死）

**✅ 复用不改**：`analysis/` 全部算法、`asr/local_whisper.py` 识别逻辑、`errors.py`、`config.py` 的算法常量

**🔧 最小改造**：路径解析统一走 `app_paths.py`（新增模块，默认行为不变）

**🆕 新增**：`desktop/`（PySide6 UI + service 层）、`models.py`（Model Registry）、`installer/`、`desktop_app.py`

**⛔ 绝对不改**：Chapter 算法、Story 算法、Event 聚合、Highlight 分析、五维评分、推荐策略

**解耦手段**：service layer（`desktop/services/`）+ adapter（ASR Provider）+ interface（`errors.py` 已是）

---

## 三、程序与数据目录分离方案

```
【程序目录】安装位置（默认 C:\Program Files\AI直播切片助手\）—— 只读
  AI直播切片助手.exe          # PyInstaller onedir 启动器
  _internal/                  # Python 运行时 + 依赖 + ffmpeg + Qt

【用户数据】%LOCALAPPDATA%\AILiveClipper\ —— 可写，升级/卸载时按需保留
  videos/        导入的视频（或仅记录原始路径）
  audio/         提取出的音频
  transcripts/   文字稿
  structures/    Chapter/Story 结构缓存（按稿隔离，D-045）
  projects/      每个视频一份项目结果 JSON（分析结果）
  models/        本地 ASR 模型（**不塞 Program Files**）
  config/        api_key.txt / custom_dictionary.json / user_lexicon.txt / settings.json
  logs/          运行日志
  temp/          临时文件
```

**覆盖方式**：环境变量 `LIVE_CLIPPER_HOME` 指向用户数据目录。
- 开发态（未设置该变量）→ 回退到项目根目录 ⇒ **现有测试与网页版行为完全不变**
- 打包态（frozen）→ 默认 `%LOCALAPPDATA%\AILiveClipper`

---

## 四、目标架构

```
桌面 UI（PySide6）
   MainWindow
     ├── ProjectPanel        视频/项目信息
     ├── RecommendedPanel    ⭐ 推荐剪辑
     ├── StructurePanel      🧭 视频 → Chapter → Story
     └── DeveloperPanel      🔧 原始 JSON / 被拒候选 / 成本 / 错误 traceback
   Dialogs: NewAnalysisDialog / ModelManagerDialog / SettingsDialog
        │
        ▼  (Qt Signal / Slot，后台线程)
Service Layer（desktop/services/）
   ├── project_store.py    项目持久化（每个视频独立结果）
   ├── analysis_service.py 包 analyze_transcript_v2
   ├── asr_service.py      包 ASR Provider + pipeline
   └── model_manager.py    Model Registry 检测/下载/校验/安装
        │
        ▼
现有核心（不改）
   pipeline.py（视频→文稿，分层错误）
   asr/  →  Provider 抽象 → LocalASR(faster-whisper) / CloudASR(预留)
   analysis/ → analyze_transcript_v2
   errors.py
```

---

## 五、十阶段实施计划与完成标准

**进度（2026-09-11）**：阶段 1~8 ✅ ｜ 阶段 9 🔨 构建中 ｜ 阶段 10 ⬜

| 阶段 | 内容 | 完成标准 | 状态 | Git 节点 |
|---|---|---|---|---|
| 1 | 仓库审查 + 迁移边界 | 本文件 | ✅ | `v0.4.5`（tag 已打：`60c0457`） |
| 2 | 桌面骨架（app_paths + MainWindow） | 桌面窗口能启动，网页版/测试不受影响 | ✅ | `desktop-foundation` |
| 3 | 接入分析核心（service 层 + 项目持久化） | 能跑通 文稿→分析→落盘 project.json | ✅ | `desktop-analysis` |
| 4 | 新 UI（信息/推荐/结构/开发者） | 四个面板按 design 呈现真实数据 | ✅ | `desktop-ui` |
| 5 | 接入本地 ASR（导入视频→文稿） | 桌面内完成 导入视频→文稿 | ✅ | （并入 analysis 节点） |
| 6 | 模型检测 + 一键安装 | 无模型能检测出，可一键下载安装 | ✅ | `model-manager` |
| 7 | Model Registry | 模型元数据集中管理，可扩展 | ✅ | `model-manager` |
| 8 | ASR Provider 抽象 | CloudASR 接口就位，LocalASR 走 provider | ✅ | `asr-provider` |
| 9 | Windows 安装器 | 产出 `AI直播切片助手_Setup.exe` | 🔨 | `windows-installer` |
| 10 | 完整回归 + 安装包实测 | 14 项验收 + 安装后运行 | ⬜ | `v0.5.0` |

### 阶段 2~8 实际落点（与计划的差异）

- 服务层多了一个 `settings_store.py`（钥匙 / 分析模式 / 引擎选择落工作区 `settings.json`）
- `model_manager.py` 除了"下载安装"还多了三条**离线友好**的路：
  `adopt_from_hf_cache()`（用户以前跑过网页版 → 直接沿用缓存，不重复下载）、
  `copy_into_workspace()`（网络不通时手动指定模型文件夹）、`verify(deep=True)`（完整性校验）
- 界面从"三个面板"变成**四个**：多一个 📺 视频信息（项目/文稿/概览/上次失败详情）
- 安装器技术选型：环境里没有 Inno Setup / NSIS，改为**自带安装程序**（tkinter + PowerShell 建快捷方式 +
  HKCU 注册卸载项，默认装到 `%LOCALAPPDATA%\Programs\` → **不需要管理员权限**）

---

## 六、风险评估

| 风险 | 影响 | 应对 |
|---|---|---|
| PyInstaller 打包 faster-whisper / ctranslate2 | 可能缺 DLL | 用 hooks + 显式收集 ctranslate2 / tokenizers / onnxruntime / av 的 DLL 与 ffmpeg 可执行文件；已核对产物 |
| Qt 插件缺失导致窗口起不来 | 装完打不开 | spec 里保留 PySide6 hooks（`qwindows.dll` 已核对在 `_internal/PySide6/plugins/platforms/`） |
| 安装包体积过大 | 用户下载困难 | 载荷 LZMA 压缩；**模型不打包**（首次运行按需下载）；exclude 掉 streamlit/pandas/matplotlib 等 |

| 安装包体积 | 可能 300MB+ | 不含模型；PySide6 只装 Essentials |
| 模型下载网络 | 代理 502（D-046 同源） | 提供「手动放置模型目录」的兜底说明 + 重试 |
| 无 Inno Setup / NSIS | 无法用现成安装器 | **自研 PySide6 安装器**（复制文件 + 快捷方式 + 卸载注册），不依赖外部工具 |
| Python 3.14 较新 | 第三方包兼容 | PySide6 用 abi3 wheel（已验证可用） |

---

## 七、桌面版不做的事（明确边界）

- 不改任何分析算法与阈值
- 不接入云端 ASR 具体服务（只留接口）
- 不实现视频播放/剪辑（只预留入口）
- 不照搬 Streamlit 页面结构，按用户任务重新组织
