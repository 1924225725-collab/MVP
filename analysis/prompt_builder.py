"""prompt_builder —— 把带时间戳的文字稿，拼成一份发给 DeepSeek 的「需求单」。

成本控制第 1 道闸门在这里：
文字稿超过 config.MAX_TRANSCRIPT_CHARS 字时，按「行」截断（不切半句话）。
"""

import config

# 需求单模板。{transcript} 是占位符，会被真实文字稿替换掉。
# 模板里 JSON 示例的花括号要写成 {{ }} 才不会被 .format() 误认成占位符。
_PROMPT_TEMPLATE = """你是一位资深的直播内容运营，擅长从直播录像中挑出适合做成短视频切片的「高光时刻」。

下面是一场直播的带时间戳文字稿，每行格式为：[开始时间 - 结束时间] 台词。时间格式为「分:秒」。

请从中挑选 3~6 个最适合做切片的片段，只输出一个 JSON 对象，不要输出任何其他文字（包括解释、问候、markdown 代码块标记）。

JSON 格式（严格遵守）：
{{
  "highlights": [
    {{
      "start_time": "片段开始时间，如 01:23（必须用文字稿里出现过的原始时间戳）",
      "end_time": "片段结束时间，如 01:58",
      "score": 8,
      "reason": "这个片段值得切片的理由，40字以内",
      "suggested_title": "适合发短视频平台的标题，20字以内"
    }}
  ]
}}

评分标准（score 为 1-10 的整数）：
- 9-10：爆点密集 / 观点炸裂 / 情绪拉满，切片必火
- 7-8：话题性强，容易引发评论区讨论
- 5-6：内容尚可但平淡
- 低于 5 的片段不值得切片，不要输出

挑选要求：
- 可以把相邻几行合并成一个片段，成片时长建议在 30 秒 ~ 3 分钟
- 优先选：金句、反转、吵架、离谱言论、情绪高潮
- suggested_title 要吸引点击，但不要失实

文字稿如下：
{transcript}"""


def build_prompt(transcript_text: str):
    """把文字稿装进需求单。

    返回三个东西：
        prompt    —— 拼好的完整需求单（发给 AI 的全部内容）
        used_chars —— 实际使用的文字稿字数（成本报表要用）
        truncated —— 是否因超长被截断（True = 文字稿没装完）
    """
    # 按行装填：一行一行往需求单里放，放不下就停
    # （比直接切字符串好，不会把某句台词或时间戳切成两半）
    kept_lines = []
    used_chars = 0
    for line in transcript_text.splitlines():
        if used_chars + len(line) > config.MAX_TRANSCRIPT_CHARS:
            break
        kept_lines.append(line)
        used_chars += len(line)

    truncated = used_chars < len(transcript_text.replace("\n", ""))
    prompt = _PROMPT_TEMPLATE.format(transcript="\n".join(kept_lines))
    return prompt, used_chars, truncated


# ============================================================
# 以下为 v0.3 阶段 2 提示词：AI 海选 + AI 复审 + 漏检质检
#
# 身份定位（DECISIONS.md D-003）：
#   AI 不是总结助手，是「直播短视频运营人员」——
#   判断的不是「哪里有内容」，而是「哪里值得剪、发出去有没有人看」。
#
# v0.3.1 策略调整（DECISIONS.md D-017）：
#   召回优先，再谈精准。海选宁多勿少，复审分级，不轻易零输出——
#   P0 实测「0 推荐」证明严格筛选会误杀真爆点。
#
# v0.3.2 判断体系 v3（DECISIONS.md D-022 / D-023）：
#   核心视角从「发生了什么」转向：
#     「一个不了解主播的新用户刷到这个片段，为什么会停下来？」
#   复审只让 AI 打五个子分（hook/contrast/persona/standalone/completeness），
#   final_score 由本地按 config.SCORE_V3_WEIGHTS 加权计算——
#   定级可解释、可审计，也杜绝 AI「先给理由、再顺手打个高分」。
#   负面清单（普通失误/普通展示/单纯惊讶/依赖上下文/普通评价）命中即本地封顶 B 级。
# ============================================================

# V0.4.3（D-044）：AI 写出的文案会直接展示给用户，禁止出现等级字母——
# 用户看到「B 级」会以为「不值得剪」而错过好内容。质量高低一律说人话。
_NO_GRADE_RULE = (
    "写文案时禁止出现 S/A/B/C/D 之类的等级字母（不要写「B级」「A 级内容」这类说法），"
    "要表达质量就直接说人话（如「有反差爆点」「内容比较平稳」）。"
)

SCREENING_SYSTEM = (
    "你是一名拥有多年经验的直播短视频运营人员。"
    "你的任务不是总结直播内容，而是判断哪些片段值得剪辑发布。"
    "你的原则是宁可多给候选，绝不提前杀死可能爆的片段——后面还有复审把关。"
    + _NO_GRADE_RULE +
    "必须严格输出合法 JSON，禁止输出任何解释性文字。"
)

REVIEW_SYSTEM = (
    "你是一名拥有多年经验的直播短视频运营人员，正在做候选片段的终审。"
    "你的任务是把候选分级，不是把它们杀光。你只审判、不新增候选。"
    + _NO_GRADE_RULE +
    "必须严格输出合法 JSON，禁止输出任何解释性文字。"
)

MISS_CHECK_SYSTEM = (
    "你是一名直播内容质检员。你的任务不是找高光，"
    "而是检查海选有没有漏掉明显的爆点。"
    "必须严格输出合法 JSON，禁止输出任何解释性文字。"
)

REPORT_SYSTEM = (
    "你是一名资深直播短视频运营，负责给整场分析写一份简短复盘报告。"
    "你俯瞰整场的事件精华，用三句话以内讲清本场水平和最强传播点。"
    + _NO_GRADE_RULE +
    "必须严格输出合法 JSON，禁止输出任何解释性文字。"
)

EVENT_JUDGE_SYSTEM = (
    "你是一名直播切片分镜师，负责把零散的爆点片段还原成完整的事件。"
    "你的任务是判断几个片段是否属于同一件事，并给出这个事件最合适的剪辑边界。"
    "你判断的是「故事」，不是「句子」——一句话好玩不等于它自己就是一个完整片段。"
    + _NO_GRADE_RULE +
    "必须严格输出合法 JSON，禁止输出任何解释性文字。"
)

# ---- 海选提示词：每个区块独立发一次 ----
# {live_type} 直播类型；{weights} 该类型的评分侧重；{max_candidates} 候选上限；{chunk_text} 区块原文
_SCREENING_TEMPLATE = """你正在审看一场「{live_type}」直播的一段录像（下面是带时间戳的文字稿）。

你不是总结助手。你是直播短视频运营，这一轮只需要回答一个问题：
这段录像里，有没有可能值得剪成短视频发布的片段？

【最重要的原则：宁多勿少】
- 拿不准的候选，给。让后面的复审去淘汰，不要在海选阶段就下杀手。
- 每段至少挑出 1 个最有潜力的候选；只有整段从头到尾确实毫无可剪点，才允许返回空列表。
- 「不够完美」不是不给候选的理由；「完全没有可看性」才是。

判断视角（v0.3.2 评分体系 v3，本场侧重：{weights}）：
每个候选都自问一句——一个不认识主播的新用户刷到开头几秒，为什么会停下来？
用这五个维度去发现候选（海选只做粗略直觉判断，打分会留给复审）：
1. 三秒吸引力：标题 + 开头 3 秒有没有钩子（误会 / 悬念 / 强反差 / 离谱事件）
2. 反差 / 意外：以为 A 结果 B、高期待低结果、身份反差、认知冲突（误会 > 反转 > 普通事件）
3. 人物表现力：主播的独特反应、经典表达、夸张情绪，能不能形成主播标签
4. 独立成片：剪出来不需要大量直播背景，陌生观众能否理解
5. 事件完整度：有没有 开始 → 过程 → 结果 的结构

同时警惕「假高光」——以下情况只是表面热闹，通常不是真爆点（复审会过滤，但你在海选时别把它们当第一选择）：
- 普通失误（东西掉了、洒了、小操作失败）
- 普通展示（开包装、展示商品、普通介绍）
- 单纯惊讶（「哇好少」——没有反差、故事、冲突的惊讶）
- 普通评价（「不好吃」「一般」）
除非它们伴随巨大反差或主播反应极强，才值得给候选。

候选分三种类型，各有各的判断标准：
1. 事件型——有明确事件、冲突、信息价值、完整逻辑（适合知识/访谈/分析）
2. 情绪型——直播的核心类型：情绪爆发、震惊反应、生气、感动、争议回应
3. 梗型——直播非常重要的类型：一句话成为梗、逆天发言、搞笑反应

其他要求：
- 时间必须用文字稿里出现过的原始时间戳；相邻台词可以合并成一个片段。
- 文字稿由语音识别生成，可能有错字，按语义容错理解。

只输出一个 JSON 对象，格式如下（本段 1~{max_candidates} 个候选）：
{{
  "candidates": [
    {{
      "start_time": "片段开始时间",
      "end_time": "片段结束时间",
      "title": "适合发短视频的标题，20字以内",
      "highlight_type": "事件型/情绪型/梗型 之一",
      "score": 8,
      "reason": "为什么值得剪：必须回答『陌生观众为什么会停留』，40字以内",
      "category": "冲突/反转/金句/情绪/操作/观点/其他 之一",
      "viral_probability": "高/中/低",
      "editing_advice": "剪辑建议，含开头3秒怎么设计，40字以内",
      "confidence": 0.8,
      "event_context": "（可选，≤60 字）这段内容的前置背景——如果读者没看前几分钟直播，需要知道什么才能看懂这条？若上下文已在当前块内清晰，可省略。",
      "event_boundary_note": "（可选，≤40 字）你选这个 start/end 的理由：起点在哪里停的、为什么不是更早/更晚；终点为什么停在这里、不是更早/更晚。若事件边界很自然（如一段完整对话自然结束），可省略。"
    }}
  ]
}}
确实没有任何可剪点才输出 {{"candidates": []}}。

文字稿：
{chunk_text}"""

# 漏检重扫时的追加提示（质检怀疑该区块有漏网之鱼）
_RETRY_HINT = """
【特别提示】质检环节怀疑这一段存在被漏掉的爆点，请用更宽的标准重新审视这一段。
重点找：情绪型（情绪变化、语气突变）和梗型（可做标题的逆天发言）片段。
"""


def build_screening_prompt(chunk_text: str, live_type: str, max_candidates: int,
                           weights: str = "", second_pass: bool = False) -> str:
    """拼海选需求单（一个区块一份）。

    chunk_text     —— chunker 吐出来的区块带时间戳文本
    live_type      —— 直播类型（提示词里告诉 AI 这是什么场）
    max_candidates —— 该区块最多几个候选（Token 降级时会压到 1）
    weights        —— 该类型的评分侧重（config.LIVE_TYPE_WEIGHTS）
    second_pass    —— 质检漏检后的重扫（True 时加更宽标准的提示）
    """
    prompt = _SCREENING_TEMPLATE.format(
        live_type=live_type,
        weights=weights or "各维度均衡",
        max_candidates=max_candidates,
        chunk_text=chunk_text,
    )
    if second_pass:
        prompt = _RETRY_HINT + prompt
    return prompt


# ---- 漏检质检提示词：候选列表 + 区块摘要 → 哪些区块可能漏了爆点 ----
_MISS_CHECK_TEMPLATE = """你是直播内容质检员。海选刚刚完成了对一场「{live_type}」直播的分段扫描，
你的任务是检查一件事：有没有区块明显存在爆点，却没有产出任何候选（或候选明显偏弱）？

你不是在找高光，你是在找「海选的漏检」。

判断线索：
- 摘要里的强信号句（情绪词、冲突词密集）但该区块候选很少或没有 → 可疑
- 摘要显示情绪变化、语气突变、话题转折，但候选池没覆盖 → 可疑
- 普通闲聊区块没有候选 → 正常，不要报

只把你认为真的可疑的区块报出来；都不可疑就输出空列表。

只输出一个 JSON 对象，格式如下：
{{
  "checks": [
    {{
      "chunk": 3,
      "miss_risk": true,
      "reason": "该区域存在明显情绪变化，但未进入候选池"
    }}
  ]
}}

【各区块摘要】
{summaries_text}

【已进入候选池的片段】
{candidates_text}"""


def build_miss_check_prompt(live_type: str, summaries_text: str,
                            candidates_text: str) -> str:
    """拼漏检质检需求单（区块摘要 + 候选简表，一次调用查完）。"""
    return _MISS_CHECK_TEMPLATE.format(
        live_type=live_type,
        summaries_text=summaries_text,
        candidates_text=candidates_text,
    )


# ---- 复审提示词：一个 batch 的事件一次审完，五维打分 + 动态时长 ----
# v0.3.2 评分体系 v3 + v0.4 步骤 3：
#   · AI 只输出五维子分（1-10），不输出 final_score / grade——
#     本地按 config.SCORE_V3_WEIGHTS 加权 ×10 得 100 分制、按阈值定级（可解释可审计）。
#   · 输出动态剪辑范围 recommended_start/end/duration + duration_reason（不固定长度）。
#   · 上下文是「阅读范围」，recommended_duration 是「最终剪辑长度」——两者完全分离：
#     为了判断完整你可能读了一大段，但剪出来只取最能讲清这个故事的最短一段。
#   · 分批复审：一批若干事件，不写整场报告（报告由编排器单独做一次调用）。
_REVIEW_TEMPLATE = """你是一名资深直播短视频运营，现在进入终审环节。

前面已经把零散的爆点片段，聚合成了一批**完整事件**（拆包装 → 掉出来 → 尝一口 → 难吃 → 吐掉，
这一整件事才算一个候选）。你的任务不是找更多，而是逐条审判：「剪出来发出去，有没有人看？」
——一个不认识主播、偶然刷到的新用户，为什么会停下来？

【最重要的视角转变：区分三种「看似热闹实则不值得剪」】
- 「有意义」≠「值得剪」（讲了个背景故事但没传播点）
- 「主播情绪强烈」≠「适合短视频」（情绪没落点、没反差）
- 「发生了事情」≠「有传播价值」（普通事故/普通展示，只是有事发生）
所以：故事结构（铺垫 → 发展 → 结果）比单句爆点更重要；缺头缺尾、只有情绪没有来龙去脉的，
分数要压下来。

【五维评分】对每个事件，只输出以下五个子分（每个 1-10 整数，独立判断）：
1. hook（三秒吸引力，权重最高）：标题 + 开头 3 秒的钩子强度。陌生人看到第一眼会不会想看下去？
   高分例：「主播以为黄腐鸡是咖啡，喝之前完全不知道」；低分例：「主播洒了一杯饮料」「普通介绍商品」
2. contrast（反差/意外）：以为 A 结果 B、高期待→低结果、身份反差、认知冲突。误会 > 反转 > 普通事件
3. personality（人物表现力）：主播独特的反应/经典表达/夸张情绪，能不能形成主播标签。不是「说了句话」而是「有没有个人辨识度」
4. standalone（独立成片）：不依赖直播背景，陌生观众能否看懂；需大量前因后果 → 低分
5. completeness（事件完整度）：有没有 开始→发展→结果 的完整结构；只有半截情绪 → 低分

【不值得剪的负面清单】判断事件**整体**是否命中（某一瞬间普通不因此判掉整件事），命中填 negative_flags：
1. 普通失误  2. 普通展示  3. 单纯惊讶  4. 依赖上下文  5. 普通评价
命中的事件会被系统自动封顶（最高 B 级，进不了 A/S），请诚实判断。

【案例对照——帮助你校准判断】
值得剪（给高分）：误把黄腐鸡当咖啡喝下去（误会+反差+结果）；评价军粮「像纸盒子」（具体形容、一句话能当标题）；评价罐头「像指甲盖」（独特表达、天然记忆点）
不值得剪（别给高分）：饮料粉冲泡洒了出来（只有事故、没传播结构）；打开包装发现东西少喊「哇好少」（单纯惊讶、无强反差）

【每个事件必答】
1. why_cut（为什么值得剪，50 字内）：必须包含——陌生观众为什么停留？核心传播点是什么？写不出来说明可能不值得剪。
2. risk（最大风险/短板，40 字内）：必须诚实指出。例如需要前因后果、画面冲击依赖剪辑、主播反应不够强、题材太小众。不许写「无」。

【动态剪辑范围（v0.4 步骤 3 核心）】
取消固定 20/30/60 秒。你要替这个事件决定「剪多长、从哪到哪，陌生观众才能最完整看懂」：
- 找 setup/铺垫、development/发展、conflict/冲突变化、payoff/结果、strongest_moment/最强爆点
- recommended_start：从哪起剪，陌生观众才能看懂背景（太晚=没头没尾，太早=拖沓）
- recommended_end：在哪收，payoff 一完就收（别拖无关内容）
- recommended_duration：recommended_start 到 recommended_end 的长度（秒）
- duration_reason：为什么是这个长度（一句话，如「需要保留开头发现问题的铺垫，和最后的反应才能形成完整反转」）
长度不设限：一句话梗可短到 8~15 秒，完整反转可能 40 秒，连续事件 1~3 分钟甚至更长——不要为了统一长度强行截断。
注意：你读到的「上下文」可能前后各几分钟，那是给你判断用的阅读范围；真正要剪的长度只取决于事件本身讲清楚要多久。
若 recommended_duration 超过你实际读到的上下文，或你明显需要更多前后文才能确定边界，
把 context_incomplete 设为 true——系统会给你更大上下文重审这一次。

【为什么判它「不值得剪」——四种原因要分清（v0.4 A3，重要）】
当你认为某个事件不值得剪（会给它打低分、落到 C/D）时，必须想清楚**到底是哪种原因**，
并在该条目的 reject_reason_kind 里填对应的值（四选一，绝不混淆）：
1. truly_low_value —— 内容**本身**低价值：无聊、没看点、纯闲聊、平淡无传播点。**只有这种情况才算真垃圾。**
2. context_insufficient —— 你**看到的上下文不够**判断它：setup/payoff 明显在你读的范围外，你没法确定它是不是个好故事。这时**应把 context_incomplete 设 true**，让系统给你更大上下文重审。
3. event_incomplete —— 这**不是一个完整事件**：只有半截情绪/动作，没头没尾，可能只是某个更大故事被切出来的一段。它未必没价值，只是作为独立片段不成立。
4. ai_uncertain —— 你**拿不准**它有没有价值（可能有意思但你不确定会不会传播）。**拿不准 ≠ 不值得剪。**
铁律：**只有 truly_low_value 才算「该淘汰」**。其余三种（上下文不够/事件不完整/AI 不确定）
都不能当成「内容本身差」——系统会把它们保留为 C 档供人工复核，而不是直接淘汰。
值得剪的事件（你打高分的）reject_reason_kind 留空字符串。

【分级参考（系统会按五维子分加权定级，你不用输出等级）】
S 爆款（必剪）｜A 强推荐（强烈建议剪成正式切片）｜B 值得测试｜C 备用/不推荐。命中负面清单最高到 B。

只输出一个 JSON 对象（本批共 {event_count} 个事件，results 条目数必须一致），格式如下：
{{
  "results": [
    {{
      "event_id": "对应事件编号（如 ev-001），从清单原样复制，不要改，系统靠它对号",
      "title": "对应事件标题，原样返回",
      "is_worth_clipping": true,
      "scores": {{
        "hook": 8,
        "contrast": 6,
        "personality": 7,
        "standalone": 5,
        "completeness": 6
      }},
      "recommended_start": "00:37:20",
      "recommended_end": "00:39:42",
      "recommended_duration": 142,
      "duration_reason": "需要保留开头发现问题的铺垫和最后反应才能形成完整反转",
      "why_cut": "陌生观众为什么停留 + 核心传播点，50字内",
      "strongest_moment": "整个事件里最强的爆点一句话",
      "risk": "最大风险或短板，40字内",
      "negative_flags": [],
      "confidence": 0.7,
      "context_incomplete": false,
      "reject_reason_kind": ""
    }}
  ]
}}
event_id 必须原样复制；negative_flags 没命中填 []，命中几个填几个（只能从上面 5 条规则里选）。
不要输出任何 other 文字（不要 markdown 代码块、不要解释）。

候选清单：
{candidates_text}"""


def build_review_prompt(candidates_text: str, event_count: int = None) -> str:
    """拼复审需求单（一个 batch 的事件清单）。

    兼容旧调用：event_count 不传时尝试从清单里数出事件个数（旧 _format_events_for_review
    用「### 事件」开头）。新代码走 build_batch_review_prompt（显式传 blocks + 计数）。
    """
    if event_count is None:
        event_count = candidates_text.count("### 事件")
    return _REVIEW_TEMPLATE.format(
        event_count=event_count or 1, candidates_text=candidates_text)


def build_batch_review_prompt(blocks: list) -> str:
    """拼一个 batch 的分批复审需求单。

    blocks —— 编排器已拼好的每事件清单文本（含各自上下文原文），list。
    """
    text = "\n\n".join(b.strip() for b in blocks if b and b.strip())
    return build_review_prompt(text, event_count=len(blocks))


# ---- 整场分析报告提示词（分批复审后单独一次调用，基于事件精华卡） ----
_REPORT_TEMPLATE = """你是资深直播短视频运营。下面是系统对一场直播做完事件分析后给出的
「各事件精华卡」（编号｜等级｜100 分制得分｜标题｜为什么值得剪）。你俯瞰整场，给用户写一份
简短复盘报告，帮他们理解：这场内容整体水平如何、最强的传播点在哪、为什么推荐这么少。

只输出一个 JSON 对象，格式如下：
{{
  "summary": "本场直播主要内容，60字以内",
  "best_spread_point": "本场最强传播点是什么、为什么，40字以内",
  "overall": "对整场内容的整体评价，40字以内",
  "why_not_more": "为什么没有推荐更多片段，向用户解释清楚，60字以内"
}}
不要输出任何 other 文字。

事件精华卡：
{cards}"""


def build_report_prompt(cards: str) -> str:
    """拼整场复盘报告需求单。"""
    return _REPORT_TEMPLATE.format(cards=cards or "（无事件）")


# ============================================================
# 以下为 v0.4 步骤 2 提示词：AI 事件判断（Event Judge）
#
# 本地只负责粗聚类（soft signals），「是不是同一件事」由 AI 说了算。
# AI 同时负责给出这个事件的完整边界——长度不固定，
# 原则是「能把这个事件讲清楚的最短长度」。
# ============================================================

_EVENT_JUDGE_TEMPLATE = """下面是海选捞出来的一组候选片段，以及它们前后的上下文原文。

先判断：这几个候选**是不是同一件事**？然后把这件事的完整边界找出来。

【Story 边界规则（V0.4.1 核心）】
系统已给每个候选标注了所属 Story（如 ch-02-st-01）。请严格遵守：
- **同 Story 内**：默认倾向是同一事件，除非有明确证据表明主题完全不同、时间间隔极大（>10分钟）、或中间有完整的情节转折。
- **跨 Story**：默认认为不是同一事件，除非你能找到强证据（如连续对话被 Story 边界切断、同一个事件的 setup 和 payoff 分处两个 Story）。
- 不要仅因为时间接近就跨 Story 合并；要有实质性的内容连续性。

【判断「同一件事」的标准】逐条问自己：
1. 是不是围绕同一个对象 / 同一个主题？（都是这包口粮，而不是口粮聊完又聊游戏）
2. 后一个候选是不是前一个候选的**结果或发展**？（打开包装 → 东西掉出来 → 尝一口，一环扣一环）
3. 中间有没有**主题切换**？哪怕时间很接近，只要主题换了就不是同一件事
4. 合并之后能不能形成一个完整故事（开始 → 发展 → 结果）？
5. **Story 边界检查**：这些候选是否在同一 Story 内？跨 Story 合并需要更强的证据。

【必须合并的例子】
「打开包装」→「东西掉出来」→「尝了一口」→「发现特别难吃」→「直接吐掉」
这五个是**一个完整事件**，不是五个高光。拆开任何一段都会变得莫名其妙。

【必须拆开的反例】
「主播拆包装」→（3 分钟后）→「开始讲游戏」→「又突然回答一个粉丝问题」
时间虽然接近，但主题完全不同，这是三个事件，不许硬凑。

【事件边界：能讲清楚的最短长度】
不要套用「20 秒」「30 秒」这种固定长度。从陌生观众的角度问：
- 从哪里开始，他才能看懂背景（setup）？
- 哪里进入事件、发生冲突或变化（development）？
- 哪里完成 payoff（结果/反应/结论）？
- 什么时候可以结束——payoff 完了就收，不要拖着把无关内容拉进来

短的笑话可能只有 10 秒；一个完整反转可能 40 秒；
一个连续事件可能 1~3 分钟甚至更长。**不要为了固定时长强行截断。**

【上下文不够就直说】
如果 setup 或 payoff 明显落在当前给你的上下文之外（比如开头没头没尾、结尾话没说完），
就输出 need_more_context = true，并说明要往前扩、往后扩、还是两边都扩。
系统会再给你更大的上下文重判一次。

只输出一个 JSON 对象，格式如下：
{{
  "same_event": true,
  "event_summary": "一句话说清这件事：谁、发生了什么、结果如何（40字内）",
  "event_type": "事件类型，如：试吃翻车 / 误会反转 / 突发状况 / 金句吐槽 / 互动整活",
  "event_start": "事件开始时间 mm:ss",
  "event_end": "事件结束时间 mm:ss",
  "structure": {{
    "setup": "铺垫：背景和期待是什么",
    "development": "发展：冲突/变化/意外发生在哪里",
    "payoff": "结果：反应、结论、最爆的那一句"
  }},
  "strongest_moment": "整个事件里最强的爆点是什么（一句话 + 大概时间）",
  "reason": "为什么认为它们是（或不是）同一件事，50字内",
  "confidence": 0.9,
  "need_more_context": false,
  "expand_direction": ""
}}

说明：
- 只有一个候选时，same_event 填 true，但你仍然要判断它的**完整边界**——
  这个爆点是不是需要前面的铺垫才成立？是的话把 event_start 往前挪。
- 如果判断不是同一件事（same_event = false），event_start/end 只给最强那一段，
  系统会把候选拆开各自处理。
- expand_direction 只能在 "before" / "after" / "both" 里选，不需要扩展就填空字符串。

候选片段：
{candidates_text}

上下文原文：
{context_text}"""


def build_event_judge_prompt(candidates_text: str, context_text: str) -> str:
    """拼事件判断需求单（一簇候选 + 它的上下文原文）。"""
    return _EVENT_JUDGE_TEMPLATE.format(
        candidates_text=candidates_text or "（无）",
        context_text=context_text or "（无上下文）",
    )


# ============================================================
# V0.4.4：Chapter / Story 分割提示词
#
# 算法直接沿用已验证的 PoC（poc/ai_chapter_v2.py + poc/story_segmentation_v2.py）：
#   1. 先用「整场事件列表」让 AI 按内容主题切 Chapter（大环节）；
#   2. 再在每个 Chapter 内，用该 Chapter 的事件列表让 AI 按「连续活动/因果链」切 Story。
# 这里只把提示词搬到统一位置 + 加「不写等级字母」规则（D-044），算法本身不改。
# ============================================================

CHAPTER_SYSTEM = (
    "你是直播内容分析专家。你负责按内容主题把整场直播切成几个大环节。"
    + _NO_GRADE_RULE +
    "必须严格输出合法 JSON，禁止输出任何解释性文字。"
)

_STORY_SYSTEM_BASE = "你是直播内容分析专家，擅长识别连续活动和因果链。"

STORY_SYSTEM = _STORY_SYSTEM_BASE + _NO_GRADE_RULE + "必须严格输出合法 JSON，禁止输出任何解释性文字。"

_CHAPTER_TEMPLATE = """你是一名直播内容分析师。以下是一场直播的事件列表（已按时间排序），全场时长 {duration}：

{event_text}

请根据事件的内容结构，将这些事件划分为若干个 Chapter（大环节/节目部分）。

Chapter 表示直播中的"大环节"，如不同测评主题、游戏环节、互动环节等。
边界应基于内容主题的切换，而非固定时间。
Chapter 数量控制在 {max_chapters} 个以内，宁可少而准，不要为了凑数硬切。

请输出合法 JSON，格式：
{{"chapters": [{{"chapter_id": "ch-01", "start_time": "MM:SS", "end_time": "MM:SS", "chapter_title": "标题", "chapter_summary": "摘要(50字内)", "boundary_reason": "边界原因(30字内)", "event_ids": ["ev-xxx"]}}]}}"""

_STORY_TEMPLATE = """你是一名直播内容分析师。以下是「{chapter_title}」章节内的事件（共 {count} 个）：

{event_text}

请根据"连续活动/因果链"原则，将这些事件划分为若干个 Story。

Story 划分原则：
1. Story 是"连续活动"，不是关键词主题
2. 同一 Story 内的事件应该有因果关系或时间连续性
3. 不要把每个物品/一句话机械切成 Story
4. 一个 Story 可以包含多个事件（如"拆包装→试吃→评价"）

输出 JSON 格式：
{{"stories": [{{"story_id": "st-01", "name": "故事标题", "start_time": "MM:SS", "end_time": "MM:SS", "event_ids": ["ev-xxx"], "summary": "故事摘要(30字内)", "reason": "为什么这样划分(20字内)"}}]}}"""


def build_chapter_prompt(event_text: str, duration: str = "", max_chapters: int = 8) -> str:
    """拼 Chapter 分割需求单（整场事件列表）。"""
    return _CHAPTER_TEMPLATE.format(
        event_text=event_text or "（无事件）",
        duration=duration or "未知",
        max_chapters=max_chapters,
    )


def build_story_prompt(chapter_title: str, event_text: str, count: int) -> str:
    """拼某个 Chapter 内的 Story 分割需求单（该 Chapter 的事件列表）。"""
    return _STORY_TEMPLATE.format(
        chapter_title=chapter_title or "未知章节",
        event_text=event_text or "（无事件）",
        count=count,
    )
