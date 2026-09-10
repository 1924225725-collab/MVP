"""story_context —— Story 前置层接入（v0.4 步骤 4）。

职责：
  1. 加载已验证的 Story 分割结果（poc/story_segmentation_result.json）
  2. 把每个 Story 的起止时间映射成 seconds 区间
  3. 给候选列表打故事标注（_annotate_candidates）—— 每个候选记录它属于哪个 Story
  4. 构建 story_groups：{story_id: [候选下标列表]} —— 供 event_cluster.build_clusters 用

关键约束（DECISIONS.md D-025/D-026）：
  - Story 是软边界，不阻止跨 Story 取上下文
  - 不推翻 A1/A2/A3/B1，不改海选/复审逻辑
  - 只影响事件聚合层：同 Story 内候选关联分 +0.05，跨 Story 不额外减速（保持原逻辑）
  - 若 Story 文件不存在或格式错误，静默跳过，行为退化成无故事标注（不崩）
"""

import json
from pathlib import Path


def _ts2s(t):
    """'01:23' / '00:01:23' / '120' → 秒。不合法返回 None。"""
    if t is None:
        return None
    try:
        # 先尝试纯数字（秒数）
        if isinstance(t, (int, float)):
            return int(t)
        s = str(t).strip()
        if s.isdigit():
            return int(s)
        parts = [int(p) for p in s.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except (ValueError, AttributeError):
        pass
    return None


def _read_structure_source(source):
    """把「结构来源」读成 dict。

    source 可以是：
      - dict：直接用（主流程由 chapter_story 生成后传进来，推荐方式）
      - str / Path：读该 JSON 文件（测试夹具、离线复算用）
      - None：返回空结构

    ⚠️ V0.4.4 修复：**None 不再回落到 poc/story_segmentation_result.json**。
    那个文件是开发阶段对一场固定 51 分钟测试视频的 PoC 产物，曾被当成生产默认值，
    导致换任何视频 UI 都显示同一套 Chapter/Story（严重数据绑定 bug）。
    """
    if source is None:
        return {}
    if isinstance(source, dict):
        return source
    try:
        with open(source, encoding="utf-8") as f:
            return json.load(f) or {}
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        return {}


def _stories_of(source) -> list:
    """从结构来源里取出 stories 列表（统一入口，绝不隐式加载固定文件）。"""
    return _read_structure_source(source).get("stories", []) or []


def load_story_groups(source=None) -> dict:
    """加载 Story 结构，返回 {story_id: {"start": sec, "end": sec, "chapter_id": str}}。

    source 语义见 _read_structure_source：dict（主流程）/ 路径（测试夹具）/ None（空）。

    注意：Story ID 可能重复（不同 Chapter 都用 st-01），因此实际返回的 key 是
    "chapter_id-story_id"（如 "ch-01-st-01"），保证唯一性。

    ⚠️ V0.4.4：不再有「默认读 poc 样例文件」的行为。
    """
    stories = _stories_of(source)
    if not stories:
        return {}
    groups = {}
    for st in stories:
        chapter_id = st.get("chapter_id", "unknown")
        story_id = st.get("story_id", "unknown")
        unique_id = f"{chapter_id}-{story_id}"
        start = _ts2s(st.get("start_time"))
        end = _ts2s(st.get("end_time"))
        if start is None or end is None:
            continue
        groups[unique_id] = {
            "start": start,
            "end": end,
            "chapter_id": chapter_id,
            "story_id": story_id,
        }
    return groups


def annotate_candidates(candidates: list, story_groups: dict) -> list:
    """给候选列表注入 story_id 字段（原地修改，返回 candidates）。

    逻辑：候选时间戳区间与 Story 时间戳区间有交集 → 打上该 story_id。
    若多个 Story 时间重叠（理论上不应发生），取第一个命中的；
    若都不命中 → 标为 "__unknown__"（方便审计「有多少候选没被 Story 覆盖」）。
    """
    story_list = sorted(story_groups.items(), key=lambda kv: kv[1]["start"])
    for c in candidates:
        cs = _ts2s(c.get("start_time"))
        ce = _ts2s(c.get("end_time"))
        matched = None
        if cs is not None and ce is not None:
            for sid, interval in story_list:
                if not (ce <= interval["start"] or cs >= interval["end"]):
                    matched = sid
                    break
        c["story_id"] = matched if matched else "__unknown__"
    return candidates


def build_story_groups(candidates: list, story_groups: dict) -> dict:
    """从已标注 story_id 的候选列表，构建 {story_id: [候选下标]}。

    用于 event_cluster.build_clusters 做同 Story 加分。
    返回结构：
      {
        "st-01": [0, 1, 2],   # 候选下标
        "st-02": [3, 4],
        "__unknown__": [5, 6],
      }
    """
    groups = {}
    for idx, c in enumerate(candidates):
        sid = c.get("story_id", "__unknown__")
        groups.setdefault(sid, []).append(idx)
    return groups


# ============================================================
# V0.4.2：内容结构层（Chapter → Story → Event 展示用）
#
# 职责边界（重要）：
#   - 只做「读取已验证结构 + 把事件挂到 Story 下 + 派生展示用评分」，纯本地零成本；
#   - 不改任何分析/评分算法，不改海选/复审/事件聚合；
#   - 结构缺失时静默降级为空结构，主流程照常返回结果（UI 自动退化为无结构展示）。
# ============================================================

def _default_story_file() -> str:
    """⚠️ V0.4.4 起**不再用于生产**。仅作为 PoC 夹具的路径提示，供文档/脚本引用。

    真正的结构来源是主流程里 `chapter_story.get_or_build_structure()` 按视频现算的结果。
    """
    return str(Path(__file__).resolve().parent.parent / "poc" / "fixtures"
               / "story_segmentation_result.json")


def load_structure(source=None) -> dict:
    """加载 Chapter/Story 层级结构（source 语义见 _read_structure_source）。

    返回 {"chapters": [...], "stories": [...]}，每项都已补 seconds 区间：
      chapter: {chapter_id, title, summary, boundary_reason, start_time, end_time, start, end}
      story:   {story_id(唯一 ch-xx-st-yy), raw_story_id, chapter_id, title, summary,
                reason, start_time, end_time, start, end}

    ⚠️ V0.4.4 修复：**默认（source=None）返回空结构**，不再读固定样例文件。
    主流程会把 `chapter_story` 为当前视频生成的结构 dict 直接传进来。
    """
    data = _read_structure_source(source)
    if not data:
        return {"chapters": [], "stories": []}

    chapters = []
    for ch in data.get("chapters", []) or []:
        start = _ts2s(ch.get("start_time"))
        end = _ts2s(ch.get("end_time"))
        if start is None or end is None:
            continue
        chapters.append({
            "chapter_id": ch.get("chapter_id", "unknown"),
            "title": ch.get("chapter_title", ""),
            "summary": ch.get("chapter_summary", ""),
            "boundary_reason": ch.get("boundary_reason", ""),
            "start_time": ch.get("start_time", ""),
            "end_time": ch.get("end_time", ""),
            "start": start,
            "end": end,
        })

    stories = []
    for st in data.get("stories", []) or []:
        start = _ts2s(st.get("start_time"))
        end = _ts2s(st.get("end_time"))
        if start is None or end is None:
            continue
        chapter_id = st.get("chapter_id", "unknown")
        raw_id = st.get("story_id", "unknown")
        stories.append({
            "story_id": f"{chapter_id}-{raw_id}",   # 唯一化（不同 Chapter 会重复用 st-01）
            "raw_story_id": raw_id,
            "chapter_id": chapter_id,
            # 兼容两种键名：主流程 AI 输出用 name/summary，PoC 夹具用 story_title/story_summary
            "title": st.get("story_title") or st.get("name", ""),
            "summary": st.get("story_summary") or st.get("summary", ""),
            "reason": st.get("reason", ""),
            "start_time": st.get("start_time", ""),
            "end_time": st.get("end_time", ""),
            "start": start,
            "end": end,
        })

    return {"chapters": chapters, "stories": stories}


def _grade_from_score(score):
    """按 config 的 S/A/B/C 阈值给分定级。分缺失/非法 → 空字符串（未评）。"""
    try:
        score = float(score)
    except (TypeError, ValueError):
        return ""
    try:
        import config
        s_line, a_line, b_line, c_line = (
            config.GRADE_S_SCORE, config.GRADE_A_SCORE,
            config.GRADE_B_SCORE, config.GRADE_C_SCORE,
        )
    except Exception:      # 极端情况下 config 不可用，用与 config 同构的兜底阈值
        s_line, a_line, b_line, c_line = 90, 80, 60, 50
    if score >= s_line:
        return "S"
    if score >= a_line:
        return "A"
    if score >= b_line:
        return "B"
    if score >= c_line:
        return "C"
    return "D"


def _event_brief(e: dict) -> dict:
    """把内部事件压成结构层/UI 需要的精简字段（不复制大块原文）。"""
    return {
        "event_id": e.get("event_id") or e.get("clip_id", ""),
        "grade": e.get("grade", ""),
        "score": e.get("final_score", e.get("score")),
        "start_time": e.get("start_time", ""),
        "end_time": e.get("end_time", ""),
        "title": e.get("title", ""),
        "summary": e.get("summary", "") or e.get("reason", ""),
        "event_type": e.get("event_type", ""),
        "duration": e.get("duration"),
        "recommended": bool(e.get("recommended")),
        "recommend_tier": e.get("recommend_tier", ""),
    }


def build_content_structure(structure: dict, events: list) -> dict:
    """把事件按时间交集挂到 Story 下，并派生 Story / Chapter 的展示用评分。

    Story 评分 = 该 Story 内最强事件的分数（不是新算一套评分——不碰评分模型）；
    Story 等级 = 该分数按 config 阈值定级。Story 下没有事件 → score=None、grade=""。

    返回：
      {
        "chapters": [
          {chapter_id, title, summary, boundary_reason, start_time, end_time,
           score, grade, story_count, event_count,
           stories: [{story_id, title, summary, reason, start_time, end_time,
                      score, grade, best_event_id, event_count, events: [brief...]}]}
        ],
        "stats": {chapter_count, story_count, stories_with_events, best_story_id, ...}
      }
    """
    chapters = list(structure.get("chapters", []) or [])
    stories = list(structure.get("stories", []) or [])
    briefs = [_event_brief(e) for e in (events or [])]

    def _overlaps(brief, story):
        bs = _ts2s(brief.get("start_time"))
        be = _ts2s(brief.get("end_time"))
        if bs is None or be is None:
            return False
        return not (be <= story["start"] or bs >= story["end"])

    by_chapter = {}
    for st in stories:
        by_chapter.setdefault(st["chapter_id"], []).append(st)

    # Chapter 缺失但 Story 存在的兜底（防御，不常见）
    known = {c["chapter_id"] for c in chapters}
    for cid in by_chapter:
        if cid not in known:
            chapters.append({
                "chapter_id": cid, "title": cid, "summary": "",
                "boundary_reason": "", "start_time": "", "end_time": "",
                "start": min(s["start"] for s in by_chapter[cid]),
                "end": max(s["end"] for s in by_chapter[cid]),
            })

    out_chapters = []
    for ch in chapters:
        out_stories = []
        for st in by_chapter.get(ch["chapter_id"], []):
            members = [b for b in briefs if _overlaps(b, st)]
            members.sort(key=lambda b: -(b.get("score") or 0))
            best = members[0] if members else None
            score = best.get("score") if best else None
            out_stories.append({
                "story_id": st["story_id"],
                "raw_story_id": st.get("raw_story_id", ""),
                "title": st["title"],
                "summary": st["summary"],
                "reason": st.get("reason", ""),
                "start_time": st["start_time"],
                "end_time": st["end_time"],
                "start": st["start"],
                "end": st["end"],
                "score": score,
                "grade": _grade_from_score(score),
                "best_event_id": best.get("event_id") if best else "",
                "event_count": len(members),
                "events": members,
            })
        out_stories.sort(key=lambda s: s["start"])
        ch_score = max((s["score"] for s in out_stories if s.get("score") is not None),
                       default=None)
        out_chapters.append({
            "chapter_id": ch["chapter_id"],
            "title": ch["title"],
            "summary": ch["summary"],
            "boundary_reason": ch.get("boundary_reason", ""),
            "start_time": ch["start_time"],
            "end_time": ch["end_time"],
            "start": ch["start"],
            "end": ch["end"],
            "score": ch_score,
            "grade": _grade_from_score(ch_score),
            "story_count": len(out_stories),
            "event_count": sum(s["event_count"] for s in out_stories),
            "stories": out_stories,
        })
    out_chapters.sort(key=lambda c: c["start"])

    all_stories = [s for c in out_chapters for s in c["stories"]]
    with_events = [s for s in all_stories if s["event_count"] > 0]
    best = max(with_events, key=lambda s: (s.get("score") or 0), default=None)
    stats = {
        "chapter_count": len(out_chapters),
        "story_count": len(all_stories),
        "stories_with_events": len(with_events),
        "stories_without_events": len(all_stories) - len(with_events),
        "best_story_id": best["story_id"] if best else "",
        "best_story_title": best["title"] if best else "",
        "best_story_score": best.get("score") if best else None,
    }
    return {"chapters": out_chapters, "stats": stats}

