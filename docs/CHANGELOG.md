# CHANGELOG —— 版本变更日志

> 每次版本发布必须更新本文件 + VERSION_PLAN.md + DEVELOPMENT_LOG.md + AI_HANDOVER.md（规范 v1.0 要求）。
> 格式：版本 / 日期 / 新增 / 修改 / 删除 / 原因 / 测试结果。

---

## v0.5.1（2026-09-11，修打包漏文件：装到别的盘后语音识别必崩）

- **现象（用户装机实测，装在 D:////AILiveClipper）**：点识别就报「语音识别推理失败」，
  原始报错是 `onnxruntime NoSuchFile: Load model from
  .../_internal/faster_whisper/assets/silero_vad_v6.onnx failed`
- **根因**：`faster_whisper/assets/silero_vad_v6.onnx`（1.2 MB，人声检测模型）
  是这个包里**唯一的非 .py 文件**。打包配置只做了 `collect_submodules`（只收 .py），
  数据文件一个都没收 → **开发态永远正常**（读的是 venv 里的源文件），
  只有装到别的盘、真跑一次识别才炸。
- **修复**：
  - `packaging/live_clipper.spec`：显式收集 `faster_whisper/assets` 下所有文件
    （构建时会打印 `[spec] 已收进 faster_whisper/assets：['silero_vad_v6.onnx']`）
  - `asr/local_whisper.py`：这类"程序自带组件缺失"（NoSuchFile / onnx / silero）
    不再笼统归到「推理失败」，改判为 `dependency` 阶段，
    文案直说"程序组件不完整，建议重新安装"——**不是视频或模型的问题**
  - `desktop/ui/main_window.py`：错误弹窗除分类文案外也带上 `ProcessError.message`
    （以前只显示"缺少依赖组件"，看不出缺的到底是什么）
- **补上验收盲区（这次真正的教训）**：
  - `desktop_app.py`：自检时可设 `LIVE_CLIPPER_SMOKE_TRANSCRIBE=<视频>`，
    让装好的程序**真跑一次本地识别**，结果写进 `logs/desktop_smoke.json`
  - `packaging/verify_install.py`：新增该步骤的断言。
    之前只验"能 import / 能构造识别器 / 能找到 ffmpeg"——
    **这三样在漏文件时全都正常**，所以漏网。现在必须真跑一次才算过。
- **测试结果**：`verify_install` **33/33**（含「真的识别出内容了」）；
  `test_desktop_smoke` 52/52；`test_desktop_e2e` 24/24；回归 step7 20/20、UI 15/15、v045 18/18
- **交付**：`dist_setup/AI直播切片助手_Setup.exe`（138 MB）

---

## v0.5.0（2026-09-11，**完成**：产品化为 Windows 独立桌面软件）

> 目标：**下载一个 Setup.exe，双击装好，桌面快捷方式双击即用** —— 不需要 Python、不需要命令行、不需要浏览器。
> 核心分析算法（Chapter / Story / Event / Highlight / 评分 / 推荐）**一行不改**，只换"外壳"与"数据落点"。

### 阶段一～八 已完成（骨架 + 服务层 + 界面 + 模型管理 + ASR 抽象）

- **新增（路径层）**：
  - `app_paths.py`：唯一的路径解析入口。程序目录（只读）与用户数据目录（可写）彻底分开；
    优先级 = `LIVE_CLIPPER_HOME` 环境变量 → 打包态 `%LOCALAPPDATA%\AILiveClipper` → 开发态项目根。
    首次运行建目录 + 释放模板文件（存在就跳过）。详见 **D-047**
- **新增（服务层 `desktop/services/`，界面只跟它打交道）**：
  - `project_store.py`：**每个视频一份独立项目**（`projects/<项目ID>/project.json`）。
    状态机 created/transcribed/analyzed/failed，原子写（`.tmp` → `replace`），
    读时校验 `project_id` —— **从一个视频的结果串到另一个视频在结构上不可能发生**（延续 V0.4.4 要求）
  - `tasks.py`：`probe_video` / `import_video` / `transcribe_video` / `analyze_transcript` / `wrap_error`。
    **只做编排与包装**，直接调用原有 `pipeline.process_video` 与 `analysis.analyze_transcript_v2`
  - `model_manager.py`：Model Registry 的读、检测、下载安装（进度/断点续传/校验/卸载/沿用缓存）。详见 **D-049**
  - `settings_store.py`：用户设置（钥匙 / 直播类型 / 分析模式 / 数量模式 / 语音识别引擎），
    钥匙同时镜像到 `api_key.txt`，命令行与网页版行为一致
- **新增（ASR 抽象）**：
  - `asr/provider.py`：`AsrProvider` 约定 + `FasterWhisperProvider`（本地，`model_path` 直读目录 → 完全离线）
    + `CloudAsrProvider` / `TwoPassProvider`（**只预留接口**）
  - `asr/registry.py`：`build_provider(id)` / `list_providers()` / `DEFAULT_PROVIDER_ID`。详见 **D-048**
  - `asr/local_whisper.py`：新增 `model_path` 参数（`_load_from_dir`，不问 HuggingFace）
- **新增（界面 `desktop/ui/`，PySide6）**：
  - `main_window.py`：左侧项目列表 + 右侧四页签（⭐推荐剪辑 / 🧭直播内容结构 / 📺视频信息 / 🔧开发者视图）；
    耗时任务走后台线程（`desktop/workers.py`），界面不假死
  - `recommended_panel.py`：推荐卡片（排名 / 档位 / 分数 / 时间区间 / 建议时长 / 摘要 / 为什么值得剪 /
    风险 / 五维构成 / 所属 Chapter→Story / clip_id / 👍👎 反馈），支持「只看推荐 / 全部候选 / 只看被拒」
  - `structure_panel.py`：Video → Chapter（可折叠）→ Story（标题/时间/评分/档位/理由/推荐数）→ Event
  - `project_panel.py`：视频与项目信息、文字稿信息、分析概览
  - `developer_panel.py`：路径布局 / ASR 引擎与模型状态 / 元信息 / 成本 / 运行日志 / 完整结果 JSON（可复制）
  - `error_text.py`：沿用 D-046 分层思路的**桌面版**文案，并多给一步「点哪个按钮能修好」
  - `theme.py` / `widgets.py`：样式与共用控件（**展示层继续不露 S/A/B/C/D 字母**，D-044）
- **新增（入口 / 构建）**：
  - `desktop_app.py`：桌面版入口（工作区初始化 → 高 DPI → 主题 → 主窗口 → 首次运行模型检测）；
    支持 `LIVE_CLIPPER_SMOKE=1` 离屏自检（打包后没控制台，自检结果落 `logs/desktop_smoke.json`）
  - `models_registry.json`：Model Registry（tiny / base / **small 默认** / medium）
  - `packaging/`：`live_clipper.spec`（主程序 onedir）、`uninstaller.spec` + `uninstaller.py`、
    `setup.spec` + `setup_app.py` + `shortcuts.py`（安装程序，单文件 Setup.exe）
  - `build_desktop.py`：一键构建（卸载程序 → 主程序 → 合并 → LZMA 载荷 → Setup.exe）
  - `test_desktop_smoke.py`：桌面骨架自测（**52/52**，离线，不联网、不跑 ASR、不调 AI）
  - `test_desktop_e2e.py`：桌面版端到端实测（**24/24**，真跑本地 ASR：探测 → 导入 → 出稿 →
    项目落盘 → 界面绑定 → 两项目互不污染 → 四种错误仍分层）
  - `packaging/verify_install.py`：**30/30**（安装程序自检 + 模拟安装 + 装好的 exe 实机启动）
  - `packaging/make_screenshots.py` + `docs/screenshots/`：用**同一场 51 分钟真实结果**渲染的六张界面图

- **修改**：
  - `pipeline.py` / `analysis/{feedback,dictionary,event_scanner,deepseek_client,chapter_story}.py` / `ui.py`：
    路径改为问 `app_paths`（**开发态行为逐项一致**，不做算法改动）
- **未改动（硬约束）**：`analysis/` 的提示词、评分体系、Chapter/Story/Event 逻辑、推荐筛选、聚类与分批复审；
  `ui.py` 网页版功能；`main.py` 命令行入口

- **测试结果**：`test_desktop_smoke.py` **52/52**；`test_desktop_e2e.py` **24/24**（真跑本地 ASR）；
  `packaging/verify_install.py` **30/30**；回归 step1~7 = 23/21/24/17/11/24/20 全过；
  `test_ui_selftest.py` 15/15；`test_v045_asr_errors.py` 18/18

---

## v0.4.5（2026-09-11，修复本地 ASR 错误处理链路：分层提示 + 模型离线加载）

- **新增**：
  - `errors.py`：全项目统一的 `ProcessError(stage, message, detail)` + 10 个 stage 常量
  - `pipeline.check_video_readable()`：文件存在 / 非目录 / 非空 检查
  - `pipeline.probe_media()`：用 `ffmpeg -i` 探测媒体（可读性 / 有无音轨 / 时长），不额外引入 ffprobe
  - `ui.py._ASR_ERROR_UI` + `_asr_error_ui()`：按 stage 给「标题 + 该怎么做」的十条界面文案
  - `test_v045_asr_errors.py`（18 项，覆盖 7 种失败情况）
- **修改**：
  - `asr/local_whisper.py`：**模型改离线优先加载**（`local_files_only=True`，不再联网校验）；缓存里没有该模型时才联网下载；`ImportError` / `SystemExit(1)` 改为抛 `ProcessError`；`transcribe()` 用 try 包住整个惰性生成器循环（推理失败 → `asr_inference`）
  - `pipeline.extract_audio()` / `process_video()`：**失败改为抛 ProcessError（带 stage），不再返回 None**；流程显式拆成 可读性检查 → 媒体探测 → 音轨检测 → 音频提取
  - `pipeline.get_recognizer()`：只缓存**成功**的识别器（加载失败不留半成品）
  - `asr/__init__.py`：`ASR_BACKEND` 写错时抛 `ProcessError`（原为裸 `ValueError`，UI 只能显示"未知错误"）
  - `ui.py`：上传识别失败不再是「视频处理失败，请换一个文件试试」；按 stage 分别提示，完整 traceback / 原始 detail / 控制台输出放进「🔧 开发者」折叠区
  - `main.py`：把「判 None」改成 try/except ProcessError（行为等价，命令行也能看出是哪一层坏了）
  - `.gitignore`：加 `_test_media/`、`v045_asr_report.txt`、`_*.log`
- **删除**：`asr/local_whisper.py` 里的 `raise SystemExit(1)`（非 Exception，UI 的 `except Exception` 根本抓不到）
- **原因**：用户实测——**正常视频也统一提示「视频处理失败，请换一个文件试试」**。真因是加载本地 Whisper 模型时会联网校验，本机代理返回 502 Bad Gateway，异常被统一吞掉；而「损坏 / 没音轨 / 模型没装」也被压成同一句，无法区分，且看不到 traceback
- **测试结果**：test_v045_asr_errors.py **18/18**（7 种情况 stage 互不相同）；真实 6 分钟视频 41 句 / 85s 成功走完本地 ASR；测试视频2（51 分钟）不受影响；UI 自测 15/15；step1~6 回归全过

---

## v0.4.4（2026-09-11，修复严重数据绑定 bug：Chapter/Story 与当前视频绑定）

- **新增**：
  - `analysis/chapter_story.py`：**主流程内生成 Chapter/Story**（本视频现算）+ 按视频隔离的结构缓存
    - `cache_path_for()` / `load_cached_structure()` / `save_cached_structure()`（只认**同名 + 同时长**，否则返回 None）
    - `segment_chapters()` / `segment_stories()` / `get_or_build_structure()`（返回 `(data, source)`，source ∈ fresh/cache/empty）
  - `analysis/prompt_builder.py`：`CHAPTER_SYSTEM` / `STORY_SYSTEM` + `build_chapter_prompt()` / `build_story_prompt()`
  - `config.CHAPTER_STORY`（enabled / max_chapters / chapter_output_tokens / story_output_tokens / reuse_cache）
  - `test_v040_step7.py`（20 项，V0.4.4 验收）；`verify_v044_two_videos.py`（真实双视频验证）
- **修改**：
  - `analysis/story_context.py`：`load_structure()` / `load_story_groups()` 的 `source=None` **返回空**（不再隐式读固定样例）；统一 `_read_structure_source()` / `_stories_of()` 入口；兼容主流程 AI 输出的 `name`/`summary` 与 PoC 夹具的 `story_title`/`story_summary`
  - `analysis/__init__.py`：第 8 层改为 `chapter_story.get_or_build_structure(...)` 现算当前视频结构；返回值新增 `structure_source`；`_run_event_aggregation()` 加 `transcript_path` 参数，Story 先验改读**本视频缓存**
  - `config.STORY_CONTEXT`：**删除** `"story_file"`（固定 51 分钟样例路径，bug 源），新增 `"cache_dir": "structures"`
  - `ui.py`：无结构降级文案去掉对 `poc/story_segmentation_result.json` 的引用
  - PoC 夹具迁移 `poc/story_segmentation_result.json` + `poc/ai_chapter_result.json` → `poc/fixtures/`；`poc/*.py` 与 `test_*.py` 路径同步，测试显式传夹具路径
- **删除**：`config.STORY_CONTEXT["story_file"]`；`load_structure()` / `load_story_groups()` 对固定样例文件的默认读取与静默 fallback
- **原因**：用户实测发现——换任何视频，「推荐剪辑」正确但「直播内容结构」**永远显示开发阶段那场 51 分钟测试视频的固定 Chapter 01/02/03/04**。根因是 Chapter/Story 从未接主流程，结构一直读的是 PoC 写死的产物文件
- **测试结果**：test_v040_step7.py **20/20**（两视频结构各自对应、连续运行不互相继承、推荐与结构同源、缓存按视频隔离、无固定 fallback、step1~6 全量回归 OK）；test_ui_selftest.py **15/15**；step1~6 回归 23/21/24/17/11/24 零 FAIL；真实双视频验证见 `v044_two_videos_report.txt`

---

## v0.4.3（2026-09-11，界面去等级字母：展示层模糊化）

- **新增**：
  - `config.GRADE_RANK`（内部排序用）；`GRADE_UI` 改为模糊化两档映射
  - `analysis/prompt_builder._NO_GRADE_RULE`：禁止 AI 在 why_cut / risk / summary / 报告里写等级字母，追加到海选/复审/事件判断/报告四个 system
  - `ui.py._soften()`：展示层正则兜底，抹掉历史缓存或模型残留的「B级」字样
  - `test_ui_selftest.py` 新增「界面不露分级字母」检查
- **修改**：
  - 展示档位：S/A → 🌟 高光内容；B/C → ✨ 有看点（合并，避免「C 比 B 差」的隐性排序）；D 不显示徽章
  - 推荐层级：重点推荐 / 推荐 / 值得一看 / 备选参考（原「B 级补位 / C 级兜底」）
  - `_select_quantity` 落选理由去字母（「内容质量很高，但推荐数量已达目标」）
  - `analyze_v2.py` 控制台输出同步去字母
  - 开发者视图保留原始 `grade=X` 并标注「内部原始数据」
- **删除**：无（内部 grade 仍是 S/A/B/C/D，JSON 数据不变）
- **原因**：用户反馈「界面上写 B 级 / C 级，用户会以为 B/C 不值得剪」，错过有观看价值的内容
- **测试结果**：UI 自测 15/15；step1~6 全量回归 23/21/24/17/11/24 零 FAIL

---

## v0.4.2（2026-09-11，评分/推荐解耦 + 内容结构层 + 新版 UI）

- **新增**：
  - `analysis/__init__.py` → `_pick_recommendations()` + `_tier_of()`：**产品层推荐筛选**，与内容评分/评级解耦。策略 A 优先 → 高质量 B 补位 → C 兜底，D 永不推荐
  - `analysis/story_context.py` → `load_structure()` / `build_content_structure()`：**内容结构层**（Chapter → Story → Event），事件按时间交集挂到 Story，Story 评分 = 组内最强事件分（纯本地零成本）
  - `analyze_transcript_v2` 返回值新增 `structure` 段（第 8 层，构建失败静默降级为空结构）
  - config：`AUTO_SELECT_TARGET`(8) / `AUTO_B_FILL_MIN_SCORE`(60) / `AUTO_C_FALLBACK_MAX`(3) / `RECOMMEND_TIER_LABEL`
  - 高光条目新增字段：`recommended`（是否进推荐名单）、`recommend_tier`（S/A/B_fill/C_fallback）
  - **新版 UI**（ui.py 重写结果展示层）：📺 视频信息 → ⭐ 推荐剪辑 → 🧭 直播内容结构（Chapter 折叠 → Story 卡片）→ 🔧 开发者视图
  - test_v040_step6.py（24 项）+ test_ui_selftest.py（13 项）
- **修改**：
  - `_select_quantity` 三模式分支重写：自动精选不再等于「只取 S/A」；候选池/自定义数量语义不变，推荐标记独立计算
  - 被拒条目的 `reject_reason` 新增「X 级内容，但推荐数量已达目标（N 条）」说明（解耦的可见后果）
  - ui.py 中 `ai_recommend` 仅作兼容展示（原义 = S/A 内容级背书不变）；推荐卡片改用「推荐层级」徽章
  - Story 卡片内两个嵌套折叠合并为「评分依据与内容明细」一个（避免界面变调试页）
- **删除**：无（旧字段 `ai_recommend`、旧数量模式语义、开发者视图全部保留；旧格式结果无 `structure` 时静默降级）
- **原因**：真实 51 分钟稿跑出 13 条 B/C（最高 79.5）→ 旧自动精选因「只取 S/A」**输出 0 条高光**；同时旧 UI 只堆 JSON、用户看不懂整场直播结构
- **测试结果**：test_v040_step6.py 24/24；test_ui_selftest.py 13/13；回归 test_v040_step1~5 全过（23/21/24/17/11，零 FAIL）；真实 V0.4.1 结果回放：自动精选 0 条 → 8 条推荐

---

## v0.4 第三步（2026-09-09，复审改分批 + 上下文时间窗 + 动态时长 + 100 分制）

- **新增**：
  - 分批复审 `_review_in_batches`：按 `REVIEW_BATCH.max_events_per_batch`（默认 3）分批，每批独立复审，结果按 event_id 对号入座（禁依赖顺序）；AI 报 context_incomplete → 单独扩窗重审（最多 1 层深扩）
  - 复审上下文改时间窗口 `_event_review_context`：事件边界 ±60s 起步，可扩 ±180s/±300s；以事件边界为锚整段捞取，长事件不被截断；Context Window 与 Clip Duration 完全分离
  - 动态剪辑时长：复审 AI 输出 recommended_start/end/duration + duration_reason（不再固定 20/30/60s）；时长不设硬上限，实测最短 8s、最长 99s 的事件级推荐
  - 全局排序（Global Ranking）：分批复审后全量按 final_score 降序排（跨 batch 统一，消除前半段偏置）
  - 整场复盘报告独立调用 `_build_ai_report`（REPORT_SYSTEM），基于事件精华卡，与分批复审解耦
  - recommended 时间格式规范化 `_norm_rec_ts`（HH:MM:SS→mm:ss、越界钳回）+ 合理性 drift 校验（偏离事件边界 >120s 兜底）
  - 复审 schema 校验：缺 event_id/五维子分/recommended_* → 记 warning + 明确 fallback，绝不静默用 5 分掩盖；兼容嵌套 scores / 平铺 hook / hook_score / personality→persona 别名
- **修改**：
  - 评分升级 100 分制：`_weighted_final` 加权后 ×10（0-100 整数）；对外四档 S≥90/A≥80/B≥60/C≥50，D<50 仅内部淘汰（原 1-10 制 ×10 语义同构）
  - config 新增 REVIEW_CONTEXT / REVIEW_BATCH / REPORT_OUTPUT_TOKENS / GRADE_UI / RECOMMEND_MAX_DRIFT；REVIEW_MAX_OUTPUT_TOKENS 6000→2000（分批单事件量小）
  - `_parse_review_reply` 不再返回整场 report（报告拆到 `_build_ai_report`）
- **原因**：事件聚合后单事件原文变长，一次审完所有事件会 prompt 过大、后半段被忽略、前半段偏置；固定时长破坏真实剪辑逻辑；1-10 分区分度不足
- **测试结果**：test_v040_step3.py 24/24 过；test_v040_step1.py 23/23 回归过；test_v040_step2.py 21/21 回归过；真实 API 51 分钟稿（标准模式）两次跑通，罐头事件正确聚合为完整高光、动态时长跨 8s~99s、recommended 格式统一

---

## v0.4 第二步（2026-09-09，事件聚合层：从「评价一句话」升级为「评价一件事」）

- 新增：
  - **analysis/event_cluster.py**（本地粗聚类）：soft signals（时间距离 0.30 / 时间重叠 0.25 / 主题相似 0.30 / 相邻加分 0.15）给候选两两打关联分 → 连通分量成簇；**孤立候选自成一簇绝不删**；无任何「超过 X 秒就断开」的硬规则
  - **AI 事件判断（Event Judge）**：`prompt_builder.build_event_judge_prompt` + `EVENT_JUDGE_SYSTEM`，判断一簇候选是否同一件事，输出 event_summary / event_type / event_start/end / structure{setup,development,payoff} / strongest_moment / reason / confidence / need_more_context + expand_direction（自适应上下文）
  - **事件级候选**：`_make_event`（event_id/clip_id/cluster_id/source_candidates/source_count/judge_reason/split_by_ai 等），`_dedupe_events`（时间重叠>50% 且主题相同才合并），`_run_event_aggregation`（聚合主编排：粗聚类→AI 判断→自适应扩大→去重）
  - config.py 的 v0.4 第二步配置段：EVENT_CLUSTER / EVENT_JUDGE_CONTEXT / EVENT_JUDGE_MAX_OUTPUT_TOKENS / EVENT_REVIEW_CONTEXT_LIMIT
  - **test_v040_step2.py**（离线自测 6 场景 21 项，含事件级完整流程，报告写 v040_step2_report.txt）
- 修改：
  - analysis/__init__.py：主流程在海选/质检之后、复审之前插入事件聚合层（先聚合再评分）；复审对象从「候选」换成「事件」；`_format_events_for_review`（事件清单含结构/最强爆点/来源）；复审合并优先按 event_id 对号入座
  - analysis/prompt_builder.py：复审提示词改为「审一件事」视角 + results 条目补 event_id 字段；新增事件判断提示词
  - **修 3 个潜伏 bug**：① 复审提示词缺 event_id 字段（AI 漏条乱序会错位）② 五维子分键名不一致（提示词 hook_score vs 解析器 hook，真实 API 下全会回落 5 分）③ 事件拆分时共用 judge 边界导致去重误合并（D-035）
- 删除：无（v0.3 候选级能力全部保留，只是复审基本单位从「候选」换成「事件」）
- 原因：v0.4 核心目标「让 AI 理解完整事件并判断传播价值」（D-025）。人工测试发现最大问题不是找不到爆点，而是「AI 把一个完整事件拆成碎片、排序不符合人工判断」，所以先做事件聚合层验证「事件单位」是否正确
- 测试结果：离线自测 **21/21 全过**（本地聚类 6 项含长事件不硬拆/孤立不删/全覆盖、解析 3 项、事件生成 3 项、去重 2 项、聚合编排 5 项、事件级完整流程 3 项含负面封顶/零输出禁令不回退）；真实 API 跑 51 分钟稿：**19 候选 → 16 事件（AI 合并 3 次、拆分 2 次、上下文扩大 2 次、去重 0）**，动态时长生效（高光 11 秒~162 秒），关键爆点「2014 罐头异物」正确聚合为 2.6 分钟完整事件（B 级 7.8 分，全场最高），成本 ¥0.3078

## v0.4 第一步（2026-09-09，词库纠错 + 人工反馈：先把输入弄干净、把判断攒下来）

- 新增：
  - **analysis/dictionary.py**（ASR 词库纠错）：加载 custom_dictionary.json（分类结构摊平成对照表）→ 纯字符串替换；提供 apply_correction（文本）/ correct_segments（识别结果，dict 与 Segment 对象都支持）/ correct_transcript_file（文字稿文件，只改台词）/ create_dictionary_template（生成模板）；文件不存在或写坏 → 空表不崩
  - **custom_dictionary.json**（项目根目录，用户可自己改）：按「主播名字 / 游戏名称 / 品牌 / 网络热词 / 其他」分类，示例已填「福岛→伏特加」「和平经营→和平精英」「英雄连门→英雄联盟」
  - **analysis/feedback.py**（人工反馈记录）：本地 feedback.json（JSON 数组），字段 clip_id / user_choice / reason / timestamp + 可选 snapshot；同一 clip_id 覆盖并继承旧 snapshot；文件写坏自动备份为 feedback.corrupt.json 后重新开始
  - **test_v040_step1.py**（离线自测 5 场景 23 项，纯本地零成本，报告写 v040_step1_report.txt）
  - config.py 的 v0.4 配置段：CUSTOM_DICTIONARY_FILE / FEEDBACK_FILE / FEEDBACK_CHOICES / FEEDBACK_REASONS
- 修改：
  - pipeline.py：新增 apply_dictionary（识别完、存稿前纠错，返回改了几处）与 correct_existing_transcript（历史稿单独纠错）；process_video 在「语音识别」之后、「存文字稿」之前自动纠错一步，返回结果新增 dictionary_hits 字段
  - config.py：新增 v0.4 第一段配置（见上）
- 删除：无（旧流程全部保留兼容，main.py 命令行行为不变）
- 原因：v0.4 的总目标是把 AI 从「寻找片段」升级为「理解事件并判断传播价值」（D-025）。第一步先做两件不碰 AI 判断逻辑的基础能力——**输入干净了 AI 才判断得准**（词库纠错），**反馈攒下来了将来才有得学**（feedback.json）。两个都是纯本地零成本，可以先把地基打稳再动核心链路
- 测试结果：离线自测 **23/23 全过**（词库加载 6 项含坏 JSON/缺文件容错、文本替换 4 项含长词优先、识别结果纠正 2 项、文字稿纠正 4 项含「时间戳一个字没变」、反馈记录 7 项含同 id 覆盖与坏文件自愈）；py_compile 全过；真实链路验证「福岛→伏特加」「和平经营→和平精英」替换成功

## v0.3.2 第二步（2026-09-09，评分体系 v3：把 AI 从「总结助手」变成「短视频运营剪辑师」）

- 新增：test_v032.py（离线自测 4 场景 18 项，假 AI 客户端零成本）；config.py 的 v0.3.2 配置段（SCORE_V3_WEIGHTS / GRADE_S_SCORE / NEGATIVE_RULES / NEGATIVE_RULE_CAP_GRADE）
- 修改：
  - config.py：五维权重 v3（三秒吸引力 30 / 反差意外 25 / 人物表现力 20 / 独立成片 15 / 事件完整度 10）；S 级线 9.0；「不值得剪」负面清单 5 条 + 封顶规则（命中最高 B 级）；REVIEW_MAX_OUTPUT_TOKENS 4000→6000；LIVE_TYPE_WEIGHTS 文案换成 v3 视角
  - prompt_builder.py：海选提示词加 v3 判断视角（一个不认识主播的新用户刷到开头 3 秒，为什么会停下来）+ 假高光警惕清单；复审模板重写——**AI 只打五维子分（1-10），不再直接输出总分和等级**；新增典型案例校准（黄腐鸡误当咖啡/军粮像纸盒子/罐头像指甲盖 = 高价值；饮料粉洒出来/「哇好少」= 低价值）+ 负面清单标记 negative_flags + why_cut/risk 双理由必答
  - analysis/__init__.py：新增**本地定级引擎**——_weighted_final（按权重加权算总分，可解释可审计）、_grade_from_score（S/A/B/C/D 五级映射）、_apply_negative_cap（命中负面清单封顶 B，只降不升）、_entry_dims（中文五维判决书）；复审合并逻辑改用五维子分定级；D 级淘汰理由本地组装；数量模式重定义（自动精选=S/A；候选池=S/A/B/C；自定义=按分取前 N 标注质量名）
  - ui.py：结果卡片升级 S/A/B/C 四徽章 + 五维判决书进度条（逐维显示「三秒吸引力 8分」）+ 负面封顶 warning + 最大风险展示
- 删除：复审 AI 直接输出 final_score/grade 的旧格式（回复里带了也忽略，全部以本地定级引擎为准）
- 原因：真实测试 + 人工复盘发现 AI 仍在当「直播内容总结助手」——饮料粉洒出来、军粮份量少这类「事故型」片段被评高分，部分 B 级反而比 A 级更适合做短视频。判断标准要从「发生了什么」换成「陌生用户刷到为什么要停下来」
- 测试结果：离线自测 18/18 全过（51 分钟稿全流程：S/A 精选 12 个、D 档全进 rejected、五维判决书中文标签完整、命中负面规则封顶 B、零输出禁令两条路径、质检坏 JSON 不崩）；lint 0 错误；待用户真实视频做人工命中率验收

## v0.3.2 第一步（2026-09-09，Phase 3 UI 接入：网页版切到 v2 流程）

- 新增：无新文件（改动集中在 ui.py）
- 修改：ui.py 全面重写——①「开始分析」从旧 v0.2 流程切换到 analyze_transcript_v2；②侧边栏新增三设置（直播类型下拉 / 分析模式带描述单选 / 数量模式 + 自定义个数）；③文字稿与 AI 分析拆成两步（识别过的稿子直接换设置重跑，不重复烧 ASR）；④运行前预算预估（时长/区块数、预计 token、预计费用，超预算提示自动降级，D-015）；⑤结果区改 A/B/C 分级卡片（三类高光/评分/置信度/剪辑建议/forced_keep 标记/clip_id）+ AI 分析报告四字段 + 被拒候选（带拒绝理由）+ 完整 JSON 下载
- 删除：旧版高光卡片渲染（评分/时间段/标题/理由的 v0.2 格式；命令行 main.py 旧流程不动，保留兼容）
- 原因：v0.3.1 判断链路已过真实 API 验证，UI 严重滞后（停留在 v0.2），用户准备多视频做精准度测试需要脱离命令行
- 测试结果：语法编译通过；Streamlit 服务启动 HTTP 200；待用户用真实视频实测（👍/👎 反馈按钮留到下一步）

## v0.3.1（2026-09-09，召回优先 + 分级输出，待真实 API 复测）

- 新增：漏检质检层（prompt_builder.build_miss_check_prompt + 编排器第 5.5 层 + 重扫 second_pass）、test_v031.py、clip_id 字段
- 修改：config.py（精细预算 8 万 / A-B-C 分级线 / 质检配置 / 删 MIN_QUALITY_SCORE、HIGH_QUALITY_SCORE）；prompt_builder.py（海选宁多勿少 + 三类高光 + 权重 v2；复审 A/B/C/D 分级 + 零输出禁令）；analysis/__init__.py（质检重扫 + 分级合并 + 零输出兜底 + 数量模式按分级重定义）；budget.py（计入质检/重扫）；analyze_v2.py（打印分级）
- 删除：复审二元 recommend 输出格式（兼容读入保留，输出改为 grade + ai_recommend 派生字段）
- 原因：P0 首测 0 推荐被人工复盘推翻——海选漏掉大量潜在高光 + 复审过严。策略调整为「先保证召回率，再保证精准率」（D-017~D-021）
- 测试结果：离线自测（FakeClient）14/14 项通过；真实 API 复测通过（精细模式 ¥0.19：36 候选、质检查出 2 个漏检区块重扫、7A/19B/10C 分级、上版漏掉的爆点全部召回、不再零推荐）

## 2026-09-09  开发规范升级（无代码变更）

- 新增：docs/CHANGELOG.md（本文件）
- 修改：VERSION_PLAN.md（长期路线 + P0-P3 优先级）、DECISIONS.md（D-012 ~ D-015）、AI_HANDOVER.md（交接记录格式、开发原则）、ARCHITECTURE.md（规划中模块）
- 删除：无
- 原因：用户下发《长期开发规范 v1.0》，明确平台不绑定、五维评分标准、文本纠错优先级提升（P1）、云端部署方向（本地 ASR + 云端 AI 分析）、Token 预估展示要求
- 测试结果：纯文档变更，不涉及代码

## v0.3 Phase 2（2026-09-09，待真实 API 实测）

- 新增：analysis/budget.py、analyze_v2.py、test_phase2.py、docs/ 交接文档体系（5 文件）
- 修改：config.py（TOKEN_MODES/QUANTITY_MODES/LIVE_TYPE_WEIGHTS/评分阈值）、prompt_builder.py（海选+复审提示词）、deepseek_client.py（CostTracker）、chunker.py（粗切降级参数）、analysis/__init__.py（analyze_transcript_v2 编排器）
- 删除：无（v0.2 全流程保留兼容）
- 原因：AI 身份从总结助手改为短视频运营；增加淘汰机制与分析报告；Token 预算控制
- 测试结果：离线自测（FakeClient）23/23 项通过；真实 API 实测待 DEEPSEEK_API_KEY

## v0.3 Phase 1（2026-09-09）

- 新增：analysis/transcript_parser.py、event_scanner.py、chunker.py、test_phase1.py、user_lexicon.txt
- 修改：config.py（BUCKET/HOT_CHUNK 等配置）
- 删除：无
- 原因：解决 v0.2 前半段偏置与截断丢内容问题；扫描层只调深度绝不过滤
- 测试结果：51:39 真实稿 14 区块，时间轴覆盖 100%；类型词库区分有效（娱乐 54 分 vs 游戏 0 分）

## v0.2.2（2026-09-09，提交 e269f8f，标签 v0.2.2）

- 新增：TUTORIAL.md
- 修改：ui.py（四步任务清单/进度条/日志进网页/署名）、start_webui.bat
- 原因：网页版操作可视化，降低使用门槛
- 测试结果：网页版全流程可用

## v0.2 ~ v0.2.1（2026-09-08 ~ 09）

- 新增：pipeline.py、ui.py（Streamlit）、start_webui.bat
- 修改：main.py（变薄壳，行为不变）
- 原因：抽出核心流程便于复用；提供网页界面；API Key 网页填写
- 测试结果：命令行行为回归通过；修 subprocess GBK 解码崩溃

## v0.1 MVP（2026-09-08 ~ 09，提交 bd5dc20，标签 MVP-v0.1）

- 新增：main.py、config.py、asr/（可插拔识别器）、analysis/（DeepSeek 单次分析）、videos/、audio/、transcripts/
- 原因：打通最小闭环：视频 → 音频 → 文字稿 → AI 分析
- 测试结果：6.5 分钟测试视频识别 41 句成功
