# ============================================================
# test_v040_step7.py —— V0.4.4 数据绑定修复验收测试
#
# 背景（严重 bug）：
#   Chapter/Story 从未接进主流程，只在 PoC 阶段对一场固定 51 分钟测试视频跑过，
#   产物写死在 poc/story_segmentation_result.json；主流程无条件读它，
#   于是**换任何视频，UI 的「直播内容结构」都是同一套 ch-01~ch-04**。
#
# 本测试针对性验收（对应用户列的 5 条）：
#   1. 视频 A → 结构与 A 一致（标题含 A 的标记）
#   2. 换视频 B → 结构发生变化，且与 B 对应
#   3. 连续跑 A、B → B 的结果不含 A 的任何 Chapter/Story，反之亦然
#   4. 推荐剪辑与内容结构来自**同一次**分析（事件集合一致）
#   5. Story 结构缓存按视频隔离；时长/文件名不匹配一律不复用
#
# 零 API 成本：用假客户端模拟 Chapter/Story/海选/复审/报告全部回复。
#
# 运行：.\.venv\Scripts\python test_v040_step7.py
# 结果：v040_step7_report.txt
# ============================================================

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config
from analysis import (
    analyze_transcript_v2,
    SCREENING_SYSTEM,
    REVIEW_SYSTEM,
    MISS_CHECK_SYSTEM,
    EVENT_JUDGE_SYSTEM,
    REPORT_SYSTEM,
)
from analysis.prompt_builder import CHAPTER_SYSTEM, STORY_SYSTEM
from analysis import chapter_story, story_context as sc

LINES = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    LINES.append(f"[{tag}] {name} —— {detail}")
    print(f"[{tag}] {name} —— {detail}")
    return ok


USAGE = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}


def make_client(tag: str):
    """假客户端：海选/事件判断/复审/报告 + Chapter/Story 分割，全部按 tag 标记。"""
    state = {"screen": 0, "chapter": 0, "story": 0}

    def client(prompt, system=None, max_tokens=None):
        # ---- 海选：两个候选，标题带 tag（供 Chapter 提示词识别是哪个视频） ----
        if system == SCREENING_SYSTEM:
            state["screen"] += 1
            cands = [
                {"start_time": "00:00", "end_time": "00:30", "title": f"视频{tag}开场爆点",
                 "highlight_type": "事件型", "score": 7, "reason": f"视频{tag}开场有反差",
                 "category": "其他", "viral_probability": "高",
                 "editing_advice": "", "confidence": 0.8},
                {"start_time": "05:00", "end_time": "05:30", "title": f"视频{tag}后段爆点",
                 "highlight_type": "事件型", "score": 7, "reason": f"视频{tag}后段有梗",
                 "category": "其他", "viral_probability": "中",
                 "editing_advice": "", "confidence": 0.7},
            ]
            # 只在覆盖这两段时间的区块返回候选（按区块时间命中判断）
            if "00:00" in prompt or "05:00" in prompt:
                return json.dumps({"candidates": cands}, ensure_ascii=False), USAGE
            return json.dumps({"candidates": []}), USAGE

        if system == MISS_CHECK_SYSTEM:
            return json.dumps({"checks": []}), USAGE

        # ---- 事件判断：每个候选各自成事件（不聚合） ----
        if system == EVENT_JUDGE_SYSTEM:
            return json.dumps({
                "same_event": False,
                "event_summary": f"视频{tag}的一段内容",
                "event_type": "试吃",
                "event_start": "00:00", "event_end": "05:30",
                "structure": {"setup": "s", "development": "d", "payoff": "p"},
                "strongest_moment": "m", "reason": "不同事件", "confidence": 0.5,
                "need_more_context": False, "expand_direction": "",
            }, ensure_ascii=False), USAGE

        # ---- 复审：固定五维 = 7 → 70 分 ----
        if system == REVIEW_SYSTEM:
            import re
            eids = re.findall(r"（(ev-\d+)）", prompt)
            return json.dumps({"results": [{
                "event_id": eid, "title": f"事件{eid}",
                "scores": {"hook": 7, "contrast": 7, "personality": 7,
                           "standalone": 7, "completeness": 7},
                "recommended_start": "00:00", "recommended_end": "00:30",
                "recommended_duration": 30, "duration_reason": "完整",
                "negative_flags": [], "why_cut": "有反差", "strongest_moment": "m",
                "risk": "无", "confidence": 0.7, "context_incomplete": False,
            } for eid in eids]}), USAGE

        if system == REPORT_SYSTEM:
            return json.dumps({"summary": f"视频{tag}复盘", "best_spread_point": "开场",
                               "overall": "中等", "not_more": "", "why_not_more": "偏平淡",
                               "overall_note": ""}), USAGE

        # ---- V0.4.4 新增：Chapter 分割（按 tag 产出不同结构） ----
        if system == CHAPTER_SYSTEM:
            state["chapter"] += 1
            return json.dumps({"chapters": [
                {"chapter_id": "ch-01", "start_time": "00:00", "end_time": "02:00",
                 "chapter_title": f"视频{tag}第一章·开场", "chapter_summary": f"{tag}开场内容",
                 "boundary_reason": "主题切换", "event_ids": []},
                {"chapter_id": "ch-02", "start_time": "02:30", "end_time": "06:00",
                 "chapter_title": f"视频{tag}第二章·后段", "chapter_summary": f"{tag}后段内容",
                 "boundary_reason": "内容转折", "event_ids": []},
            ]}, ensure_ascii=False), USAGE

        # ---- V0.4.4 新增：Story 分割（按 chapter_title 里的标记区分第几章） ----
        if system == STORY_SYSTEM:
            state["story"] += 1
            is_first = "第一章" in prompt
            rng = ("00:00", "02:00") if is_first else ("02:30", "06:00")
            return json.dumps({"stories": [{
                "story_id": "st-01", "name": f"视频{tag}{'开场' if is_first else '后段'}故事",
                "start_time": rng[0], "end_time": rng[1], "event_ids": [],
                "summary": f"{tag}的一段连续内容",
                "reason": "连续活动",
            }]}, ensure_ascii=False), USAGE

        return json.dumps({"candidates": []}), USAGE

    return client, state


def write_transcript(path: Path, tag: str, minutes: int = 6):
    """造一份带 tag 标记的稿子（时间轴到 minutes 分钟）。"""
    lines = []
    # 每 30 秒一句，保证 chunker 能盖满时间轴
    t = 0
    while t < minutes * 60:
        mm, ss = divmod(t, 60)
        mm2, ss2 = divmod(t + 30, 60)
        lines.append(f"[{mm:02d}:{ss:02d} - {mm2:02d}:{ss2:02d}] 视频{tag}的第{t // 30 + 1}段内容，主播在聊事情")
        t += 30
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


print("=" * 70)
print("V0.4.4 验收：Chapter/Story 是否与当前视频正确绑定")
print("=" * 70)

# 把结构缓存指到临时目录，避免污染项目 structures/（同时验证 cache_dir 可配置）
tmp = Path(tempfile.mkdtemp())
config.STORY_CONTEXT["cache_dir"] = str(tmp / "structures")

transcript_a = write_transcript(tmp / "视频A.txt", "A")
transcript_b = write_transcript(tmp / "视频B.txt", "B")

# ============================================================
# 1 + 2. 两个不同视频，各自结构与自己一致
# ============================================================
print("\n--- 1/2. 两个视频分别分析，结构必须各自对应 ---")
client_a, state_a = make_client("A")
res_a = analyze_transcript_v2(transcript_a, live_type="娱乐聊天", token_mode="精细",
                              quantity_mode="自动精选", client=client_a, verbose=False)
client_b, state_b = make_client("B")
res_b = analyze_transcript_v2(transcript_b, live_type="娱乐聊天", token_mode="精细",
                              quantity_mode="自动精选", client=client_b, verbose=False)

struct_a = res_a["structure"]
struct_b = res_b["structure"]

titles_a = [c["title"] for c in struct_a["chapters"]]
titles_b = [c["title"] for c in struct_b["chapters"]]
check("1. 视频A 的结构来自视频A", bool(titles_a) and all("视频A" in t for t in titles_a),
      f"chapters={titles_a}")
check("2. 视频B 的结构来自视频B", bool(titles_b) and all("视频B" in t for t in titles_b),
      f"chapters={titles_b}")
check("2b. 换视频后结构确实发生变化", titles_a != titles_b,
      f"A={titles_a[:1]} vs B={titles_b[:1]}")

# ============================================================
# 3. 连续运行不互相继承
# ============================================================
print("\n--- 3. 连续跑两个视频，结果不互相污染 ---")
blob_a = json.dumps(struct_a, ensure_ascii=False)
blob_b = json.dumps(struct_b, ensure_ascii=False)
check("3. 视频B 的结果里不含视频A 的章节/故事", "视频A" not in blob_b,
      "未出现 视频A" if "视频A" not in blob_b else "发现串场！")
check("3b. 视频A 的结果里不含视频B 的章节/故事", "视频B" not in blob_a,
      "未出现 视频B" if "视频B" not in blob_a else "发现串场！")
check("3c. 两边的 Chapter 数量与标题各自独立",
      len(struct_a["chapters"]) == len(struct_b["chapters"]) == 2,
      f"A={len(struct_a['chapters'])}章, B={len(struct_b['chapters'])}章")
check("3d. 结构来源标记为本次现算（fresh）",
      struct_a.get("source") == "fresh" and struct_b.get("source") == "fresh",
      f"A={struct_a.get('source')}, B={struct_b.get('source')}")

# ============================================================
# 4. 推荐剪辑与内容结构来自同一次分析
# ============================================================
print("\n--- 4. 推荐剪辑 与 内容结构 同源 ---")
recs = [h for h in res_a["highlights"] if h.get("recommended")]
all_ids = {h.get("event_id") or h.get("clip_id") for h in res_a["highlights"] + res_a["rejected"]}
struct_event_ids = {e["event_id"] for ch in struct_a["chapters"]
                    for s in ch["stories"] for e in s["events"]}
check("4. 结构里的事件都来自本次分析的候选池",
      struct_event_ids.issubset(all_ids),
      f"结构事件={sorted(struct_event_ids)} / 本次全部={sorted(all_ids)}")
rec_ids = {h.get("event_id") or h.get("clip_id") for h in recs}
check("4b. 本次推荐剪辑都能在结构里找到归属",
      rec_ids.issubset(struct_event_ids),
      f"推荐={sorted(rec_ids)} 命中结构={len(rec_ids & struct_event_ids)}/{len(rec_ids)}")
check("4c. 本次确实产出了推荐剪辑（否则该断言无意义）", len(recs) >= 1,
      f"推荐 {len(recs)} 条")

# ============================================================
# 5. 结构缓存按视频隔离 + 校验
# ============================================================
print("\n--- 5. 结构缓存按视频隔离，绝不跨视频复用 ---")
cache_a = chapter_story.cache_path_for(transcript_a)
cache_b = chapter_story.cache_path_for(transcript_b)
check("5. 两个视频各自有独立缓存文件", cache_a != cache_b and cache_a.exists() and cache_b.exists(),
      f"{cache_a.name} / {cache_b.name}")

cached_a = chapter_story.load_cached_structure(transcript_a, res_a["meta"] and 360)
check("5b. 视频A 能读回自己的缓存",
      bool(cached_a) and all("视频A" in json.dumps(c, ensure_ascii=False)
                             for c in cached_a.get("chapters", [])),
      f"chapters={[c.get('chapter_title') for c in (cached_a or {}).get('chapters', [])]}")

# 用「另一份稿子的时长」去读 → 必须拒绝
check("5c. 时长不匹配的缓存拒绝复用",
      chapter_story.load_cached_structure(transcript_a, 99999) is None,
      "已拒绝跨时长复用")

# 不存在的稿子 → 没有缓存（绝不能退化成别的视频的结构）
check("5d. 没有缓存的视频返回 None（不会借用别人的结构）",
      chapter_story.load_cached_structure(tmp / "从未分析过.txt", 360) is None,
      "返回 None")

# 缓存中的 transcript 字段必须指向自己
meta_a = json.loads(cache_a.read_text(encoding="utf-8"))["meta"]
check("5e. 缓存 meta 记录了本视频路径与时长",
      Path(meta_a["transcript"]).name == "视频A.txt" and meta_a["duration_seconds"] == 360,
      f"transcript={Path(meta_a['transcript']).name}, duration={meta_a['duration_seconds']}")

# ============================================================
# 6. story_context 不再有固定文件 fallback
# ============================================================
print("\n--- 6. 固定样例文件 fallback 已彻底移除 ---")
check("6. load_structure() 默认返回空结构（不再读固定样例）",
      sc.load_structure() == {"chapters": [], "stories": []},
      f"实际={sc.load_structure()}")
check("6b. load_story_groups() 默认返回空（不再读固定样例）",
      sc.load_story_groups() == {},
      f"实际={sc.load_story_groups()}")
check("6c. config 里已无 story_file 固定路径项",
      "story_file" not in (getattr(config, "STORY_CONTEXT", {}) or {}),
      f"STORY_CONTEXT keys={list((getattr(config, 'STORY_CONTEXT', {}) or {}).keys())}")
poc_sample = Path(__file__).parent / "poc" / "story_segmentation_result.json"
check("6d. 开发样例已移出 poc 根目录（不会被执行路径误读）",
      not poc_sample.exists(),
      "poc/story_segmentation_result.json 不存在" if not poc_sample.exists() else "仍在原处！")

# ============================================================
# 7. 现有回归（step1~6）全部通过
# ============================================================
print("\n--- 7. 现有 Chapter/Story/Event/Highlight 回归 ---")
regression_ok = True
regression_detail = []
for n in range(1, 7):
    tfile = Path(__file__).parent / f"test_v040_step{n}.py"
    r = subprocess.run([sys.executable, str(tfile)], capture_output=True, cwd=str(Path(__file__).parent))
    report = Path(__file__).parent / f"v040_step{n}_report.txt"
    fails = 0
    if report.exists():
        fails = report.read_text(encoding="utf-8").count("[FAIL]")
    ok = r.returncode == 0 and fails == 0
    regression_ok &= ok
    regression_detail.append(f"step{n}:{'OK' if ok else 'FAIL'}")
check("7. step1~6 全量回归通过", regression_ok, " ".join(regression_detail))

# ---- 清理临时缓存 ----
shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 70)
total = len(LINES)
passed = sum(1 for l in LINES if l.startswith("[PASS]"))
print(f"结果：{passed}/{total} 通过" + ("" if passed == total else f"，{total - passed} 个失败"))
print("=" * 70)

(Path(__file__).parent / "v040_step7_report.txt").write_text(
    "V0.4.4 数据绑定修复验收报告（Chapter/Story 与视频正确绑定）\n\n"
    + "\n".join(LINES) + f"\n\n结果：{passed}/{total} 通过\n",
    encoding="utf-8",
)
print(f"report saved: {Path(__file__).parent / 'v040_step7_report.txt'}")
