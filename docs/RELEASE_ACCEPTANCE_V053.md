# AI Live Clipper v0.5.3 发布验收记录

> 验收日期：2026-09-14<br>
> 发布级别：Release Candidate baseline<br>
> 平台：Windows x64

## 1. 验收范围

本轮只验证 v0.5.3 既有能力的发行状态，不增加功能，不修改视频处理、ASR、AI 分析、纠错或 Speaker 业务逻辑。

验收覆盖：

- PyInstaller 冻结程序。
- Windows 安装、重复安装与升级路径。
- DKN Brand Reveal、System Initialization、Welcome Setup 和主窗口。
- 首次启动状态保存与二次启动分流。
- 100%、125%、150% DPI 布局。
- 标准用户权限与用户数据目录。
- 核心业务模块导入。

## 2. 测试环境

| 项目 | 环境 |
|---|---|
| 操作系统 | Windows 10 22H2 x64 |
| 用户权限 | 标准用户，无管理员运行要求 |
| Python 开发环境 | Python 3.14.7 x64 |
| 桌面框架 | PySide6 / Qt Quick / QML |
| 打包方式 | PyInstaller |
| 安装程序 | Windows EXE 安装器 |
| DPI | 100%、125%、150% |

## 3. 安装与启动测试

| 验收项 | 结果 |
|---|---|
| 全新安装后启动冻结程序 | 通过 |
| DKN Brand Reveal 播放与进入交互 | 通过 |
| System Initialization 六项检测展示 | 通过 |
| Welcome Setup 五步首次引导 | 通过 |
| 完成或跳过后保存首次启动状态 | 通过 |
| 保留状态后的二次启动直接进入主界面 | 通过 |
| 同版本重复安装 | 通过 |
| 已安装版本升级覆盖 | 通过 |
| 异常提示与非阻塞状态展示 | 通过 |

首次启动数据仅写入用户目录：

```text
%LOCALAPPDATA%\AILiveClipper
```

安装目录不保存 API Key、首次启动状态或运行日志。

## 4. DPI 验收

100%、125%、150% 缩放比例均完成截图检查：

- DKN 动画保持正确比例。
- 字体无明显截断或重叠。
- 圆角窗口和边框渲染正常。
- 初始化卡片布局正常。
- Welcome Setup 按钮和内容区域没有错位。
- 主窗口三栏和状态区域保持可用。

## 5. 回归与安全

- P0/P1 UI 与首次启动测试：27 项通过。
- 安装升级专项测试：通过。
- `pipeline`、`asr`、`analysis`、`correction`、`speaker` 导入检查通过。
- 冻结程序中的 QtSvgWidgets 与资源加载通过。
- 真实 API Key、密码、本地模型、测试媒体、日志、缓存和安装包均不进入源码仓库。

## 6. 已知限制

1. `correction/` 与 `speaker/` 作为独立能力模块保存，尚未全部接入桌面生产流程。
2. 本地 ASR 质量和速度取决于用户设备及已安装模型。
3. 云端 AI 与云端 Speaker 验证需要用户自行提供凭据和可访问的服务环境。
4. v0.5.3 提供内容理解、候选片段和粗剪基础数据；完整视频导入、高光展示与粗剪导出闭环属于后续版本范围。
5. 安装包不提交到源码仓库，应作为 GitHub Release Asset 单独发布。

## 7. 验收结论

AI Live Clipper v0.5.3 已完成品牌桌面外壳、首次启动体验、核心分析架构和 Windows 发行链路验收，可以作为 Release Candidate 开发基线冻结。
