"""deepseek_client —— 负责和 DeepSeek API 通信：发请求、收结果、报成本。

安全约定：API Key 只从环境变量 DEEPSEEK_API_KEY 读取，
本文件（以及整个项目）里不出现任何真实密钥。

成本控制的第 2、3、4 道闸门在这里：
- 闸门 2：请求里带 max_tokens，限制 AI 输出上限
- 闸门 3：发请求前打印本次请求的字数
- 闸门 4：收完结果打印 token 用量和成本估算，方便按视频统计
"""

import os
from pathlib import Path

import requests

import config

# DeepSeek 官方 API 地址
API_URL = "https://api.deepseek.com/chat/completions"

# 钥匙文件（网页版保存的钥匙放这里；此文件已被 .gitignore 排除，不会上传）
KEY_FILE = Path(__file__).resolve().parent.parent / "api_key.txt"


def get_api_key():
    """拿钥匙：先看环境变量，再看网页版保存的 api_key.txt，都没有才报错。"""

    # 途径 1：环境变量（命令行用户 / 服务器部署时用）
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key

    # 途径 2：网页版保存的钥匙文件
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key

    raise SystemExit(
        "\n[缺钥匙] 没有找到 DeepSeek API Key。\n"
        "网页版：在左侧边栏「API Key」里粘贴保存即可。\n"
        "命令行：设置环境变量 DEEPSEEK_API_KEY，或把钥匙存进 api_key.txt。\n"
        "拿钥匙的地址：https://platform.deepseek.com\n"
    )


def call_deepseek(prompt: str, system: str = None, max_tokens: int = None):
    """把需求单发给 DeepSeek，返回 (AI 的回复文本, 用量统计字典)。

    system / max_tokens 不传就用默认值（v0.2 老代码的调用方式完全不受影响）；
    v0.3 海选/复审会用不同的 system 身份和输出上限。
    """

    # ---- 1. 拿钥匙：环境变量或钥匙文件，绝不写死在代码里 ----
    api_key = get_api_key()

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
                "content": system
                or "你是直播内容运营专家。必须严格输出合法 JSON，禁止输出任何解释性文字。",
            },
            {"role": "user", "content": prompt},
        ],
        # 强制 JSON 模式：DeepSeek 会保证回复能被 json.loads 解析
        "response_format": {"type": "json_object"},
        # 闸门 2：输出上限，防止 AI 话痨把 token 烧光
        "max_tokens": max_tokens or config.MAX_OUTPUT_TOKENS,
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


# ============================================================
# v0.3 阶段 2：成本累加器
#
# 一场分析要调好多次 AI（每个区块海选一次 + 复审一次），
# 只看单次账单没意义，用户要的是「这一场总共花了多少钱」。
# ============================================================

class CostTracker:
    """把一场分析里所有 API 调用的用量累加起来，最后一次性报总账。"""

    def __init__(self):
        self.calls = 0            # 调了几次 API
        self.input_tokens = 0     # 累计输入 token
        self.output_tokens = 0    # 累计输出 token

    def add(self, usage: dict):
        """收一次调用的用量（usage 就是 API 返回里的那个字典）。"""
        self.calls += 1
        self.input_tokens += usage.get("prompt_tokens", 0)
        self.output_tokens += usage.get("completion_tokens", 0)

    @property
    def cost_yuan(self) -> float:
        """这一场分析的总花费（元，按 config.py 价格表估算）。"""
        return (
            self.input_tokens * config.PRICE_INPUT_PER_MTOKEN
            + self.output_tokens * config.PRICE_OUTPUT_PER_MTOKEN
        ) / 1_000_000

    def to_dict(self) -> dict:
        """变成能直接塞进 highlights_v2.json 的字典。"""
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_yuan": round(self.cost_yuan, 4),
        }

    def report(self) -> str:
        """报总账（返回文本，编排器决定打印还是塞进网页日志）。"""
        return (
            f"[成本] 本场共调用 API {self.calls} 次："
            f"输入 {self.input_tokens} token + 输出 {self.output_tokens} token，"
            f"预估总花费 ¥{self.cost_yuan:.4f}（以官网账单为准）"
        )
