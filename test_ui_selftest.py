# ============================================================
# test_ui_selftest.py —— 新版 UI 基本自测（Streamlit AppTest，无浏览器、零成本）
#
# 目的：不点击浏览器也能确认「页面能跑起来、渲染出关键区块、不抛异常」。
#   S1 新格式结果（带 structure）→ 顶部信息 / ⭐推荐剪辑 / 🧭内容结构 / 🔧开发者视图 都在
#   S2 旧格式结果（无 structure）→ 静默降级，不崩
#   S3 空推荐结果 → 提示语正常，不崩
#
# 运行：.\.venv\Scripts\python test_ui_selftest.py
# 结果：ui_selftest_report.txt
# ============================================================

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
UI = ROOT / "ui.py"

from streamlit.testing.v1 import AppTest

from analysis import _select_quantity
from analysis import story_context as sc

LINES = []


def check(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    LINES.append(f"[{tag}] {name} —— {detail}")
    print(f"[{tag}] {name} —— {detail}")
    return ok


def _load_real_result():
    """用真实 V0.4.1 结果 + 新推荐逻辑 + 结构层，拼一份"新版格式"结果。"""
    d = json.loads((ROOT / "poc" / "v04_result.json").read_text(encoding="utf-8"))
    events = d["highlights"] + d["rejected"]
    for e in events:
        e["final_score"] = e.get("score")
        e["event_id"] = e.get("clip_id")
        if e["grade"] == "D":
            e["reject_reason"] = e.get("reject_reason") or ["低价值"]

    highlights, rejected = _select_quantity(events, "自动精选", None)
    structure = sc.build_content_structure(
        sc.load_structure(str(Path(__file__).parent / "poc" / "fixtures" / "story_segmentation_result.json")), events)
    return {
        "meta": d["meta"],
        "highlights": highlights,
        "rejected": rejected,
        "report": d.get("report", {"summary": "测试总结", "best_spread_point": "咖啡道歉",
                                   "overall": "中等", "why_not_more": "偏平淡"}),
        "structure": structure,
        "cost": d.get("cost", {"calls": 34, "cost_yuan": 0.3537}),
    }


def _all_text(at):
    """把页面所有 markdown / header / caption / metric 文本拼成一坨，便于断言。"""
    chunks = []
    for attr in ("markdown", "header", "subheader", "caption", "title", "info", "warning"):
        for el in getattr(at, attr, []):
            chunks.append(str(getattr(el, "value", "") or ""))
    for el in getattr(at, "metric", []):
        chunks.append(str(getattr(el, "label", "")) + str(getattr(el, "value", "")))
    for el in getattr(at, "expander", []):
        chunks.append(str(getattr(el, "label", "")))
    for el in getattr(at, "tabs", []):
        for t in getattr(el, "children", []) or []:
            pass
    return "\n".join(chunks)


print("=" * 70)
print("新版 UI 自测（Streamlit AppTest）")
print("=" * 70)

# ---------------- S1 新格式结果 ----------------
result = _load_real_result()
at = AppTest.from_file(str(UI), default_timeout=60)
at.session_state["v2_result"] = result
at.session_state["v2_transcript"] = "测试视频2.txt"
at.run()

ok = not at.exception
check("S1 页面运行无异常", ok,
      f"exceptions={[str(e) for e in at.exception][:2] if at.exception else '无'}")

text = _all_text(at)
ok = "视频信息" in text
check("S1 渲染顶部「视频信息」区", ok, "找到 视频信息" if ok else "未找到")

ok = "推荐剪辑" in text
check("S1 渲染主区域「⭐ 推荐剪辑」", ok, "找到 推荐剪辑" if ok else "未找到")

ok = "直播内容结构" in text
check("S1 渲染「🧭 直播内容结构」区", ok, "找到 直播内容结构" if ok else "未找到")

ok = "开发者视图" in text
check("S1 保留「🔧 开发者视图」（debug 能力未删）", ok, "找到 开发者视图" if ok else "未找到")

ok = "来自" in text
check("S1 推荐剪辑标注了来源 Story（关联闭环）", ok, "找到 来自" if ok else "未找到")

# 章节标题应出现在展开器/内容里
ok = "俄罗斯口粮深度测评与健康自嘲" in text
check("S1 展示 Chapter 标题", ok, "找到 Chapter 标题" if ok else "未找到")

ok = "咖啡测评：吐槽与豪饮" in text
check("S1 展示 Story 标题", ok, "找到 Story 标题" if ok else "未找到")

expander_labels = [str(e.label) for e in getattr(at, "expander", [])]
ok = any("俄罗斯口粮" in lb for lb in expander_labels)
check("S1 Chapter 以可展开形式呈现", ok,
      f"expander 数={len(expander_labels)}")

# ---- V0.4.3：界面不露 S/A/B/C/D 字母（D-044） ----
import re as _re
leaks = _re.findall(r"[SABCD]级|必剪|值得测试|备用/不推荐|强烈推荐", text)
ok = not leaks
check("S1 界面不露 S/A/B/C/D 分级字母与旧四档文案", ok,
      f"未发现分级字母" if ok else f"发现泄漏：{set(leaks)}")

ok = ("高光内容" in text) or ("有看点" in text)
check("S1 使用模糊化内容档位（高光内容 / 有看点）", ok,
      "找到 高光内容/有看点" if ok else "未找到模糊档位")

# ---------------- S2 旧格式结果（无 structure） ----------------
old = dict(result)
old.pop("structure", None)
old["highlights"] = [
    {k: v for k, v in h.items() if k not in ("recommended", "recommend_tier")}
    for h in result["highlights"]
]
at2 = AppTest.from_file(str(UI), default_timeout=60)
at2.session_state["v2_result"] = old
at2.session_state["v2_transcript"] = "测试视频2.txt"
at2.run()
ok = not at2.exception
check("S2 旧格式结果（无 structure）不崩", ok,
      f"exceptions={[str(e) for e in at2.exception][:2] if at2.exception else '无'}")
text2 = _all_text(at2)
ok = "没有 Chapter" in text2 or "旧版本" in text2
check("S2 无结构时给出降级提示", ok, "找到降级提示" if ok else "未找到提示")

# ---------------- S3 空推荐 ----------------
empty = dict(result)
empty["highlights"] = []
empty["rejected"] = result["highlights"] + result["rejected"]
at3 = AppTest.from_file(str(UI), default_timeout=60)
at3.session_state["v2_result"] = empty
at3.session_state["v2_transcript"] = "测试视频2.txt"
at3.run()
ok = not at3.exception
check("S3 空推荐结果不崩", ok,
      f"exceptions={[str(e) for e in at3.exception][:2] if at3.exception else '无'}")
text3 = _all_text(at3)
ok = "没有产生推荐剪辑" in text3
check("S3 空推荐给出提示语", ok, "找到提示" if ok else "未找到")


print("\n" + "=" * 70)
total = len(LINES)
passed = sum(1 for l in LINES if l.startswith("[PASS]"))
print(f"结果：{passed}/{total} 通过"
      + ("" if passed == total else f"，{total - passed} 个失败"))
print("=" * 70)

(ROOT / "ui_selftest_report.txt").write_text(
    "新版 UI 自测报告（Streamlit AppTest，纯本地零成本）\n\n"
    + "\n".join(LINES) + f"\n\n结果：{passed}/{total} 通过\n",
    encoding="utf-8",
)
print(f"report saved: {ROOT / 'ui_selftest_report.txt'}")
