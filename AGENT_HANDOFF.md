# AGENT_HANDOFF — Audio Understanding PoC 接力交接（2026-09-13 凌晨 更新）

> 范围：Speaker Diarization 路线的两条并行线——
>   **A 线（本轮进行中）**：说话人识别 Provider 化；**当前主用阿里云智能语音**（§7），火山引擎保留暂停
>   **B 线（环境已就绪）**：pyannote 对照轮（环境全绿，等 HF token，见 §3）
> 项目全景交接读 `CODEX_HANDOFF.md`（权威）；决策红线读 `docs/DECISIONS.md`。

---

## 7. 【A 线 · 更新】说话人识别 Provider 化 → 当前主用 阿里云智能语音（2026-09-13 02:00）

**状态**：模块已完成并离线验证通过；**未接生产流程**。

**路线变更记录**：
- `pyannote` → **暂停**（环境已就绪，文件原样保留，见 §3）
- `volcengine` → **暂停**（代码保留，`volcengine.py` + `test_speaker.py` 原样保留）
- `aliyun` → **当前主用**（本轮新实现）

**新增/更新模块 `live_clipper/speaker/`**：

| 文件 | 职责 |
|---|---|
| `base.py` | 统一契约 `SpeakerTurn`（start/end/speaker）+ 基类 `BaseSpeakerProvider` |
| `config.py` | 环境变量读取（阿里云 `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` / `ALIYUN_APP_KEY`；火山 `VOLC_*` 保留）+ 安全摘要（打码，不泄露密钥）|
| `aliyun.py` | **【新】阿里云智能语音「录音文件识别」两阶段异步封装（SubmitTask + GetTaskResult），RPC HMAC-SHA1 签名，开 `enable_speaker_diarization`** |
| `volcengine.py` | 火山引擎豆包封装（保留，暂停使用）|
| `__init__.py` | 对外出口 + Provider 注册表（`build_provider` / `list_providers`），**默认 provider = `aliyun`** |
| `test_aliyun.py` | **【新】阿里云本地测试脚本（44 项离线全过；`--live` 可选真实调用）** |
| `test_speaker.py` | 火山本地测试脚本（35 项离线全过）|
| `README.md` | 用法、接口细节、边界、下一步（已更新为阿里云主用）|
| `.env.example`（项目根）| 环境变量模板（阿里云为主 + 火山保留）；`.gitignore` 已加 `.env` 排除 |

**统一输出格式**：`[{"start": 0, "end": 5, "speaker": "spk_0"}, ...]`

**关键设计点**：
- 阿里云录音文件识别**只吃公网可访问的音频 URL**，不吃本地文件 → 模块提供 `upload_fn` 回调钩子，不内置任何存储方案（保持可替换）。
- RPC 签名（HMAC-SHA1）**覆盖 HTTP 方法**（GET≠POST），已用阿里云官方文档示例验证签名一致（`OLeaidS1JvxuMvnyHOwuJ+uX5qY=`）。
- 响应字段为 PascalCase（`TaskStatus`/`StatusText`/`Result.Sentences[].BeginTime|EndTime|SpeakerId`）。
- 缺说话人标签时**返回空列表，绝不伪造**（沿用项目铁律）。
- 配置不硬编码：所有凭据只从环境变量读。

**未做（用户明令）**：未改 ASR / DeepSeek 高光 / Story·Event·Recommendation / 评分 / UI；未接 pipeline；未删 pyannote 文件（`poc/audio_understanding/pyannote_*` 原样保留）；未做大范围重构。

**验证**：`test_aliyun.py` **44 通过 / 0 失败**（含签名对齐官方示例、格式转换、异常不崩）；`test_speaker.py` 回归 **35 通过 / 0 失败**。
**真实 API 调用**：本机**未设置** `ALIYUN_*` 环境变量 → 真实调用**未执行**（仅离线验证）。需用户提供 AK/SK/AppKey + 公网音频 URL 后方可跑 `--live`。

**下一步**：真实链路（上传 OSS→URL→`--live`）→ 用已有 benchmark 片段与人工 GT 对照，核心看「短插话被长独白吸收」是否改善。

---

## 1. 任务是什么

判断直播切片的 **Speaker Diarization（说话人分离）**技术路线：
CAM++（funasr 自带，已在用）是否可用？不行的话 pyannote community-1 / 火山引擎豆包 是否更好？
**核心判定问题：短插话 speaker 被主讲人长独白吸收（cam++ 最严重问题）能否被解决。**

四轮推进：
1. ✅ **候选检索**：扫描媒体库，导出 2 个 30-90s 双人/三人 benchmark 片段（`poc/fixtures/`）
2. ✅ **人工 GT**：用户用自创 **AAA 标注法**（正文连打 ≥3 个 A = 换人）标注，turn sheet 由 AI 解析回填：
   - `t2_0274_0360`：2 人 / 5 次切换；`t2_2630_2685`：3 人 / 14 次切换（A×4 连续段按 1 次切换计）
   - GT 切换点是字符插值估算，精度 ±1-2s → 主容差 **±1.5s**（附 ±1.0/±2.0 敏感性）
3. ✅ **CAM++ 正式评测 = FAIL**（`poc/audio_understanding/outputs/speaker_benchmark_report.md`）：
   - 0274（关键简单题）：A 配置判 1 人（✗），B 配置 2 人但切换 R=0（全容差）；attribution 93% ≈ "全判主讲人"基线，无信息量
   - 2630：A 3/3 人但 R=0.143；B 人数错（5/3）、human3 获 0ms
   - 根因：CAM++ embedding/聚类扛不住 2-4s 短插话被长独白支配；**切句粒度已证明不是瓶颈**
4. ⏸️ **pyannote community-1 对照轮（环境已全绿 ⤵，等 HF token）** → 见 §3

## 2. 关键文件（都在 `live_clipper/` 下）

| 文件 | 说明 |
|---|---|
| `poc/audio_understanding/speaker_benchmark.py` / `eval_speaker_benchmark.py` | CAM++ 推理 + 评测（协议权威实现，勿改） |
| `poc/audio_understanding/outputs/speaker_benchmark_report.md` | CAM++ FAIL 报告（含 A→B 四问答案） |
| `poc/audio_understanding/fixtures/speaker_ground_truth_t2_*.json` | 最终人工 GT（含 `_filled_by` 与估算精度说明） |
| `poc/audio_understanding/parse_human_gt.py` / `finalize_human_gt.py` | AAA 标注解析（含踩坑记录，重用先读） |
| `poc/audio_understanding/pyannote_env_check.py` / `pyannote_benchmark.py` / `eval_pyannote_benchmark.py` | **pyannote 轮三件套（已写好，未跑）** |
| `speaker/` (base/config/**aliyun**/volcengine/__init__/test_*/README) | **【A 线】说话人识别 Provider 化；当前主用阿里云（`aliyun.py`），火山保留（未接生产）** |
| `docs/PYANNOTE_INSTALL_STATUS.md` | **环境安装全记录（已全绿）+ FFmpeg 解法与踩坑 + 最短解决路径（先读这个）** |
| `poc/audio_understanding/outputs/scan/benchmark_candidates_report.md` | 候选检索报告（含模型上下文依赖发现） |

## 3. 当前中断点

- **环境已全绿**：独立环境 **`D:\AI_ENV\pyannote_env`**（Python 3.13.14，**建在项目目录外**——这是本轮成功关键，项目内 venv 会撞沙箱批量删除保护）。
  - 已装实测：torch **2.14.0+cpu** / torchaudio **2.11.0** / torchcodec **0.16.0** / **pyannote.audio 4.0.7** / pyannote.core 6.0.1 / pipeline 4.0.0 / huggingface-hub 1.31.0；`pip check` 无错。
  - 验证：`import torch` ✅、`import pyannote.audio` ✅、`from pyannote.audio import Pipeline` ✅、**torchcodec 实解码 fixture wav ✅（85.64s / 16kHz / mono，3 个 fixture 全过，空环境复现亦通过）**。
- **原 torchcodec 阻塞已解决（2026-09-13 复核确认）**：复用项目 venv 里 **PyAV 18.1.0 内置的 FFmpeg 8.x** shared 库（`\.venv\Lib\site-packages\av.libs`，25 DLL / 62.6MB）复制到 `torchcodec\` 目录。实测版本 avutil `60.26.102` / avformat `62.12.102`。
  验证：3 个 fixture wav 全部可解码；`env -i`（无 PATH/无 env）下同样通过 → 依赖按**目录邻近性**解析，部署稳健。
  ⚠️ 两个坑已验证：**①** PyAV 的 `lib*` DLL 带 hash 改名，不能只做去 hash 重命名（会断依赖链），须保留原名；**②** `PATH` / `os.add_dll_directory()` 都无效，`torch.ops.load_library` 按被加载 DLL 所在目录搜索依赖。详见 `docs/PYANNOTE_INSTALL_STATUS.md` §3。
- **HF token 仍缺（当前唯一前置）**：`hf_token_file_present: false` / `hf_token_env_present: false`。模型 `pyannote/speaker-diarization-community-1` 是 gated：需用户接受协议 + 同账号 Read token；**token 不进代码/日志/Git/对话**（脚本只依赖 `HF_TOKEN` 环境变量或标准 token 文件，AI 不接触 token 本体）。
- 详细记录 + 解决路径见 `docs/PYANNOTE_INSTALL_STATUS.md` §3/§4，**不要凭记忆重试**。

## 4. 恢复后的执行序列（照做，别发挥）

0. ~~先解 torchcodec 阻塞~~ ✅ **已完成并复核**（2026-09-12 完成 / 2026-09-13 复核通过）。环境已可直接进第 1 步。
1. （可选复核）跑 `pyannote_env_check.py` 确认全绿，重点看 `torchcodec_decode.ok`
2. **等用户确认 token 就位后**：`pyannote_benchmark.py --mode auto`（**每 fixture 仅 1 次推理**，异常才复跑；不传 num_speakers）
3. 仅当 auto 人数错时跑 `--mode oracle`（0274=2、2630=3，诊断用，从 GT 读数）
4. `eval_pyannote_benchmark.py --mode auto`（协议与 CAM++ 完全一致，overlap 剔除单独计数）
5. 性能记录：冷启动（新进程全程）/ warm（`--warm`）/ RTF / HF cache 体积 / CPU vs GPU
6. 与 CAM++ 直接对比 → 写 `poc/audio_understanding/outputs/pyannote_speaker_benchmark_report.md`（PASS/BORDERLINE/FAIL 三选一）
7. 向用户汇报 10 项：环境 / 模型版本 / 授权需求 / Primary 结果 / Oracle（如跑）/ CAM++ 对比 / 性能体积 / Windows 部署风险 / 判定 / 下一步唯一建议。**完成后停止。**

## 5. 本轮禁令（用户明令，勿越）

不修改生产代码 / ASR Provider / Chapter·Story·Event·Recommendation / 评分 / UI / pipeline / sidecar schema；
不调 CAM++ 参数；不引 sherpa-onnx；不进三视频 PoC；不动 Git；
**不换源重装、不改安装方案**（历史叫停原因；本轮安装已成功，无需重装）；真实 API 调用需用户明确要求。

## 6. 用户约定（长期有效）

小步走一次一件事；最小修改不重构；不为过测试调阈值；要完整性要召回不过度合并；
docs 每版本必更新；DECISIONS 禁随意推翻；汇报按功能维度（什么样→什么样、为什么、效果）。
