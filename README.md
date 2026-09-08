# AI 直播切片助手

把直播录像（MP4）自动转换成**带时间戳的文字稿**，为后续找高光片段、做切片打基础。

## 阶段一目标

MP4 视频 → 提取音频 → 语音识别 → 带时间戳的文字稿

## 目录结构

```
live_clipper/
├── main.py            # 程序入口（目前：扫描视频 + 提取音频）
├── config.py          # 配置面板（选 local 还是 api，都在这改）
├── README.md          # 项目说明（本文件）
├── .venv/             # 项目专属 Python 环境（虚拟环境），ffmpeg 装在这里面
├── asr/               # 语音识别模块（可插拔：本地/云端随时切换）
│   ├── __init__.py    # 工厂函数 create_recognizer()：按配置造识别器
│   ├── base.py        # 公约：Segment 统一格式 + 识别器统一接口
│   ├── local_whisper.py  # 本地 Whisper（步骤 3 实现）
│   └── cloud_api.py      # 云端 API（接口已预留，以后实现）
├── videos/            # 存放要处理的 MP4 直播录像
├── audio/             # 存放从视频里提取出的音频
└── transcripts/       # 存放生成的带时间戳文字稿
```

## 语音识别模块设计（可插拔架构）

```
main.py  ──只问一句──▶  config.py（你选 local / api）
                            │
                    asr/__init__.py  create_recognizer()
                            │（按配置二选一）
              ┌─────────────┴─────────────┐
        local_whisper.py            cloud_api.py
              └─────────────┬─────────────┘
                     都返回同一种格式：
              [Segment(start, end, text), ...]
                            │
                     写入 transcripts/
```

三条设计原则：

1. **公约统一**（asr/base.py）：每个识别器都必须实现 `transcribe(音频路径) → [Segment, ...]`。
   Segment 用秒数记时间，不管来源是本地模型还是云端，格式完全一样。
2. **工厂分发**（asr/\_\_init\_\_.py）：main.py 永远只调 `create_recognizer()`，
   不关心背后是谁。以后加第三种识别方式（比如讯飞），只要新写一个文件 + 工厂里加一行。
3. **配置切换**（config.py）：换识别方式 = 改一个单词，业务代码零改动。

> 目录和文件名用英文，是为了避免中文路径在后续视频处理工具里出现编码问题。

## 怎么运行

1. 按 Win 键，输入 `PowerShell`，回车打开
2. 进入项目目录：
   ```
   cd C:\Users\admin\WorkBuddy\20260908235421\live_clipper
   ```
3. 用项目自带的 Python 运行程序：
   ```
   .\.venv\Scripts\python main.py
   ```
4. 正常会依次看到：启动成功 → 找到几个视频 → 每个视频的音频提取结果

## 网页版（v0.2 新增）

**最简单的启动方式：双击项目文件夹里的 `start_webui.bat`**，浏览器会自动打开。

等价的命令行方式（在 live_clipper 文件夹里）：
```
.\.venv\Scripts\streamlit run ui.py
```

页面功能：上传 MP4 → 点「开始分析」→ 查看文字稿 + 高光卡片（评分/时间/标题/理由）
→ 下载 highlights.json。

**API Key 在网页左侧边栏填**（粘贴 → 点「💾 保存」即可，存到本机 api_key.txt，
已被 .gitignore 排除不会上传）。命令行用户也可以继续用环境变量 DEEPSEEK_API_KEY，
两者都设了时环境变量优先。

命令行版和网页版共用同一套核心代码（pipeline.py）。

## 关于 .venv（为什么运行命令变了）

`.venv` 是「虚拟环境」——这个项目专属的 Python 工具箱。装在里面的库只归本项目用，
不会影响电脑上其他项目。以后给本项目装任何库，都这样装：

    .\.venv\Scripts\python -m pip install 库名

## 开发进度

- [x] 步骤 0：创建项目结构 + 检查 Python 环境（Python 3.14.7）
- [x] 步骤 1：扫描 videos/ 文件夹，列出里面的视频文件（只认 .mp4，其他文件忽略）
- [x] 步骤 2：从视频提取音频（保存到 audio/，16kHz 单声道 MP3，由 ffmpeg 完成）
- [x] 步骤 2.5：语音识别模块架构设计（可插拔：local/api，接口已定，实现为空）
- [x] 步骤 3：实现 LocalWhisperRecognizer（faster-whisper，small 模型，CPU int8），生成带时间戳文字稿
- [x] 步骤 4：analysis 高光分析模块（DeepSeek API + 成本控制四闸门），待设置 API Key 后实测
- [x] v0.2：pipeline.py 核心流程抽离 + ui.py 网页版（Streamlit），命令行版行为不变
- [ ] 以后：实现 CloudApiRecognizer（云端 API）
