# -*- coding: utf-8 -*-
"""speaker/test_speaker.py —— 说话人识别模块本地测试脚本（不接生产流程）

用途：
  离线验证 speaker/ 模块的正确性，并在环境变量就位时可选择性发起**真实**调用。

用法：
  # 1) 只跑离线结构测试（不联网、不需要密钥）—— 默认
  python speaker/test_speaker.py

  # 2) 追加一次真实 API 调用（需要 3 个环境变量 + 一个公网可访问的音频 URL）
  python speaker/test_speaker.py --live --audio-url https://example.com/a.mp3

  # 3) 若音频在本地且你已有上传函数，可自行在代码里传 upload_fn（脚本不内置上传）

注意：
  - 本脚本不写入任何生产数据、不改任何现有文件、不接 pipeline。
  - 真实调用会消耗火山引擎的识别额度，只在你明确 --live 时才发生。
  - 密钥只从环境变量读；本脚本任何输出都不打印密钥内容。
"""

import argparse
import json
import os
import sys

# 让脚本可直接从项目根运行
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from speaker import (  # noqa: E402
    SpeakerTurn,
    VolcengineSpeakerProvider,
    build_provider,
    list_providers,
    provider_ids,
    to_unified,
)
from speaker import config  # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# ---------------------------------------------------------------
# 离线结构测试
# ---------------------------------------------------------------

def test_contract():
    """1. 统一输出格式契约。"""
    print("\n[1] 统一输出格式契约")
    t = SpeakerTurn(start=0, end=5, speaker="spk_0")
    d = t.to_dict()
    check("to_dict 含 start/end/speaker",
          {"start", "end", "speaker"} <= set(d), f"实际 {d}")
    check("start/end 为数值", isinstance(d["start"], float) and isinstance(d["end"], float))
    check("speaker 为字符串", isinstance(d["speaker"], str))

    lst = to_unified([SpeakerTurn(0, 1.5, "spk_0"), SpeakerTurn(1.5, 3.2, "spk_1")])
    check("to_unified 返回 list[dict]", isinstance(lst, list) and isinstance(lst[0], dict))
    check("to_unified 字段齐全",
          all({"start", "end", "speaker"} <= set(x) for x in lst))
    # 幂等：dict 进 dict 出
    check("to_unified 对 dict 幂等",
          to_unified([{"start": 0, "end": 1, "speaker": "spk_0"}])[0]["speaker"] == "spk_0")


def test_registry():
    """2. Provider 注册表。"""
    print("\n[2] Provider 注册表")
    ids = provider_ids()
    check("provider_ids 非空", len(ids) > 0, f"实际 {ids}")
    check("包含 volcengine", "volcengine" in ids)
    p = build_provider("volcengine")
    check("build_provider 返回实例",
          isinstance(p, VolcengineSpeakerProvider), f"实际 {type(p)!r}")

    infos = list_providers()
    check("list_providers 返回列表且元素为 dict",
          isinstance(infos, list) and all(isinstance(i, dict) for i in infos))
    for i in infos:
        check(f"  info 含 available/reason（{i.get('provider_id')}）",
              "available" in i and "reason" in i)

    # 未知 id 必须报错，不能静默
    try:
        build_provider("不存在的引擎")
        check("未知 provider 抛错", False, "没有抛错")
    except KeyError:
        check("未知 provider 抛错", True)


def test_config_safety():
    """3. 配置读取与安全（不泄露密钥）。"""
    print("\n[3] 配置读取与安全")
    # 顶层 summary() 现在是 {"aliyun": {...}, "volcengine": {...}}，
    # 火山相关字段挂在 volcengine 子字典下。
    s = config.summary()
    check("summary 含 aliyun/volcengine 两段",
          "aliyun" in s and "volcengine" in s, f"{list(s)}")
    v = s.get("volcengine", {})
    check("volcengine summary 含 credentials_present", "credentials_present" in v)
    check("volcengine summary 含 missing 列表", isinstance(v.get("missing"), list))
    # 关键安全断言：摘要里不能出现真实密钥
    tok = config.get_access_token()
    if tok:
        check("summary 不泄露 access_token 原文", tok not in json.dumps(s))
    else:
        check("summary 不泄露 access_token 原文（未配置，跳过）", True)
    check("resource_id 有默认值", bool(v.get("resource_id")))

    missing = config.describe_missing()
    check("describe_missing 返回列表", isinstance(missing, list))


def test_parse_and_merge():
    """4. 响应解析 + 相邻同人合并（离线，用模拟响应）。"""
    print("\n[4] 响应解析与合并（模拟响应）")
    p = VolcengineSpeakerProvider(app_id="dummy", access_token="dummy")

    # 形态 A：说话人在 additions.speaker（大模型版）
    resp_a = {"result": {"utterances": [
        {"start_time": 0, "end_time": 1800, "text": "你好", "additions": {"speaker": "1"}},
        {"start_time": 1800, "end_time": 3600, "text": "在吗", "additions": {"speaker": "1"}},
        {"start_time": 3600, "end_time": 5200, "text": "嗯", "additions": {"speaker": "2"}},
        {"start_time": 5200, "end_time": 9000, "text": "好", "additions": {"speaker": 2}},
    ]}}
    turns = p._merge_adjacent(p._parse_response(resp_a))
    uni = to_unified(turns)
    check("形态A 解析出 2 段（合并后）", len(uni) == 2, f"实际 {len(uni)}: {uni}")
    check("形态A 秒换算正确（0~3.6s）",
          uni and abs(uni[0]["start"] - 0.0) < 1e-6 and abs(uni[0]["end"] - 3.6) < 1e-6,
          f"实际 {uni[0] if uni else None}")
    check("形态A 说话人编号正确",
          uni == [{"start": 0.0, "end": 3.6, "speaker": "spk_1", "text": "你好"},
                  {"start": 3.6, "end": 9.0, "speaker": "spk_2", "text": "嗯"}]
          or [u["speaker"] for u in uni] == ["spk_1", "spk_2"],
          f"实际 {uni}")

    # 形态 B：result 直接是 list
    resp_b = {"result": [
        {"start_time": 0, "end_time": 1000, "speaker": "spk_a"},
        {"start_time": 1000, "end_time": 2000, "speaker": "spk_b"},
    ]}
    uni_b = to_unified(p._parse_response(resp_b))
    check("形态B 解析出 2 段", len(uni_b) == 2, f"实际 {uni_b}")
    check("形态B 保留原始标签", [u["speaker"] for u in uni_b] == ["spk_a", "spk_b"])

    # 缺说话人字段 → 必须丢弃，绝不伪造
    resp_c = {"result": {"utterances": [
        {"start_time": 0, "end_time": 1000, "text": "无标签"},
    ]}}
    check("缺说话人字段时返回空（不伪造）", p._parse_response(resp_c) == [])

    # 静音音频 → 合法空结果
    check("静音响应返回空列表",
          p._parse_response({"result": {"utterances": []}, "_note": "silent_audio"}) == [])

    # 空/异常响应不崩
    for bad in ({}, {"result": None}, {"result": []}, {"result": "x"}, None):
        try:
            p._parse_response(bad)
        except Exception as e:  # noqa: BLE001
            check(f"异常响应不崩（{bad!r}）", False, f"抛了 {type(e).__name__}: {e}")
            break
    else:
        check("异常响应不崩", True)


def test_url_resolution():
    """5. URL 解析：URL 直通 / 本地文件报错清晰 / upload_fn 生效。"""
    print("\n[5] URL 解析")
    p = VolcengineSpeakerProvider(app_id="dummy", access_token="dummy")
    check("http URL 直通",
          p._resolve_url("https://x.com/a.mp3") == "https://x.com/a.mp3")
    check("https URL 直通",
          p._resolve_url("http://x.com/a.mp3") == "http://x.com/a.mp3")

    try:
        p._resolve_url("D:/tmp/a.mp3")
        check("本地路径无 upload_fn 时报错", False, "没有抛错")
    except Exception as e:  # noqa: BLE001
        check("本地路径无 upload_fn 时报错", "URL" in str(e), f"消息不清晰：{e}")

    p2 = VolcengineSpeakerProvider(app_id="d", access_token="d",
                                   upload_fn=lambda path: "https://cdn/x.mp3")
    check("upload_fn 生效", p2._resolve_url("D:/tmp/a.mp3") == "https://cdn/x.mp3")


def test_availability():
    """6. 可用性判定（不发网络请求）。"""
    print("\n[6] 可用性判定")
    p_none = VolcengineSpeakerProvider(app_id="", access_token="")
    ok, reason = p_none.is_available()
    check("缺密钥时 available=False", ok is False, f"实际 {ok}")
    check("缺密钥时给出原因", bool(reason), f"reason={reason!r}")

    p_ok = VolcengineSpeakerProvider(app_id="a", access_token="b")
    ok2, reason2 = p_ok.is_available()
    check("密钥齐备时 available=True", ok2 is True, f"实际 {ok2}, {reason2}")

    # diarize 在未配置时应抛明确错误，而不是静默返回空
    try:
        p_none.diarize("https://x.com/a.mp3")
        check("未配置时 diarize 抛错", False, "没有抛错")
    except Exception as e:  # noqa: BLE001
        check("未配置时 diarize 抛错", "配置" in str(e) or "requests" in str(e))


# ---------------------------------------------------------------
# 真实调用（可选）
# ---------------------------------------------------------------

def test_live(audio_url):
    """7. 真实 API 调用（只在 --live 时跑）。"""
    print("\n[7] 真实 API 调用")
    missing = config.describe_missing()
    if missing:
        print(f"  [SKIP] 缺少环境变量：{', '.join(missing)}；已跳过真实调用。")
        return

    p = VolcengineSpeakerProvider()
    ok, reason = p.is_available()
    if not ok:
        print(f"  [SKIP] provider 不可用：{reason}")
        return

    print(f"  调用中（音频：{audio_url}）...")
    try:
        result = p.diarize_unified(audio_url)
    except Exception as e:  # noqa: BLE001
        check("真实调用成功", False, f"{type(e).__name__}: {e}")
        return

    check("真实调用返回 list", isinstance(result, list))
    shape_ok = all({"start", "end", "speaker"} <= set(x) for x in result)
    check("每段含 start/end/speaker", shape_ok)
    t_sorted = all(result[i]["start"] <= result[i + 1]["start"]
                   for i in range(len(result) - 1))
    check("按时间排序", t_sorted)
    speakers = sorted({x["speaker"] for x in result})
    print(f"  识别到 {len(speakers)} 位说话人，{len(result)} 段：{speakers}")
    print("  前 5 段：")
    print(json.dumps(result[:5], ensure_ascii=False, indent=2))

    # 附带把结果落盘到临时文件（不属于生产数据）
    out = os.path.join(HERE, "outputs")
    os.makedirs(out, exist_ok=True)
    fp = os.path.join(out, "test_speaker_live_result.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  结果已存：{fp}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="追加一次真实 API 调用（需环境变量 + --audio-url）")
    ap.add_argument("--audio-url", default="",
                    help="真实调用用的公网音频 URL")
    args = ap.parse_args()

    print("=" * 60)
    print("speaker 模块本地测试")
    print("=" * 60)

    print("\n[环境概览]")
    print(json.dumps(config.summary(), ensure_ascii=False, indent=2))

    test_contract()
    test_registry()
    test_config_safety()
    test_parse_and_merge()
    test_url_resolution()
    test_availability()

    if args.live:
        if not args.audio_url:
            print("\n[7] 真实 API 调用")
            print("  [SKIP] --live 需要同时提供 --audio-url")
        else:
            test_live(args.audio_url)

    print("\n" + "=" * 60)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
