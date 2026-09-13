# -*- coding: utf-8 -*-
"""speaker/test_aliyun.py —— 阿里云说话人识别模块本地测试脚本（不接生产流程）

用途：
  离线验证 speaker/aliyun.py 的正确性；环境变量就位时可选择性发起**真实**调用。

用法：
  # 1) 只跑离线结构测试（默认；不联网、不需密钥）
  python speaker/test_aliyun.py

  # 2) 追加一次真实 API 调用（需 3 个环境变量 + 一个公网可访问的音频 URL）
  python speaker/test_aliyun.py --live --audio-url https://example.com/a.mp3

注意：
  - 不写生产数据、不改现有文件、不接 pipeline。
  - 真实调用会消耗阿里云识别额度；只在 --live 时发生。
  - 密钥只从环境变量读；本脚本任何输出都不打印密钥内容。
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from speaker import (  # noqa: E402
    AliyunError,
    AliyunSpeakerProvider,
    SpeakerTurn,
    build_provider,
    list_providers,
    provider_ids,
    to_unified,
)
from speaker import config  # noqa: E402
from speaker import aliyun as ali  # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _mk_provider(**kw):
    """造一个带假密钥的 provider（离线测试用，绝不发真实请求）。"""
    base = dict(access_key_id="testid", access_key_secret="testsecret",
                app_key="testappkey")
    base.update(kw)
    return AliyunSpeakerProvider(**base)


# ---------------------------------------------------------------
# 1. 统一输出格式契约
# ---------------------------------------------------------------

def test_contract():
    print("\n[1] 统一输出格式契约")
    t = SpeakerTurn(start=0, end=5, speaker="spk_0")
    d = t.to_dict()
    check("to_dict 含 start/end/speaker", {"start", "end", "speaker"} <= set(d), f"{d}")
    lst = to_unified([SpeakerTurn(0, 1.5, "spk_0"), SpeakerTurn(1.5, 3.2, "spk_1")])
    check("to_unified 返回 list[dict]", isinstance(lst, list) and isinstance(lst[0], dict))
    check("字段齐全", all({"start", "end", "speaker"} <= set(x) for x in lst))


# ---------------------------------------------------------------
# 2. 注册表
# ---------------------------------------------------------------

def test_registry():
    print("\n[2] Provider 注册表")
    ids = provider_ids()
    check("aliyun 已注册", "aliyun" in ids, f"实际 {ids}")
    check("volcengine 保留", "volcengine" in ids, f"实际 {ids}")
    p = build_provider("aliyun")
    check("build_provider('aliyun') 返回 AliyunSpeakerProvider",
          isinstance(p, AliyunSpeakerProvider), f"实际 {type(p)!r}")
    infos = list_providers()
    check("list_providers 正常", isinstance(infos, list) and len(infos) >= 2)
    try:
        build_provider("不存在的引擎")
        check("未知 provider 抛错", False, "没有抛错")
    except KeyError:
        check("未知 provider 抛错", True)


# ---------------------------------------------------------------
# 3. 配置与安全
# ---------------------------------------------------------------

def test_config_safety():
    print("\n[3] 配置读取与安全")
    s = config.aliyun_summary()
    check("summary 含 credentials_present", "credentials_present" in s)
    check("summary 含 missing", isinstance(s.get("missing"), list))
    check("summary 含 host/region",
          bool(s.get("file_trans_host")) and bool(s.get("region_id")), f"{s}")
    secret = config.get_aliyun_access_key_secret()
    if secret:
        check("summary 不泄露 secret 原文",
              secret not in json.dumps(s, ensure_ascii=False))
    else:
        check("summary 不泄露 secret 原文（未配置，跳过）", True)
    # app_key 缺失时 missing 应包含它
    missing = config.aliyun_describe_missing()
    if not config.get_aliyun_app_key():
        check("缺 appkey 时 missing 含 ALIYUN_APP_KEY",
              config.ENV_ALI_APP_KEY in missing, f"实际 {missing}")


# ---------------------------------------------------------------
# 4. RPC 签名（关键：与阿里云官方规范一致）
# ---------------------------------------------------------------

def test_signature():
    print("\n[4] RPC 签名算法")
    p = _mk_provider()

    # 4.1 percent-encode 规则
    cases = [("/", "%2F"), ("*", "%2A"), ("~", "~"),
             (" ", "%20"), ("a+b", "a%2Bb")]
    ok = all(p._percent_encode(raw) == exp for raw, exp in cases)
    check("percent-encode 规则正确", ok,
          f"{[(r, p._percent_encode(r), e) for r, e in cases]}")

    # 4.2 用阿里云官方文档给出的完整示例验证签名（GET / DescribeRegions）
    #     文档值：AK=testid, SK=testsecret, Timestamp=2016-02-23T12:46:24Z
    #             SignatureNonce=3ee8c1b8-83d3-44af-a94f-4e0ad82fd6cf
    #             期望 Signature=OLeaidS1JvxuMvnyHOwuJ+uX5qY=
    official = {
        "Action": "DescribeRegions",
        "Format": "XML",
        "Version": "2014-05-26",
        "AccessKeyId": "testid",
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": "2016-02-23T12:46:24Z",
        "SignatureVersion": "1.0",
        "SignatureNonce": "3ee8c1b8-83d3-44af-a94f-4e0ad82fd6cf",
    }
    sig = p._sign(official, method="GET")
    check("签名与阿里云官方示例一致", sig == "OLeaidS1JvxuMvnyHOwuJ+uX5qY=",
          f"得到 {sig}，期望 OLeaidS1JvxuMvnyHOwuJ+uX5qY=")

    # 4.3 签名覆盖 HTTP 方法：GET 与 POST 必须不同
    check("签名覆盖 HTTP 方法（GET≠POST）",
          p._sign(official, "GET") != p._sign(official, "POST"))

    # 4.4 确定性：同参数同方法签名稳定
    check("同参数签名可复现",
          p._sign(official, "POST") == p._sign(official, "POST"))

    # 4.5 秘密不同 → 签名不同
    p2 = _mk_provider(access_key_secret="othersecret")
    check("不同 secret 签名不同",
          p._sign(official, "POST") != p2._sign(official, "POST"))


# ---------------------------------------------------------------
# 5. 请求构造
# ---------------------------------------------------------------

def test_request_build():
    print("\n[5] 请求构造")
    p = _mk_provider(speaker_max=3)

    task = p._build_task("https://cdn.example.com/a.mp3")
    check("Task 含 appkey", task.get("appkey") == "testappkey")
    check("Task 含 file_link", task.get("file_link") == "https://cdn.example.com/a.mp3")
    check("开启说话人分离（enable_speaker_diarization）",
          task.get("enable_speaker_diarization") is True)
    check("开启词级时间戳", task.get("enable_words") is True)

    params = p._build_common_params("SubmitTask")
    check("公共参数含 Action", params.get("Action") == "SubmitTask")
    check("公共参数含 Version", params.get("Version") == config.ALI_API_VERSION)
    check("公共参数含 SignatureMethod=HMAC-SHA1",
          params.get("SignatureMethod") == "HMAC-SHA1")
    check("公共参数含 AccessKeyId", params.get("AccessKeyId") == "testid")
    check("公共参数含 SignatureNonce/Timestamp",
          bool(params.get("SignatureNonce")) and bool(params.get("Timestamp")))

    # host 按 region 推导
    p2 = _mk_provider(region_id="cn-beijing", host=None)
    check("host 按 region 推导",
          p2.host == "filetrans.cn-beijing.aliyuncs.com", f"实际 {p2.host}")


# ---------------------------------------------------------------
# 6. 响应解析与转换（核心：→ 统一格式）
# ---------------------------------------------------------------

def test_parse():
    print("\n[6] 响应解析与格式转换")
    p = _mk_provider()

    # 6.1 标准响应（Result.Sentences[] + SpeakerId）
    resp = {
        "TaskId": "t1", "StatusText": "SUCCESS", "StatusCode": 21050000,
        "Result": {"Sentences": [
            {"BeginTime": 0,    "EndTime": 2000, "Text": "甲说话", "SpeakerId": 0},
            {"BeginTime": 2000, "EndTime": 4200, "Text": "乙说话", "SpeakerId": 1},
            {"BeginTime": 4200, "EndTime": 7000, "Text": "甲又说", "SpeakerId": 0},
        ]},
    }
    turns = p._parse_response(resp)
    uni = to_unified(turns)
    check("解析出 3 段", len(uni) == 3, f"实际 {uni}")
    check("毫秒→秒换算正确",
          uni[0]["start"] == 0.0 and uni[1]["start"] == 2.0 and uni[1]["end"] == 4.2,
          f"实际 {uni}")
    check("说话人标签正确（spk_N）",
          [u["speaker"] for u in uni] == ["spk_0", "spk_1", "spk_0"], f"实际 {uni}")

    # 6.2 相邻同人合并
    resp2 = {"Result": {"Sentences": [
        {"BeginTime": 0, "EndTime": 1000, "SpeakerId": 0},
        {"BeginTime": 1000, "EndTime": 2500, "SpeakerId": 0},
        {"BeginTime": 2500, "EndTime": 4000, "SpeakerId": 1},
    ]}}
    merged = to_unified(p._merge_adjacent(p._parse_response(resp2)))
    check("相邻同人合并为 2 段", len(merged) == 2, f"实际 {merged}")
    check("合并后时间跨度正确",
          merged[0]["start"] == 0.0 and merged[0]["end"] == 2.5, f"实际 {merged}")

    # 6.3 缺说话人字段 → 空列表（绝不伪造）
    resp3 = {"Result": {"Sentences": [
        {"BeginTime": 0, "EndTime": 1000, "Text": "无标签"},
    ]}}
    check("缺 SpeakerId 时返回空（不伪造）", p._parse_response(resp3) == [])

    # 6.4 字符串型说话人标签保留
    resp4 = {"Result": {"Sentences": [
        {"BeginTime": 0, "EndTime": 1000, "SpeakerId": "用户1"},
    ]}}
    u4 = to_unified(p._parse_response(resp4))
    check("字符串说话人标签保留", u4 and u4[0]["speaker"] == "用户1", f"实际 {u4}")

    # 6.5 异常输入不崩
    for bad in ({}, {"Result": None}, {"Result": []}, {"Result": "x"}, None, []):
        try:
            p._parse_response(bad)
        except Exception as e:  # noqa: BLE001
            check(f"异常响应不崩（{bad!r}）", False, f"{type(e).__name__}: {e}")
            break
    else:
        check("异常响应不崩", True)


# ---------------------------------------------------------------
# 7. URL 解析
# ---------------------------------------------------------------

def test_url():
    print("\n[7] URL 解析")
    p = _mk_provider()
    check("http URL 直通", p._resolve_url("https://x.com/a.mp3") == "https://x.com/a.mp3")
    try:
        p._resolve_url("D:/tmp/a.mp3")
        check("本地路径无 upload_fn 时报错", False, "没有抛错")
    except AliyunError:
        check("本地路径无 upload_fn 时报错", True)
    p2 = _mk_provider(upload_fn=lambda path: "https://oss/x.mp3")
    check("upload_fn 生效", p2._resolve_url("D:/tmp/a.mp3") == "https://oss/x.mp3")


# ---------------------------------------------------------------
# 8. 可用性判定
# ---------------------------------------------------------------

def test_availability():
    print("\n[8] 可用性判定")
    p_none = AliyunSpeakerProvider(access_key_id="", access_key_secret="", app_key="")
    ok, reason = p_none.is_available()
    check("缺密钥时 available=False", ok is False, f"实际 {ok}")
    check("缺密钥时给出原因", bool(reason))
    try:
        p_none.diarize("https://x.com/a.mp3")
        check("未配置时 diarize 抛错", False, "没有抛错")
    except AliyunError:
        check("未配置时 diarize 抛错", True)

    p_ok = _mk_provider()
    ok2, reason2 = p_ok.is_available()
    check("密钥齐备时 available=True", ok2 is True, f"实际 {ok2}, {reason2}")
    check("info 不泄露密钥", 
          "testsecret" not in json.dumps(p_ok.info(), ensure_ascii=False))


# ---------------------------------------------------------------
# 9. 真实调用（可选）
# ---------------------------------------------------------------

def test_live(audio_url):
    print("\n[9] 真实 API 调用")
    missing = config.aliyun_describe_missing()
    if missing:
        print(f"  [SKIP] 缺少环境变量：{', '.join(missing)}；已跳过真实调用。")
        return

    p = AliyunSpeakerProvider()
    ok, reason = p.is_available()
    if not ok:
        print(f"  [SKIP] provider 不可用：{reason}")
        return

    print(f"  调用中（音频：{audio_url}）...")
    try:
        result = p.diarize_unified(audio_url)
    except AliyunError as e:
        check("真实调用成功", False, f"{e}")
        return

    check("真实调用返回 list", isinstance(result, list))
    check("每段含 start/end/speaker",
          all({"start", "end", "speaker"} <= set(x) for x in result))
    check("按时间排序",
          all(result[i]["start"] <= result[i + 1]["start"]
              for i in range(len(result) - 1)))
    speakers = sorted({x["speaker"] for x in result})
    print(f"  识别到 {len(speakers)} 位说话人，{len(result)} 段：{speakers}")
    print("  前 5 段：")
    print(json.dumps(result[:5], ensure_ascii=False, indent=2))

    out = os.path.join(HERE, "outputs")
    os.makedirs(out, exist_ok=True)
    fp = os.path.join(out, "test_aliyun_live_result.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"  结果已存：{fp}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="追加一次真实 API 调用（需环境变量 + --audio-url）")
    ap.add_argument("--audio-url", default="", help="真实调用用的公网音频 URL")
    args = ap.parse_args()

    print("=" * 60)
    print("阿里云 speaker 模块本地测试")
    print("=" * 60)

    print("\n[环境概览]")
    print(json.dumps(config.aliyun_summary(), ensure_ascii=False, indent=2))

    test_contract()
    test_registry()
    test_config_safety()
    test_signature()
    test_request_build()
    test_parse()
    test_url()
    test_availability()

    if args.live:
        if not args.audio_url:
            print("\n[9] 真实 API 调用")
            print("  [SKIP] --live 需要同时提供 --audio-url")
        else:
            test_live(args.audio_url)

    print("\n" + "=" * 60)
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
