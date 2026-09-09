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
⑥ AI 复审（prompt_builder.build_review_prompt，一次调用）
   │                  v0.3.1 分级：A 强烈推荐 / B 建议测试 / C 备用素材 / D 淘汰
   │                  零输出禁令：全灭时最佳候选 ≥4 分强制保留 1 个 C（forced_keep）（D-018）
   │                  同时产出 AI 分析报告（总结/最强传播点/为什么不推荐更多）
   ▼
⑦ 数量模式选择        自动精选（只出 A 级）/ 候选池（A+B+C 全展示）/ 自定义数量（前 N 分层：高质量/普通/备用）
   ▼
输出 highlights_v2.json（highlights + rejected + report + cost，每个候选带 clip_id）
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
| analysis/prompt_builder.py | 提示词 | v0.2 `build_prompt`；v0.3 `build_screening_prompt / build_review_prompt` |
| analysis/deepseek_client.py | API 通信 + 成本 | `call_deepseek(prompt, system, max_tokens)`、`CostTracker`、`get_api_key` |
| analysis/budget.py | Token 预算估算 | `estimate_total(chunks, max_candidates)` |
| analysis/__init__.py | 分析编排 | v0.2 `analyze_transcript`；v0.3 `analyze_transcript_v2` |
| analyze.py / analyze_v2.py | 命令行分析入口 | 旧 / 新 |

## 数据结构约定

- **Segment**：`{start: 秒, end: 秒, text: str}`（parser 输出，贯穿全流水线）
- **bucket**（分钟格子）：`{start, end, strong, normal, score, hot}`
- **chunk**（区块）：`{start, end, hot, score, segments, speech_start, speech_end, text, char_count}`
- **candidate**（海选候选）：`{start_time, end_time, title, highlight_type(事件型/情绪型/梗型), score, reason, category, viral_probability, emotion_score, conflict_score, editing_advice, confidence}` + 编排器附加 `chunk_index / context / clip_id / final_score / grade(A/B/C/D) / reject_reason / forced_keep`
- **输出**：`{meta, highlights, rejected, report, cost}`

## 规划中模块（规范 v1.0，禁止提前实现，见 VERSION_PLAN 优先级）

```
文字稿 → ⑧ 文本纠错 correction.py（v0.4 / P1，Whisper 错字修正）
              │   用户词库管理 UI（添加/删除/修改/导入/导出）
              ▼
         （进入 ① 事件扫描，位置在解析之后、扫描之前）
```

- `analysis/correction.py`：文本纠错第一阶段（用户词库），新建模块不重构现有代码（D-014）
- `analysis/user_profile.py`：用户画像（v0.4 雏形）
- `analysis/feedback.py`：反馈数据分析（v0.4+，v0.3 只攒 data：feedback.jsonl）
- 云端 AI 分析接口（v0.5 / P3）：视频读取与 ASR 留本地，仅文字稿上行（D-013）
