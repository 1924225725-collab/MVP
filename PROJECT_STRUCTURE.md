# PROJECT_STRUCTURE —— AI 直播切片助手 · 目录结构说明

> 本文档记录**真实的**目录结构、各目录职责、以及哪些内容应进仓库。
> 最后更新：2026-09-13
> 配套文档：`docs/CLEANUP_REPORT_FINAL.md`（体积分析与清理建议）

---

## 0. 一句话概览

输入一段直播视频 → 本地 ASR 转文字 → 纠错 → DeepSeek 分析高光 → 输出可剪辑的时间段。
支持 **桌面版（PySide6）** 与 **网页版（Streamlit）** 两种入口，可打包为 Windows 安装包。

---

## 1. 顶层结构

```
<workspace>\                   ← workspace 根
├── live_clipper\              ← 项目本体（git 仓库在这里）
└── .workbuddy-ai\             ← 工具元数据（记忆/技能），不属于项目

live_clipper\
├── .gitignore                 ← 忽略规则（已按体积+敏感度分类）
├── requirements.txt           ← 运行时依赖
├── requirements-dev.txt       ← 开发/打包依赖
├── PROJECT_STRUCTURE.md       ← 本文件
├── README.md                  ← 使用说明
├── TUTORIAL.md                ← 上手教程
│
├── CODEX_HANDOFF.md           ← 交接文档（早期）
├── AGENT_HANDOFF.md           ← 交接文档（当前，最新）
├── CURRENT_STATE.md           ← 状态快照
│
├── docs\                      ← 【文档】决策记录、审计报告、方案
│   ├── DECISIONS.md           ← ⭐ 设计红线（改代码前必读）
│   ├── CHANGELOG.md           ← 版本变更
│   ├── DEVELOPMENT_LOG.md     ← 开发日志
│   ├── ARCHITECTURE.md        ← 架构说明
│   ├── VERSION_PLAN.md        ← 版本规划
│   ├── CLEANUP_REPORT_FINAL.md← 本次整理勘察报告
│   ├── screenshots\           ← 界面截图
│   └── ...（共 30+ 篇专题文档）
│
├── main.py                    ← 【入口】CLI 主程序
├── desktop_app.py             ← 【入口】桌面版主程序
├── ui.py                      ← 【界面】Streamlit 网页版
├── start_webui.bat            ← 【入口】网页版启动脚本
├── build_desktop.py           ← 【构建】桌面版打包脚本
├── app_paths.py               ← 【基础】程序数据/用户数据路径（D-047）
├── config.py                  ← 【基础】配置管理
├── errors.py                  ← 【基础】分级错误（ProcessError，D-046）
├── stages.py                  ← 【基础】真实进度的阶段定义（D-050）
├── pipeline.py                ← 【核心】主流程编排
│
├── asr\                       ← 【模块】语音识别
├── analysis\                  ← 【模块】高光分析
├── correction\                ← 【模块】ASR 纠错（后处理）
├── speaker\                   ← 【模块】说话人分离（实验）
├── desktop\                   ← 【模块】桌面版 UI 组件
├── audio\                     ← 【数据】ASR 抽取的音频
├── structures\                ← 【缓存】文稿结构缓存
├── transcripts\               ← 【数据】ASR 文字稿
├── videos\                    ← 【数据】测试视频素材
├── outputs\                   ← 【产物】运行输出（仅 speaker/aliyun_RUNBOOK.md 入库）
├── logs\                      ← 【产物】运行日志
├── projects\                  ← 【产物】项目数据（开发态）
├── models\                    ← 【产物】模型文件（开发态）
├── temp\                      ← 【临时】
├── poc\                       ← 【实验】PoC 与基准评测
├── packaging\                 ← 【构建】安装包制作
├── _test_media\               ← 【临时】验收用媒体
├── build\ / dist\ / dist_setup\ ← 【构建产物】不入库
└── .venv\ / .venv-*-poc\      ← 【虚拟环境】不入库
```

---

## 2. 核心模块职责

### 2.1 业务模块

| 目录 | 职责 | 关键文件 | 可改？ |
|---|---|---|---|
| `asr\` | 语音识别抽象层 | `provider.py`（Provider 抽象，D-048）、`local_whisper.py`、`cloud_api.py`、`registry.py`、`base.py` | ⚠️ 谨慎 |
| `analysis\` | 高光分析（DeepSeek + 本地规则） | `__init__.py`（主入口 `analyze_transcript_v2`）、`deepseek_client.py`、`event_scanner.py`、`chunker.py`、`budget.py`、`prompt_builder.py`、`dictionary.py`、`story_context.py`、`chapter_story.py`、`event_cluster.py`、`feedback.py` | ⚠️ 谨慎 |
| `correction\` | ASR 后处理纠错（独立模块） | `corrector.py`、`scorer.py`、`converter.py`、`pipeline_step.py`、`dictionary\`、`README.md` | ✅ 可独立开发 |
| `speaker\` | 说话人分离（实验性） | `aliyun.py`、`volcengine.py`、`base.py`、`config.py` | ✅ 实验 |
| `desktop\` | 桌面版 UI 组件 | `ui\`、`services\`、`workers.py`、`theme.py` | ✅ UI 层 |

### 2.2 `correction\` 模块详解（当前重点）

```
correction\
├── README.md                ← ⭐ 模块完整说明（词库格式/评分公式/安全闸门）
├── __init__.py              ← 对外导出
├── dictionary\              ← 转换后的词库（程序用）
│   ├── converted_hot_words.json   (92 条 / 393 别名)
│   ├── converted_people.json      (696 条 / 2298 别名)
│   ├── converted_books.json       (0 条，源本为空)
│   ├── converted_movies.json      (250 条 / 196 别名)
│   └── raw_sources\               ← 🔴 用户原始词库快照（勿删！）
├── converter.py             ← 原始 txt → JSON 转换
├── corrector.py             ← 检测 → 决策 → 替换
├── scorer.py                ← 四维加权置信度评分
├── pipeline_step.py         ← 接入测试流程的独立步骤
├── run_pipeline_test.py     ← 端到端测试运行器
├── test_minimal.py          ← 24 项最小测试（A替换/B不误伤/C灰区/D完整性/E一致性）
└── test_pipeline_step.py    ← 15 项流程接入测试
```

**设计要点**：纠错是「候选检测 → 上下文判断 → 置信度评分 → 三档决策」，
**不是暴力字符串替换**。评分公式与安全闸门详见 `correction/README.md`。

### 2.3 基础层（改动影响面最大）

| 文件 | 职责 | 相关决策 |
|---|---|---|
| `app_paths.py` | 程序资源 vs 用户数据分离 | D-047 |
| `errors.py` | 分级错误 `ProcessError` | D-046 |
| `stages.py` | 真实进度阶段（禁止假进度） | D-050 |
| `pipeline.py` | 主流程：抽音频 → ASR → 纠错 → 分析 → 输出 | — |
| `config.py` | 配置读写与校验 | — |

---

## 3. 数据流向

```
videos\*.mp4
    │  ① 抽取音频（ffmpeg）
    ▼
audio\*.mp3
    │  ② ASR 识别（asr\，本地 faster-whisper 或云端）
    ▼
transcripts\*.txt              ← 原始文字稿（只读保留）
    │  ③ 纠错（correction\pipeline_step）
    ▼
transcripts\corrected\*.corrected.txt   + *.correction_report.json
    │  ④ 高光分析（analysis\，读 corrected 稿）
    ▼
outputs\  /  highlights_v2.json
```

**关键约定**：
- 原始文字稿**永不覆盖**，纠错结果单独成文。
- 纠错报告记录：原文本 / 修正文本 / 修改位置 / 置信度。
- 时间戳 `[mm:ss - mm:ss]` 在纠错中**逐字节不变**。

---

## 4. 文件归属规则（什么该进仓库）

### ✅ 应提交（源码与文档）

| 类型 | 说明 |
|---|---|
| `*.py` | 全部源码（含 poc 与 packaging） |
| `*.md` / `*.txt`（文档类） | 说明、决策、审计报告 |
| `*.json`（配置类） | `models_registry.json`、`custom_dictionary.json`、`correction/dictionary/converted_*.json`、`correction/dictionary/raw_sources/*` |
| `poc/**/fixtures/` | 🔴 **人工标注真值（GT），必须提交，不可重建** |
| `*.spec` / `*.bat` | 构建与启动脚本 |
| `.gitkeep` | 保持空目录结构 |

### ❌ 不应提交（已在 `.gitignore`）

| 类型 | 原因 |
|---|---|
| `.venv/`、`.venv-*/` | 体积大（2.7 GB），每台机器自己装 |
| `build/`、`dist/`、`dist_setup/`、`packaging/build/` | 打包产物（1 GB+），装机时现打 |
| `videos/*`、`audio/*`、`transcripts/*` | 素材与产物，体积大/含个人数据 |
| `poc/*.wav`、`poc/*.mp3`、`poc/*.npy`、`poc/*/outputs/` | 实验中间产物 |
| `api_key.txt`、`.env`、`.env.*` | 🔴 **密钥，绝不能上传** |
| `__pycache__/`、`*.pyc` | 运行缓存 |
| `logs/`、`projects/`、`models/`、`structures/`、`outputs/` | 运行数据（`outputs/speaker/aliyun_RUNBOOK.md` 除外） |
| `*_report.txt`、`highlights*.json`、`feedback.json` | 每次运行都不同的产物 |

---

## 5. 目录体积参考（清理前）

| 目录 | 大小 | 可删除？ |
|---|---|---|
| `.venv-audio-poc/` | 1.40 GB | ✅ 可重建 |
| `.venv/` | 847 MB | ✅ 可重建（但需重下模型） |
| `.venv-pyannote-poc/` | 450 MB | ✅ 可重建 |
| `dist/` | 423 MB | ✅ 可重建 |
| `videos/` | 346 MB | 🔴 **唯一副本，勿删** |
| `packaging/build/` | 294 MB | ✅ 可重建 |
| `dist_setup/` | 276 MB | ✅ 可重建 |
| `poc/` | 167 MB | 🟡 部分（保留 fixtures 与脚本） |
| `build/` | 35 MB | ✅ 可重建 |
| `_test_media/` | 31 MB | ✅ 可重建 |
| 源码 + 文档 | **< 5 MB** | 🔴 项目本体 |

详见 `docs/CLEANUP_REPORT_FINAL.md`。

---

## 6. 开发约定（红线）

1. **改代码前先读 `docs/DECISIONS.md`** —— 里面是历史决策与红线。
2. **不修改核心业务逻辑**：涉及 `asr/` `analysis/` `pipeline.py` 的改动需另开决策记录。
3. **禁止假进度**（D-050）：所有进度必须反映真实阶段。
4. **评分与推荐解耦**（D-041）。
5. **本地规则不删除候选**（D-030）。
6. **原始数据只读**：文字稿、词库快照、用户素材不得原地覆盖。
7. **新模块优先做成独立可测**（参照 `correction/` 的做法：纯标准库 + 独立测试 + 不拖入生产模块）。

---

## 7. 快速上手

```bash
cd <workspace>\live_clipper

# 1) 建环境
python -m venv .venv
.venv\Scripts\activate
# requirements-dev.txt 已包含 requirements.txt
pip install -r requirements-dev.txt

# 2) 冒烟测试（纯标准库，离线可跑，最快）
python correction\test_minimal.py          # 24 项
python correction\test_pipeline_step.py    # 15 项

# 3) 跑一次完整流程
python main.py                             # CLI
python desktop_app.py                      # 桌面版
start_webui.bat                            # 网页版
```

---

## 8. 常见问题

**Q：为什么虚拟环境这么大？**
A：`faster-whisper` + `ctranslate2` + `PySide6` + `onnxruntime` 都是重量级运行时。
`.venv-audio-poc` 还含 torch（Pyannote 评测用），所以单它就有 1.4 GB。

**Q：可以删 `videos/` 吗？**
A：**不建议**。那是测试素材的唯一副本（346 MB），删了无法再跑端到端流程。

**Q：`poc/audio_understanding/fixtures/` 能删吗？**
A：**绝对不能**。里面是人工标注的说话人真值（GT），无法从任何源重建，
删了所有 benchmark 对比都会失效。

**Q：改了代码怎么验证？**
A：先跑 `correction` 的 39 项测试当冒烟，再跑 `test_desktop_smoke.py` 等桌面测试。
