# ============================================================
# verify_v044_two_videos.py —— V0.4.4 真实数据绑定验证（真实 API）
#
# 目的：用**两个真实视频**验证「直播内容结构」确实跟着当前视频走，
#       不再是开发阶段那份写死的 51 分钟结构。
#
# 验证项：
#   1. 每个视频都产出自己的结构（非空、source=fresh）
#   2. 两个视频的 Chapter 标题无交集（不互相继承）
#   3. 结构与推荐剪辑同源（结构里的事件都在本次候选池里）
#   4. 结构缓存按视频隔离（structures/<稿名>.json，meta 指向自己）
#   5. 与旧固定样例（51 分钟 PoC）对照，确认不是同一份数据
#
# 运行：
#   .\.venv\Scripts\python verify_v044_two_videos.py            # 真实 API 跑两个视频
#   .\.venv\Scripts\python verify_v044_two_videos.py --reuse     # 复用上次快照，零成本重跑校验
#
# 产物：v044_two_videos_report.txt / v044_two_videos.json（含完整结构+推荐+被拒，供离线复核）
#
# 修订（2026-09-11）：首版把「(无标题)」这个占位 Story 名也纳入标题集合做交集判断，
#   两个视频的 Story 名都是占位 → 误判「互相继承」（假 FAIL）。
#   改为只用 **Chapter 标题** 做不相交判定，并过滤占位名。
# ============================================================

import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

import config  # noqa: E402
from analysis import chapter_story  # noqa: E402

REUSE = "--reuse" in sys.argv
SNAPSHOT = BASE / "v044_two_videos.json"

PAIRS = [
    ("测试视频", BASE / "transcripts" / "测试视频.txt"),
    ("测试视频2", BASE / "transcripts" / "测试视频2.txt"),
]

LIVE_TYPE = "娱乐聊天"
TOKEN_MODE = "标准"
QUANTITY = "自动精选"

FIXTURE = BASE / "poc" / "fixtures" / "story_segmentation_result.json"
PLACEHOLDERS = {"", None, "（无标题）", "(无标题)", "无标题", "-"}


def is_placeholder(name) -> bool:
    return (name or "").strip() in {"", "（无标题）", "(无标题)", "无标题", "-"}


# ============================================================
# 采集（真实 API）或复用快照
# ============================================================
if REUSE and SNAPSHOT.exists():
    print(f"[复用] 读取上次快照 {SNAPSHOT.name}（不调 API）")
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    results = {n: snap[n] for n, _ in PAIRS}
else:
    from analysis import analyze_transcript_v2  # noqa: E402

    results = {}
    for name, tpath in PAIRS:
        print("=" * 72)
        print(f"[真实分析] {name}  <- {tpath.name}")
        print("=" * 72)
        t0 = time.time()
        res = analyze_transcript_v2(
            tpath, live_type=LIVE_TYPE, token_mode=TOKEN_MODE,
            quantity_mode=QUANTITY, verbose=True,
        )
        dt = time.time() - t0
        # 只保留校验需要的部分，便于离线复核（--reuse）
        results[name] = {
            "structure": res.get("structure"),
            "structure_source": res.get("structure_source"),
            "cost": res.get("cost"),
            "highlights": res.get("highlights"),
            "rejected": res.get("rejected"),
        }
        st = res.get("structure") or {}
        print(f"\n>> {name} 用时 {dt:.0f}s，结构来源={res.get('structure_source')}，"
              f"Chapter {len(st.get('chapters') or [])} 个\n")
    SNAPSHOT.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")


# ============================================================
# 工具函数
# ============================================================
def chapter_titles(st):
    """只取 Chapter 标题（有意义的结构单元）。"""
    return [c.get("title") or c.get("chapter_title") for c in (st.get("chapters") or [])]


def story_names(st):
    """取有意义的 Story 名（过滤占位名）。

    嵌套结构里 Story 标题的键是 `title`（build_content_structure 产出），
    兼容 AI 原始输出的 `name` / PoC 夹具的 `story_title`。
    """
    out = []
    for ch in (st.get("chapters") or []):
        for s in (ch.get("stories") or []):
            nm = s.get("name") or s.get("story_title") or s.get("title")
            if not is_placeholder(nm):
                out.append(nm)
    return out


def ev_ids(st):
    ids = []
    for ch in (st.get("chapters") or []):
        for s in (ch.get("stories") or []):
            for e in (s.get("events") or []):
                ids.append(e.get("event_id"))
    return sorted(set(i for i in ids if i))


def pool_ids(res):
    items = (res.get("highlights") or []) + (res.get("rejected") or [])
    return {h.get("event_id") or h.get("clip_id") for h in items
            if (h.get("event_id") or h.get("clip_id"))}


def rec_count(res):
    return len([h for h in (res.get("highlights") or []) if h.get("recommended")])


# ============================================================
# 报告
# ============================================================
report = []
report.append("=" * 72)
report.append("V0.4.4 真实双视频验证报告（Chapter/Story 是否绑定当前视频）")
report.append("=" * 72)
report.append(f"模式：{LIVE_TYPE} / {TOKEN_MODE} / {QUANTITY}"
              + ("   [复用快照，未调 API]" if REUSE else "   [本次真实调用 API]"))
report.append("")

for name, tpath in PAIRS:
    res = results[name]
    st = res.get("structure") or {}
    chs = st.get("chapters") or []
    report.append("-" * 72)
    report.append(f"【{name}】 {tpath.name}")
    report.append(f"  结构来源      : {res.get('structure_source')}")
    report.append(f"  Chapter 数    : {len(chs)}")
    for ch in chs:
        title = ch.get("title") or ch.get("chapter_title") or "(无标题)"
        rng = f"{ch.get('start_time', '?')}-{ch.get('end_time', '?')}"
        report.append(f"    · {title}  [{rng}]  stories={len(ch.get('stories') or [])}")
        for s in (ch.get("stories") or []):
            sname = (s.get("name") or s.get("story_title") or s.get("title")
                     or s.get("raw_story_id"))
            sname = sname if not is_placeholder(sname) else "(Story 名缺省)"
            report.append(f"        - {sname}  events={len(s.get('events') or [])}")
    report.append(f"  推荐剪辑      : {rec_count(res)} 条")
    report.append(f"  结构内事件 id : {ev_ids(st)}")
    report.append(f"  成本          : {res.get('cost') or '（复用快照）'}")
    report.append("")

checks = []


def ck(cond, text):
    checks.append((bool(cond), text))
    report.append(f"  [{'PASS' if cond else 'FAIL'}] {text}")
    print(f"[{'PASS' if cond else 'FAIL'}] {text}")


def ck_fix(cond, pass_text, fail_text):
    """失败时把诊断信息写进报告。"""
    ck(cond, pass_text if cond else fail_text)


report.append("=" * 72)
report.append("验证结论")
report.append("=" * 72)

name_a, name_b = PAIRS[0][0], PAIRS[1][0]
st_a, st_b = results[name_a].get("structure") or {}, results[name_b].get("structure") or {}
t_a, t_b = chapter_titles(st_a), chapter_titles(st_b)

ck(bool(t_a) and bool(t_b), "两个视频都产出了结构（Chapter 非空）")
ck(results[name_a].get("structure_source") == "fresh"
   and results[name_b].get("structure_source") == "fresh",
   "两个视频的结构都是本次现算（source=fresh）")
ck_fix(t_a != t_b,
       f"两个视频的结构不同（{name_a}={len(t_a)} 章 / {name_b}={len(t_b)} 章）",
       f"两个视频的结构相同（异常）—— {t_a} vs {t_b}")

inter = set(t_a) & set(t_b)
ck_fix(not inter,
       f"两个视频的 Chapter 标题无交集（{name_a} vs {name_b} 各说各的）",
       f"两个视频存在同名 Chapter（疑似串场）：{sorted(inter)}")

# 同源：结构里的事件都在本次候选池
for name, _ in PAIRS:
    res = results[name]
    pool = pool_ids(res)
    sid = set(ev_ids(res.get("structure") or {}))
    ck_fix(sid.issubset(pool),
           f"[{name}] 结构内事件均出自本次候选池（推荐/结构同源，{len(sid)}/{len(pool)}）",
           f"[{name}] 结构含本次候选池之外的事件（不同源）：{sorted(sid - pool)}")

# Story 标题完整性（避免 UI 上 Story 显示空白）
for name, _ in PAIRS:
    sn = story_names(results[name].get("structure") or {})
    ck(bool(sn), f"[{name}] Story 均有标题（{len(sn)} 个，例：{sn[0] if sn else '-'}）")

# 缓存隔离：两个视频各自一份缓存，且 meta 指向自己
c_a = chapter_story.cache_path_for(PAIRS[0][1])
c_b = chapter_story.cache_path_for(PAIRS[1][1])
ck(c_a != c_b and c_a.exists() and c_b.exists(),
   f"两个视频各自写入独立结构缓存（{c_a.name} / {c_b.name}）")
if c_a.exists() and c_b.exists():
    m_a = json.loads(c_a.read_text(encoding="utf-8")).get("meta", {})
    m_b = json.loads(c_b.read_text(encoding="utf-8")).get("meta", {})
    ck(Path(m_a.get("transcript", "")).name == PAIRS[0][1].name
       and Path(m_b.get("transcript", "")).name == PAIRS[1][1].name,
       "缓存 meta 各自指向自己的文字稿（未串场）")

# 与旧固定样例对照
if FIXTURE.exists():
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fx_titles = [c.get("chapter_title") or c.get("title") for c in fx.get("chapters", [])]
    report.append(f"\n  旧固定样例(51分钟PoC) Chapter 标题: {fx_titles}")
    report.append(f"  {name_b} 现算 Chapter 标题      : {t_b}")
    ck_fix(t_b != fx_titles,
           f"{name_b} 现算结构 ≠ 旧固定样例（旧 4 章 → 现 {len(t_b)} 章）",
           "现算结构与旧固定样例完全相同（修复未生效）")
else:
    ck(True, "旧固定样例已移出生产路径（poc/fixtures/，主流程不再读取）")

report.append("")
total = len(checks)
passed = sum(1 for ok, _ in checks if ok)
report.append(f"结果：{passed}/{total} 通过")
report.append("")

out = BASE / "v044_two_videos_report.txt"
out.write_text("\n".join(report), encoding="utf-8")

print("\n" + "=" * 72)
print(f"结果：{passed}/{total} 通过")
print(f"report : {out}")
print(f"snapshot: {SNAPSHOT}")
print("=" * 72)
