# ARCHITECTURE —— 系统架构

> 任何架构调整必须同步更新本文件。

## 整体流水线

```
视频（videos/xxx.mp4）
   │  pipeline.extract_audio（ffmpeg，16kHz 单声道 MP3）
   ▼
音频（audio/xxx.mp3）
   │  pipeline.transcribe_audio（faster-whisper，asr/ 可插拔工厂）
   ▼
带时间戳文字稿（transcripts/xxx.txt，格式：[mm:ss - mm:ss] 台词）
   │
   │  ★ v0.4：pipeline.apply_dictionary（ASR 词库纠错）
   │    custom_dictionary.json 对照表 → 纯字符串替换
   │    只改台词、时间戳一个字不动；历史稿用 correct_existing_transcript 补
   ▼
干净的文字稿
   │
   │ ─────────── 以下为 v0.3 多阶段分析流水线 ───────────
   │
   ▼
① transcript_parser   时间戳解析 → [{start, end, text}]（秒级）
   ▼
② event_scanner       候选信号扫描：每分钟一格打分（强词×2 + 普词×1）
   │                  词库 = 通用强词 + 5 类型词库 + 用户词库（user_lexicon.txt）
   │                  铁律：只调分析深度，绝不过滤区域
   ▼
③ chunker             智能分区：热区桥接 → 热区≤180s 细切 / 普通区≤600s 粗切
   │                  check_coverage() 验收时间轴 100% 覆盖
   ▼
④ 预算规划（budget）   Token 三模式（快速 1 万 / 标准 2 万 / 精细 8 万）
   │                  超预算三级降级：粗切 → 限候选 → 提示继续
   ▼
⑤ AI 海选（prompt_builder.build_screening_prompt）
   │                  每个区块独立调 DeepSeek，短视频运营视角找候选
   │                  身份：直播短视频运营人员，不是总结助手
   │                  v0.3.1 召回优先：宁多勿少，每区块至少 1 候选（D-017）
   │                  三类高光：事件型 / 情绪型 / 梗型（D-020）
   ▼
⑤.5 漏检质检（build_miss_check_prompt，一次调用 + 限次重扫）
   │                  本地区块摘要（热/普 + 信号分 + 候选数 + 强词关键句）
   │                  → 质检 AI 查「有没有区块明显有爆点却没进池」
   │                  → 可疑区块用更宽标准重扫（second_pass），去重并入（D-019）
   ▼
候选池（每个候选带原文节选 context + clip_id）
   ▼
⑤.6 事件聚合（v0.4 步骤 2）
   │                  event_cluster.build_clusters：soft signals 粗聚类（连通分量，孤立候选自成一簇不删）
   │                  → AI 事件判断 build_event_judge_prompt：是否同一件事 + 边界/摘要/结构/最强爆点
   │                  自适应上下文：先 ±90s，need_more_context 再扩到 ±240s（最多 1 轮）
   │                  _dedupe_events：时间重叠>50% 且主题相同 → 合并（先聚合再评分，D-029~D-035）
   ▼
事件池（event_id/clip_id/cluster_id/summary/structure/source_candidates，先聚合再评分）
   ▼
⑥ AI 复审（v0.4 步骤 3：分批复审 _review_in_batches，评审对象 = 事件）
   │                  _event_review_context：上下文 = 事件边界 ± 时间缓冲（默认 ±60s，可扩 ±180/±300）
   │                  —— Context Window（阅读范围）与 Clip Duration（剪辑长度）完全分离（D-038）
   │                  每批 ≤ REVIEW_BATCH.max_events_per_batch（默认 3）事件，结果按 event_id 对号
   │                  AI 报 context_incomplete → 该事件单独扩窗重审（最多 1 层深扩）
   │                  评分：AI 只打五维子分(1-10)，本地加权 ×10 得 100 分制；四档 S≥90/A≥80/B≥60/C≥50
   │                  recommended_start/end/duration + duration_reason（动态时长，不固定长度）
   │                  负面清单封顶 B（事件级）、schema 校验缺字段记 warning + 兜底（D-036~D-039）
   ▼
⑥.5 Global Ranking   分批复审后全量按 final_score 降序排（跨 batch 统一，消除前半段偏置）
   │                  独立整场报告 _build_ai_report（REPORT_SYSTEM，基于事件精华卡）
   ▼
⑦ 数量模式选择        自动精选（S/A）/ 候选池（S/A/B/C）/ 自定义数量（前 N 分层）
   ▼
输出 highlights_v2.json（highlights + rejected + report + cost，每个事件带 event_id + recommended_*）
```

## v0.2 兼容流程（仅命令行 analyze.py / main.py 使用）

```
文字稿 → analysis.analyze_transcript（截断 6000 字 + 单次 AI 调用）→ highlights.json
```

> 已知缺陷（v0.3 要解决的）：6000 字截断丢后半段、LLM 开头注意力偏置。
> **v0.3.2 起 ui.py 已切换到 v2 流程**，此路径仅命令行保留作为回退。

## 模块职责表

| 文件 | 职责 | 关键接口 |
|---|---|---|
| main.py | 命令行入口（薄壳） | — |
| pipeline.py | 核心流程（音频/识别/存稿） | `extract_audio / transcribe_audio / save_transcript / process_video / get_recognizer` |
| ui.py | Streamlit 网页 | — |
| asr/ | 语音识别可插拔 | `create_recognizer()` 工厂、`Segment`、`BaseRecognizer.transcribe()` |
| analysis/transcript_parser.py | 时间戳解析 | `parse_transcript / parse_transcript_file / total_duration` |
| analysis/event_scanner.py | 候选信号扫描 | `scan(segments, live_type)`、`LEXICONS`、`AVAILABLE_TYPES`、`load_user_lexicon()` |
| analysis/chunker.py | 智能分区 | `build_chunks(buckets, segments, hot_seconds=None, normal_seconds=None)`、`check_coverage`、`format_time` |
| analysis/prompt_builder.py | 提示词 | v0.2 `build_prompt`；v0.3 `build_screening_prompt / build_review_prompt`；v0.4 `build_event_judge_prompt / EVENT_JUDGE_SYSTEM` |
| analysis/deepseek_client.py | API 通信 + 成本 | `call_deepseek(prompt, system, max_tokens)`、`CostTracker`、`get_api_key` |
| analysis/budget.py | Token 预算估算 | `estimate_total(chunks, max_candidates)` |
| analysis/__init__.py | 分析编排 | v0.2 `analyze_transcript`；v0.3 `analyze_transcript_v2`（v0.4 起含事件聚合层 `_run_event_aggregation / _make_event / _dedupe_events`） |
| analyze.py / analyze_v2.py | 命令行分析入口 | 旧 / 新 |
| analysis/dictionary.py | **ASR 词库纠错（v0.4）** | `load_dictionary / apply_correction / correct_segments / correct_transcript_file / create_dictionary_template` |
| analysis/feedback.py | **人工反馈记录（v0.4）** | `save_feedback / load_feedback / get_feedback / feedback_stats` |
| analysis/event_cluster.py | **事件粗聚类（v0.4 步骤 2）** | `build_clusters / build_cluster_context / cluster_stats`（soft signals + 连通分量，只提分组不删候选） |

## 数据结构约定

- **Segment**：`{start: 秒, end: 秒, text: str}`（parser 输出，贯穿全流水线）
- **bucket**（分钟格子）：`{start, end, strong, normal, score, hot}`
- **chunk**（区块）：`{start, end, hot, score, segments, speech_start, speech_end, text, char_count}`
- **candidate**（海选候选）：`{start_time, end_time, title, highlight_type(事件型/情绪型/梗型), score, reason, category, viral_probability, emotion_score, conflict_score, editing_advice, confidence}` + 编排器附加 `chunk_index / context / clip_id / final_score / grade(A/B/C/D) / reject_reason / forced_keep`
- **输出**：`{meta, highlights, rejected, report, cost}`

## 规划中模块（规范 v1.0，禁止提前实现，见 VERSION_PLAN 优先级）

```
文字稿 → ⑧ 文本纠错 correction.py（高级版，v0.5+，上下文感知纠错）
              │   用户词库管理 UI（添加/删除/修改/导入/导出）
              ▼
         （进入 ① 事件扫描，位置在解析之后、扫描之前）
```

- ✅ `analysis/dictionary.py`：**已实现（v0.4 第一步）**——基础版纯字符串替换（D-028）。高级的上下文感知纠错仍在规划中，届时不动本模块接口
- ✅ `analysis/feedback.py`：**已实现（v0.4 第一步）**——本地 feedback.json 记录（JSON 数组，同 clip_id 覆盖并继承 snapshot，D-027）。**反馈数据的分析/训练**才是 v0.5/v1.0 的事
- `analysis/correction.py`：上下文感知纠错（高级版）
- `analysis/user_profile.py`：用户画像（v0.5+）
- 事件聚合层（v0.4 步骤 2，混合方案 D-026）：本地按时间粗合并 + AI 校正
- 云端 AI 分析接口（v0.5 / P3）：视频读取与 ASR 留本地，仅文字稿上行（D-013）
