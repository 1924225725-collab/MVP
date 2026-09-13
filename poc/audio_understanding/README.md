# poc/audio_understanding —— Audio Understanding PoC（只验证，不进生产）

依据 `docs/ASR_AUDIO_UNDERSTANDING_DESIGN_20260912.md`（P1 最小验证轮）。
**红线**：不改 Chapter/Story/Event/Recommendation、不改旧 Segment、不改 transcript.txt、
不改 UI、不改评分系统；不伪造 emotion/speaker/audio event；模型没有的输出一律留空。

## 环境（完全隔离，不碰主 .venv）

```bash
# 已建好的隔离环境（torch CPU + funasr + modelscope）
.venv-audio-poc/Scripts/python -m pip list
```

## 运行

```bash
# 离线自测（不需要模型，秒级）
.venv/Scripts/python poc/audio_understanding/test_poc.py

# 真实最小推理（90s 切片；首次会从 modelscope.cn 下载 ~970MB 模型）
.venv-audio-poc/Scripts/python poc/audio_understanding/run_funasr.py \
  --input poc/audio_understanding/fixtures/clip_51min_000_090.wav --dump-raw
```

## 产物（outputs/）

- `*.audio_understanding.v1.json` —— sidecar（毫秒时间戳；utterances/speaker_turns/audio_events/性能）
- `*.audio_understanding.v1.transcript_candidate.txt` —— legacy 投影候选稿（**不**接入 pipeline）
- `raw_probe.json` —— sentence_info 原始结构样本（审计用）

## 文件

| 文件 | 职责 |
|---|---|
| schema.py | v1 契约构造 + 校验 + 防伪造（有 label 必须有 raw_label） |
| normalize.py | SenseVoice rich token 拆解与归一化查表（未知 token 原样上报） |
| run_funasr.py | runner：输入 → sidecar + RTF/环境信息 |
| legacy_projection.py | sidecar → [MM:SS - MM:SS] text（与生产 format_time/save_transcript 同格式） |
| test_poc.py | 离线自测（含用生产 transcript_parser 验证投影兼容性） |

## 已知边界

- speaker role 一律 `unknown`（本轮不做 role 推断，见设计文档 §5.3）
- `<|Speech|>` 是"人声标记"不是事件，不进 audio_events
- 模型 revision 为 best-effort 记录（master(auto)），进入生产前需 pin
- emotion confidence：SenseVoice 不输出可靠概率 → 一律 null，禁止编造
