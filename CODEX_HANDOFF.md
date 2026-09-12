# CODEX_HANDOFF — AI 直播切片助手 / DKN 工程交接

> 交接日期：2026-09-12 ｜ 基线：`master @ a6f6b8a`（tag `v0.5.3`）｜ 工作树干净、已全部推送
> 本文档以**当前代码 + Git history + 实际测试结果**为准。历史文档（尤其 `docs/AI_HANDOVER.md`、`DESKTOP_MIGRATION_PLAN.md`）部分内容已过时，冲突时以本文档和代码为准。
> 读这份文档前先读：`CURRENT_STATE.md`（30 秒版）→ 本文档 → `docs/DECISIONS.md`（53 条决策）。

---

## 1. WHY — 这个项目为什么存在

主播（本项目唯一用户，也是产品定义者）直播后想把直播流剪成可传播的短视频。市面工具只能"按音量找热闹片段"，无法理解**一段完整的事件**（起因→经过→爆点→收尾），剪出来是半截对话。

因此做一条**理解驱动**的流水线：把直播转写、理解结构、聚合出**完整事件**、判断"值得剪"，最后给出**推荐剪辑**。用户身份双重：既是开发者也是唯一 Ground Truth 来源——**他的人工判断高于一切模型自评**。

品牌名 **DKN**（Der Klang des rastlosen Nachtregens，"无休止夜雨之声"），未来产品以 DKN 品牌化（见 §9）。

---

## 2. 演变史（按 Git tags 顺序）

| 版本 | tag | 内容 |
|---|---|---|
| MVP v0.1 | `MVP-v0.1` | 视频 → ffmpeg 提音频 → faster-whisper ASR → transcript → **AI 直接找 Highlight**（DeepSeek）→ 输出 JSON。命令行。 |
| v0.2 | `v0.2.2` | Streamlit 网页版 + 教程。 |
| v0.3~v0.3.2 | `v0.3` | 多阶段分析（海选→质检→聚合→复审），评分升 S/A/B/C/D 五级 + 100 分制五维（SCORE_V3_WEIGHTS，冻结）。 |
| v0.4.x | `v0.4.1`/`windows-installer` | **从"找片段"到"理解事件"**：本地聚类 + AI 事件判断 + 分批复审 + 排序；加 Chapter/Story 结构层；评分与推荐**解耦**；网页 UI 去等级字母；ASR 错误分层。 |
| v0.5.0 | `v0.5.0` | **Windows 独立桌面版**（PySide6）：程序/数据目录分离、服务层、Provider 抽象、Model Registry、安装包+卸载程序。 |
| v0.5.1~v0.5.3 | `v0.5.1`~`v0.5.3` | 桌面加固：真实进度、环境自检、卸载修复、模型镜像下载、下载↔识别链路接通。 |

**各层职责（现状）**：
- **Chapter**：整场大环节（如"美军口粮测评"），AI 基于全局采样划界。**软上下文边界，不是硬门**。
- **Story**：Chapter 内的连续活动/因果链（如"咖啡测评：吐槽与豪饮"）。同样软边界。跨 Story 候选合并会被轻微惩罚（-0.15）但**绝不禁止**。
- **Event**：一段完整的、值得剪的事（聚合后的候选组，有 event_id）。
- **Highlight**：事件级五维评分（SCORE_V3_WEIGHTS：hook30/complete25/interaction20/emotion15/spread10 → S/A/B/C/D）。
- **Recommendation**：与评分**解耦**的最终推荐（A 优先 + B 补位，数量由用户选项决定），`recommended: true` 标记。

---

## 3. 关键实验与已证伪方案（不要重做）

每条格式：**问题 → 尝试 → 结果 → 结论**。

1. **transcript 直接喂 LLM 找 Highlight** → 一场 50 分钟超出上下文，截断后 AI 只见局部；输出不稳定 → **必须分块**（chunker）。
2. **固定长度 chunk** → 把完整事件切成两半，AI 各看一半都判"不完整" → 改为**热/常规双粒度**（HOT_CHUNK_SECONDS=180 / NORMAL=600，BUCKET_SECONDS=60 热度分桶）。
3. **"有意义 ≠ 值得剪"** → AI 早期把科普讲解判高分（有意义但无聊）→ 五维里加 **spread（传播价值）** 与 **hook**，与"内容价值"分开。
4. **事件碎片化**（短句爆点各成一事件）→ A1：候选完整性聚合 + 边界扩展；**A2**：QA near-duplicate 合并（同问题同答案）；**A3**：630 行审计修复。三者已冻结，**不要推翻**（背景见 `docs/HANDOVER_20260910.md`）。
5. **B1 event-seed 基线**：38 候选 → 18 事件（A1/B11/C3/D3），中位 51s，¥0.493。`poc/v04_result.json`、`poc/v04_b1_compare.json`。**这是 V0.4 一切改动的对照组。**
6. **本地粗聚类误删候选** → D-030：**本地规则绝不删候选**，孤立候选自成一簇，删不删由 AI 复审决定。
7. **去重误合并** → D-035：事件拆分用**候选自己的边界**，不用整簇边界。
8. **Chapter PoC / Story PoC**（`poc/ai_chapter_result.json`、`poc/story_segmentation_result.json`，人工验收通过）→ 51 分钟测试稿：4 Chapter / 10 Story。已知瑕疵：ch-03 被 AI 过度拆分；**Story 分割漏掉 45:21-47:08 牛肉罐头完整事件（落进 Story 间隙，标记 __unknown__）**——Story 分割精度是已知待改进点（O-001）。
9. **Story-aware clustering 的双刃剑**：Story 强先验避免跨 Story 误合并（正确），但也让 B1 里跨 Story 的合并消失（ev-012 候选 4→2）。人工判定**符合设计预期**。跨 Story 再合并是 D-040 记录的已知风险。
10. **Auto-select 只选 S/A → 0 输出** → D-041：改 **A 优先 + B 补位**，且与评级解耦。
11. **固定 51 分钟测试结构串进其他视频**（D-045 前）→ Chapter/Story **必须由主流程按当前视频现算**，任何固定样例 fallback 禁止。桌面版 project_store 每视频一项目、读时校验 project_id，结构上杜绝串场。
12. **Chapter/Story 缓存跨视频污染** → D-045 + story_context.py 按 video 绑定。
13. **Audio DSP（RMS/ZCR/能量热点）**（`poc/audio_layers*.py`、`docs/AUDIO_POC_REPORT_20260909.md`）→ 能找到文本系统外的 83 个热区，**但 BGM 鼓点/环境音/礼物音效全是假阳性，无法区分笑声/普通说话/BGM** → 结论：**本地 DSP 到瓶颈，暂停**；未来要走**语义级音频事件模型**（如 YamNet 只在能量热点附近跑），且降级版结果**不得直接进评分**。
14. **视觉分析**：暂缓。未来倾向只对高价值 Story/Event 做**局部**视觉分析，不做整场逐帧。
15. **DKN Logo 动画**：AI 生成静态图 → 矢量化得到的是 **outline geometry**，不是手写 centerline/stroke path → 交叉笔画处出现补笔/时序错乱。**正确方向**：以静态 Logo 为视觉参考，重建 stroke-based handwriting paths（每自然笔画独立 path + start/end/order）再做 SVG 动画。**不要再靠改动画提示词解决结构问题。**
16. **评分调参救不了事件不完整** → 完整性是上游（聚类/边界）问题；人工结论反复确认"事件完整性 > 分数微调"。

---

## 4. 真实人工验证结论（Ground Truth，不可改写）

- 51 分钟真实直播（美军军粮测评）是全程对照组。人工复盘记录：`docs/V041_MANUAL_REVIEW_20260910.md`、`docs/V04_DIFF_ANALYSIS_20260910.md`、`docs/V041_STORY_AUDIT_20260910.md`；原始数据：`poc/v04_result.json`、`poc/v04_b1_compare.json`、`poc/v04_diff_summary.json`、`feedback.json`。
- 人工确认的核心结论：
  - **B 级 ≠ 没价值**：ev-012（微波炉炸 + 高血脂自曝，B 78 分）人工认可为好素材；**B/C 是主要素材来源**，不要因评级低就丢弃。
  - **高分 ≠ 完整**：存在 AI 高分但边界残缺的事件；反之 D 级里确实有纯垃圾（评级体系本身可信，但**只作参考**）。
  - **"传播价值"与"素材价值"是两个维度**：有的完整事件值得留存当素材，未必适合直接传播；推荐逻辑必须让用户可调（quantity / 优先级）。
  - **事件完整性 > 调分**：ev-011 落在 Story 间隙暴露的是上游分割问题，不是评分问题。
- 规则：AI 自评不能替代人工标签；**不要改写/重解释这些人工结论**，只能新增。

---

## 5. 当前真实架构（按代码，2026-09-12）

```
[桌面入口 desktop_app.py]  ── Qt 主循环；启动后台环境自检；打包自检 LIVE_CLIPPER_SMOKE
  └ desktop/ui/main_window.py（左侧项目列表 + 顶栏进度 + 四页签）
       ├ services/tasks.py      ← UI 只跟这层说话
       │    ├ transcribe_video → pipeline.process_video(recognizer=_desktop_recognizer())
       │    └ analyze_transcript → analysis.analyze_transcript_v2（不改算法，只流式接日志做进度）
       ├ services/project_store.py  每视频一项目 projects/<id>/project.json（原子写，读时校验 project_id）
       ├ services/model_manager.py  Model Registry：检测/一键安装(镜像优先)/校验/沿用HF缓存/手动指定
       ├ services/selfcheck.py      6 项自检 + 四类错误归类
       └ services/ai_progress.py    分析日志 → 进度事件（不改 analysis/）
```

**识别链**（`pipeline.py`）：
`check_video_readable` → `probe_media`（ffmpeg -i 探测时长/音轨）→ `extract_audio`（ffmpeg → 16kHz mp3）→ `transcribe_audio`（ASR Provider：桌面版传 `FasterWhisperProvider(model_path=工作区模型)`，见 `asr/provider.py`/`asr/local_whisper.py`，vad_filter=True，段级真实进度）→ `apply_dictionary`（词库纠错）→ `save_transcript`。
进度协议：`stages.py` 六阶段结构化事件（video_read/audio_extract/vad/asr/ai_analyze/finalize），ASR 百分比=已处理音频秒/总秒（**D-050：禁假进度**）。

**分析链**（`analysis/__init__.py::analyze_transcript_v2`，唯一入口）：
`transcript_parser`（解析时间戳）→ `chunker`（热/常规双粒度分块）→ `event_scanner`（海选，每块出候选）→ `event_cluster`（本地 soft-signal 粗聚类，**不删候选** D-030）→ **AI 事件判断**（`prompt_builder` + `deepseek_client`，分批复审 D-037，全局排序）→ `chapter_story` + `story_context`（结构层，按当前视频现算 D-045）→ Event Completion → Highlights（五维 + S/A/B/C/D）→ recommended（A 优先 B 补位 D-041）→ `budget.py` 成本统计。
每步 print 日志（`[分区]/[海选]/[复审]/[结构]/[报告]`）——这也是 ai_progress 的进度来源。
**是否调 AI**：海选/聚类/结构 = 本地；事件判断与复审 = DeepSeek API；ASR = 本地。

**输出数据结构**（`projects/<id>/project.json`）：
`{project_id, created_at, state, video{path,name,duration}, transcript{path,lines}, analysis{highlights[...] , cost, meta}, ...}`
highlight 关键字段：`event_id`、`start/end`、`scores`（五维子分+总分）、`grade`（S/A/B/C/D）、`recommended`、`story_id`、`reasons`。结构层：`structure.chapters[].stories[]`。

**AI 评分 prompt 的契约**（复审输出 schema）有校验，缺字段不静默填 5（D-039）。

---

## 6. 桌面版真实状态（核对过代码与测试）

**已完成（有测试背书）**：
- 安装包 `dist_setup/AI直播切片助手_Setup.exe`（~138MB）：静默安装支持、无管理员、卸载程序（复制自身到 %TEMP% + 后台兜底清理 + 注册表必清）。
- 安装 → 启动 → 导入视频 → 本地 ASR（真实进度）→ AI 分析 → Chapter/Story/推荐展示 → 卸载。全流程自动化验收通过。
- 模型管理：镜像优先下载（hf-mirror.com，官方兜底，自动换源、断点续传）、完整性校验、沿用 HF 缓存、手动指定文件夹。
- 环境自检（FFmpeg/识别依赖/VAD 模型/本地模型/配置/存储权限，四类归类）。
- 启动日志 / 安装日志 / 卸载日志（路径见 §12）。
- 错误分类弹窗（视频/程序组件/模型/权限 + 具体原因）。

**入口与页面**：⭐推荐剪辑 / 🧭直播内容结构（Chapter 折叠→Story→Event） / 📺视频信息 / 🔧开发者视图（含环境自检、运行日志、元信息/成本、完整 JSON）。设置对话框（API Key、数量、token 模式、模型选择）。

**预留接口（未实现，别当已完成）**：云端 ASR（`asr/cloud_api.py` 只有接口）、两遍引擎（`TwoPassProvider`）、词库管理 UI（`custom_dictionary.json` 已生效但无编辑界面）、用户画像、云端部署。

---

## 7. 本地 ASR 与打包史（faster-whisper）

- 引擎：faster-whisper（CTranslate2 CPU int8）。默认模型 **small**（`config.WHISPER_MODEL_SIZE`），桌面版实际路径来自 Model Manager 工作区 `models/<id>/`（**不读 HF 缓存路径，除非工作区没有**——回退）。
- **模型不随安装包分发**（D-049）：清单 `models_registry.json`（repo_id/revision/base_url/mirrors/files/min_primary_bytes）；下载到 `%LOCALAPPDATA%\AILiveClipper\models\<id>\`；marker 记录来源（workspace/hf_cache/manual + source_url）。
- FFmpeg：`imageio_ffmpeg` 提供，打包时显式收进程序目录（构建日志有 `[spec] 已收进 ffmpeg`）。
- Cloud ASR 抽象已存在（`asr/cloud_api.py`，未实现）。
- **著名打包 Bug（已修，勿重蹈）**：`faster_whisper/assets/silero_vad_v6.onnx` 是该包**唯一非 .py 文件**；PyInstaller 只 `collect_submodules` 时 .py 进了包、ONNX 没进 → 开发态永远正常，**装到别的盘真跑识别必崩**（NoSuchFile）。修复：spec 显式收集 assets + 错误分类（缺文件→"程序组件问题，请重装"）+ **验收必须真跑一次 ASR inference**（`packaging/test_install_uninstall.py`、`packaging/verify_install.py` 都有）。
- **教训已写进 D-050/D-051 与验收：安装验收只验 import/构造器/ffmpeg 存在 = 不合格。**

---

## 8. 桌面工程问题状态表（以当前代码与测试为准）

| 问题 | 状态 | 证据 |
|---|---|---|
| ASR 真实进度（已处理时长/总时长） | **DONE** | `stages.py`+`progress_view.py`，`test_desktop_progress.py` 34/34（含"百分比=真实时间比"硬校验） |
| 首次安装假死 | **DONE**（本机验证；真实干净机复测待做） | 安装器重活全在后台线程；`packaging/test_install_uninstall.py` 35/35 |
| 卸载不干净 | **DONE**（逻辑修复+自动验收；残留案例的根因=程序运行中句柄占用，已写进文案） | 卸载器重写（%TEMP% 自复制+重试+后台兜底+注册表必清）；30/30 |
| 环境自检 | **DONE** | `selfcheck.py`，验收 3/3 项断言 |
| 错误分类（四类） | **DONE** | `error_text.py`+`selfcheck.category_of_stage` |
| 安装/卸载自动化测试 | **DONE** | `packaging/test_install_uninstall.py` 35 项、`verify_install.py` 33 项 |
| 模型检测/下载 | **DONE**（本机干净工作区验证；真实外网镜像长跑只有 tiny 75MB 实测） | `test_model_sources.py` 12/12；small 464MB 真机下载由用户实测通过 |
| **干净 Windows 全新机全流程** | **TODO**（用户已在真机测过两轮并暴露并修复 3+2 个 bug；下一轮复测待做） | — |
| 首次运行无模型时的联网引导（装完即见） | **PARTIAL** | 逻辑在，但"全新机首次弹窗→下载"未端到端实测 |
| 真实视频全流程（导入→识别→AI 分析→推荐） | **TODO**（用户尚未在新包上回报成功案例） | — |
| 词库管理 UI / 用户画像 / 云端部署 | **TODO**（规划内，未开工） | — |

---

## 9. 品牌：DKN

- 全名 **Der Klang des rastlosen Nachtregens**（意境：夜晚的雨声在寂静中显得格外叨扰）。
- 视觉方向：黑白极简、手写签名风。Logo 动画踩坑与正确路径见 §3 第 15 条（outline≠stroke path）。
- 软件品牌化尚未落到代码（窗口标题仍是"AI 直播切片助手"）——改名时注意 `desktop/__init__.py` 的 APP_TITLE、安装器 `setup_app.py`/`uninstaller.py` 的 APP_NAME/APP_ID、`app_paths.py`。

---

## 10. 下一代方向（NEXT / DESIGN，**未实施**）

优先级：**Audio Understanding > 继续调 Text Judge**。目标把 Transcript 从"时间+文字"升级为：
`时间 + Speaker A/B/C + Speaker Role + 说了什么 + 情绪/强度/变化 + Audio Event`。

构想分层：`Video → Audio Understanding（ASR/Diarization/Speaker Role/Emotion/Audio Event）→ Chapter → Story → Event → Highlight`。

**自适应分析密度**：稳定/低价值区 ~10–15s 级；音频变化/高兴趣区 ~3–5s 级。
**红线**：不能用最终 Highlight score 决定音频分析密度（循环依赖）；要建独立的 **Audio Change / Audio Interest signal**。
 DSP 实验结论（§3 第 13 条）直接适用：要语义级模型（YamNet 类），启发式只能当热区提示。
视觉理解暂缓；倾向对高价值 Story/Event 局部分析。

---

## 11. 产品设计原则（12 条，违反前先找用户）

1. 准确率优先于极端省 token；可以省重复调用，不能省真正需要的分析与真实验证。
2. "重要/有意义" ≠ "值得剪"。
3. "素材价值" ≠ "传播价值"（两个维度，都要报给用户）。
4. Event completeness 比调分重要。
5. Chapter/Story 是上下文结构，**不是硬过滤器**。
6. Event/Cluster/Judge 等内部概念只进 Developer Mode。
7. 普通用户的理解模型：Video → Chapter → Story → 推荐剪辑。
8. Grade 与 Recommendation 解耦（D-041）。
9. UI 绝不能显示其他视频的结构数据（D-044/045，历史事故）。
10. 真实用户人工判断 > 模型自评。
11. 不为重构而重构已验证稳定的核心（analysis/ 主链尤其如此）。
12. 普通界面不露 S/A/B/C/D 字母（D-044）。

---

## 12. 构建 / 测试 / 发布（真实命令，Windows）

环境：Windows + Python 3.13（venv 在 `live_clipper/.venv`）；关键依赖 faster-whisper、ctranslate2、imageio-ffmpeg、PySide6、PyInstaller、requests、DeepSeek 用 REST（`requests`，无 SDK）。

```bash
# 开发态（仓库根 = 开发态程序目录；用户数据 = %LOCALAPPDATA%\AILiveClipper）
./.venv/Scripts/python desktop_app.py                 # 桌面版
./.venv/Scripts/streamlit run ui.py                   # 网页版（8501）
LIVE_CLIPPER_SMOKE=1 QT_QPA_PLATFORM=offscreen ./.venv/Scripts/python desktop_app.py   # 打包自检

# 测试（全部离线，除注明）
./.venv/Scripts/python test_desktop_smoke.py          # 52 项界面/数据
./.venv/Scripts/python test_desktop_e2e.py            # 24 项 真跑 ASR（~90s，可 --long）
./.venv/Scripts/python test_desktop_progress.py       # 34 项 进度协议
./.venv/Scripts/python test_model_sources.py          # 12 项 下载多源（--net 真连镜像）
./.venv/Scripts/python test_v040_step{1..7}.py        # 核心回归 23/21/24/17/11/24/20
./.venv/Scripts/python test_ui_selftest.py            # 15；test_v045_asr_errors.py 18

# 打包（~3 分钟；本机沙箱可能拦批量删除，需提权）
./.venv/Scripts/python build_desktop.py               # 全量：卸载器+主程序+payload+Setup
./.venv/Scripts/python build_desktop.py --skip-app    # 只重打 payload+Setup（卸载器改动时）
# 产物：dist_setup/AI直播切片助手_Setup.exe（+ AILiveClipper_Setup.exe 英文名副本）

# 安装/卸载/发布验收
./.venv/Scripts/python packaging/verify_install.py            # 33 项（模拟安装+实机启动）
./.venv/Scripts/python packaging/test_install_uninstall.py [--purge-test]   # 35 项全流程
./.venv/Scripts/python packaging/setup_app.py --selftest      # 安装器自检
```

- **API Key**：`DEEPSEEK_API_KEY` 环境变量优先，其次工作区 `api_key.txt`。**api_key.txt 永不入库**（.gitignore 已含）；仓库里若有历史残留不得复制到新分支文档。
- 日志：安装 `%TEMP%\AILiveClipper_setup.log`（装完复制进安装目录 setup.log）；启动 `logs/desktop_startup.log`；卸载 `%TEMP%\AILiveClipper_uninstall.log`。
- 发布流程：跑完全部测试 → build_desktop.py → verify_install → test_install_uninstall（可选 --purge-test）→ 人工双击走一遍 → commit + tag `v0.5.x` → push --follow-tags。

---

## 13. Git 状态与可信基线

- 分支 `master`，HEAD `a6f6b8a`（v0.5.3），**工作树干净，与 origin/master 完全同步**（截至 2026-09-12 18:00）。
- tags：`MVP-v0.1 v0.2.2 v0.3 v0.4.1 v0.5.0 v0.5.1 v0.5.2 v0.5.3`（另有历史过程 tag）。
- **可信基线 = a6f6b8a / v0.5.3**。不存在未推送提交。
- 版本号定义处：`desktop/__init__.py`（APP_VERSION，当前 "0.5.2"——**注意：包已是 v0.5.3 内容但 APP_VERSION 字符串落后一个小版本，下一版一起改**）与 `packaging/setup_app.py`（"0.5.2"，同样待同步为 0.5.3）。
- 开发机注意：仓库内 `api_key.txt`、`models/`、`videos/`、`projects/`、`dist*`、各类 `*_report.txt` 均被 .gitignore 忽略或属本地产物，不要提交。
- 近期关键 commit：`4aca2d1`（镜像源）、`278f4eb`（emit 信号名）、`a6f6b8a`（下载↔识别接通 + 函数名覆盖修复 + 卸载文案）。

---

## 14. 绝对不要推翻的决策（黑名单）

- **D-030** 本地规则绝不删候选；**D-035** 拆分用候选自身边界；**D-032** 事件去重阈值。
- **D-036/D-024** 评分体系（SCORE_V3_WEIGHTS 30/25/20/15/10；S≥90/A≥80/B≥60/C≥50；负面清单封顶 B）。
- **D-041** 评分与推荐解耦；**D-044** 界面不露字母。
- **D-045** Chapter/Story 现算 + 禁固定样例；**Chapter/Story 是软边界**。
- **D-046** ASR 错误分层 + 模型离线优先；**D-047** 目录分离；**D-048** Provider 抽象；**D-049** 模型不分发。
- **D-050** 真实进度禁假动画；**D-051** 不阻塞主线程 + 失败必留日志。
- 冻结的实验能力：A1/A2/A3/B1（见 `docs/HANDOVER_20260910.md`）。

## 15. 新 Agent 的阅读顺序

1. `CURRENT_STATE.md` → 2. 本文档 → 3. `docs/DECISIONS.md`（只看标题+红线） → 4. `pipeline.py` + `analysis/__init__.py`（主链） → 5. `desktop/services/tasks.py` + `desktop/ui/main_window.py` → 6. `packaging/test_install_uninstall.py`（验收标准即规格） → 7. 需要历史细节再翻 `docs/HANDOVER_20260910.md` / `DEVELOPMENT_LOG.md` / `CHANGELOG.md`。

## 16. 当前最重要的 3 个 TODO

1. **干净 Windows 全流程复测**：装新包 → 模型下载（small 464MB 走镜像）→ 导入视频 → 识别 → AI 分析 → 卸载；把问题反馈回来。
2. **真实视频全流程出一份结果**：导入 → 识别 → AI 分析 → 推荐剪辑，人工看推荐质量（这是唯一能验证"理解"是否达标的办法）。
3. **修 Story 分割精度（O-001）与 D-040 跨 Story 再合并**：Story 间隙漏事件（ev-011 案例）是已知最大质量损失点。

---

*交接审计（2026-09-12）：按"仅凭本文档 + 仓库"自检通过——构建/测试命令均为仓库现行命令；所有"已证明无效方案"均给出代码或 PoC 产物位置；人工结论仅转述未改写；当前架构与桌面状态逐项对照过代码与测试输出。*
