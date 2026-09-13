# ASR / Audio Understanding 输入层升级：技术方案与 PoC 设计

日期：2026-09-12  
状态：Design / PoC only  
范围：ASR、Speaker Diarization、Speaker Role、Emotion / Paralinguistic Understanding、Audio Event Detection  
红线：本阶段不改生产主流程、不改 A1/A2/A3/B1、不改五维评分与推荐规则。

## 1. 结论

本阶段采用“**结构化富音频 sidecar + 旧文字稿兼容投影**”方案，而不是直接扩大现有 `Segment` 或改写 Chapter / Story / Event / Recommendation。

推荐的 PoC 主路线：

- **Rich ASR / 情绪 /有限音频事件**：SenseVoiceSmall。
- **VAD / 长音频分段**：FSMN-VAD。
- **Speaker Diarization**：CAM++ 说话人向量 + 聚类，由 FunASR 组合流水线先验证。
- **Speaker Role**：不使用声学模型强猜角色；用“可选声纹登记 + 会话行为特征 + 文本证据”做独立推断，低置信度必须保留 `unknown`。
- **部署候选对照**：sherpa-onnx（Windows / CPU / ONNX）做第二轨可部署性验证；pyannote `community-1` 只作精度对照，不作为第一部署选择。

SenseVoiceSmall 的官方能力覆盖中文 ASR、语音情绪和 BGM / 掌声 / 笑声 / 哭声 / 咳嗽 / 喷嚏等事件；Speaker Diarization 不是 SenseVoice 自身能力，而是 FunASR 用独立 CAM++ 组合得到。现有音频 DSP PoC 已证明 RMS / ZCR / 相对能量无法在本项目直播音频中可靠区分笑声、普通说话和 BGM，因此不再继续调阈值。

## 2. 当前架构事实与约束

### 2.1 当前真实数据流

当前生产流不是先生成 Chapter / Story 再发现 Event，而是：

```text
video
  -> ffmpeg: 16 kHz / mono / MP3
  -> faster-whisper: Segment(start, end, text)
  -> transcript.txt: [mm:ss - mm:ss] text
  -> transcript parser: {start, end, text}
  -> 候选发现
  -> Event 聚类 / 理解 / 完整性 / 复审
  -> Recommendation
  -> 用本场 Event 反向生成 Chapter / Story 并挂载 Event
  -> UI: Chapter -> Story -> Event / Recommendation
```

这条顺序本阶段不改。这里所说的“架构兼容”，定义为：

1. 旧 `transcript.txt` 和旧 `Segment(start, end, text)` 完全可继续工作；
2. 富音频信息只作为可选证据，不存在时行为必须与当前版本一致；
3. Chapter / Story 仍是软边界；
4. 音频证据不能删除候选，不能单独决定评分或推荐；
5. 每个项目的富音频结果独立存储，禁止跨视频 fallback。

### 2.2 当前阻塞点

- `asr/base.py::Segment` 只有 `start/end/text`。
- `pipeline.save_transcript()` 把内存结果投影成三字段纯文本，任何 speaker / emotion / event 都会丢失。
- `analysis/transcript_parser.py` 也只恢复三字段。
- ASR Provider 的边界目前是“音频 -> `[Segment]`”，适合旧 ASR，却无法表达多轨音频理解结果。
- 当前 ASR 用 MP3 足够；情绪 / 音频事件 PoC 应从原视频另导出 PCM WAV，避免把 ASR 的压缩格式当成所有声学任务的唯一输入。

因此，不能只给 `Segment` 加几个字段；那会同时破坏 Provider 契约、文字稿格式、解析层和测试。应先引入旁路数据契约。

## 3. 目标架构

```text
                         +-> LegacyProjection -> Segment[] -> transcript.txt
video -> Audio Frontend -|
                         +-> RichAudio Worker -> audio_understanding.v1.json
                                                   |
                                                   v
                         EvidenceIndex(time window query, optional)
                                                   |
                    Chapter / Story / Event / Recommendation
                         （PoC 阶段只 shadow，不参与决策）
```

### 3.1 三个边界

1. **Recognizer**：音频转文字，继续满足旧 `AsrProvider`。
2. **AudioUnderstandingProvider**：音频转结构化 `AudioUnderstandingDocument`，新接口，不塞进旧 `Segment`。
3. **EvidenceIndex**：按时间窗查询 speaker / role / affect / audio event，供未来各层按需读取。

未来可以由同一个底层模型同时实现 1 和 2，但接口职责必须分开。

### 3.2 存储位置

建议 sidecar 放在：

```text
<workspace>/projects/<project_id>/artifacts/audio_understanding.v1.json
```

不放进 `transcript.txt`，也不放全局固定文件。未来只需在 `project.json` 增加可选引用：

```json
{
  "transcript": {
    "path": "...",
    "source": "asr",
    "rich_audio_path": ".../audio_understanding.v1.json"
  }
}
```

字段缺失即表示旧项目，必须正常降级。

## 4. Sidecar v1 数据契约

时间统一用整数毫秒，避免当前 `mm:ss` 投影造成亚秒级边界损失。原始模型标签与归一化标签同时保存，便于审计。

```json
{
  "schema_version": "audio-understanding.v1",
  "meta": {
    "project_id": "...",
    "source_media": "测试视频2.mp4",
    "source_fingerprint": "sha256:...",
    "duration_ms": 3100123,
    "timebase": "milliseconds",
    "engines": {
      "asr": {"id": "sensevoice-small", "revision": "pinned"},
      "vad": {"id": "fsmn-vad", "revision": "pinned"},
      "diarization": {"id": "campplus", "revision": "pinned"}
    }
  },
  "speakers": [
    {
      "speaker_id": "spk-00",
      "display_name": "说话人 1",
      "role": "host",
      "role_confidence": 0.88,
      "role_source": "enrolled_voice|rules_llm|manual|unknown",
      "role_evidence": ["开场自称主播", "全场主导话轮"]
    }
  ],
  "speaker_turns": [
    {
      "turn_id": "turn-000001",
      "start_ms": 600,
      "end_ms": 2510,
      "speaker_ids": ["spk-00"],
      "overlap": false,
      "confidence": null
    }
  ],
  "utterances": [
    {
      "utterance_id": "utt-000001",
      "start_ms": 600,
      "end_ms": 2510,
      "text": "欢迎大家来直播间",
      "speaker_id": "spk-00",
      "speaker_role": "host",
      "language": "zh",
      "affect": {
        "label": "happy",
        "confidence": null,
        "arousal": null,
        "valence": null,
        "raw_label": "<|HAPPY|>",
        "source": "sensevoice"
      },
      "paralinguistic_tags": ["laughter"],
      "quality": {"overlap": false, "low_confidence": false}
    }
  ],
  "audio_events": [
    {
      "audio_event_id": "ae-000001",
      "start_ms": 1800,
      "end_ms": 2600,
      "label": "laughter",
      "raw_label": "<|Laughter|>",
      "confidence": null,
      "source": "sensevoice",
      "speech_overlap": true,
      "speaker_ids": ["spk-00"],
      "linked_utterance_ids": ["utt-000001"]
    }
  ],
  "warnings": []
}
```

### 4.1 置信度规则

- 模型没有可靠概率时写 `null`，禁止伪造置信度。
- `raw_label` 永不覆盖，归一化映射出错时仍可回溯。
- `speaker_id` 只表示本视频内聚类身份，不等于真实人物身份。
- 多人重叠时 `speaker_turns.speaker_ids` 可有多个；给 ASR 文本的 `speaker_id` 使用 exclusive / 最大重叠投影，但必须在 `quality.overlap` 标记信息损失。
- 对 emotion 的产品语义使用“可观察到的声音表达”，不得表述成对人的心理状态诊断。

## 5. 四项能力设计

### 5.1 ASR

PoC 不立即替换 faster-whisper。两条转写并行比较：

- Baseline：现有 faster-whisper small，确保主流程结果不变。
- Candidate：SenseVoiceSmall + FSMN-VAD，生成富输出。

只有 Candidate 在中文字符错误率、专名、时间戳稳定性和运行成本上通过门槛，才讨论成为新 ASR Provider。否则只把它用作 rich-audio analyzer，文本仍以 Whisper 为主。

对齐规则：

- Candidate 自带 `sentence_info` 时优先采用其 speaker / timestamp 结果。
- 若保留 Whisper 文本，则用时间交并比把 diarization turn 投影到 Whisper segment。
- 单一 speaker 覆盖率不足 60% 或多人重叠时，标 `unknown/overlap`，不强分配。

### 5.2 Speaker Diarization

PoC 首选 FunASR + CAM++，理由是中文、CPU 可跑，并能直接输出带 `spk` 的 `sentence_info`。对照组选：

- sherpa-onnx：Windows / CPU / 离线部署路径更接近当前桌面产品；使用 speaker segmentation + 中文 speaker embedding 模型。
- pyannote community-1：作为准确率参考。优点是 regular / exclusive diarization、重叠说话与 speaker embedding 输出成熟；缺点是 PyTorch 依赖重、模型下载需接受条件与 token，不适合作为首个桌面交付方案。

必须保留两个视图：

- `speaker_turns`：真实 diarization，可表达重叠。
- `utterances.speaker_id`：为了下游文本使用的 exclusive 投影。

### 5.3 Speaker Role

角色和说话人不是同一问题。模型通常只输出 `spk-00`，不能直接知道谁是主播。

角色词表建议：

```text
host | cohost | guest | remote_guest | audience | media_or_system | unknown
```

推断优先级：

1. 用户手工映射或登记主播 10~30 秒参考音频；
2. 已登记声纹匹配；
3. 会话级特征：开场/收场、自我介绍、称呼关系、发起话题、话轮占比、回应模式；
4. LLM 读取“匿名 speaker 的少量代表话轮 + 统计特征”给出角色、证据和置信度；
5. 不足则 `unknown`。

禁止规则：不能仅因“说话最多”就判 host；不能把礼物提示音、视频内对白误认成 guest；不能跨视频复用 `spk-00` 身份。

### 5.4 Emotion / Paralinguistic Understanding

采用双层表示：

- 原始离散标签：SenseVoice 的 emotion token。
- 归一化层：`neutral/happy/sad/angry/fearful/disgusted/surprised/other`，未来再补 `arousal/valence`。

处理原则：

- 以 2~10 秒 utterance / VAD 片段为基本单位，不对整段长直播给一个情绪。
- 相邻同 speaker 的结果做中值/多数平滑，短暂单帧跳变不直接形成事件。
- `angry` 与高唤醒/激动容易混淆，PoC 要单独统计这类混淆，不能直接写“愤怒”。
- 笑声、哭声、喘息、停顿、语速突变属于 paralinguistic evidence；它们和 emotion label 并列，不互相覆盖。

### 5.5 Audio Event Detection

第一阶段只验证与直播剪辑强相关的紧凑词表：

```text
laughter | applause | cry | cough | sneeze | bgm | music_sting |
scream_or_exclamation | impact | notification | silence | other
```

- SenseVoice 覆盖其中一部分，适合快速验证中文直播里的笑声/掌声/BGM 等。
- 若召回不足，再用 YAMNet 或 sherpa-onnx audio tagging 做补充。YAMNet 是 521 类 AudioSet 分类器，不应沿用旧文档中的“224 类”描述。
- DSP 只保留为检索候选窗/辅助特征，不再承担语义分类。
- Audio event 永远是 `evidence`，不直接等于 highlight。

## 6. 与 Chapter -> Story -> Event -> Recommendation 的兼容映射

PoC 阶段只做 shadow report，不修改任何结果：

| 层级 | 可读取的新证据 | PoC 输出 | 暂不做 |
|---|---|---|---|
| Chapter | 参与 speaker、角色占比、情绪走势、音频事件密度 | Chapter 音频摘要对照表 | 不改变 Chapter 边界 |
| Story | speaker 进入/退出、角色互动、情绪转折 | Story 证据时间线 | 不把 Story 变成硬边界 |
| Event | speaker 组合、笑声/惊呼、情绪峰值、重叠说话 | 每个 Event 的 `audio_evidence_shadow` | 不加分、不删候选、不改边界 |
| Recommendation | 现有推荐与音频证据的相关/漏检分析 | uplift / conflict 报告 | 不改五维权重和推荐策略 |

建议的未来 Event 可选字段：

```json
{
  "audio_evidence": {
    "speaker_ids": ["spk-00", "spk-01"],
    "roles": ["host", "guest"],
    "affect_peaks": [{"label": "surprised", "at_ms": 120340}],
    "events": [{"label": "laughter", "start_ms": 121000, "end_ms": 122400}],
    "interaction": {"turn_count": 8, "overlap_ms": 620}
  }
}
```

该字段缺失时，所有现有代码必须保持旧行为。

## 7. PoC 实施设计

### P0：夹具与人工真值

输入使用现有三场视频：`测试视频.mp4`、`测试视频2.mp4`、`测试视频4.mp4`，不只对单一视频调参。

建立以下真值：

- Diarization：每场抽 10 分钟，覆盖单人、双人、重叠、BGM/视频内对白；标 speaker 区间。
- Role：每个已知人物标真实角色，无法确认则 unknown。
- Emotion：每场分层抽样 50 个 3~10 秒片段，双人独立标注；允许 `uncertain`。
- Audio Event：复用旧 Audio Top25 y/n，再补每场至少 30 个正/负片段。
- ASR：每场抽 5 分钟逐字校对，重点标人名、品牌、网络用语。

产物：`poc/audio_understanding/fixtures/*.json`，所有标注带 `source_video` 和毫秒时间戳。

### P1：隔离式 Rich Audio Worker

新增 PoC 目录，不 import 到生产包：

```text
poc/audio_understanding/
  README.md
  run_funasr.py
  normalize.py
  align.py
  infer_roles.py
  schema.py
  evaluate.py
  fixtures/
  outputs/
```

环境使用独立 `.venv-audio-poc` 或单独进程，避免污染现有 `.venv` 和 PyInstaller spec。模型必须固定 revision，输出记录模型版本、耗时、峰值内存和失败信息。

### P2：兼容投影验证

实现但不接主流程：

```text
audio_understanding.v1.json
  -> LegacyProjection
  -> 与当前 Segment 等价的 start/end/text
  -> 临时 transcript_candidate.txt
```

验证：旧 `transcript_parser` 能解析、现有分析测试不需要改、无富数据时完全降级。

### P3：Shadow Evidence Report

读取现有 `highlights_v2.json` / 分析结果，把 audio evidence 按时间窗挂到 Event 的临时副本，仅生成对照报告：

- 现有推荐中有多少包含可靠笑声/惊呼/多人互动；
- 未推荐区间中有哪些强音频证据；
- 音频证据与人工 y/n 的 precision / recall；
- role / speaker 信息是否能解释事件完整性问题；
- 不写回项目、不影响 UI。

### P4：部署可行性对照

仅当 P1/P3 有增量价值，再对同一夹具跑 sherpa-onnx：

- 与 FunASR 比 DER、事件 F1、RTF、峰值内存、模型体积；
- 验证 Windows CPU 与打包可行性；
- 决定生产候选是“FunASR 独立 worker”还是“sherpa-onnx 原生旁路”。

## 8. 评价指标与门槛

### 8.1 ASR

- 中文 CER：不得比 faster-whisper baseline 相对恶化超过 5%。
- 专名召回：不得低于 baseline；同时记录自定义词库纠错后的结果。
- 时间戳：95% utterance 起止误差不超过 800 ms（人工样本）。
- 空输出 / 幻觉单独计数。

### 8.2 Diarization

- DER（含 miss / false alarm / confusion）≤ 20% 为 Go，20~30% 只允许 shadow，>30% No-Go。
- Speaker count MAE ≤ 0.5。
- ASR utterance speaker attribution accuracy ≥ 85%。
- 重叠说话单独报告，不能藏在总体平均里。

### 8.3 Role

- 已知 host 的准确率 ≥ 95%。
- 其他角色 macro-F1 ≥ 0.75。
- 低置信度样本必须能 abstain；目标是错误强判率 < 5%，不是覆盖率 100%。

### 8.4 Emotion / Paralinguistics

- 类别 macro-F1 ≥ 0.60 才可进入 shadow evidence；达不到则只保留 raw tag 供审计。
- 高唤醒二分类（平静 vs 明显激动）F1 ≥ 0.75。
- 人工标注一致率先报告；若标注者本身一致率低，禁止拿模型低分直接做产品决策。

### 8.5 Audio Event

- 第一优先 laughter：precision ≥ 0.80、recall ≥ 0.70。
- applause / cry / cough / BGM 分别报告，不做 micro-average 掩盖小类。
- 在旧 Top25 标注集上，必须明显好于 DSP 的 13/25 命中表现。

### 8.6 工程成本

- 51 分钟视频 CPU RTF、峰值 RAM、模型总大小、首次下载成功率全部记录。
- PoC 可接受独立环境；进入桌面版前必须给出安装包增量和离线模型管理方案。
- 任一模型失败不得影响旧 ASR 和主分析结果。

## 9. 模型选择矩阵

| 方案 | 能力 | 优点 | 主要风险 | PoC 定位 |
|---|---|---|---|---|
| SenseVoiceSmall + FSMN-VAD + CAM++ / FunASR | ASR + emotion + 部分 AED + diarization | 中文统一链路、快速产出结构化结果、CPU 可跑 | PyTorch/FunASR 依赖与包体；模型许可需逐项固化 | 主验证路线 |
| sherpa-onnx | ASR / SenseVoice / diarization / audio tagging | Windows、CPU、离线、ONNX、部署友好 | 组合输出和标签质量需自行验证 | 部署候选路线 |
| pyannote community-1 | diarization / overlap / embedding | 成熟，exclusive diarization 便于和 ASR 对齐 | PyTorch 重；HF gated/token；非首选桌面交付 | 精度对照 |
| YAMNet | 521 类 audio event | 类别广、帧级分数 | TensorFlow 依赖重，直播域误报需校准 | AED 补充对照 |
| 当前 faster-whisper small | ASR | 已验证、稳定、已打包 | 无 speaker / emotion / AED | 不动的 baseline |

## 10. 风险与控制

1. **包体和依赖冲突**：PoC 独立环境/进程；未经对照不得改 PyInstaller。
2. **许可证**：代码许可证与模型权重许可证分开记录；每个模型 registry 条目固定 license URL、revision、hash、attribution。SenseVoice 官方代码为 MIT，但权重遵循单独的 FunASR Model Open Source License。
3. **speaker label 漂移**：ID 只在单视频内有效；跨项目身份必须靠登记声纹或人工确认。
4. **角色误判**：允许 unknown 和人工覆盖；不把 talk-time 当唯一规则。
5. **情绪伦理与误读**：输出“声音呈现/表达”，不输出心理诊断。
6. **音频事件误报**：事件只是 evidence；不得直接升分、推荐或过滤。
7. **时间轴漂移**：所有 sidecar 绑定 source fingerprint 和 duration；不匹配立即拒绝加载。
8. **缓存串场**：每项目独立 artifact；禁止固定样例 fallback。

## 11. Go / No-Go 决策

PoC 完成后按以下顺序决策：

1. Rich audio 在人工真值上是否可靠；
2. 是否对 Event 召回、完整性或解释性产生可量化增量；
3. 是否能在 Windows CPU 成本内运行；
4. 是否有可接受的模型许可和下载路径；
5. 通过后才设计最小生产接入点，优先只增加 sidecar 写入与 shadow UI；
6. 未通过则保留现有 faster-whisper 主线，不因已经投入 PoC 而强行接入。

## 12. 建议执行顺序

第一迭代只做 P0 + P1：三视频夹具、FunASR rich output、sidecar v1、离线评估脚本。  
第二迭代做 P2 + P3：旧文字稿兼容投影和 Event shadow report。  
第三迭代仅在有增量时做 P4：sherpa-onnx / pyannote 对照与生产接入 ADR。

这能在完全不触碰主流程的前提下，先回答最重要的问题：新增的 speaker、role、emotion、audio event 是否真的让“完整事件”和“值得剪”判断获得了增量证据。

## 参考资料（核验日期：2026-09-12）

- SenseVoice 官方仓库：https://github.com/QwenAudio/SenseVoice
- FunASR 官方仓库与组合示例：https://github.com/modelscope/FunASR
- FunASR Python API：https://www.funasr.com/en/docs/python-api.html
- pyannote.audio 官方仓库：https://github.com/pyannote/pyannote-audio
- sherpa-onnx 官方仓库：https://github.com/k2-fsa/sherpa-onnx
- YAMNet 官方教程：https://www.tensorflow.org/hub/tutorials/yamnet

