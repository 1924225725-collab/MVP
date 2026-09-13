# speaker/ —— 说话人识别（Diarization）Provider 模块

把「说话人识别」做成一**可替换 Provider**：今天用阿里云智能语音，明天换火山豆包 / pyannote / 本地模型，
上层代码一行都不用改。

> 当前状态：**PoC / 独立模块**。未接入生产流程（不改 ASR、不改 DeepSeek 高光、不改 Story/Event/Recommendation、不改 UI）。

> Provider 现状：**`aliyun`（当前主用）** · `volcengine`（保留，暂停使用）· pyannote（环境已就绪，文件原样保留）

---

## 1. 统一输出格式

任何 Provider 最终都必须吐出这个格式（秒为单位，float）：

```json
[
  {"start": 0,    "end": 5,   "speaker": "spk_0"},
  {"start": 5,    "end": 9.4, "speaker": "spk_1"}
]
```

- `start` / `end`：秒，支持小数
- `speaker`：说话人标识，同一段音频内同名 = 同一个人（`spk_0` / `spk_1` …）

> 铁律：**模型没给出可靠说话人标签时，宁可返回空列表，禁止伪造。**

---

## 2. 文件结构

| 文件 | 职责 |
|---|---|
| `base.py` | 数据契约 `SpeakerTurn` + 抽象基类 `BaseSpeakerProvider` |
| `config.py` | 环境变量读取（钥匙只从环境变量来）+ 安全摘要（打码） |
| `aliyun.py` | **阿里云智能语音「录音文件识别」说话人分离封装（当前主用）** |
| `volcengine.py` | 火山引擎豆包「录音文件识别（大模型版）」说话人分离封装（保留） |
| `test_aliyun.py` | 阿里云本地测试脚本（44 项离线全过；`--live` 可选真实调用） |
| `test_speaker.py` | 火山本地测试脚本（35 项离线全过；`--live` 可选真实调用） |
| `__init__.py` | 对外出口 + Provider 注册表（默认 `aliyun`） |
| `README.md` | 本文件 |

---

## 3. 快速上手（阿里云）

### 3.1 配置密钥（环境变量）

```bash
# Git Bash / Linux
export ALIYUN_ACCESS_KEY_ID="你的AccessKeyId"
export ALIYUN_ACCESS_KEY_SECRET="你的AccessKeySecret"
export ALIYUN_APP_KEY="你的项目AppKey"
# 可选：
export ALIYUN_REGION_ID="cn-shanghai"          # 默认 cn-shanghai
export ALIYUN_FILE_TRANS_HOST=""               # 留空 = 按 region 推导
export ALIYUN_SPEAKER_MAX=""                   # 留空 = 自动判断人数
```

```powershell
# Windows PowerShell
$env:ALIYUN_ACCESS_KEY_ID="你的AccessKeyId"
$env:ALIYUN_ACCESS_KEY_SECRET="你的AccessKeySecret"
$env:ALIYUN_APP_KEY="你的项目AppKey"
```

也可以复制 `.env.example` → `.env` 填好（`.env` 已被 `.gitignore` 排除）。

**去哪拿？**
- **AccessKey**：阿里云控制台右上角头像 → **AccessKey 管理** → 创建（建议用 RAM 子账号 + 最小权限）。
- **AppKey**：**智能语音交互控制台** → 项目 → 创建项目（类型选「录音文件识别」）→ 项目详情里的 **Appkey**。

### 3.2 调用

```python
from speaker import AliyunSpeakerProvider

p = AliyunSpeakerProvider()              # 钥匙自动从环境变量读
ok, why = p.is_available()               # 轻量检查，不联网
print(ok, why)

# 音频是公网可访问 URL（生产推荐）
turns = p.diarize("https://example.com/a.mp3")            # -> [SpeakerTurn, ...]
data  = p.diarize_unified("https://example.com/a.mp3")    # -> list[dict]（统一格式）
```

### 3.3 本地文件怎么办

⚠️ **阿里云这个接口只吃「公网可访问的音频 URL」，不支持直接读本地文件。**

两种办法：

**办法 A（推荐，生产用）**：先上传到**阿里云 OSS**（或任意公网可访问的地址），把 URL 传进来。
注意 URL 只能用域名、不能是 IP、不能含空格 / 中文。

**办法 B（回调钩子）**：给 provider 传一个「本地路径 → URL」的函数，模块自动帮你换：

```python
def my_upload(local_path: str) -> str:
    # 你自己实现：上传到 OSS/OSS/S3/临时文件服务，返回公网 URL
    ...
    return "https://your-bucket.oss-cn-shanghai.aliyuncs.com/uploaded.mp3"

p = AliyunSpeakerProvider(upload_fn=my_upload)
turns = p.diarize("D:/videos/live.mp3")   # my_upload 会被调用
```

> 为什么模块不内置上传？上传属于**存储层**职责，各家方案不同（OSS/TOS/S3/自建）。
> 内置任何一个都会把存储方案焊死，违背「可替换」的设计目标。

### 3.4 用注册表按 id 选引擎

```python
from speaker import build_provider, list_providers, provider_ids

print(provider_ids())        # ['aliyun', 'volcengine']
for info in list_providers():
    print(info)              # 看每个引擎当前可用状态

p = build_provider("aliyun")       # 换引擎只改这个 id
p = build_provider("volcengine")   # 也支持火山
```

---

## 4. 支持的 Provider

| provider_id | 名称 | 形态 | 状态 |
|---|---|---|---|
| `aliyun` | 阿里云智能语音说话人分离 | cloud | ✅ **已实现（当前主用）** |
| `volcengine` | 火山引擎豆包说话人分离 | cloud | ✅ 已实现（保留，暂停使用）|

将来加新引擎 = 写一个 `BaseSpeakerProvider` 子类 + 在 `__init__.py` 的 `_PROVIDERS` 加一行。

---

## 5. 阿里云实现细节（当前主用）

### 走哪个接口

**录音文件识别 OpenAPI**，两阶段异步：

| 阶段 | 地址 |
|---|---|
| 提交 | `POST https://filetrans.<region>.aliyuncs.com/?Action=SubmitTask` |
| 查询 | `POST https://filetrans.<region>.aliyuncs.com/?Action=GetTaskResult` |

`Version` 固定 `2018-08-17`；`RegionId` 默认 `cn-shanghai`，host 不显式配置时按 region 推导为
`filetrans.<region>.aliyuncs.com`。

### 鉴权：RPC 风格签名（HMAC-SHA1）

用 `AccessKeyId` / `AccessKeySecret` 对请求参数签名，**不传 Bearer token**。算法：

1. 参数（除 `Signature` 外）按 key 字典序排列，做 percent-encode 后拼成 `k=v&k=v`
   - percent-encode：先 UTF-8，再 quote；空格 → `%20`（不是 `+`）；`*` → `%2A`；`~` 不编码
2. `StringToSign = METHOD & percentEncode("/") & percentEncode(canonicalQuery)`
3. `Signature = Base64(HMAC-SHA1(AccessKeySecret + "&", StringToSign))`
4. 把 `Signature` 作为普通参数一起发出

> ⚠️ **签名覆盖 HTTP 方法**：GET 与 POST 的签名不同，必须与实际发请求的方法一致，否则服务端判 `SignatureDoesNotMatch`。
> 本模块统一用 **POST**（`Task` 参数是 JSON 串，POST 无 URL 长度限制，更稳）。
>
> ✅ 算法已用**阿里云官方文档示例**验证一致（`AK=testid / SK=testsecret / DescribeRegions` → 期望签名 `OLeaidS1JvxuMvnyHOwuJ+uX5qY=`，本实现 GET 下完全匹配）。

### 开启说话人分离的关键参数

`SubmitTask` 的 `Task` 字段（JSON 字符串）：

```json
{
  "appkey": "你的AppKey",
  "file_link": "https://.../a.mp3",
  "version": "4.0",
  "enable_words": true,
  "enable_sample_rate_adaptive": true,
  "enable_speaker_diarization": true,   // ★ 开启说话人分离
  "diarization_enabled": true,          // 兼容旧字段名的等价开关
  "enable_timestamp_alignment": true,
  "speaker_count": 3                    // 可选：ALIYUN_SPEAKER_MAX 设置了才带
}
```

官方说明：说话人分离 **10 人以内效果较好**。

### 返回字段（PascalCase）

`GetTaskResult` 的 `Result.Sentences[]`，每项：

| 字段 | 含义 |
|---|---|
| `BeginTime` / `EndTime` | 句起止时间，**毫秒** |
| `Text` | 该句文本 |
| `SpeakerId` | **说话人编号**（开启分离时才有） |

本模块把 `毫秒 → 秒`、`SpeakerId → spk_N`（数字型）或原样保留（字符串型），并合并相邻同人段。
**找不到 `SpeakerId` 时该句被跳过；整段都没有则返回空列表（绝不伪造）。**

### 任务状态（`StatusText`）

| 状态 | 含义 | 模块行为 |
|---|---|---|
| `SUCCESS` | 成功 | 解析结果 |
| `QUEUEING` / `RUNNING` | 排队中 / 处理中 | 继续轮询（默认 5s 间隔，最长 30min）|
| `FAILED` | 失败 | 抛 `AliyunError`（消息不含密钥）|
| 其它 | 未知 | 抛 `AliyunError`（不静默吞掉）|

---

## 6. 本地测试

```bash
# 阿里云离线结构测试（默认；不联网、不需密钥）
.venv/Scripts/python speaker/test_aliyun.py

# 追加一次真实调用（需 3 个环境变量 + 公网音频 URL；会消耗识别额度）
.venv/Scripts/python speaker/test_aliyun.py --live --audio-url https://example.com/a.mp3

# 火山（保留）离线测试
.venv/Scripts/python speaker/test_speaker.py
```

离线测试覆盖：统一格式契约 / 注册表 / 配置安全（不泄露密钥）/ **RPC 签名（对齐阿里云官方示例）** /
请求构造 / 响应解析与合并 / URL 解析 / 可用性判定 / 异常输入不崩。

当前结果：**阿里云 44 通过 / 0 失败**；火山 35 通过 / 0 失败。

---

## 7. 边界（本模块不做的事）

- ❌ 不修改现有 ASR（`asr/`）
- ❌ 不修改 DeepSeek 高光分析（`analysis/`）
- ❌ 不修改 Chapter / Story / Event / Recommendation
- ❌ 不接入生产 pipeline / 不改 UI
- ❌ 不删除 pyannote 相关文件（`poc/audio_understanding/pyannote_*` 原样保留）
- ❌ 不内置任何对象存储上传方案
- ❌ 配置不硬编码：所有凭据只从环境变量读

---

## 8. 下一步建议

1. **打通真实链路**：拿一个真实直播音频 → 上传到阿里云 OSS（或任意公网存储）→ 跑
   `test_aliyun.py --live --audio-url <URL>` 验证说话人分离实际效果。
   （注：本机当前**未设置** `ALIYUN_*` 环境变量，真实调用尚未执行。）
2. **与人工 GT 对照**：复用 `poc/audio_understanding/fixtures/` 里已有 benchmark 片段与人工标注，
   评估「短插话被长独白吸收」这个 CAM++ 的老问题在阿里云上是否改善（这是本轮核心判定问题）。
3. **确认上传方案**：生产用阿里云 OSS 最顺（同账号、同区域、内网免流量），再实现 `upload_fn`。
4. **Provider 化落地**：确认效果后再谈接入 pipeline（届时只加一个 `speaker_id` 字段，不碰评分逻辑）。
