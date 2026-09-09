# CHANGELOG —— 版本变更日志

> 每次版本发布必须更新本文件 + VERSION_PLAN.md + DEVELOPMENT_LOG.md + AI_HANDOVER.md（规范 v1.0 要求）。
> 格式：版本 / 日期 / 新增 / 修改 / 删除 / 原因 / 测试结果。

---

## v0.3.2 第二步（2026-09-09，评分体系 v3：把 AI 从「总结助手」变成「短视频运营剪辑师」）

- 新增：test_v032.py（离线自测 4 场景 18 项，假 AI 客户端零成本）；config.py 的 v0.3.2 配置段（SCORE_V3_WEIGHTS / GRADE_S_SCORE / NEGATIVE_RULES / NEGATIVE_RULE_CAP_GRADE）
- 修改：
  - config.py：五维权重 v3（三秒吸引力 30 / 反差意外 25 / 人物表现力 20 / 独立成片 15 / 事件完整度 10）；S 级线 9.0；「不值得剪」负面清单 5 条 + 封顶规则（命中最高 B 级）；REVIEW_MAX_OUTPUT_TOKENS 4000→6000；LIVE_TYPE_WEIGHTS 文案换成 v3 视角
  - prompt_builder.py：海选提示词加 v3 判断视角（一个不认识主播的新用户刷到开头 3 秒，为什么会停下来）+ 假高光警惕清单；复审模板重写——**AI 只打五维子分（1-10），不再直接输出总分和等级**；新增典型案例校准（黄腐鸡误当咖啡/军粮像纸盒子/罐头像指甲盖 = 高价值；饮料粉洒出来/「哇好少」= 低价值）+ 负面清单标记 negative_flags + why_cut/risk 双理由必答
  - analysis/__init__.py：新增**本地定级引擎**——_weighted_final（按权重加权算总分，可解释可审计）、_grade_from_score（S/A/B/C/D 五级映射）、_apply_negative_cap（命中负面清单封顶 B，只降不升）、_entry_dims（中文五维判决书）；复审合并逻辑改用五维子分定级；D 级淘汰理由本地组装；数量模式重定义（自动精选=S/A；候选池=S/A/B/C；自定义=按分取前 N 标注质量名）
  - ui.py：结果卡片升级 S/A/B/C 四徽章 + 五维判决书进度条（逐维显示「三秒吸引力 8分」）+ 负面封顶 warning + 最大风险展示
- 删除：复审 AI 直接输出 final_score/grade 的旧格式（回复里带了也忽略，全部以本地定级引擎为准）
- 原因：真实测试 + 人工复盘发现 AI 仍在当「直播内容总结助手」——饮料粉洒出来、军粮份量少这类「事故型」片段被评高分，部分 B 级反而比 A 级更适合做短视频。判断标准要从「发生了什么」换成「陌生用户刷到为什么要停下来」
- 测试结果：离线自测 18/18 全过（51 分钟稿全流程：S/A 精选 12 个、D 档全进 rejected、五维判决书中文标签完整、命中负面规则封顶 B、零输出禁令两条路径、质检坏 JSON 不崩）；lint 0 错误；待用户真实视频做人工命中率验收

## v0.3.2 第一步（2026-09-09，Phase 3 UI 接入：网页版切到 v2 流程）

- 新增：无新文件（改动集中在 ui.py）
- 修改：ui.py 全面重写——①「开始分析」从旧 v0.2 流程切换到 analyze_transcript_v2；②侧边栏新增三设置（直播类型下拉 / 分析模式带描述单选 / 数量模式 + 自定义个数）；③文字稿与 AI 分析拆成两步（识别过的稿子直接换设置重跑，不重复烧 ASR）；④运行前预算预估（时长/区块数、预计 token、预计费用，超预算提示自动降级，D-015）；⑤结果区改 A/B/C 分级卡片（三类高光/评分/置信度/剪辑建议/forced_keep 标记/clip_id）+ AI 分析报告四字段 + 被拒候选（带拒绝理由）+ 完整 JSON 下载
- 删除：旧版高光卡片渲染（评分/时间段/标题/理由的 v0.2 格式；命令行 main.py 旧流程不动，保留兼容）
- 原因：v0.3.1 判断链路已过真实 API 验证，UI 严重滞后（停留在 v0.2），用户准备多视频做精准度测试需要脱离命令行
- 测试结果：语法编译通过；Streamlit 服务启动 HTTP 200；待用户用真实视频实测（👍/👎 反馈按钮留到下一步）

## v0.3.1（2026-09-09，召回优先 + 分级输出，待真实 API 复测）

- 新增：漏检质检层（prompt_builder.build_miss_check_prompt + 编排器第 5.5 层 + 重扫 second_pass）、test_v031.py、clip_id 字段
- 修改：config.py（精细预算 8 万 / A-B-C 分级线 / 质检配置 / 删 MIN_QUALITY_SCORE、HIGH_QUALITY_SCORE）；prompt_builder.py（海选宁多勿少 + 三类高光 + 权重 v2；复审 A/B/C/D 分级 + 零输出禁令）；analysis/__init__.py（质检重扫 + 分级合并 + 零输出兜底 + 数量模式按分级重定义）；budget.py（计入质检/重扫）；analyze_v2.py（打印分级）
- 删除：复审二元 recommend 输出格式（兼容读入保留，输出改为 grade + ai_recommend 派生字段）
- 原因：P0 首测 0 推荐被人工复盘推翻——海选漏掉大量潜在高光 + 复审过严。策略调整为「先保证召回率，再保证精准率」（D-017~D-021）
- 测试结果：离线自测（FakeClient）14/14 项通过；真实 API 复测通过（精细模式 ¥0.19：36 候选、质检查出 2 个漏检区块重扫、7A/19B/10C 分级、上版漏掉的爆点全部召回、不再零推荐）

## 2026-09-09  开发规范升级（无代码变更）

- 新增：docs/CHANGELOG.md（本文件）
- 修改：VERSION_PLAN.md（长期路线 + P0-P3 优先级）、DECISIONS.md（D-012 ~ D-015）、AI_HANDOVER.md（交接记录格式、开发原则）、ARCHITECTURE.md（规划中模块）
- 删除：无
- 原因：用户下发《长期开发规范 v1.0》，明确平台不绑定、五维评分标准、文本纠错优先级提升（P1）、云端部署方向（本地 ASR + 云端 AI 分析）、Token 预估展示要求
- 测试结果：纯文档变更，不涉及代码

## v0.3 Phase 2（2026-09-09，待真实 API 实测）

- 新增：analysis/budget.py、analyze_v2.py、test_phase2.py、docs/ 交接文档体系（5 文件）
- 修改：config.py（TOKEN_MODES/QUANTITY_MODES/LIVE_TYPE_WEIGHTS/评分阈值）、prompt_builder.py（海选+复审提示词）、deepseek_client.py（CostTracker）、chunker.py（粗切降级参数）、analysis/__init__.py（analyze_transcript_v2 编排器）
- 删除：无（v0.2 全流程保留兼容）
- 原因：AI 身份从总结助手改为短视频运营；增加淘汰机制与分析报告；Token 预算控制
- 测试结果：离线自测（FakeClient）23/23 项通过；真实 API 实测待 DEEPSEEK_API_KEY

## v0.3 Phase 1（2026-09-09）

- 新增：analysis/transcript_parser.py、event_scanner.py、chunker.py、test_phase1.py、user_lexicon.txt
- 修改：config.py（BUCKET/HOT_CHUNK 等配置）
- 删除：无
- 原因：解决 v0.2 前半段偏置与截断丢内容问题；扫描层只调深度绝不过滤
- 测试结果：51:39 真实稿 14 区块，时间轴覆盖 100%；类型词库区分有效（娱乐 54 分 vs 游戏 0 分）

## v0.2.2（2026-09-09，提交 e269f8f，标签 v0.2.2）

- 新增：TUTORIAL.md
- 修改：ui.py（四步任务清单/进度条/日志进网页/署名）、start_webui.bat
- 原因：网页版操作可视化，降低使用门槛
- 测试结果：网页版全流程可用

## v0.2 ~ v0.2.1（2026-09-08 ~ 09）

- 新增：pipeline.py、ui.py（Streamlit）、start_webui.bat
- 修改：main.py（变薄壳，行为不变）
- 原因：抽出核心流程便于复用；提供网页界面；API Key 网页填写
- 测试结果：命令行行为回归通过；修 subprocess GBK 解码崩溃

## v0.1 MVP（2026-09-08 ~ 09，提交 bd5dc20，标签 MVP-v0.1）

- 新增：main.py、config.py、asr/（可插拔识别器）、analysis/（DeepSeek 单次分析）、videos/、audio/、transcripts/
- 原因：打通最小闭环：视频 → 音频 → 文字稿 → AI 分析
- 测试结果：6.5 分钟测试视频识别 41 句成功
