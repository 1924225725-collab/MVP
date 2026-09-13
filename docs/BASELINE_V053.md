# AI Live Clipper v0.5.3 开发基线

> 基线日期：2026-09-14<br>
> 发布状态：Release Candidate baseline<br>
> 产品品牌：DKN / AI Live Clipper<br>
> 开发者：夜雨声烦

## 1. 版本范围

当前源码、桌面应用和 Windows 安装程序统一使用版本 **0.5.3**。本基线冻结 P0 品牌系统、P1 首次启动体验以及已有核心业务架构，不包含 v0.5.4 或 v0.6 的功能开发。

## 2. 已完成能力

### P0：品牌与桌面外壳

- DKN SVG 路径书写启动动画。
- 夜雨声烦签名与 AI Live Clipper 品牌展示。
- 无边框、圆角、深色桌面窗口。
- 三栏工作区、任务进度区和状态区基础结构。
- 主窗口低调开发者署名。

### P1：首次启动体验

- `setup_state` 用户状态判断与安全保存。
- 六项 System Initialization 检测。
- 中文 Welcome Setup 五步引导。
- 本地模式与 AI 增强模式选择。
- 完成、稍后设置和跳过流程。
- 已配置用户二次启动直接进入主界面。

### 核心工程能力

- FFmpeg 媒体探测和音频提取。
- faster-whisper 本地 ASR 与统一识别接口。
- AI 高光分析、评分、推荐和内容结构生成。
- 独立 ASR 纠错模块。
- Speaker Provider 与评估基线。
- PySide6 桌面端、Streamlit 网页端和 CLI 入口。
- PyInstaller 冻结构建与 Windows 安装程序。

## 3. 已验证功能

- Windows 10 22H2 标准用户安装和启动。
- 全新安装、重复安装与升级路径。
- 首次启动：Brand Reveal → Initialization → Welcome Setup → 主界面。
- 二次启动：Brand Reveal → 主界面。
- 100%、125%、150% DPI 布局。
- P0/P1 UI 与状态测试。
- 核心业务模块导入与离线测试。

完整记录见 [`RELEASE_ACCEPTANCE_V053.md`](RELEASE_ACCEPTANCE_V053.md)。

## 4. 当前目录结构

```text
live_clipper/
├── asr/                  # 生产语音识别
├── analysis/             # 高光与内容结构分析
├── desktop/              # 桌面 UI、服务和后台任务
├── correction/           # 独立纠错模块
├── speaker/              # 说话人识别 Provider
├── poc/                  # 实验、评估和人工标注
├── docs/                 # 架构、决策、基线和报告
├── packaging/            # Windows 构建与验收
├── pipeline.py           # 生产流程编排
├── desktop_app.py        # 桌面入口
├── ui.py                 # Streamlit 入口
├── main.py               # CLI 入口
├── requirements.txt      # 运行依赖
└── requirements-dev.txt  # 开发与打包依赖
```

详细职责见 [`../PROJECT_STRUCTURE.md`](../PROJECT_STRUCTURE.md)。

## 5. 数据与发行边界

- API Key、密码和其他凭据不得进入源码或文档。
- 用户设置、首次启动状态和日志写入 `%LOCALAPPDATA%\AILiveClipper`。
- 本地模型、测试媒体、运行输出、虚拟环境和构建缓存不提交。
- Windows 安装包仅作为 GitHub Release Asset 发布。
- 人工标注的 JSON/TXT 基准数据保留；对应的大型音视频夹具不提交。

## 6. 已知限制

1. `correction/` 与 `speaker/` 尚未全部接入桌面生产流程。
2. 本地识别依赖用户设备能力和可用模型。
3. 云端 AI 与 Speaker 真实服务需要用户自行配置凭据。
4. v0.5.3 尚未形成视频导入、高光展示与粗剪导出的完整 MVP 闭环。

## 7. 下一阶段方向

- v0.5.4：UX 优化。
- v0.6：视频导入、高光展示和粗剪导出的 MVP 闭环。

以上仅作为 Roadmap；本基线不提前包含后续版本功能。
