"""deepseek_client —— 负责和 DeepSeek API 通信：发请求、收结果、报成本。

安全约定：API Key 只从环境变量 DEEPSEEK_API_KEY 读取，
本文件（以及整个项目）里不出现任何真实密钥。

成本控制的第 2、3、4 道闸门在这里：
- 闸门 2：请求里带 max_tokens，限制 AI 输出上限
- 闸门 3：发请求前打印本次请求的字数
- 闸门 4：收完结果打印 token 用量和成本估算，方便按视频统计
"""

import os

import requests

import config

# DeepSeek 官方 API 地址
API_URL = "https://api.deepseek.com/chat/completions"


def call_deepseek(prompt: str):
    """把需求单发给 DeepSeek，返回 (AI 的回复文本, 用量统计字典)。"""

    # ---- 1. 拿钥匙：只认环境变量，绝不写死在代码里 ----
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "\n[缺钥匙] 没有找到环境变量 DEEPSEEK_API_KEY。\n"
            "设置方法（PowerShell，只对当前窗口生效）：\n"
            '  $env:DEEPSEEK_API_KEY = "sk-你的钥匙"\n'
            "拿到钥匙的地址：https://platform.deepseek.com\n"
        )

    # ---- 2. 闸门 3：出发前，先报一下这次带了多少货 ----
    print(f"[成本] 本次请求共 {len(prompt)} 字（中文约 {len(prompt) * 0.6:.0f} token）")

    # ---- 3. 组装请求 ----
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "你是直播内容运营专家。必须严格输出合法 JSON，禁止输出任何解释性文字。",
            },
            {"role": "user", "content": prompt},
        ],
        # 强制 JSON 模式：DeepSeek 会保证回复能被 json.loads 解析
        "response_format": {"type": "json_object"},
        # 闸门 2：输出上限，防止 AI 话痨把 token 烧光
        "max_tokens": config.MAX_OUTPUT_TOKENS,
    }

    # ---- 4. 发请求（120 秒超时，网络卡死也不会永久挂起） ----
    try:
        resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
    except requests.exceptions.Timeout:
        raise SystemExit("[超时] DeepSeek 120 秒没响应，稍后再试一次。")
    except requests.exceptions.ConnectionError:
        raise SystemExit("[网络] 连不上 DeepSeek，检查一下网络。")

    if resp.status_code != 200:
        # 常见错误：401 钥匙错 / 402 余额不足 / 429 请求太频繁
        raise SystemExit(
            f"[HTTP {resp.status_code}] DeepSeek 拒绝了请求：\n{resp.text[:500]}"
        )

    data = resp.json()
    reply_text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})  # 里面有真实的 token 用量
    return reply_text, usage


def print_cost_report(prompt_chars: int, usage: dict):
    """闸门 4：收工后打印账单，方便按视频统计成本。"""
    in_tokens = usage.get("prompt_tokens", 0)
    out_tokens = usage.get("completion_tokens", 0)

    # 成本 = 输入 token × 输入单价 + 输出 token × 输出单价（单价按百万 token 计）
    cost = (
        in_tokens * config.PRICE_INPUT_PER_MTOKEN
        + out_tokens * config.PRICE_OUTPUT_PER_MTOKEN
    ) / 1_000_000

    print(f"[成本] 请求字数：{prompt_chars} 字")
    print(f"[成本] 实际用量：输入 {in_tokens} token + 输出 {out_tokens} token")
    print(f"[成本] 输出上限：{config.MAX_OUTPUT_TOKENS} token（闸门已生效）")
    print(f"[成本] 本次预估花费：约 ¥{cost:.4f}（按 config.py 里的价格估算，以官网账单为准）")
