"""chapter_story —— Chapter / Story 分割接入主流程（V0.4.4 修复严重数据绑定问题）

【为什么有这个模块】（根因记录）
V0.4.2 接入「内容结构层」时，Chapter/Story **并没有接进主流程**：
它们只是在 PoC 阶段对一场固定的 51 分钟测试视频跑过一次，产物写死在
`poc/story_segmentation_result.json`；而 `story_context.load_structure()` 无条件读这个文件。
结果：换任何视频，UI 的「直播内容结构」都显示同一套 ch-01~ch-04 的 10 个 Story。
这不是 UI 的问题，是**结构数据从未按视频生成**。

【本模块做什么】
把 PoC 阶段已验证的分割算法（`poc/ai_chapter_v2.py` + `poc/story_segmentation_v2.py`）
搬进主流程，并**按 transcript 分别生成与缓存**：
  1. `segment_structure()` —— 用「当前视频的事件列表」调 AI 切 Chapter，再在每个 Chapter 内切 Story；
  2. 结果缓存到 `structures/<transcript 文件名>.json`，并校验时长一致，防止串场；
  3. 聚合阶段的 Story 软先验只读**本视频自己的缓存**（没有就跳过，绝不借用别的视频）。

【边界】
- 只读事件结果，不改评分/Event/Highlight/Recommendation 任何逻辑；
- 结构是软边界，不参与硬过滤；
- 任何一步失败都降级为空结构，不阻塞主流程。
"""

import json
import re
from datetime import datetime
from pathlib import Path

import config

from .chunker import format_time
from .prompt_builder import (
    build_chapter_prompt,
    build_story_prompt,
    CHAPTER_SYSTEM,
    STORY_SYSTEM,
)

# 缓存里的时长允许误差（秒）：同一份稿子时长应该完全一致，留一点余量防止浮点误差
_DURATION_TOLERANCE = 2


# ============================================================
# 路径与缓存
# ============================================================

def cache_dir() -> Path:
    """结构缓存目录（相对项目根目录，可用 config.STORY_CONTEXT['cache_dir'] 改）。"""
    cfg = getattr(config, "STORY_CONTEXT", None) or {}
    name = cfg.get("cache_dir") or "structures"
    return Path(__file__).resolve().parent.parent / name


def cache_path_for(transcript_path) -> Path:
    """每个视频一份结构缓存：structures/<稿子文件名>.json（与视频稿一一对应）。"""
    stem = Path(str(transcript_path)).stem or "unknown"
    safe = re.sub(r'[\\/:*?"<>|]', "_", stem)
    return cache_dir() / f"{safe}.json"


def load_cached_structure(transcript_path, duration_seconds=None):
    """读取「这份稿子自己的」结构缓存。

    不是本文件的缓存、时长对不上、文件坏了 → 一律返回 None（**绝不退回别的视频的结构**）。
    """
    path = cache_path_for(transcript_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    meta = data.get("meta") or {}
    # 只认「同一份稿子」的缓存
    if Path(str(meta.get("transcript", ""))).name != Path(str(transcript_path)).name:
        return None
    cached_dur = meta.get("duration_seconds")
    if duration_seconds is not None and cached_dur is not None:
        if abs(int(cached_dur) - int(duration_seconds)) > _DURATION_TOLERANCE:
            return None
    if not data.get("chapters") and not data.get("stories"):
        return None
    return data


def save_cached_structure(transcript_path, data: dict):
    """把本次生成的结构缓存下来（供下一次同一视频的 Story 软先验复用）。"""
    path = cache_path_for(transcript_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return path


# ============================================================
# 事件清单文本（喂给 AI 的原料，纯本地拼接）
# ============================================================

def _ts2s(t):
    if t is None:
        return None
    try:
        s = str(t).strip()
        if s.isdigit():
            return int(s)
        parts = [int(p) for p in s.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except (ValueError, AttributeError):
        pass
    return None


def _event_line(e: dict, with_duration: bool = False) -> str:
    eid = e.get("event_id") or e.get("clip_id", "?")
    title = (e.get("title") or "")[:35]
    summary = (e.get("summary") or e.get("reason") or "")[:60]
    line = (f"{eid} [{e.get('grade', '?')}] "
            f"{e.get('start_time', '?')}-{e.get('end_time', '?')}"
            f"{' (' + str(e.get('duration') or '') + 's)' if with_duration and e.get('duration') else ''}"
            f"\n  {title}\n  摘要: {summary}")
    return line


def _events_text(events: list, with_duration: bool = False) -> str:
    ordered = sorted(events, key=lambda e: _ts2s(e.get("start_time")) or 0)
    return "\n\n".join(_event_line(e, with_duration) for e in ordered)


# ============================================================
# 主流程：切 Chapter → 切 Story
# ============================================================

def segment_chapters(client, tracker, events, duration_seconds, say) -> list:
    """第一步：用整场事件列表切 Chapter（算法同 PoC，提示词在 prompt_builder）。

    返回 chapters（原始 AI 结构，字段与 PoC 一致）；失败返回 []。
    """
    cfg = getattr(config, "CHAPTER_STORY", None) or {}
    max_chapters = int(cfg.get("max_chapters", 8))
    out_tokens = int(cfg.get("chapter_output_tokens", 2000))

    prompt = build_chapter_prompt(
        _events_text(events), duration=format_time(duration_seconds), max_chapters=max_chapters
    )
    try:
        reply, usage = client(prompt, system=CHAPTER_SYSTEM, max_tokens=out_tokens)
        tracker.add(usage)
    except Exception as e:
        say(f"[结构] Chapter 分割调用失败（跳过结构层）：{e}")
        return []

    data = _loads(reply)
    chapters = (data or {}).get("chapters") or []
    # 只保留字段齐全、时间合法的章节
    valid = []
    for ch in chapters:
        if _ts2s(ch.get("start_time")) is None or _ts2s(ch.get("end_time")) is None:
            continue
        ch.setdefault("chapter_id", f"ch-{len(valid) + 1:02d}")
        valid.append(ch)
    if not valid:
        say("[结构] Chapter 分割返回为空，结构层降级")
    return valid[:max_chapters]


def segment_stories(client, tracker, chapters, events, say) -> list:
    """第二步：在每个 Chapter 内、用该 Chapter 的事件切 Story（算法同 PoC）。

    失败时该 Chapter 整体降级为一个 Story（同 PoC 的降级策略）。
    """
    cfg = getattr(config, "CHAPTER_STORY", None) or {}
    out_tokens = int(cfg.get("story_output_tokens", 2000))

    stories = []
    for ch in chapters:
        ch_id = ch.get("chapter_id", "?")
        ch_start = _ts2s(ch.get("start_time"))
        ch_end = _ts2s(ch.get("end_time"))
        # 该 Chapter 内的事件（按事件起点归属，同 PoC 口径）
        ch_events = [e for e in events
                     if ch_start is not None and ch_end is not None
                     and ch_start <= (_ts2s(e.get("start_time")) or 0) < ch_end]
        if not ch_events:
            continue

        prompt = build_story_prompt(
            ch.get("chapter_title", ""), _events_text(ch_events, with_duration=True),
            len(ch_events),
        )
        got = []
        try:
            reply, usage = client(prompt, system=STORY_SYSTEM, max_tokens=out_tokens)
            tracker.add(usage)
            got = (_loads(reply) or {}).get("stories") or []
        except Exception as e:
            say(f"[结构] {ch_id} Story 分割失败，降级为单 Story：{e}")

        if got:
            for st in got:
                if _ts2s(st.get("start_time")) is None or _ts2s(st.get("end_time")) is None:
                    continue
                st["chapter_id"] = ch_id
                stories.append(st)
            say(f"[结构] {ch_id}：{len(got)} 个 Story")
        else:
            # 降级：整个 Chapter 当一个 Story（同 PoC）
            stories.append({
                "story_id": f"st-{str(ch_id).split('-')[-1]}",
                "chapter_id": ch_id,
                "name": ch.get("chapter_title", ""),
                "start_time": ch.get("start_time", ""),
                "end_time": ch.get("end_time", ""),
                "event_ids": [e.get("event_id") or e.get("clip_id") for e in ch_events],
                "summary": (ch.get("chapter_summary") or "")[:50],
                "reason": "未细分，整个 Chapter 作为一个 Story",
            })
            say(f"[结构] {ch_id}：降级为 1 个 Story")
    return stories


def get_or_build_structure(client, tracker, transcript_path, events, duration_seconds, say):
    """针对**当前视频**产出 Chapter/Story 结构。

    返回 (structure_dict, source)：
        source = "fresh"（本次现算）/ "cache"（复用同视频上次缓存）/ "empty"（降级）

    重要：默认**每次分析都重新生成**，保证结构与本场的 Event/Highlight 严格对应；
    生成后写入本视频自己的缓存，供下一次分析的事件聚合阶段做 Story 软先验。
    """
    cfg = getattr(config, "CHAPTER_STORY", None) or {}
    if not cfg.get("enabled", True):
        say("[结构] Chapter/Story 分割已在 config 中关闭")
        return {"chapters": [], "stories": []}, "empty"

    if not events:
        say("[结构] 没有事件，无法生成 Chapter/Story")
        return {"chapters": [], "stories": []}, "empty"

    # 可选：复用缓存（默认关闭——避免结构与本场事件不一致）
    if cfg.get("reuse_cache"):
        cached = load_cached_structure(transcript_path, duration_seconds)
        if cached:
            meta = cached.get("meta") or {}
            if int(meta.get("event_count", -1)) == len(events):
                say(f"[结构] 复用本视频缓存（事件数一致：{len(events)}）")
                return cached, "cache"

    say("[结构] 为本场视频生成 Chapter / Story …")
    chapters = segment_chapters(client, tracker, events, duration_seconds, say)
    stories = segment_stories(client, tracker, chapters, events, say)

    data = {
        "meta": {
            "transcript": str(transcript_path),
            "duration_seconds": int(duration_seconds),
            "event_count": len(events),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "method": "chapter_story_v1",
        },
        "chapters": chapters,
        "stories": stories,
    }
    if chapters or stories:
        save_cached_structure(transcript_path, data)
        say(f"[结构] 生成完成：{len(chapters)} 个 Chapter / {len(stories)} 个 Story"
            f"（已缓存到 {cache_path_for(transcript_path).name}）")
        return data, "fresh"

    say("[结构] 未产出有效结构，降级为空（UI 会提示无结构）")
    return {"chapters": [], "stories": []}, "empty"


def _loads(reply):
    """AI 回复 → dict；坏 JSON 返回 None（结构层不因解析失败而崩）。"""
    if isinstance(reply, dict):
        return reply
    try:
        return json.loads(reply)
    except (json.JSONDecodeError, TypeError):
        return None
