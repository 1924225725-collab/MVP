# ============================================================
# test_v040_step1.py —— v0.4 第一步离线自测（纯本地，零 API 成本）
#
# 本次只做两件基础能力：ASR 词库纠错 + 人工反馈记录。
# 都不碰 AI 判断逻辑，所以全部可以离线验证。
#
# 验收目标：
#   A 词库加载：
#     1. 分类结构能摊平成对照表
#     2. _开头的注释字段被跳过
#     3. 文件不存在 → 空表，不崩
#     4. 坏 JSON → 空表，不崩
#     5. 扁平写法（不分分类）也兼容
#     6. 项目里的 custom_dictionary.json 能正常读出来
#   B 文本替换：
#     7. 错词被改成正确词
#     8. 长词优先（先替「伏特加酒」再替「伏特加」）
#     9. 没命中时原样返回
#     10. 空词库 / 空文本不崩
#   C 识别结果纠正：
#     11. dict 列表能纠正，命中数准确
#     12. Segment 对象列表能纠正，命中数准确
#   D 文字稿文件纠正：
#     13. 台词被改对
#     14. 时间戳一个字都不许变（关键）
#     15. 返回改了几行
#     16. 文件不存在 → 返回 0，不崩
#   E 反馈记录：
#     17. 首次写入建文件，字段齐全
#     18. 追加第二条
#     19. 同一 clip_id 覆盖（不堆积重复数据）
#     20. snapshot 片段信息存进去了
#     21. 文件写坏了能自愈
#     22. 能按 clip_id 查回反馈
#     23. 统计文案正确
#
# 运行：.\.venv\Scripts\python test_v040_step1.py
# 结果：v040_step1_report.txt
# ============================================================

import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analysis import dictionary, feedback
from asr.base import Segment

BASE_DIR = Path(__file__).parent
REPORT_FILE = BASE_DIR / "v040_step1_report.txt"

_report = []


def log(msg=""):
    _report.append(msg)
    print(msg.encode("ascii", "replace").decode("ascii"))


def check(name, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    log(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
    return ok


# ---------------- A 词库加载 ----------------

def scenario_a():
    log("--- A 词库加载 ---")
    tmp = Path(tempfile.mkdtemp())

    # 1 分类结构摊平
    p = tmp / "dict_classified.json"
    p.write_text(json.dumps({
        "_说明": "这是注释，不该被当成词条",
        "主播名字": {"河石": "河石"},
        "品牌": {"福岛": "伏特加"},
        "网络热词": {"卧槽": "我靠"},
    }, ensure_ascii=False), encoding="utf-8")
    m = dictionary.load_dictionary(p)
    check("分类结构摊平成对照表",
          m.get("福岛") == "伏特加" and m.get("卧槽") == "我靠" and len(m) == 3,
          f"{m}")

    # 2 注释字段跳过
    check("_开头注释字段被跳过", "_说明" not in m, f"keys={list(m)}")

    # 3 文件不存在 → 空表
    check("文件不存在返回空表不崩",
          dictionary.load_dictionary(tmp / "nope.json") == {})

    # 4 坏 JSON → 空表
    bad = tmp / "bad.json"
    bad.write_text("{这不是合法 JSON", encoding="utf-8")
    check("坏 JSON 返回空表不崩", dictionary.load_dictionary(bad) == {})

    # 5 扁平写法兼容
    flat = tmp / "flat.json"
    flat.write_text(json.dumps({"福岛": "伏特加", "河石": "河石"},
                               ensure_ascii=False), encoding="utf-8")
    m2 = dictionary.load_dictionary(flat)
    check("扁平写法（不分分类）也兼容",
          m2.get("福岛") == "伏特加" and len(m2) == 2, f"{m2}")

    # 6 项目真实词库
    real = dictionary.load_dictionary()
    check("项目 custom_dictionary.json 可读",
          len(real) >= 1 and "福岛" in real,
          f"{len(real)} 条，示例：{list(real.items())[:3]}")


# ---------------- B 文本替换 ----------------

def scenario_b():
    log()
    log("--- B 文本替换 ---")

    # 7 单词替换
    m = {"福岛": "伏特加"}
    check("错词被改成正确词",
          dictionary.apply_correction("这瓶福岛真好喝", m) == "这瓶伏特加真好喝",
          dictionary.apply_correction("这瓶福岛真好喝", m))

    # 8 长词优先
    m2 = {"伏特加": "短词版", "伏特加酒": "长词版"}
    r = dictionary.apply_correction("喝了伏特加酒", m2)
    check("长词优先替换（不把长词咬一半）",
          "长词版" in r and "短词版" not in r, r)

    # 9 无命中
    check("没命中时原样返回",
          dictionary.apply_correction("今天天气不错", m) == "今天天气不错")

    # 10 空值不崩
    ok = (dictionary.apply_correction("", m) == ""
          and dictionary.apply_correction("有福岛", {}) == "有福岛"
          and dictionary.apply_correction(None, m) is None)
    check("空词库 / 空文本不崩", ok)


# ---------------- C 识别结果纠正 ----------------

def scenario_c():
    log()
    log("--- C 识别结果纠正 ---")
    m = {"福岛": "伏特加"}

    # 11 dict 列表
    segs = [
        {"start": 0.0, "end": 2.0, "text": "这瓶福岛真好喝"},
        {"start": 2.0, "end": 4.0, "text": "今天天气不错"},
        {"start": 4.0, "end": 6.0, "text": "再喝一口福岛"},
    ]
    hits = dictionary.correct_segments(segs, m)
    check("dict 列表能纠正且命中数准确",
          hits == 2 and segs[0]["text"] == "这瓶伏特加真好喝"
          and segs[2]["text"] == "再喝一口伏特加",
          f"命中 {hits} 处：{[s['text'] for s in segs]}")

    # 12 Segment 对象列表
    objs = [
        Segment(start=0.0, end=2.0, text="这瓶福岛真好喝"),
        Segment(start=2.0, end=4.0, text="没什么事"),
    ]
    hits2 = dictionary.correct_segments(objs, m)
    check("Segment 对象列表能纠正且命中数准确",
          hits2 == 1 and objs[0].text == "这瓶伏特加真好喝",
          f"命中 {hits2} 处：{objs[0].text}")


# ---------------- D 文字稿文件纠正 ----------------

def scenario_d():
    log()
    log("--- D 文字稿文件纠正（时间戳必须不动） ---")
    tmp = Path(tempfile.mkdtemp())
    m = {"福岛": "伏特加"}

    p = tmp / "稿子.txt"
    original = (
        "[00:12 - 00:15] 这瓶福岛真好喝\n"
        "[00:15 - 00:20] 再喝一口福岛\n"
        "[01:05 - 01:30] 今天天气不错"
    )
    p.write_text(original, encoding="utf-8")
    before_stamps = [line.split("]")[0] + "]" for line in original.splitlines()]

    changed = dictionary.correct_transcript_file(p, m)
    after = p.read_text(encoding="utf-8").splitlines()
    after_stamps = [line.split("]")[0] + "]" for line in after]

    # 13 台词改对
    check("台词被改对",
          "伏特加" in after[0] and "福岛" not in after[0], after[0])

    # 14 时间戳不动（关键验收）
    check("时间戳一个字没变（关键）",
          before_stamps == after_stamps, f"{after_stamps}")

    # 15 改了几行
    check("返回改了几行", changed == 2, f"changed={changed}（应为 2）")

    # 16 文件不存在
    check("文件不存在返回 0 不崩",
          dictionary.correct_transcript_file(tmp / "nope.txt", m) == 0)


# ---------------- E 反馈记录 ----------------

def scenario_e():
    log()
    log("--- E 反馈记录 ---")
    tmp = Path(tempfile.mkdtemp())
    fb = tmp / "feedback.json"

    # 17 首次写入
    r1 = feedback.save_feedback("clip-001", "喜欢", "很好笑",
                                snapshot={"title": "罐头异物", "final_score": 8.5},
                                path=fb)
    ok17 = (fb.exists() and r1 is not None
            and r1["clip_id"] == "clip-001"
            and r1["user_choice"] == "喜欢"
            and r1["reason"] == "很好笑"
            and bool(r1.get("timestamp")))
    check("首次写入建文件且字段齐全", ok17, f"{r1}")

    # 18 追加
    feedback.save_feedback("clip-002", "不喜欢", "太普通", path=fb)
    recs = feedback.load_feedback(fb)
    check("能追加第二条", len(recs) == 2, f"{len(recs)} 条")

    # 19 同 clip_id 覆盖
    feedback.save_feedback("clip-001", "不喜欢", "缺上下文", path=fb)
    recs = feedback.load_feedback(fb)
    c1 = [r for r in recs if r["clip_id"] == "clip-001"]
    ok19 = len(recs) == 2 and len(c1) == 1 and c1[0]["user_choice"] == "不喜欢"
    check("同一 clip_id 覆盖不堆积", ok19, f"{len(recs)} 条，clip-001={c1}")

    # 20 snapshot
    check("snapshot 片段信息存下来了",
          any(r.get("snapshot", {}).get("title") == "罐头异物" for r in recs),
          str([r.get("snapshot") for r in recs]))

    # 21 坏文件自愈
    bad = tmp / "broken.json"
    bad.write_text("这不是 JSON", encoding="utf-8")
    check("坏文件能自愈（返回空表）",
          feedback.load_feedback(bad) == [])

    # 22 查询
    got = feedback.get_feedback("clip-002", fb)
    check("能按 clip_id 查回反馈",
          got is not None and got["reason"] == "太普通", str(got))

    # 23 统计
    stats = feedback.feedback_stats(fb)
    check("统计文案正确",
          "2" in stats and "喜欢" in stats, stats)


# ---------------- 总入口 ----------------

def main():
    log("v0.4 第一步离线自测报告（词库纠错 + 反馈记录，纯本地零成本）")
    log()

    scenario_a()
    scenario_b()
    scenario_c()
    scenario_d()
    scenario_e()

    log()
    lines = [l for l in _report if l.startswith("[PASS]") or l.startswith("[FAIL]")]
    total = len(lines)
    passed = len([l for l in lines if l.startswith("[PASS]")])
    log(f"合计：{passed}/{total} 项通过")
    log()
    log("(通过标准：全部 PASS。有 FAIL 先修再继续，不许带病过验收。)")

    REPORT_FILE.write_text("\n".join(_report), encoding="utf-8")
    print(f"\nreport saved: {REPORT_FILE.name}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
