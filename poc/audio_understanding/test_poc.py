# test_poc.py —— Audio Understanding PoC 最小自测（直接运行，风格与项目现有测试一致）
#
# 只测三件事：
#   1) sidecar v1 的 schema 校验与防伪造规则
#   2) SenseVoice rich token 解析（真实 token 才产出，没有就留空）
#   3) legacy 投影与生产 transcript_parser 的兼容性 + 缺富数据时的降级
# 不需要 funasr / 模型，全部离线，秒级完成。

import importlib.util
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


schema = _load("schema")
normalize = _load("normalize")
projection = _load("legacy_projection")

# 生产 parser 直接按文件加载，绕开 analysis/__init__ 的包级副作用（只读使用，不修改）
_parser_spec = importlib.util.spec_from_file_location(
    "prod_transcript_parser",
    os.path.join(HERE, "..", "..", "analysis", "transcript_parser.py"),
)
prod_parser = importlib.util.module_from_spec(_parser_spec)
_parser_spec.loader.exec_module(prod_parser)

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS  " if cond else "FAIL  ") + name + (f"  | {detail}" if detail and not cond else ""))


# ---------- 1. schema：合法文档 ----------
doc = schema.new_document(
    project_id="poc-test",
    source_media="clip.wav",
    duration_ms=90_000,
    engines={"asr": {"id": "sensevoice-small", "revision": "poc"},
             "vad": {"id": "fsmn-vad", "revision": "poc"},
             "diarization": {"id": "campplus", "revision": "poc"}},
)
schema.add_speaker(doc, 0)
schema.add_utterance(doc, 600, 2510, "欢迎大家来直播间", speaker_id="spk-00",
                     language="zh", affect={"label": "neutral", "raw_label": "<|NEUTRAL|>", "source": "sensevoice"})
schema.add_audio_event(doc, 1800, 2600, "laughter", "<|Laughter|>")
schema.add_speaker_turn(doc, 600, 2510, ["spk-00"])
check("schema: 合法文档通过校验", schema.validate_document(doc) == [],
      str(schema.validate_document(doc)))

# ---------- 2. schema：缺 schema_version 拒绝 ----------
bad = json.loads(json.dumps(doc))
bad["schema_version"] = "audio-understanding.v9"
check("schema: 错误 schema_version 被拒", len(schema.validate_document(bad)) == 1)

# ---------- 3. schema：时间倒挂拒绝 ----------
bad2 = json.loads(json.dumps(doc))
bad2["utterances"][0]["end_ms"] = 100
check("schema: end_ms < start_ms 被拒",
      any("end_ms" in e for e in schema.validate_document(bad2)))

# ---------- 4. 防伪造：有 label 无 raw_label → 丢弃并警告 ----------
doc3 = schema.new_document("t", "m", 1000, {})
schema.add_utterance(doc3, 0, 500, "hi", affect={"label": "happy", "source": "sensevoice"})
u3 = doc3["utterances"][0]
check("防伪造: 无 raw_label 的 affect 被丢弃", u3["affect"] is None and len(doc3["warnings"]) == 1)
doc4 = schema.new_document("t", "m", 1000, {})
check("防伪造: 无 raw_label 的 audio_event 被拒收",
      schema.add_audio_event(doc4, 0, 100, "laughter", "") is None)

# ---------- 5. normalize：rich token 解析 ----------
parsed = normalize.parse_rich_text("<|zh|><|HAPPY|><|Speech|><|woitn|>这个太搞笑了<|Laughter|>")
check("normalize: 语言/情绪/事件/纯文本拆解",
      parsed["language"] == "zh" and parsed["emotion_raw"] == "<|HAPPY|>"
      and parsed["events_raw"] == ["<|Speech|>", "<|Laughter|>"]   # Speech 也是真实事件 token
      and parsed["clean_text"] == "这个太搞笑了", json.dumps(parsed, ensure_ascii=False))
check("normalize: 归一化映射", normalize.normalize_emotion("<|HAPPY|>") == "happy"
      and normalize.normalize_event("<|BGM|>") == "bgm")

plain = normalize.parse_rich_text("没有任何 token 的普通句子")
check("normalize: 无 token → 情绪/事件留空（不伪造）",
      plain["emotion_raw"] is None and plain["events_raw"] == []
      and plain["clean_text"] == "没有任何 token 的普通句子")
weird = normalize.parse_rich_text("<|zz|><|GHOST|>奇怪输出")
check("normalize: 未知 token 原样上报不猜",
      weird["unknown_tokens"] == ["<|zz|>", "<|GHOST|>"]
      and weird["emotion_raw"] is None and weird["events_raw"] == [])

# ---------- 6. projection：与生产 parser 兼容 ----------
sidecar = {
    "utterances": [
        {"start_ms": 600, "end_ms": 2510, "text": "欢迎大家来直播间", "speaker_id": "spk-00"},
        {"start_ms": 2600, "end_ms": 89000, "text": "今天聊点什么", "speaker_id": None},
        {"start_ms": 89_500, "end_ms": 90_000, "text": "", "speaker_id": None},
    ]
}
text = projection.to_transcript_text(sidecar["utterances"])
segs = prod_parser.parse_transcript(text)
check("投影: 生产 parser 可解析", len(segs) == 2, text)
check("投影: 段落时间一致(毫秒→秒, mm:ss 本身有亚秒有损, 与生产行为一致)",
      segs[0]["start"] == 0 and segs[0]["end"] == 2          # 0.6s→00:00, 2.51s→00:02
      and segs[0]["text"] == "欢迎大家来直播间")
check("投影: 空文本句被跳过", len(segs) == 2)

long_u = [{"start_ms": 4521_000, "end_ms": 4525_000, "text": "超一小时时间戳"}]
long_segs = prod_parser.parse_transcript(projection.to_transcript_text(long_u))
check("投影: >59 分钟分钟制时间戳与生产 format_time 一致",
      long_segs and long_segs[0]["start"] == 4521, projection.to_transcript_text(long_u))

# ---------- 7. 降级：空 / 缺字段 ----------
check("降级: 空 utterances → 空文字稿不崩", projection.to_transcript_text([]) == "")
check("降级: utterances 缺失(None) → 空文字稿不崩", projection.to_transcript_text(None) == "")
doc5 = schema.new_document("t", "m", 1000, {})
check("降级: 全空文档校验通过", schema.validate_document(doc5) == [])

# ---------- 汇总 ----------
failed = [n for n, ok, _ in RESULTS if not ok]
print(f"\n===== PoC selftest: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed =====")
if failed:
    print("FAILED:", *failed, sep="\n  - ")
sys.exit(1 if failed else 0)
