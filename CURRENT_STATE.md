# CURRENT_STATE — 项目当前状态（读这个文件，不要重新审计）

更新时间：2026-09-12 14:45 ｜ 版本：**V0.5.2（桌面版加固：真实进度 / 启动体验 / 环境自检 / 卸载修复）** ／ 上一个 **V0.5.1**

## 运行方式
- 环境：`./.venv/Scripts/python`（Windows，venv 在 live_clipper/.venv）
- **🖥️ 桌面版（新）**：`./.venv/Scripts/python desktop_app.py`
  - 打包产物：`dist/AILiveClipper/AILiveClipper.exe`（onedir，410 MB，含 ffmpeg / ctranslate2 / onnxruntime / av / Qt）
  - 安装包：`dist_setup/AI直播切片助手_Setup.exe`（由 `./.venv/Scripts/python build_desktop.py` 构建）
  - 打包自检：`LIVE_CLIPPER_SMOKE=1 QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python desktop_app.py`
    → 结果写 `logs/desktop_smoke.json`
- 网页版（保留）：`./.venv/Scripts/streamlit run ui.py`（8501）；或双击 `start_webui.bat`
- 命令行（保留）：`main.py`（ASR）、`analyze_v2.py`（AI 分析）
- 真实 API 分析（**需用户明确要求才跑**）：
  `./.venv/Scripts/python analyze_v2.py --transcript "transcripts/测试视频2.txt" --type 娱乐聊天 --mode 精细 --quantity 候选池`
- 测试：
  - 桌面版：`test_desktop_smoke.py`（52 项，离线）；`test_desktop_e2e.py`（24 项，真跑本地 ASR）
  - 安装包：`packaging/verify_install.py`（30 项，模拟安装 + 装好的 exe 实机启动）
  - 回归：`test_v040_step{1,2,3,4,5,6,7}.py` + `test_ui_selftest.py` + `test_v045_asr_errors.py`
    （当前全过：23/21/24/17/11/24/20 + UI 15/15 + ASR 18/18）
- 交接文档：**`docs/HANDOVER_20260910.md`**；桌面版迁移计划：**`docs/DESKTOP_MIGRATION_PLAN.md`**

## V0.5.2 状态（2026-09-12）—— 桌面版加固（六个任务）
**只做桌面软件工程问题**：Story / Event / 评分 / 推荐 / UI 整体设计**一行未改**。

1. **真实处理进度**：六阶段（读取视频→提取音频→VAD→语音识别→AI分析→生成结果）；
   语音识别用「已处理音频时间 / 总时长」算**真百分比**（`45%　23:10 / 51:00`），
   算不出的阶段如实显示"进行中"；AI 阶段解析自身日志推进进度（不改 analysis 代码）。见 **D-050**
2. **安装/启动不卡**：安装器解压/统计/快捷方式全搬到后台线程；启动"界面先显示、自检后台跑"；
   项目列表异步加载。新增安装日志与启动日志（含各阶段耗时；实测启动 0.15~0.24 秒）。
3. **环境自检**：6 项检查 + **四类问题归类**（视频 / 程序组件 / 模型 / 权限），每类给不同解决办法；
   启动后台自动跑，有问题才提示；开发者视图可随时重查。见 **D-051**
4. **卸载修复**：卸载器先复制自己到 %TEMP% 再执行（否则删不掉自己所在的目录）；删除带重试 +
   系统后台兜底清理；**注册表必定清理**（「应用和功能」不再残留）；全流程写日志。
5. **全流程验收**：`packaging/test_install_uninstall.py` **35/35**（装→用→卸→查残留→删数据分支）。
6. **开发报告**：`docs/V052_DESKTOP_HARDENING_REPORT.md`

**测试**：进度 34/34 ｜ 安装卸载 35/35 ｜ 安装包 33/33 ｜ 桌面自测 52/52 ｜ 端到端 24/24 ｜
回归 step1~7 + UI 15/15 + ASR 18/18 全过。

## 主干流程（V0.4 目标架构）
ASR → **Chapter**(大环节) → **Story**(连续活动) → Event Discovery → 本地聚类 → Event Understanding → Event Completion → Review/排序 → **推荐剪辑筛选** → 最终 Highlight

## V0.5.0 状态（2026-09-11）—— Windows 独立桌面版，阶段 1~8 完成
**目标**：下载一个 `Setup.exe` → 双击装好 → 桌面快捷方式双击即用。不需要 Python / 命令行 / 浏览器。
**核心算法一行不改**，只换外壳与数据落点。

- **路径分离**（D-047）：`app_paths.py` 是唯一路径入口。程序目录（只读）与用户数据目录（可写，
  `%LOCALAPPDATA%\AILiveClipper`）彻底分开；开发态行为与改造前**逐项一致**。模型**绝不放在安装目录**。
- **服务层**（`desktop/services/`，UI 只跟它打交道）：
  - `project_store.py`：**每个视频 = 一个独立项目**（`projects/<ID>/project.json`，原子写，读时校验 project_id）
    → 跨视频串场在结构上不可能发生（延续 V0.4.4 的要求）
  - `tasks.py`：只做编排与包装，直接调 `pipeline.process_video` / `analysis.analyze_transcript_v2`
  - `settings_store.py`：设置存工作区；钥匙镜像到 `api_key.txt`，三端一致
  - `model_manager.py`：Model Registry 的检测 / 一键安装 / 断点续传 / 深度校验 / 沿用本机缓存 / 卸载
- **ASR 抽象**（D-048）：`asr/provider.py` + `asr/registry.py`。业务层不再依赖 faster-whisper；
  云端与两遍引擎**只留接口**。`model_path` 给定时直读模型目录 → **完全离线**。
- **模型不分发**（D-049）：`models_registry.json` 集中管理下载地址 / 文件 / 版本 / 校验；
  首次运行检测并引导一键安装。
- **新界面**（PySide6）：⭐推荐剪辑 / 🧭直播内容结构（Chapter 可折叠 → Story → Event）/ 📺视频信息 / 🔧开发者视图；
  展示层继续不露 S/A/B/C/D 字母（D-044）；错误提示沿用 D-046 分层并多给「点哪个按钮能修好」。
  耗时任务在后台线程，界面不假死。
- **测试**：`test_desktop_smoke.py` **52/52**（含「切项目后旧内容一个都不剩」「被改坏 project_id 的项目读不出来」）；
  回归 step1~7 + UI 自测 + ASR 分层全过。
- **安装包实测**：`packaging/verify_install.py` **30/30**（安装程序自检 + 模拟安装 + 装好的 exe 实机启动：
  冻结态 / 目录分离 / 内置 ffmpeg / 四页签 / 引擎可用 / 模型清单 / 程序目录无 models/）。
- **界面截图**：`docs/screenshots/`（6 张，用同一场 51 分钟直播的真实结果渲染）。
- **V0.5.1 修的坑**：`faster_whisper/assets/silero_vad_v6.onnx`（人声检测模型）是包里唯一的
  非 .py 文件，打包时没被收集 → **开发态永远正常，装到别的盘真跑识别必崩**（报 asr_inference，
  实际是缺文件）。现在：spec 显式收集该文件；缺文件类异常改判 `dependency` 并提示"重装程序"；
  `verify_install` 增加"真跑一次识别"的断言（`LIVE_CLIPPER_SMOKE_TRANSCRIBE`）。
  **教训：打包验收只验"能导入"是不够的，必须真跑一次主流程。**
- **剩余**：阶段 10 里需要人工过一遍的（自动化做不了）：
  □ 双击 Setup.exe 走完安装流程　□ 桌面/开始菜单快捷方式　□ 「应用和功能」里卸载
  □ 卸载时数据的保留/删除分支　□ 首次运行无模型时的一键安装（需联网）　□ 真实视频全流程分析

## V0.4.5 状态（2026-09-11）—— 本地 ASR 错误处理链路已修
- **问题**：网页版对**任何**视频都提示「视频处理失败，请换一个文件试试」，正常视频也被当成"视频损坏"。
- **根因（两层）**：① 加载本地 Whisper 模型会经 huggingface_hub 做**远程校验**，本机代理返回 **502 Bad Gateway** → 正常视频也失败；② `extract_audio`/`process_video` 失败只 `return None`，信息被丢弃 → 所有失败塌缩成同一句，traceback 还被 `except Exception` 吞掉。
- **修复**：模型**离线优先加载**（`local_files_only=True`，缓存缺该模型才联网下载）；新增 `errors.py`（带 stage 的 `ProcessError`）+ `check_video_readable()` + `probe_media()`；UI 十条分层文案 + 开发者视图保留完整 traceback。详见 **D-046**。
- **现在能区分**：媒体文件无法读取 / 未检测到音轨 / 音频提取失败 / FFmpeg 不可用 / 缺少依赖库 / 本地模型未安装 / 模型加载失败 / 语音识别推理失败 / 没有识别出内容。
- **测试**：test_v045_asr_errors **18/18**；真实 6 分钟视频 41 句 / 85s 走通；UI 自测 15/15；step1~6 回归全过。

## V0.4.4 状态（2026-09-11）—— 严重数据绑定 bug 已修
- **问题**：换任何视频，「推荐剪辑」对，但「直播内容结构」永远显示开发阶段那场 51 分钟测试视频的固定 Chapter 01/02/03/04。
- **根因**：Chapter/Story **从未接进主流程**；`story_context.load_structure()` 无条件读 PoC 写死的 `poc/story_segmentation_result.json`（51 分钟视频产物）。
- **修复**：新增 `analysis/chapter_story.py` —— 主流程内用**本视频事件**现算 Chapter → Story，并按视频缓存隔离 `structures/<稿名>.json`（**同名 + 同时长**才复用，否则现算）；`load_structure()` / `load_story_groups()` 的 `source=None` **返回空**（不再隐式读固定文件）；`config.STORY_CONTEXT` 删 `story_file`；PoC 夹具移入 `poc/fixtures/`。详见 **D-045**。
- **当前数据流**：`文字稿 → 事件列表 → get_or_build_structure(本稿) → structure → UI`（与本次 highlights 同源、同 event_id）。
- **测试**：test_v040_step7 **20/20**；UI 自测 15/15；step1~6 回归全过；真实双视频验证 `v044_two_videos_report.txt`。

## V0.4.3 状态（2026-09-11）
- **界面不露 S/A/B/C/D 字母**（D-044）：内部 grade 仍是 S/A/B/C/D（评分体系不动），展示层模糊化——
  S/A → 🌟 高光内容；B/C → ✨ 有看点（合并，避免「C 比 B 差」）；D 不显示徽章。
  推荐层级去字母（重点推荐/推荐/值得一看/备选参考）；AI 文案加 prompt 规则 + `_soften()` 兜底。
  开发者视图保留 `grade=X` 原始数据。
- **⚠️ 改了 config.py / prompt_builder.py → 必须重启 Streamlit 才会生效**（模块级缓存）。

## V0.4.2 状态（2026-09-11）
- **评分/评级 与 推荐剪辑已解耦**（D-041）：`grade/score` 只描述内容质量；`recommended/recommend_tier` 是产品层筛选。
  自动精选 = A 优先 → 高质量 B（≥60）补位 → 全无时 C 兜底（≤3），D 永不推荐；目标数上限 `AUTO_SELECT_TARGET=8`。
  **修掉「全场无 A → 0 条高光」**：真实 V0.4.1 结果回放，自动精选 0 条 → 8 条。
- **内容结构层**（D-042）：`analyze_transcript_v2` 返回值新增 `structure` 段（Chapter→Story→Event；
  Story 评分 = 组内最强事件分；缺失静默降级）。实现在 `analysis/story_context.py`，纯本地零成本。
- **新版 UI**（D-043）：视频信息 → ⭐推荐剪辑 → 🧭直播内容结构（Chapter 折叠→Story 卡片）→ 🔧开发者视图。
  开发者/debug 能力全部保留在底部折叠区。
- **未改动**：五维权重、S/A/B/C 阈值、负面清单封顶、零输出禁令、海选/质检/事件聚合/分批复审。

## 当前验证到哪一步（人工验收结论）
| 层级 | 状态 | 结果 |
|---|---|---|
| Chapter V3 | ✅ 人工验收通过 | 4 个 Chapter（AI 内容驱动，非固定窗口），整体合理，仅 ch-03 过渡段略长但可接受 |
| Story Layer | ✅ 人工验收通过 | 4 Chapter → 10 Story；ch-02 咖啡 5 事件正确并成一个 Story；ch-04 罐头/饼干/米饭正确拆 3 个；**仅 ch-03 过渡段应合并过度拆分（1 处小问题）** |
| A1/A2/A3/B1 | 🔒 冻结为基础能力 | 不回退，新层级需兼容它们 |
| Audio/Vision | ⏸ 不接入 | 本地 DSP 到瓶颈，Audio 已判暂停（详见下） |

## 已冻结/基础模块（不要再审计/改动，除非用户明确要求）
| 编号 | 内容 | 位置 |
|---|---|---|
| A1 | 质检重扫候选去重：exact(start,end) → overlap_score>0.5 | `analysis/__init__.py` 质检段 |
| A2 | split 事件保留候选信息：summary←候选.reason | `_make_event(split=True)` |
| A3 | D 级四分门控：非 truly_low_value 不判 D | `_review_in_batches` |
| B1 | 海选候选单位定义 + event_context/event_boundary_note 字段 | `prompt_builder.py` + `__init__.py` 解析透传 |

**A1/A2/A3 效果**：D 14→4；微波炉从"2 个 D"→A 级完整事件；split 事件带 summary 0/6→14/14。
**B1 效果**：39→38 候选，17→18 事件，≤28s 碎片 6→4，中位时长→51s。

## 当前基线结果（highlights_v2.json，B1 后，主流程未被 V0.4 PoC 改动）
精细 degrade0：**38 候选 → 18 事件**（A1/B11/C3/D3），¥0.493；事件中位时长 51s，>60s 事件 8 个，≤28s 碎片 4 个。

## 人工复核已完成的结论（关键输入）
- **B1 12 个重点事件**：Y=6 / N=6。核心问题 = **事件完整性不足**（ev-005 13s 判 A 是碎片高估、ev-002 269s 但"非全过程"、ev-006 21s 应与 ev-005 合并、ev-016 87s 可升 A）——不是纯评分校准问题，需要结构层让完整事件聚合更完整。
- **Chapter V3**：4 个全 Y。
- **Story Segmentation**：4 个问题 3 通过 1 需调整（仅 ch-03 合并规则）。

## 待办（下一步）
1. **用户真实视频实测新 UI**：确认「推荐剪辑 + Chapter/Story 结构」是否符合使用直觉；确认自动精选不再 0 输出。
2. 多视频回归测试（T1 已完成；T2/T3 待用户提供视频稿）——见 `docs/V041_REGRESSION_PLAN_20260910.md`。
3. 遗留优化项（不在 V0.4.2 内顺手改）：Story 分割精度 O-001（ch-03 过渡段）、O-002（B1 候选更多）、D-040（稀疏候选跨区块再合并）。
4. Step 3.2 其余（C 评分校准、D 推荐措辞）——优先级仍靠后。
5. v0.4 计划的「文本纠错用户词库管理页面 + 用户画像」尚未开工。

## Audio（已判暂停）
本地能量/ZCR/相对基线在有人声直播里无法区分笑声/说话/BGM → 本地 DSP 到瓶颈。
Top25 人工复核 y=13/n=12（命中率 52% 有侥幸）。出路 = YamNet（需网络恢复，huggingface/github 当前不可达）。
产物：`poc/audio_*`、`docs/AUDIO_LAYER_POC_20260909.md`。

## 关键约定（用户明确要求）
- 小步走，一次一件事，最小修改、不重构
- **不为让测试通过而调阈值/时长**（表面修复一律拒绝）
- Chapter/Story 都是**软边界**，不能阻止跨边界取上下文
- 不简单追求事件变长，要事件完整性和真实高光召回；**避免过度合并**
- 每个改动跑 step1/2/3 回归；真实 API 需用户明确要求
- 决策记录：`docs/DECISIONS.md`（D-029~D-040 为 v0.4，禁止随意推翻）

## 交接后新窗口的第一步建议
先读 `docs/HANDOVER_20260910.md`，再读本文件，然后：
1. 确认 `poc/v04_pipeline.py` 需要重设计成真正的 V0.4 主流程（Ch→St→Event），而非"加载旧结果重分组"。
2. 实施后再真实验证对比 B1。
