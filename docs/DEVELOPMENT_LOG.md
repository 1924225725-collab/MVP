# DEVELOPMENT_LOG —— 开发日志

> 每一次开发过程按「日期 / 版本 / 完成内容 / 遇到问题 / 解决方案 / 测试结果」记录。

---

## 2026-09-09  v0.4 第三步：分批复审 + 上下文时间窗 + 动态时长 + 100 分制

**背景**：第二步把候选还原成完整事件，第三步解决「AI 如何理解一个完整事件 + 这个事件该剪多长值多少分」——把复审从「一次审完所有事件」改成分批（事件原文变长装不下、前半段偏置、预算难控），评分升级 100 分制，并加入真正动态的剪辑时长。

**完成内容**：

1. **分批复审 `_review_in_batches`**：按 `REVIEW_BATCH.max_events_per_batch`（默认 3）把事件切成若干 batch，每个 batch 一次独立复审调用；结果按 event_id 对号入座（禁依赖返回顺序）；AI 报 context_incomplete → 该事件单独用更大窗口重审（最多 1 层深扩）。各 batch 用同一评分标准，复审后 `Global Ranking` 全量按 final_score 降序排（消除前半段偏置）。

2. **上下文时间窗口 `_event_review_context`**：复审上下文从「600 字符截断」改为「事件边界 ± 时间缓冲」——默认 ±60s，可扩 ±180s/±300s（config.REVIEW_CONTEXT.expand_levels）。**以事件边界为锚整段捞取**，长事件天然完整进入，不会被窗口切掉本体。Context Window 与 Clip Duration 完全分离。

3. **动态剪辑时长**：复审 AI 输出 recommended_start/end/duration + duration_reason，取消固定 20/30/60s；长度不设硬上限（一句话梗可短到 8s，完整事件按需几十秒到几分钟）。merge 时经 `_norm_rec_ts` 规范化时间格式 + drift 合理性校验（偏离事件边界 >120s 兜底回事件边界）。

4. **100 分制四档**：复审仍只打五维子分（1-10），本地 `_weighted_final` 加权后 ×10 得 0-100；对外 S≥90/A≥80/B≥60/C≥50，D<50 仅内部淘汰。语义与原 1-10 制 ×10 同构，step1/step2 不回退。

5. **schema 校验不静默兜底**：`_parse_review_reply` 缺 event_id 跳过并 warning、缺五维子分/recommended_* → 记 warning + 明确 fallback；兼容嵌套 scores / 平铺 hook / hook_score，personality→persona 别名。整场报告拆到独立 `_build_ai_report`（REPORT_SYSTEM）。

**遇到问题**：
- 一次审完所有事件 → 单次 prompt 过大、后半段被忽略、前半段偏置 → 分批解决
- 固定时长 → 剪坏完整故事 → 动态 recommended_* 解决
- 真实 API 实测 AI 混用 HH:MM:SS / MM:SS 回 recommended 时间、偶发把推荐点写成全场末尾 → `_norm_rec_ts` 规范化 + drift 兜底
- 真实 API 第一次跑把「2014 罐头事件」拆成 3 碎片全 D（degrade3 候选稀疏）→ 第二次跑（候选稍多）正确聚合为 99s 完整事件 B 级 78 分；归因为步骤 2 聚合在稀疏候选下的不稳定性（D-040），列后续候选

**测试结果**：step3 离线 24/24；step1 23/23、step2 21/21 回归过；真实 API 51 分钟稿标准模式两次跑通（¥0.31/¥0.34），罐头事件正确聚合、动态时长跨 8s~99s、recommended 格式统一

---

## 2026-09-09  v0.4 第二步：事件聚合层（从「评价一句话」到「评价一件事」）

**背景**：第一步把地基（词库纠错 + 反馈记录）打好了，这一步做 v0.4 最核心的一块——事件聚合层，解决需求五条问题里最痛的「AI 把完整事件拆成碎片」。

**完成内容**：

1. **本地粗聚类 `analysis/event_cluster.py`**：四个 soft signal（时间距离 / 时间重叠 / 主题相似二元组 / 相邻加分）给候选两两打关联分，连通分量成簇。设计红线（需求原文）：本地只提分组不删候选、无「超过 X 秒就断开」硬规则、孤立候选自成一簇。

2. **AI 事件判断（Event Judge）**：`prompt_builder.build_event_judge_prompt` + `EVENT_JUDGE_SYSTEM`。给一簇候选 + 上下文原文，让 AI 判断是否同一件事，输出事件摘要/类型/边界/结构（setup/development/payoff）/最强爆点/置信度，支持 `need_more_context` 自适应扩大上下文。

3. **聚合主编排 `_run_event_aggregation`**：粗聚类 → 逐簇 AI 判断 → 自适应扩大（最多 1 轮）→ 事件级去重（`_dedupe_events`）。跑完候选池从「爆点句子」变成「完整事件」，复审评分全部作用在事件上。

**遇到的问题与修复（3 个真 bug，自测 + 真实 API 一起逼出来的）**：

| 问题 | 怎么发现的 | 修复 |
|---|---|---|
| 复审提示词缺 event_id 字段，主流程却靠它按 id 对号入座 | 通读合并逻辑时发现 AI 漏条/乱序会错位 | 提示词 results 补 event_id，要求 AI 原样复制 |
| 五维子分键名不一致：提示词 `hook_score` vs 解析器 `hook`，真实 API 下全会回落 5 分 | 真实 API 测试前通读 `_parse_review_reply` 时发现（v0.3.2 假客户端恰好回 `hook`，离线一直没暴露） | 解析器双键名都认 |
| 事件拆分时共用 judge 边界 → 去重层把拆开的事件误合并 | 离线自测 E 场景「时间接近主题不同 → AI 拆开」失败 | `_make_event` 拆分分支改用候选自己的边界 |

**测试结果**：
- 离线自测 `test_v040_step2.py` **21/21 全过**（本地聚类 6 / 解析 3 / 事件生成 3 / 去重 2 / 聚合编排 5 / 事件级完整流程 3）
- 真实 API 跑 51 分钟稿（标准模式，¥0.3078）：**19 候选 → 16 事件**，AI 合并 3 次、拆分 2 次、上下文扩大 2 次、judge 0 次失败、去重 0
- 关键爆点「2014 罐头异物」从 2 个碎片正确聚合为 2.6 分钟完整事件（ev-012，B 级 7.8 分全场最高）
- 动态时长生效：高光从 11 秒（一句话自嘲）到 162 秒（完整事件），不再固定 20/30 秒

---

## 2026-09-09  v0.4 第一步：词库纠错 + 人工反馈（先把输入弄干净、把判断攒下来）

**背景**：用户下发《v0.4 版本开发需求》。v0.3 已完成全时间轴覆盖 / 候选召回 / AI 复审 / 评分体系 / 类型适配 / 成本控制，人工测试发现最大问题已经不是「找不到爆点」，而是五条：①排序和推荐不符合人工判断；②AI 把完整事件拆成多个碎片；③上下文不足导致「单看普通、放在故事里很有价值」的片段被埋；④S/A/B/C 等级表达不了剪辑价值；⑤固定时长限制不符合真实剪辑逻辑。
v0.4 核心目标一句话：**让 AI 从寻找片段，升级为理解完整事件并判断传播价值**（D-025）。不增加大量新功能，优先提升 AI 判断质量。

**需求共 7 项**：事件聚合层 / 上下文窗口（±60 秒，连续事件可扩到 ±3 分钟）/ 取消固定切片长度（AI 输出 recommended_duration 10 秒~5 分钟 + duration_reason）/ 100 分制评分 + 四档（开头 25 / 故事 25 / 人物 20 / 反差 20 / 独立 10；强推荐 85+）/ 事件重复合并（重叠 >50% 且主题相同）/ 人工反馈接口（本地 feedback.json）/ 词库与 ASR 纠错（custom_dictionary.json 基础版）。

**完成内容（第一步，用户拍板先做本地基础）**：

1. **现状摸底（先读代码再动手）**：确认 5 个关键约束——时长限制写死在提示词第 37 行（「成片时长建议在 30 秒 ~ 3 分钟」）；上下文是**字符数** 600 上限而非时间窗口，所以 AI 确实看不到前后文；复审是**一次调用审完所有候选**，事件级评价后原文变长必然装不下，架构要改分批；clip_id 只在最后 `_select_quantity` 才发，反馈接口需要它提前生成；现有五维权重里「故事完整度」只占 10，与事件级评价不匹配（v0.4 提到 25）

2. **词库纠错**：新建 `analysis/dictionary.py` + `custom_dictionary.json`（分类：主播名字/游戏名称/品牌/网络热词/其他），纯字符串替换；接入 `pipeline.apply_dictionary`（识别完、存稿前），另给 `correct_existing_transcript` 处理历史稿

3. **人工反馈**：新建 `analysis/feedback.py`，本地 `feedback.json`（JSON 数组），字段 clip_id / user_choice / reason / timestamp + snapshot

**遇到问题**：

1. **自测第 20 项失败**——「同一 clip_id 覆盖后 snapshot 丢失」。这不是测试写错了，是真问题：用户第二次反馈通常只改态度（不喜欢/缺上下文）、不会重新传片段信息，而 snapshot 存的是片段的客观特征，丢了将来就没法分析「用户喜欢什么样的片段」
2. **快照继承的边界**：快照该不该跟着新反馈更新？如果片段被重新分析过（分数变了），旧快照就是过期的

**解决方案**：

1. 覆盖时**继承旧 snapshot**（新反馈没带就沿用旧的）——片段客观信息不随用户态度改变，见 D-027
2. 边界保持简单：新反馈**带了** snapshot 就以新的为准（重新分析后自然更新），没带就继承。v0.4 不做更复杂的合并策略

**测试结果**：
- 离线自测 `test_v040_step1.py` **23/23 全过**（5 场景）：词库加载 6 项（含分类摊平/_注释跳过/缺文件/坏 JSON/扁平兼容/真实词库可读）、文本替换 4 项（含**长词优先**——「伏特加酒」不会被「伏特加」咬一半）、识别结果纠正 2 项（dict 与 Segment 对象都支持）、文字稿纠正 4 项（含**时间戳一个字没变**的关键验收、缺文件返回 0）、反馈记录 7 项（建文件/追加/同 id 覆盖/snapshot 继承/坏文件自愈/按 id 查询/统计文案）
- 真实链路验证：`pipeline.apply_dictionary` 实测「福岛→伏特加」「和平经营→和平精英」替换成功，命中 2 处
- `py_compile` 全过（dictionary / feedback / pipeline / config / analysis / ui）

**未完成 / 下一步**：UI 的 👍/👎 按钮与词库管理页留到步骤 4；**步骤 2 事件聚合层**（本地按时间粗合并 + AI 校正，混合方案 D-026）已在 VERSION_PLAN 排好

---

## 2026-09-09  v0.3.2 第二步：评分体系 v3（运营视角五维 + 五级分级 + 负面过滤）

**背景**：v0.3.1 真实复测虽已「召回优先」出 7A/19B/10C，但用户人工复盘发现两个判断错误：
1. 大量 A 级是「事故型」低价值片段——饮料粉洒出来、打开美军口粮发现份量少这类场景被 AI 打了高分（AI 在评价「事情大不大、主播惊不惊讶」，不是在判断「发出去有没有人看」）；
2. 部分 B 级反而比 A 级更适合做短视频（有误会、有反差、有记忆点）。
用户下发《v0.3.2 高光判断优化需求设计》：判断视角从「发生了什么」转为「**一个不了解主播的新用户刷到这个片段，为什么会停下来？**」优先改 prompt_builder / 评分规则 / 复审逻辑 / 输出等级体系，不扩大功能范围。

**完成内容**
- `config.py`：删除旧 v2 权重（传播/情绪/主播特色/争议/独立/内容），新增 v0.3.2 配置段——`SCORE_V3_WEIGHTS`（hook 30 / contrast 25 / persona 20 / standalone 15 / completeness 10）、`GRADE_S_SCORE=9.0`（A/B/C 沿用 8/6/5）、`NEGATIVE_RULES`（普通失误/普通展示/单纯惊讶/依赖上下文/普通评价）、`NEGATIVE_RULE_CAP_GRADE="B"`；`REVIEW_MAX_OUTPUT_TOKENS` 4000→6000（五维子分 + 双理由 + 报告，输出量更大）；`LIVE_TYPE_WEIGHTS` 文案全部改成 v3 视角（每类型写明哪个维度权重最高）
- `prompt_builder.py`：海选模板内嵌 v3 判断视角（每候选自问「陌生用户为什么停留」，五维只作发现候选的粗筛直觉）+「假高光」警惕清单（海选不判生死，但别把普通失误当第一选择）；复审模板重写——**AI 只输出五维子分（hook_score/contrast_score/persona_score/standalone_score/completeness_score），不再输出 final_score/grade**（总分由本地算，杜绝「先给漂亮理由再顺手打高分」）；新增典型案例 few-shot：高价值（黄腐鸡误当咖啡 / 军粮「像纸盒子」/ 罐头「像指甲盖」）vs 低价值（饮料粉洒出来 / 打开发现少「哇好少」）；每个候选必答 `why_cut`（陌生人为何停留 + 核心传播点）与 `risk`（最大短板，禁止写「无」）
- `analysis/__init__.py`：新增 v0.3.2 定级引擎（文件内注释明确划分）——`_weighted_final`（五维子分按 config 权重加权得 1-10 小数总分）、`_grade_from_score`（S≥9 / A≥8 / B≥6 / C≥5 / D）、`_apply_negative_cap`（命中负面清单即封顶 B，只降不升，C/D 不被动）、`_entry_dims`（内部键 → 「三秒吸引力（权重30%）」中文判决书）；复审合并逻辑：dims → 本地算 final_score → 本地定级 → 负面封顶 → D 级 reject_reason 本地组装（不再让 AI 写套话）；数量模式重定义（自动精选=S/A；候选池=S/A/B/C；自定义=按分取前 N 标质量名）；零输出禁令兜底保留（C 级 forced_keep）；复审漏条数时用海选分兜底定级
- `ui.py`：结果卡片支持 S/A/B/C 徽章（🚀S/🌟A/✅B/📦C）+ 五维判决书进度条 + 命中负面清单的 warning（「已封顶 B 级，仅作测试素材」）+ risk 展示
- `test_v032.py`：离线自测 4 场景 18 项（假 AI 客户端零成本，报告写 v032_report.txt）

**遇到问题 → 解决方案**
- 旧复审提示词仍让 AI 直接打总分/等级，与「本地定级」新架构冲突，测试失败 → 复审模板彻底改成只回五维子分，等级完全由代码定（测试全部转绿）
- UI 五维键名带权重（如「三秒吸引力（权重30%）」），初版用 `k[:6]` 切片会切出半个全角括号 → 改为 `k.split('（')[0]`
- 说明：初审讨论过的「D 级≥3 触发全量重审 / S 级数量上限」等附加保险丝**本轮未实现**——先让本地定级引擎 + 负面封顶过真实视频，避免一次叠太多规则无法归因（记入后续小版本候选）

**测试结果（离线，零 API 成本）**
- 场景 A 定级引擎主流程（51:39 稿 + 精细模式 + 假 AI）：不降级、候选池 29 达召回目标、质检重扫区块 3 并忽略坏编号 99、重扫重复候选去重、自动精选只出 S/A（12 个）、候选池含 C 档、D 档 5 个全进 rejected 且带理由、五维判决书中文标签完整、why_cut/risk 透传、clip_id 唯一、成本累加器 17 次合并计费
- 场景 B 负面清单：命中「普通失误」→ S/A 全被压成 B（C/D 保持原级），negative_flags 标记齐全
- 场景 C 零输出禁令：全灭且加权 4.5 → 强制保留 1 个 C（forced_keep）；加权 < 4 → 允许零输出
- 场景 D 质检回垃圾 JSON → 当无漏检，主流程不崩
- 合计 18/18 PASS；lint 0 错误

**下一步**：用户用真实视频（尤其上次 51 分钟军粮试吃稿）实测 v3 判断力，重点看：①饮料粉/份量少这类片段是否不再进 A；②B 级里翻出真爆点的能力；③AI 推荐与人工剪辑师选择的重合率。之后补 👍/👎 反馈按钮（clip_id 已就绪）与词库管理页面（P1）。

---

## 2026-09-09  v0.3.2 第一步：网页版接入 v2 分析流程

**背景**：v0.3.1 判断链路已过真实 API 复测，但 ui.py 停留在 v0.2（点「开始分析」走的还是旧整篇直喂流程，v0.3 全部新功能只能命令行用）。用户准备多视频做精准度测试，需要脱离命令行。

**完成**：ui.py 全面重写。

- 侧边栏三设置：直播类型下拉（AVAILABLE_TYPES）、分析模式单选（带 desc 描述，不露 token 数字，D-005）、数量模式（自定义时出个数输入）
- 文字稿与 AI 分析拆两步：tab「用已有文字稿」（transcripts/ 按修改时间倒序，最新默认选中）/「上传新视频识别」（本地免费，识别完 rerun，新稿自动排最前）。目的：同一场直播换类型/模式反复对照，不重复烧 ASR
- 运行前预算预估：本地跑 解析→扫描→分区→estimate_total，显示时长/区块数、预计 token、预计费用；超预算黄色提示会自动降级（D-015）
- 结果区：A/B/C 分级卡片（先按等级再按分数排序；三类高光/爆款概率/置信度/推荐理由/剪辑建议/forced_keep 警示/clip_id）+ AI 分析报告四字段 + 被拒候选（带拒绝理由）+ highlights_v2.json 下载
- 日志捕获：ASR 和 v2 分析的 verbose 输出都 redirect 到 StringIO，跑完以 expander 展示

**遇到的问题**：
1. 初版在「上传新视频」tab 里对 uploaded 为 None 时用了 st.stop()——会把另一个 tab 用户的「已有文字稿」分析区也整页拦掉（Streamlit 的 tab 不是互斥路由，两个 tab 体都会执行）。改为条件分支不 stop，页面级 stop 只看 selected_transcript 是否为 None。
2. 旧版直接调 pipeline.analyze_highlights（v0.2 流程），新版改调 analyze_transcript_v2 并传三设置；SystemExit（空稿/坏配置）单独捕获给友好报错。

**测试结果**：py_compile 语法通过；Streamlit 服务启动 HTTP 200。待用户用真实视频实测。

**下一步**：①用户实测新界面 ②👍/👎 反馈按钮写 feedback.jsonl ③词库管理页面（P1）。

---


## 2026-09-09  v0.3.1 高光识别准确率优化（召回优先 + 分级输出）

**背景**：P0 首测 0 推荐被人工复盘推翻——该直播实际有多个明显爆点。用户下发 v0.3.1 需求：从「严格筛选」转向「先保证召回率，再保证精准率」。

**完成内容**
- `config.py`：精细模式预算 5 万→8 万（D-021）；新增 GRADE_A/B/C_SCORE（8/6/5）、FORCED_KEEP_MIN_SCORE=4、MISS_CHECK_MAX_CHUNKS=3、HIGHLIGHT_TYPES 三类；删 MIN_QUALITY_SCORE/HIGH_QUALITY_SCORE（被分级线取代）；REVIEW_MAX_OUTPUT_TOKENS 2500→4000
- `prompt_builder.py`：海选提示词重写——宁多勿少、每区块至少 1 候选、三类高光（事件型/情绪型/梗型）各带评分维度、权重 v2（主播特色 15/争议讨论 15，D-020）、三问从「一票否决」降为「加分检查」；复审提示词重写——A/B/C/D 分级替代 recommend、零输出禁令（D-018）、「拿不准给 C 不杀掉」；新增质检提示词（build_miss_check_prompt + 重扫 second_pass 提示）
- `analysis/__init__.py`：编排器插入第 5.5 层漏检质检（本地区块摘要 → 质检 AI → 可疑区块重扫去重并入）；复审合并 grade；`_enforce_no_zero` 零输出禁令兜底；数量模式按分级重定义（自动精选=只出 A；候选池=A+B+C；自定义=前 N 分层）；所有候选发 clip_id（未来 👍/👎 反馈记账）；输出加 highlight_type/grade/forced_keep 字段
- `analysis/budget.py`：估算计入质检调用 + 重扫最坏情况
- `analyze_v2.py`：摘要打印 A/B/C 级 + 质检重扫区块 + 召回保留提示
- `test_v031.py`：离线自测 3 场景 14 项（test_phase2.py 标记过时留档）

**遇到问题 → 解决方案**
- 旧 test_phase2.py 断言基于 recommend 二元制，v0.3.1 后不成立 → 文件头标记过时，新验收以 test_v031.py 为准（不删，留历史）

**测试结果**
- 离线自测（FakeClient，零成本）14/14 全过：候选池 29 个（15~30 达标）、质检重扫真实区块并忽略坏编号、重复候选去重、自动精选只出 A、候选池含 C、clip_id 唯一、零输出禁令两种路径（全 4 分→强制保留 1 个 C；全 3 分→允许零输出）、质检坏 JSON 不崩
- **真实 API 复测通过（2026-09-09，精细模式，¥0.1902，18 次调用）**：候选池 36 个（目标 15~30，召回优先略超可接受）；质检真查出 2 个漏检区块（8、13，理由具体：「信号分11为该场最高但候选未覆盖」），重扫新增 3 候选；复审分级 7 个 A / 19 个 B / 10 个 C，0 淘汰；上一版被漏掉的明显爆点全部召回（49:46 微波炉炸了 A级9分、10:24 奶精翻车 A级8分、11:31 盲盒试吃 A级8分、37:20 陈年罐头 A级8分、38:43 罐头异物 B级）；时间轴 100% 覆盖、候选分布全场无偏置
- 遗留观察（不阻塞验收）：①候选池 36 略超 30 目标上限；②重扫候选与原候选可能时间重叠（49:46 出现两个高度相似候选），去重目前只按起止时间精确匹配——未来可加「时间重叠合并」，记入 v0.3.2 候选

**下一步**
- 真实 API 复测 51 分钟稿（精细模式）；随后按规范 v1.0 验收标准做人工标注测试（3 类直播各标 10 个，目标召回率 >70%、精准率 >50%）

---

## 2026-09-09  P0 真实 API 首测（analyze_v2.py 首次全流程真实跑通）

**完成内容**
- 用户在网页侧边栏填好 API Key（api_key.txt），运行 `analyze_v2.py`（51:39 真实稿 / 娱乐聊天 / 标准 / 自动精选）
- 修复 bug：CLI 入口打印成本报表时 `¥`（U+00A5）在 GBK 控制台触发 UnicodeEncodeError——analyze_v2.py 开头对 stdout/stderr 统一 `reconfigure(encoding="utf-8", errors="replace")`（与 v0.2.1 修的 ffmpeg GBK 问题同根源，见 D-006）

**遇到问题 → 解决方案**
- 首次运行在收尾打印成本时报编码错误崩掉，海选已花 ¥0.088 但结果丢失 → 修复后完整重跑，成功

**测试结果（真金白银，全场 ¥0.0918，14 次调用）**
- 标准模式对 51 分钟稿触发降级至 level 3（粗切 + 限 1 候选/块 + 超预算提示继续），13 区块全部送审，时间轴 100% 覆盖
- 海选 13 块只出 1 个候选（38:38 罐头事件），复审再把它拒掉（reject_reason 3 条：冲突不明 / 口头禅扰观 / 依赖上下文），最终高光 0 个
- ✅ 验收硬指标：被拒候选（含具体理由）✔ / 无前半段偏置（唯一候选来自 38 分钟后半段）✔ / 覆盖完整 ✔ / 坏输出不崩 ✔
- ⚠️ 待人工判断：0 推荐是「AI 判断准确（这场确实无传播点）」还是「提示词过严」——需用户对照自己对这场直播的观感裁定
- ⚠️ 标准模式降到 level 3 后每区块限 1 候选，长直播建议精细模式

**下一步**
- 用户裁定 0 推荐是否符合预期；可选加测：`--type 游戏竞技` 对照（验证类型区分）或 6 分钟短稿精细模式

---

**完成内容**
- 用户下发《AI 直播切片助手长期开发规范 v1.0》，逐条对照落地：
- 新增 `docs/CHANGELOG.md`（回填 v0.1 至今），docs/ 由 5 文件变 6 文件
- DECISIONS.md 追加 D-012 ~ D-016：五维评分标准（传播 30/情绪 25/冲突反转 20/独立观看 15/内容 10）、云端架构（本地 ASR + 云端 AI 分析）、文本纠错优先级 v0.4→P1、Token 展示规范修订（模式选择不露数字 + 运行前必须给预估 + 用户可改上限默认 5 万）、平台不绑定
- VERSION_PLAN.md：长期路线 v0.3→v1.0 + P0-P3 优先级 + 新功能四问
- AI_HANDOVER.md：交接记录格式补「日期/删除/原因/测试结果」字段；开发原则增至 9 条（平台不绑定 / 禁止大规模重构 / 新功能四问）；待办按 P0-P3 重排
- ARCHITECTURE.md：补「规划中模块」段（correction.py / user_profile.py / feedback.py / 云端接口）

**遇到问题 → 解决方案**
- 规范 v1.0「运行前显示预计 Token/费用」与 D-005「UI 不露 token 数字」表面冲突 → 澄清为两件事：模式选择界面不露参数（D-005 不变），运行前给预估消耗（D-015 修订），budget.py 已具备估算能力
- 规范 v1.0 把文本纠错提到 P1，与 D-008「推迟 v0.4」表面冲突 → 记为 D-014 修订：P0 仍是真实 AI 测试（核心验证不变），纠错第一阶段紧随其后；AI 辅助发现词库仍推迟

**测试结果**
- 纯文档变更，代码零改动，无需测试

**下一步**
- P0：用户设 DEEPSEEK_API_KEY → `.\.venv\Scripts\python analyze_v2.py` 真实验收（至少 1 个被拒候选）

---

## 2026-09-09  v0.3 Phase 2（AI 海选 + 复审）

**完成内容**
- 新增 `analysis/budget.py`：Token 预算估算 + 三级降级判定（粗切 → 限候选 → 提示继续）
- `analysis/prompt_builder.py` 新增海选/复审两套提示词：AI 身份改为「直播短视频运营人员」；海选要求回答三个问题（为什么用户会停留 / 为什么适合短视频 / 为什么不是普通聊天）；复审带淘汰机制（recommend + reject_reason）和分析报告（本场总结 / 最强传播点 / 整体评价 / 为什么没推荐更多）
- `analysis/deepseek_client.py`：call_deepseek 支持自定义 system/max_tokens（旧调用不受影响）；新增 CostTracker 跨调用成本累加
- `analysis/chunker.py`：build_chunks 增加可选 hot_seconds/normal_seconds 参数（降级粗切用，旧调用不受影响）
- `analysis/__init__.py` 新增 `analyze_transcript_v2` 编排器：解析→扫描→分区→预算→海选→复审→数量三模式→输出
- 新增 `analyze_v2.py` 命令行入口（输出 highlights_v2.json）
- 新增 docs/ 交接文档体系（本文件所在目录）
- config.py：TOKEN_MODES 三模式 / QUANTITY_MODES 三模式 / LIVE_TYPE_WEIGHTS 类型评分侧重

**遇到问题**
- 51 分钟稿标准模式估算约 2.6 万 token，超过标准预算 2 万 → 属预期行为（设计里长直播就该用精细模式），触发降级 1 粗切

**测试结果**
- test_phase2.py 离线自测（FakeClient 假 AI，零成本）：海选/复审解析、淘汰机制、数量三模式差异、降级路径全部通过
- 真实 API 实测：待 DEEPSEEK_API_KEY

---

## 2026-09-09  v0.3 Phase 1（纯本地分析层）

**完成内容**
- `analysis/transcript_parser.py`（时间戳正则解析，坏行跳过）
- `analysis/event_scanner.py`（每分钟打分：通用强词 + 5 类型词库 + ASR 错字变体 + 用户词库；只调深度不过滤）
- `analysis/chunker.py`（热区桥接 ≤2 分钟冷场；热区 ≤180s 细切 / 普通区 ≤600s 粗切；check_coverage 验收）
- `config.py` Phase 1 配置段；`user_lexicon.txt` 模板；`test_phase1.py`

**测试结果**
- 51:39 真实稿：2268 句 → 52 格，15 热区 → 14 区块，时间轴覆盖 100% 无漏无重叠
- 热区集中在 29-35 / 47-51 分钟——v0.2 的前半段偏置问题结构性解决
- 对照：娱乐词库总信号分 54 vs 游戏词库 0（类型区分有效）
- 观察：娱乐普通词（钱/喜欢/说实话）对唠嗑直播偏敏感（短稿 85% 格子算热），阈值 HOT_BUCKET_SCORE 后续用真实数据调

---

## 2026-09-09  v0.2.2 + git 提交

**完成内容**：ui.py 四步任务清单（st.empty 原地刷新）+ 总进度条 + redirect_stdout 捕获日志进网页 + 开发者署名「夜雨声烦」；TUTORIAL.md 教程
**提交**：e269f8f，标签 v0.2.2，已推送 GitHub

---

## 2026-09-08 ~ 09  v0.2 ~ v0.2.1

**完成内容**：pipeline.py 抽离核心流程（main.py 变薄壳，行为不变已验证）；ui.py Streamlit 网页版；API Key 网页侧边栏填写（api_key.txt，env 优先）；start_webui.bat 双击启动

**遇到问题 → 解决方案**
- subprocess capture_output 在中文 Windows 默认 GBK 解码 ffmpeg 的 UTF-8 输出 → 后台线程 UnicodeDecodeError 崩溃 → 加 `encoding="utf-8", errors="replace"`
- PowerShell 内联 `python -c` 引号被剥离 → 改写临时 .py 文件执行
- PowerShell `*>` 重定向写 UTF-16 → 读的时候用 encoding="utf-16"
- 控制台 print emoji GBK 报错 → 报告类输出写文件再读

---

## 2026-09-08 ~ 09  阶段一 + 阶段二（MVP v0.1）

**完成内容**
- 阶段一：视频扫描 → ffmpeg 提取 16kHz 单声道 MP3（imageio-ffmpeg 自带 ffmpeg 7.1）→ faster-whisper small（CPU int8，zh，vad_filter）→ 带时间戳文字稿
- 可插拔 ASR：asr/（base.py Segment 契约 + local_whisper.py + cloud_api.py 空壳 + 工厂）
- 阶段二：analysis 模块调 DeepSeek，成本四闸门（6000 字截断 / max_tokens 1500 / 打印字数 / 成本报表）
- 提交 bd5dc20，标签 MVP-v0.1

**测试结果**：6.5 分钟测试视频识别 41 句，时间戳准确；small 模型对嘈杂人声有错字（人名差），整体可用

---

## 2026-09-11  V0.4.2（评分/推荐解耦 + 内容结构层 + 新版 UI）

**背景**：用户实测 51 分钟稿 → 13 条 B/C（最高 79.5 分）→ 「自动精选」输出 **0 条高光**。用户要求：先审查（不重构）、区分「内容评分」与「产品推荐」、再按 Chapter→Story→推荐剪辑 做新版 UI。

**审查结论**
- 根因：`_select_quantity` 自动精选 = `grade in ("S","A")`，把内容分级直接当推荐名单；`ai_recommend` 同一处绑定。**产品逻辑问题为主，非代码 bug**。
- 结构缺口：Chapter/Story 只存在于 PoC 脚本并入的 meta，主流程结果 `structure` 缺失，UI 无法按结构展示。

**改动**
1. `_pick_recommendations()` 新增（A 优先 → B 补位 → C 兜底，D 永不推荐）；`_select_quantity` 三模式分支重写，推荐标记与 grade 解耦；新增 `recommended`/`recommend_tier`
2. `story_context.load_structure()` / `build_content_structure()` 新增；`analyze_transcript_v2` 返回新增 `structure` 段（静默降级）
3. ui.py 结果展示层重写：视频信息 → ⭐推荐剪辑 → 🧭直播内容结构 → 🔧开发者视图
4. 新增 test_v040_step6.py / test_ui_selftest.py

**测试结果**：step6 24/24；UI 自测 13/13；回归 step1~5 全过（23/21/24/17/11）；真实结果回放自动精选 0→8 条

**未做（明确留给后续）**：Story 分割精度（ch-03 过渡段，O-001）、跨区块稀疏候选再合并（D-040）、S 级上限、D≥3 自动重审、词库管理页

---

## 2026-09-11  V0.4.3（界面去等级字母：展示层模糊化）

**起因**：用户反馈界面上写「B 级 / C 级」，用户会以为 B/C 不值得剪，错过有观看价值的内容。

**改动**
1. `config.GRADE_UI`：S/A → 🌟 高光内容；B/C → ✨ 有看点（合并）；D → 不显示。新增 `GRADE_RANK`（仅内部排序）
2. `config.RECOMMEND_TIER_LABEL`：重点推荐 / 推荐 / 值得一看 / 备选参考（去字母）
3. `prompt_builder._NO_GRADE_RULE`：禁止 AI 写等级字母，追加到海选/复审/事件判断/报告四个 system
4. `ui.py._soften()` 正则兜底 + 全部展示点接入；开发者视图保留 `grade=X` 并标注内部数据
5. `analysis/__init__.py` 落选理由去字母；`analyze_v2.py` 控制台同步去字母
6. `test_ui_selftest.py` 新增「界面不露分级字母」检查

**未动**：五维权重、S/A/B/C/D 阈值、负面清单封顶、推荐筛选算法、内容结构层。内部 grade 仍是 S/A/B/C/D，JSON 数据不变。

**测试结果**：UI 自测 15/15；step1~6 全量回归 23/21/24/17/11/24 零 FAIL

---

## 2026-09-11  V0.4.4（修复严重数据绑定 bug：Chapter/Story 与当前视频绑定）

**起因（用户实测报告）**：用新视频分析时，「推荐剪辑」内容是正确的（来自本次分析），但「直播内容结构」**始终显示开发阶段那次 51 分钟测试视频的固定 Chapter 01/02/03/04**——换视频、重跑都不变。用户要求先定位根因再做最小修复，并给出两条硬要求：**每分析新视频必须得到该视频自己的 Video→Chapter→Story**；**绝不能固定读取 51 分钟结果、不能用开发样例当默认、不能静默 fallback 到另一场视频结构**。

**根因定位**
- Chapter/Story 分层**从未接进主流程**。它只在 PoC 阶段（`poc/v04_pipeline.py`）对一场 51 分钟测试视频跑过一次，产物写死为 `poc/story_segmentation_result.json`。
- 主流程第 8 层 `analysis/story_context.load_structure()` **无条件读这个固定文件**；`load_story_groups()` 在 `source=None` 时也回落到它。
- 结果：**结构恒定 = 那场 51 分钟视频的；推荐剪辑 = 本次视频的；两者不同源**。这不是评分/聚合层的问题，是「结构数据来源」问题。

**改动（最小修复，不动已验证算法）**
1. 新增 `analysis/chapter_story.py`：`cache_path_for` / `load_cached_structure`（只认同名 + 同时长）/ `save_cached_structure` / `segment_chapters` / `segment_stories` / `get_or_build_structure`（返回 `(data, source)`，source ∈ fresh/cache/empty）
2. `analysis/story_context.py`：`source=None` 时 `load_structure()` 返回空结构、`load_story_groups()` 返回 `{}`；统一 `_read_structure_source()` / `_stories_of()` 入口，**绝不隐式加载固定文件**；兼容 `name`/`summary`（主流程 AI 输出）与 `story_title`/`story_summary`（PoC 夹具）
3. `analysis/prompt_builder.py`：新增 `CHAPTER_SYSTEM` / `STORY_SYSTEM` + `build_chapter_prompt()` / `build_story_prompt()`（沿用已验证的切分方法论 + `_NO_GRADE_RULE`）
4. `analysis/__init__.py`：第 8 层改为 `chapter_story.get_or_build_structure(client, tracker, transcript_path, events, duration, say)` **现算当前视频结构**；返回值新增 `structure_source`；`_run_event_aggregation()` 加 `transcript_path` 参数，Story 先验改读**本视频缓存**而非全局固定文件
5. `config.py`：`STORY_CONTEXT` **删除** `"story_file"`（bug 源），新增 `"cache_dir": "structures"`；新增 `CHAPTER_STORY`（enabled / max_chapters / 输出 token 上限）
6. `ui.py`：无结构降级文案去掉 `poc/story_segmentation_result.json` 引用
7. 夹具隔离：`poc/story_segmentation_result.json` + `poc/ai_chapter_result.json` → `poc/fixtures/`；`poc/*.py` 与 `test_*.py` 路径同步并显式传夹具路径
8. 新增 `test_v040_step7.py`（20 项验收）、`verify_v044_two_videos.py`（真实双视频验证）

**当前 Chapter/Story 数据流（唯一正确路径）**
```
文字稿 → 事件发现/聚类/判断 → 事件列表
  → chapter_story.get_or_build_structure(client, transcript_path, events, duration)
      ├─ 先查 structures/<本稿名>.json（同名同时长 → source=cache）
      └─ 否则用本稿事件现算 Chapter → Story（source=fresh）并写入本视频缓存
  → 挂事件 + 派生 Story 评分 → 结果 structure → UI「直播内容结构」
（与本次 highlights 出自同一次分析、同一批 event_id）
```

**测试结果**：test_v040_step7.py **20/20**（视频A/B 结构各自对应；连续运行不互相继承；推荐剪辑与结构同源；缓存按视频隔离、时长不匹配拒绝复用、无缓存返回 None；`load_structure()`/`load_story_groups()` 默认返回空、config 无 `story_file`、夹具已移走；step1~6 全量回归 OK）；test_ui_selftest.py **15/15**；真实双视频验证见 `v044_two_videos_report.txt`。

**未动**：Event 层、本地聚类、AI 事件判断、评分体系（S/A/B/C/D）、推荐筛选算法（D-041）、Chapter/Story 软边界原则（D-025/D-026）。

---

## 2026-09-11  V0.4.5（修复本地 ASR 错误处理链路：分层提示 + 模型离线加载）

**起因（用户实测）**：网页版「上传新视频识别」对**任何**视频都统一提示「视频处理失败，请换一个文件试试」——正常视频、损坏视频、无音轨视频完全一样，无法定位。

**定位过程（实测复现，非猜测）**
1. 照抄 ui.py 的调用方式跑 `pipeline.process_video(videos/测试视频.mp4)` → 抛 `httpx.ProxyError: 502 Bad Gateway`，`result=None`。
2. 栈顶是 `huggingface_hub.hf_api.model_info` —— **加载模型时会联网做远程校验**，即使模型已在本地缓存。
3. 查环境：`http_proxy=http://127.0.0.1:4492` → 访问 HuggingFace 被代理拦成 502。
4. 验证修复可行性：`WhisperModel('small', device='cpu', compute_type='int8', local_files_only=True)` → **1.7s 加载成功**（完全离线）。
5. 第二层根因：`extract_audio`/`process_video` 失败只 `return None`，ui.py 拿到 None 只能给一句通用提示；`except Exception` 还把 traceback 吞了（`SystemExit` 甚至抓不到）。

**改动**
1. 新增 `errors.py`：`ProcessError(stage, message, detail)` + 10 个 stage 常量（供 UI 映射）
2. `pipeline.py`：新增 `check_video_readable()` 与 `probe_media()`（`ffmpeg -i` 解析 `Input #0` / `Audio:` / `Duration:`，关键字表判损坏）；`extract_audio()`/`process_video()` 改为**抛 ProcessError 而非返回 None**；`get_recognizer()` 只缓存成功结果
3. `asr/local_whisper.py`：**离线优先加载**（`local_files_only=True`）→ 缓存缺该模型才联网下载；`ImportError`/`SystemExit(1)` 改抛 `ProcessError`；`transcribe()` 的 try 包住整个惰性生成器循环
4. `asr/__init__.py`：`ASR_BACKEND` 写错抛 `ProcessError`
5. `ui.py`：`_ASR_ERROR_UI` 十条分层文案；失败时展示 stage + 原始错误；**完整 traceback / 原始 detail / 控制台输出**进「🔧 开发者」折叠区
6. `main.py`：try/except ProcessError，命令行也能看到出错层级
7. 新增 `test_v045_asr_errors.py`（18 项）；`.gitignore` 加 `_test_media/` 等

**测试用的媒体（`_test_media/`，均已 gitignore）**
正常（真实片段，有音轨）/ 无音轨（`-an` 生成）/ 损坏（随机字节）/ 静音（有音轨无内容）/ 完整 6 分钟真实视频

**测试结果**
- test_v045_asr_errors.py **18/18**：7 种情况 stage 互不相同（正常=OK / no_audio_track / media_unreadable / model_missing / asr_empty / model_load / asr_inference）
- 真实完整视频：`测试视频.mp4`（6:28）→ **41 句 / 85s**，模型「离线加载」成功
- UI 自测 15/15；step1~6 回归全过

**未动**：ASR 架构与阶段划分、Chapter/Story/Event/Highlight/Recommendation、评分体系。
