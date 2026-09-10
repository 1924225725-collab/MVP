# AI_HANDOVER —— AI 开发工具交接文档

> 任何 AI 开发工具（WorkBuddy / Cursor / Claude Code 等）接手本项目时，**第一步必须读完本文件**。
> 每完成一个版本，必须按文末格式追加更新记录。

---

## 项目目标

构建一个能够**模拟专业直播运营判断能力**的 AI 高光切片系统。

核心判断不是「哪里有内容？」，而是：

> **「哪里值得剪成短视频，并且有传播价值？」**

后续所有版本开发必须围绕这个目标。外围优化（词库扩展、用户画像、反馈分析）
只有在核心判断能力验证之后才允许投入。

---

## 当前版本

- 版本：**v0.4 第三步**（复审改分批 + 上下文时间窗 + 动态时长 + 100 分制；离线 24/24，真实 API 51 分钟稿跑通）｜上一版 v0.3.2 已定稿，v0.3 标签已上架 GitHub
- 仓库：https://github.com/1924225725-collab/MVP.git（私有；原 ai-.git 会重定向到新地址）
- 标签：MVP-v0.1（bd5dc20）、v0.2.2（e269f8f）、**v0.3（eeb3ffc，已上架）**
- 运行环境：Windows + Python 3.14.7，依赖装在 `.venv`（用 `.\.venv\Scripts\python xxx.py` 运行）

## 技术栈

| 环节 | 技术 |
|---|---|
| 音频提取 | ffmpeg 7.1（imageio-ffmpeg 自带，subprocess 调用） |
| 语音识别 | faster-whisper small（CPU int8，language=zh，vad_filter） |
| AI 分析 | DeepSeek chat API（requests 调用，deepseek-chat 模型） |
| 网页界面 | Streamlit（不用 React，用户明确要求） |

## 当前架构

见 [ARCHITECTURE.md](ARCHITECTURE.md)。一句话版：

```
视频 → ffmpeg 提取音频 → Whisper 识别 → 带时间戳文字稿
  → 候选信号扫描（每分钟打分，只调深度绝不过滤）
  → 智能分区（热区细切/普通区粗切，时间轴 100% 覆盖铁律）
  → AI 海选（每区块独立，召回优先宁多勿少，三类高光：事件/情绪/梗；
      判断视角「陌生用户刷到开头 3 秒为什么会停下来」）
  → 漏检质检（本地区块摘要 → 质检 AI 查漏 → 可疑区块重扫并入）
  → 事件聚合（v0.4 步骤 2：本地 soft-signal 粗聚类 → AI 事件判断是否同一件事
      + 边界/结构/最强爆点 → 事件级去重；先聚合再评分）
  → 事件池 → AI 分批复审（v0.4 步骤 3：按批独立审「事件」，上下文=事件边界±时间缓冲
      （默认 ±60s 可扩 ±180/±300），只打五维子分 → 本地加权 ×10 得 100 分制 → S/A/B/C 四档
      + 负面清单封顶 B + why_cut/risk + 动态 recommended_start/end/duration + duration_reason）
  → Global Ranking（跨 batch 按 final_score 全局排）→ 独立整场报告 _build_ai_report
  → 数量模式选择（自动精选=S/A / 候选池=S/A/B/C / 自定义=前N分层）
  → highlights 输出（含 event_id/clip_id + 100 分制 score + recommended_*，为未来 👍/👎 反馈记账）
```

## 核心设计原则

1. **扫描层不是过滤层**：所有时间段必须进入 AI 分析流程，一秒都不许跳过。
2. **时间轴 100% 覆盖铁律**：分区必须无漏盖、无重叠（`chunker.check_coverage` 验收）。
3. **AI 是运营不是观众**：提示词身份是「直播短视频运营人员」，判断的是传播价值，不是内容总结。判断标准是「一个不认识主播的新用户刷到，为什么会停下来？」
4. **情绪价值 ≠ 传播价值**：感人但没有冲突/讨论点/观看动力的片段必须被拒绝（复审淘汰机制）。普通失误/单纯惊讶同理——「有事故」不等于「有传播结构」。
5. **API Key 绝不进代码/仓库**：环境变量 `DEEPSEEK_API_KEY` 或 `api_key.txt`（已 gitignore）。
6. **小步开发**：用户是 Python 初学者，一次只做一步，不提前写后续功能。
7. **平台不绑定**（规范 v1.0，见 D-016）：任何 AI 工具只是开发辅助，交接只靠本 docs/ 体系。
8. **禁止大规模重构**（规范 v1.0）：新功能优先新增模块（如 analysis/correction.py），不破坏 asr/、pipeline.py、main.py、ui.py、analysis/ 的既有接口。
9. **新功能四问**（规范 v1.0 最终原则）：提升判断准确率？降低使用门槛？增加商业价值？不会造成维护困难？——答不清楚就不开发。
10. **总分与等级由本地定，不让 AI 自评**（v0.3.2，D-022）：复审 AI 只打五维子分，`_weighted_final` 本地加权算总分、`_grade_from_score` 本地定级、`_apply_negative_cap` 负面清单命中封顶 B——定级可解释、可审计，杜绝「先给漂亮理由再顺手打高分」。

## 已完成模块

| 模块 | 文件 | 状态 |
|---|---|---|
| 视频扫描/音频提取 | pipeline.py | ✅ v0.1 |
| 本地语音识别 | asr/（base + local_whisper + cloud_api 空壳 + 工厂） | ✅ v0.1 |
| 旧版单次 AI 分析（v0.2 兼容） | analysis/prompt_builder.py + __init__.py + analyze.py | ✅ 保留运行 |
| 网页版 | ui.py + start_webui.bat | ✅ v0.2.2 |
| 时间戳解析 | analysis/transcript_parser.py | ✅ v0.3 P1 |
| 候选信号扫描 | analysis/event_scanner.py（5 类型词库 + 用户词库） | ✅ v0.3 P1 |
| 智能分区 | analysis/chunker.py | ✅ v0.3 P1 |
| AI 海选 + 复审 + 定级引擎 | analysis/__init__.py（analyze_transcript_v2；五维子分复审 + 本地加权定级 S/A/B/C/D + 负面封顶 B） | ✅ v0.3.2（待真实视频验收） |
| 网页版 v2 界面 | ui.py（v2 流程 + 三设置 + 预算预估 + S/A/B/C 徽章 + 五维判决书） | ✅ v0.3.2 第二步（反馈按钮待做） |
| ASR 词库纠错 | analysis/dictionary.py + custom_dictionary.json | ✅ v0.4 第一步（基础版纯替换，已接入 pipeline） |
| 人工反馈记录 | analysis/feedback.py + feedback.json | ✅ v0.4 第一步（本地记录，UI 按钮待接） |
| 事件聚合层 | analysis/event_cluster.py + __init__.py（_run_event_aggregation / _make_event / _dedupe_events）+ prompt_builder.build_event_judge_prompt | ✅ v0.4 第二步（本地粗聚类 + AI 事件判断 + 事件级去重；真实 API 跑通 19 候选→16 事件） |
| 分批复审 + 100 分制 + 动态时长 | __init__.py（_review_in_batches / _event_review_context / _build_ai_report / _norm_rec_ts / _parse_review_reply schema 校验）+ prompt_builder（_REVIEW_TEMPLATE 分批复审 / build_report_prompt）+ config（REVIEW_CONTEXT / REVIEW_BATCH / 100 分制阈值） | ✅ v0.4 第三步（24/24 离线；真实 API 51 分钟稿：分 4 批复审 + 3 次扩窗、100 分制 B 级为主、动态时长 8s~99s） |

## 未完成任务

- **v0.4 步骤 4（下一步）**：UI 接入（事件卡片 + 100 分制显示 + recommended 动态时长展示 + 👍/👎 反馈按钮 + 词库管理页）+ 5 项验收（见 VERSION_PLAN）
- **D-040 已知风险（步骤 4 候选）**：degrade_level 2/3（候选稀疏）时，步骤 2 事件聚合可能把同一长事件拆碎（真实 API 第一次跑把罐头事件拆成 3 碎片全 D，第二次候选稍多则正确聚合）——跨区块稀疏候选的再合并/更宽容聚类，列步骤 4 或聚合专项优化
- **P0（并行）**：真实视频人工命中率验收——用户准备素材中。v0.4 验收标准第 5 条：「人工选择 TOP10，AI 命中率明显提高」
- **P3**：云端 AI 接口（本地 ASR + 云端分析，见 D-013，v0.5）
- 后续小版本候选：D 级≥3 自动重审、S 级数量上限等附加保险丝（刻意未叠，防规则无法归因）
- 明确推迟：AI 自动发现词库、上下文感知纠错（高级版）、反馈数据分析与训练（v0.5/v1.0）

> 已完成的原 P1/P2 项：词库纠错基础版（v0.4 第一步 ✅）、反馈记录模块（v0.4 第一步 ✅，UI 按钮随步骤 4 做）。

## 禁止破坏的接口

1. `asr/base.py`：`Segment(start, end, text)` + `BaseRecognizer.transcribe()`——所有识别器的契约。
2. `pipeline.py` 各函数签名：`main.py` / `ui.py` 依赖。
3. `analysis.analyze_transcript(transcript_path) -> list`：`analyze.py`（v0.2 命令行流程）仍在调用；ui.py 已改用 `analyze_transcript_v2`。
4. 文字稿格式：`[mm:ss - mm:ss] 台词`（transcripts/ 目录，UTF-8）。
5. `user_lexicon.txt` 一行一词、`#` 注释格式。
6. 命令行入口 `main.py` 的行为（用户已习惯）。

---

## 版本更新记录

> 每完成一个版本，按以下格式追加（规范 v1.0 要求含删除/原因/测试结果；同时更新 CHANGELOG.md）：

```
### 版本：vX.Y
日期：YYYY-MM-DD
完成内容：xxx
新增：xxx
修改：xxx
删除：xxx
原因：xxx
测试结果：xxx
下一步：xxx
```

### 版本：v0.3.2 第二步（2026-09-09）
日期：2026-09-09
完成内容：评分体系 v3 重构——把 AI 从「直播总结助手」变成「短视频运营剪辑师」
新增：test_v032.py（离线 4 场景 18 项）；config 的 v0.3.2 段（SCORE_V3_WEIGHTS / GRADE_S_SCORE / NEGATIVE_RULES / NEGATIVE_RULE_CAP_GRADE）
修改：prompt_builder.py（海选 v3 视角 + 假高光警惕；复审只输出五维子分 + 典型案例校准 + why_cut/risk 双理由 + 负面清单标记）；analysis/__init__.py（本地定级引擎：加权算分 / S/A/B/C/D 五级 / 负面封顶 B / 中文五维判决书；数量模式重定义：自动精选=S/A、候选池=S/A/B/C）；config.py（五维权重 v3、S 线 9.0、REVIEW_MAX_OUTPUT_TOKENS 4000→6000、类型侧重文案 v3）；ui.py（S/A/B/C 徽章 + 五维判决书进度条 + 封顶警示 + risk）
删除：复审 AI 直接输出 final_score/grade 的格式（读入兼容，定级一律本地算）
原因：真实复测 7A 中混入事故型垃圾高光（饮料粉洒出来/军粮份量少），部分 B 级反而更有短视频潜质——判断视角要换成「陌生用户刷到为何停留」
测试结果：离线自测 18/18 全过（自动精选 S/A 12 个、D 档全进 rejected、负面命中封顶 B、零输出禁令两路径、质检坏 JSON 不崩）；lint 0 错误
下一步：真实视频人工命中率验收（用户准备素材）→ 👍/👎 反馈按钮 → 词库管理页面

### 版本：v0.3.2 第一步（2026-09-09）
日期：2026-09-09
完成内容：Phase 3 UI 接入第一步——网页版从 v0.2 旧流程切换到 v2 分析流程
新增：无新文件
修改：ui.py 全面重写——侧边栏三设置（直播类型/分析模式/数量模式+自定义个数）；文字稿与 AI 分析拆两步（已有稿可直接换设置重跑）；运行前预算预估（token/费用/超预算降级提示，D-015）；结果区 A/B/C 分级卡片（三类高光/置信度/剪辑建议/forced_keep/clip_id）+ AI 分析报告四字段 + 被拒候选 + JSON 下载
删除：ui.py 旧版 v0.2 高光卡片渲染（main.py 命令行旧流程保留兼容）
原因：判断链路 v0.3.1 已过真实 API 验证，UI 停留在 v0.2 严重滞后；用户准备多视频做精准度测试需要脱离命令行
测试结果：py_compile 语法通过；Streamlit 启动 HTTP 200；待用户真实视频实测
下一步：①用户用准备的视频实测界面 ②加 👍/👎 反馈按钮写 feedback.jsonl ③词库管理页面（P1）

### 版本：v0.3.1（2026-09-09）
日期：2026-09-09
完成内容：高光识别准确率优化——召回优先 + 漏检质检 + A/B/C 分级输出（策略转变见 D-017）
新增：漏检质检层（prompt_builder 质检/重扫提示词 + 编排器第 5.5 层）、test_v031.py、clip_id/highlight_type/grade/forced_keep 字段
修改：config.py（精细预算 8 万、分级线、质检配置）、prompt_builder.py（海选召回优先 + 三类高光 + 权重 v2、复审分级 + 零输出禁令）、analysis/__init__.py、budget.py、analyze_v2.py
删除：复审 recommend 输出格式（读入兼容保留）；config 的 MIN_QUALITY_SCORE/HIGH_QUALITY_SCORE（被 GRADE_* 取代）
原因：P0 首测 0 推荐被人工复盘推翻，海选漏检 + 复审过严，改为先召回再精准
测试结果：离线自测 14/14 项通过；真实 API 复测通过（精细模式 ¥0.19：36 候选 / 质检重扫 2 区块 / 7A+19B+10C / 上版漏掉的爆点全部召回，不再零推荐）
下一步：人工标注测试（3 类直播各标 10 个，目标召回 >70% / 精准 >50%）→ Phase 3 UI 接入

### 版本：开发规范 v1.0 落地（2026-09-09）
日期：2026-09-09
完成内容：吸收《长期开发规范 v1.0》，文档体系升级，无代码变更
新增：docs/CHANGELOG.md；DECISIONS D-012~D-016（五维评分标准 / 云端架构 / 文本纠错提前 P1 / Token 预估展示 / 平台不绑定）
修改：AI_HANDOVER（交接记录格式 + 开发原则 7~9）、VERSION_PLAN（长期路线 v0.3→v1.0 + P0-P3 优先级）、ARCHITECTURE（规划中模块）
删除：无
原因：用户下发规范 v1.0，明确长期目标、优先级与交接纪律
测试结果：纯文档变更
下一步：P0 真实 AI 测试（需 DEEPSEEK_API_KEY）

### 版本：v0.3 Phase 1（2026-09-09）
完成内容：纯本地分析层（解析→信号扫描→智能分区），零成本
新增：analysis/transcript_parser.py、event_scanner.py、chunker.py、test_phase1.py、user_lexicon.txt
修改：config.py（BUCKET/HOT_CHUNK 等配置）
验收：51:39 真实稿 14 区块，时间轴覆盖 100%；娱乐词库 54 分 vs 游戏词库 0 分（区分有效）
下一步：Phase 2 AI 海选 + 复审

### 版本：v0.3 Phase 2（开发中，2026-09-09）
完成内容：AI 海选 + AI 复审（淘汰机制）+ AI 分析报告 + Token 三模式三级降级 + 数量三模式（离线自测通过，待真实 API 实测）
新增：analysis/budget.py、analyze_v2.py、test_phase2.py、docs/ 文档体系
修改：config.py（TOKEN_MODES/QUANTITY_MODES/LIVE_TYPE_WEIGHTS）、prompt_builder.py（海选/复审提示词）、deepseek_client.py（CostTracker）、chunker.py（粗切降级参数）、analysis/__init__.py（analyze_transcript_v2）
下一步：设 DEEPSEEK_API_KEY 后 analyze_v2.py 实测；Phase 3 UI 接入

### 版本：v0.2.2（2026-09-09）
完成内容：网页版四步任务清单 + 总进度条 + 终端日志进网页 + 开发者署名「夜雨声烦」；TUTORIAL.md
新增：TUTORIAL.md
修改：ui.py、start_webui.bat
提交：e269f8f，标签 v0.2.2

### 版本：v0.2 ~ v0.2.1（2026-09-08 ~ 09）
完成内容：pipeline.py 流程抽离、Streamlit 网页版、网页填 API Key、双击启动、修 subprocess GBK 解码 bug
新增：pipeline.py、ui.py、start_webui.bat
提交：并入 v0.2.2

### 版本：MVP v0.1（2026-09-08 ~ 09）
完成内容：MP4 → ffmpeg 提取音频 → faster-whisper 识别 → 带时间戳文字稿；DeepSeek 单次分析模块
新增：main.py、config.py、asr/、analysis/、analyze.py
提交：bd5dc20，标签 MVP-v0.1
