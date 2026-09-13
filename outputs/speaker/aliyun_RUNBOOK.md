# 阿里云 Speaker 真实效果验证 —— 操作手册（你自己跑）

> 前置结论：**当前环境三个凭据全部未设置**，阿里云接口只吃「公网可访问音频 URL」，
> 本地 fixture 不能直接送进去。所以需要 ①凭据 ②把音频传上公网（本手册用内置 OSS 上传）。
> 本手册的脚本已就绪、`oss2` 已装好（2.19.1），离线链路已用 dry-run 验证通过。

---

## 0. 一次性准备（只做一次）

```bash
# 进入项目
cd "D:/Agent/ai切片助手/live_clipper"
```

---

## 1. 设置环境变量（Git Bash 示例）

需要 **7 个**变量 = 阿里云 3 个（调用/上传都用）+ OSS 4 个（上传用）。

```bash
# ---- 阿里云智能语音（必填 3 个）----
export ALIYUN_ACCESS_KEY_ID="你的AccessKeyId"
export ALIYUN_ACCESS_KEY_SECRET="你的AccessKeySecret"
export ALIYUN_APP_KEY="你的智能语音项目AppKey"

# 可选（默认 cn-shanghai，一般不用设）
export ALIYUN_REGION_ID="cn-shanghai"

# ---- OSS 上传（必填 4 个）----
# 若 OSS 与阿里云用同一对 AK/SK，前两个可省（脚本会自动回退到 ALIYUN_*）
export OSS_ACCESS_KEY_ID="你的OSS-AccessKeyId"
export OSS_ACCESS_KEY_SECRET="你的OSS-AccessKeySecret"
export OSS_ENDPOINT="oss-cn-shanghai.aliyuncs.com"   # 注意：不要带 https://
export OSS_BUCKET="你的bucket名"
```

PowerShell 版本：

```powershell
$env:ALIYUN_ACCESS_KEY_ID="你的AccessKeyId"
$env:ALIYUN_ACCESS_KEY_SECRET="你的AccessKeySecret"
$env:ALIYUN_APP_KEY="你的智能语音项目AppKey"
$env:OSS_ACCESS_KEY_ID="你的OSS-AccessKeyId"
$env:OSS_ACCESS_KEY_SECRET="你的OSS-AccessKeySecret"
$env:OSS_ENDPOINT="oss-cn-shanghai.aliyuncs.com"
$env:OSS_BUCKET="你的bucket名"
```

> ⚠️ **Bucket 要求**：读写权限、且音频 URL 需公网可访问（公共读，或已配好可匿名 GET 的权限）。
> 阿里云录音文件识别的 `file_link` **必须能被阿里云服务端拉取到**，私有 bucket 会失败。

**去哪拿？**
- **AccessKey**：阿里云控制台右上角头像 → AccessKey 管理 → 创建（建议 RAM 子账号 + 最小权限）。
- **AppKey**：智能语音交互控制台 → 项目 → 创建项目（类型选「录音文件识别」）→ 项目详情里的 **Appkey**。
- **OSS**：OSS 控制台 → 创建 Bucket（区域建议与 region 一致，如 cn-shanghai）→ 拿 Endpoint 与 Bucket 名。

---

## 2. 一键跑（推荐）

```bash
# 从项目根目录进入 PoC 目录
cd poc/audio_understanding

# 内置 OSS 上传 + 调用阿里云 + 评估 + 生成报告
../../.venv/Scripts/python.exe bench_aliyun.py --oss-upload
```

它会自动：
1. 把两个 fixture 上传到 `oss://<bucket>/bench/benchmark_t2_*.wav`
2. 调 `speaker/aliyun.py` 识别（SubmitTask → 轮询 GetTaskResult）
3. 落盘：原始 API 返回 + 标准 speaker JSON
4. 用**与 CAM++ 完全相同的协议**评估（主容差 ±1.5s）
5. 生成报告

产物位置：

```
outputs/speaker/aliyun/raw/<key>.raw.json          # 原始 API 返回
outputs/speaker/aliyun/unified/<key>.speaker.json  # 标准 speaker JSON
outputs/speaker/aliyun/benchmark_eval.json         # 评估明细
outputs/speaker/aliyun_benchmark_report.md         # 报告
```

---

## 3. 备选：音频已在公网（不用 OSS）

```bash
cd poc/audio_understanding
../../.venv/Scripts/python.exe bench_aliyun.py \
    --audio-url-base https://你的bucket.oss-cn-shanghai.aliyuncs.com/bench
```

（脚本按 `<base>/benchmark_t2_0274_0360.wav`、`<base>/benchmark_t2_2630_2685.wav` 拼 URL。）

---

## 4. 离线自检（不联网，随时可跑）

```bash
cd poc/audio_understanding
../../.venv/Scripts/python.exe bench_aliyun.py --dry-run
```

用合成假数据走通全流程，确认脚本与评估协议正常（不耗额度、不需凭据）。

---

## 5. 跑完后

把以下内容贴回给我，我做分析与对比：
- 控制台输出的 3 行 `[key/aliyun] ... count X/Y ... switch R=... P=... attribution=...`
- 或直接给我 `outputs/speaker/aliyun_benchmark_report.md` 内容

---

## 6. 常见报错对照

| 报错 | 原因 | 解决 |
|---|---|---|
| `缺少环境变量：ALIYUN_*` | 阿里云凭据没设 | 按 §1 设好（当前 shell 内 export） |
| `--oss-upload 需要 OSS_*` | OSS 变量不全 | 补上 `OSS_ENDPOINT` / `OSS_BUCKET` |
| `SubmitTask 失败：Code=...` | AppKey 错 / 项目未开通录音文件识别 / AK 权限不足 | 核对 AppKey 与服务开通状态 |
| `HTTP 403` / 拉取失败 | bucket 私有，阿里云拉不到音频 | bucket 设公共读，或给音频设匿名可读 |
| `识别任务失败` | 音频格式/采样率不被接受 | wav 一般 OK；可试转 mp3 |
| `查询超时` | 排队久 | 加大 `--poll-timeout`（如 3600） |

---

## 附：本次为何没直接跑真实调用

- 三个 `ALIYUN_*` 环境变量**均为未设置**，且项目内**无 `.env` 文件**。
- 阿里云录音文件识别**不支持本地文件**，两个 fixture 都在本地，必须先上传公网。
- 真实调用会**消耗阿里云识别额度**，且需用户自有账号凭据 —— 按项目约定「真实 API 调用需用户明确要求」。
