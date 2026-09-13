# schema.py —— audio_understanding.v1 sidecar 的文档构造与校验
#
# 依据 docs/ASR_AUDIO_UNDERSTANDING_DESIGN_20260912.md §4 数据契约。
# 铁律：模型没有可靠输出时字段留空/null，禁止伪造 emotion / speaker / audio event。
# 时间统一毫秒整数（timebase=milliseconds）。

SCHEMA_VERSION = "audio-understanding.v1"
TIMEBASE = "milliseconds"

VALID_EMOTION_LABELS = {
    "neutral", "happy", "sad", "angry", "fearful", "disgusted", "surprised", "other",
}


def new_document(project_id, source_media, duration_ms, engines, source_fingerprint=None):
    """创建一个符合 v1 契约的空文档。

    engines: {"asr": {...}, "vad": {...}, "diarization": {...}}，每项含 id/revision。
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "project_id": project_id,
            "source_media": source_media,
            "source_fingerprint": source_fingerprint,
            "duration_ms": int(duration_ms),
            "timebase": TIMEBASE,
            "engines": engines,
        },
        "speakers": [],
        "speaker_turns": [],
        "utterances": [],
        "audio_events": [],
        "warnings": [],
    }


def add_speaker(doc, speaker_index):
    """登记一个聚类说话人身份（仅表示本视频内身份，不等于真实人物）。"""
    sid = f"spk-{speaker_index:02d}"
    if not any(s["speaker_id"] == sid for s in doc["speakers"]):
        doc["speakers"].append({
            "speaker_id": sid,
            "display_name": f"说话人 {speaker_index + 1}",
            "role": "unknown",           # PoC 不做 role 推断，一律 unknown
            "role_confidence": None,
            "role_source": "unknown",
            "role_evidence": [],
        })
    return sid


def add_utterance(doc, start_ms, end_ms, text, speaker_id=None, language=None,
                  affect=None, paralinguistic_tags=None, quality=None, turn_id=None):
    """追加一句 utterance。

    affect: None 或 {"label", "raw_label", "source", "confidence"}。
            raw_label 必须来自模型真实输出；给 label 不给 raw_label 视为伪造，拒绝。
    """
    utt = {
        "utterance_id": f"utt-{len(doc['utterances']) + 1:06d}",
        "start_ms": int(start_ms),
        "end_ms": int(end_ms),
        "text": text,
        "speaker_id": speaker_id,
        "language": language,
        "affect": None,
        "paralinguistic_tags": paralinguistic_tags or [],
        "quality": quality or {},
        "turn_id": turn_id,
    }
    if affect is not None:
        if not affect.get("raw_label"):
            doc["warnings"].append(
                f"utt-{len(doc['utterances']) + 1:06d}: affect 缺 raw_label（模型原始输出），已丢弃以防伪造")
        else:
            utt["affect"] = {
                "label": affect.get("label"),
                "confidence": affect.get("confidence"),
                "arousal": None,
                "valence": None,
                "raw_label": affect["raw_label"],
                "source": affect.get("source", "sensevoice"),
            }
    doc["utterances"].append(utt)
    return utt


def add_audio_event(doc, start_ms, end_ms, label, raw_label, source="sensevoice",
                    speech_overlap=None, speaker_ids=None, linked_utterance_ids=None):
    """追加一个音频事件。raw_label 必须为模型真实 token，否则拒绝。"""
    if not raw_label:
        doc["warnings"].append("audio_event 缺 raw_label，已丢弃以防伪造")
        return None
    ev = {
        "audio_event_id": f"ae-{len(doc['audio_events']) + 1:06d}",
        "start_ms": int(start_ms),
        "end_ms": int(end_ms),
        "label": label,
        "raw_label": raw_label,
        "confidence": None,
        "source": source,
        "speech_overlap": speech_overlap,
        "speaker_ids": speaker_ids or [],
        "linked_utterance_ids": linked_utterance_ids or [],
    }
    doc["audio_events"].append(ev)
    return ev


def add_speaker_turn(doc, start_ms, end_ms, speaker_ids, overlap=False, confidence=None):
    doc["speaker_turns"].append({
        "turn_id": f"turn-{len(doc['speaker_turns']) + 1:06d}",
        "start_ms": int(start_ms),
        "end_ms": int(end_ms),
        "speaker_ids": speaker_ids,
        "overlap": bool(overlap),
        "confidence": confidence,
    })


def validate_document(doc):
    """结构性校验，返回错误列表（空列表 = 通过）。不做任何内容修补。"""
    errors = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {SCHEMA_VERSION}，实际 {doc.get('schema_version')!r}")
    meta = doc.get("meta") or {}
    if meta.get("timebase") != TIMEBASE:
        errors.append("meta.timebase 必须为 milliseconds")
    if not isinstance(meta.get("duration_ms"), int) or meta["duration_ms"] <= 0:
        errors.append("meta.duration_ms 必须为正整数毫秒")

    for i, u in enumerate(doc.get("utterances", [])):
        tag = f"utterances[{i}]({u.get('utterance_id')})"
        if not isinstance(u.get("start_ms"), int) or not isinstance(u.get("end_ms"), int):
            errors.append(f"{tag}: start_ms/end_ms 必须是整数毫秒")
        elif u["end_ms"] < u["start_ms"]:
            errors.append(f"{tag}: end_ms < start_ms")
        aff = u.get("affect")
        if aff is not None:
            if not aff.get("raw_label"):
                errors.append(f"{tag}: affect 有 label 但无 raw_label（伪造嫌疑）")
            if aff.get("label") is not None and aff["label"] not in VALID_EMOTION_LABELS:
                errors.append(f"{tag}: affect.label {aff['label']!r} 不在归一化词表内")

    for i, e in enumerate(doc.get("audio_events", [])):
        tag = f"audio_events[{i}]({e.get('audio_event_id')})"
        if not e.get("raw_label"):
            errors.append(f"{tag}: 缺 raw_label（伪造嫌疑）")
        elif e["end_ms"] < e["start_ms"]:
            errors.append(f"{tag}: end_ms < start_ms")

    for i, t in enumerate(doc.get("speaker_turns", [])):
        if not t.get("speaker_ids"):
            errors.append(f"speaker_turns[{i}]: speaker_ids 为空")
        elif t["end_ms"] < t["start_ms"]:
            errors.append(f"speaker_turns[{i}]: end_ms < start_ms")

    known_spk = {s["speaker_id"] for s in doc.get("speakers", [])}
    for i, u in enumerate(doc.get("utterances", [])):
        sid = u.get("speaker_id")
        if sid is not None and known_spk and sid not in known_spk:
            errors.append(f"utterances[{i}]: speaker_id {sid!r} 未在 speakers 登记")
    return errors
