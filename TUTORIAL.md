# AI 直播切片助手 · 使用教程

> 从零到跑通，只需要 5 分钟。
> （v0.2.2 · 开发者：夜雨声烦）

---

## 一、这个工具是干嘛的？

把一段直播录像（MP4），自动变成：

1. **带时间戳的文字稿**（本地 AI 识别，免费）
2. **高光片段推荐**（云端 DeepSeek 分析，标出哪几段适合剪成切片、为什么、起什么标题）

```
你的 MP4 ──▶ 提取音频 ──▶ 语音识别 ──▶ 文字稿 ──▶ AI 挑高光 ──▶ highlights.json
```

---

## 二、准备（只需一次）

### 1. 装好 Python

电脑上要有 Python 3.10 以上。检查方法：打开 PowerShell 输入
`python --version`，能显示版本号就行。

### 2. 拿一个 DeepSeek API Key（可选，只有"高光分析"这步需要）

1. 打开 https://platform.deepseek.com 注册账号
2. 左侧「API Keys」→ 创建 → 复制 `sk-` 开头的一串
3. 左侧「充值」→ 充 5~10 元（够分析几百个短视频）

> 不想用这步也行：文字稿功能完全本地、完全免费。

---

## 三、安装（只需一次）

在 PowerShell 里：

```powershell
cd 项目文件夹路径
python -m venv .venv
.\.venv\Scripts\python -m pip install imageio-ffmpeg faster-whisper requests streamlit
```

（第一次跑语音识别时会自动下载 Whisper small 模型约 460MB，只需一次，
之后永久离线可用。）

---

## 四、日常使用（推荐：网页版）

### 启动

**双击项目文件夹里的 `start_webui.bat`**，浏览器会自动打开
`http://localhost:8501`。

（备用启动法：PowerShell 里运行 `.\.venv\Scripts\streamlit run ui.py`）

### 填 API Key（首次）

页面左侧边栏 → 「🔑 DeepSeek API Key」→ 粘贴 → 点「💾 保存」。
钥匙只存在你自己电脑的 api_key.txt 里，页面显示打码，可随时删除。

### 分析视频

1. 拖一个 MP4 到上传框
2. 点「🚀 开始分析」
3. 盯着四步清单逐个点亮：提取音频 → 语音识别 → 生成文字稿 → AI 高光分析
   （一分钟左右的视频全程约 1~2 分钟；首次会先下载模型，耐心等）
4. 看结果：
   - **文字稿**：每句话带 [开始时间 - 结束时间]
   - **高光卡片**：评分（1-10）、时间段、推荐标题、推荐理由，按分数从高到低排
   - 点「⬇️ 下载 highlights.json」可以把结果存走
   - 「🖥️ 处理日志」里能看到本次 AI 用量和花费预估（通常不到一分钱）

### 关闭

关掉那个黑色命令行窗口即可（或按 Ctrl + C）。

---

## 五、命令行版（适合批处理）

```powershell
.\.venv\Scripts\python main.py
```

会自动处理 `videos/` 文件夹里的所有 MP4：
文字稿存到 `transcripts/`，音频存到 `audio/`。

想单独分析高光：把 API Key 设进环境变量后运行
`.\.venv\Scripts\python analyze.py`，结果输出 `highlights.json`。

---

## 六、常见问题

| 现象 | 原因 / 解法 |
|---|---|
| 提示没找到 DEEPSEEK_API_KEY | 网页左侧边栏填一下钥匙就行，不影响前 3 步 |
| 识别出来有错字 | 正常，直播嘈杂环境 + small 模型的水平；在意准确率可把 config.py 里的 WHISPER_MODEL_SIZE 改成 "medium"（更大更准更慢） |
| 首次分析特别慢 | 在下载 Whisper 模型（约 460MB），只有一次 |
| 双击 bat 闪退 | 先打开 PowerShell 手动跑 `.\.venv\Scripts\streamlit run ui.py` 看报什么错 |
| 换电脑用 | 重新做一遍第三节「安装」，然后 `git clone` 本仓库 |

---

## 七、项目结构速览

```
live_clipper/
├── main.py        # 命令行入口
├── ui.py          # 网页版入口
├── pipeline.py    # 核心流水线（两个入口共用）
├── config.py      # 配置面板（识别方式、模型大小、成本上限）
├── analyze.py     # 单独跑高光分析
├── asr/           # 语音识别模块（本地 Whisper / 云端 API 可切换）
├── analysis/      # DeepSeek 高光分析模块
├── videos/        # 放要处理的 MP4
├── audio/         # 提取出的音频（自动生成）
└── transcripts/   # 带时间戳文字稿（自动生成）
```
