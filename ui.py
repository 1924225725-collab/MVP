# ============================================================
# AI 直播切片助手 —— 网页版入口（V0.4.3：内容结构 UI + 推荐剪辑 + 模糊化档位）
#
# 用法（在 live_clipper 文件夹里）：
#   .\.venv\Scripts\streamlit run ui.py
# 然后浏览器会自动打开 http://localhost:8501
#
# 本文件只负责"界面"。真正干活的是：
#   pipeline.py（视频 → 音频 → 文字稿，本地免费）
#   analysis/（v2 流程：扫描 → 分区 → 海选 → 质检 → 事件聚合 → 分批复审 → 内容结构）
#
# V0.4.2 界面变化（这一版的核心理念：先让人看懂"这场直播发生了什么"）：
#   1. 顶部：视频基本信息（文件名 / 时长 / 分析统计）
#   2. 主要区域：⭐ 推荐剪辑 —— 产品层筛出的"优先看/优先剪"清单
#      （评分只描述内容质量；是否进推荐是产品决策，两者已解耦，见 _pick_recommendations）
#   3. 🧭 直播内容结构 —— 整场 → Chapter → Story，Story 是理解内容的单位
#   4. 推荐剪辑 ↔ Story 互相标注来源，形成闭环
#   5. Developer/Debug 能力全部保留在页面底部"开发者视图"折叠区
#
# V0.4.3 界面变化（D-044）：普通界面**不再出现 S/A/B/C/D 等级字母**
#   - 内部 grade 仍是 S/A/B/C/D（评分体系不变），只在开发者视图以 `grade=X` 露出；
#   - 展示层模糊成两档：🌟 高光内容（原 S/A） / ✨ 有看点（原 B/C），D 不显示；
#   - 推荐层级也不露字母：重点推荐 / 推荐 / 值得一看 / 备选参考；
#   - AI 文案里若有等级字母，展示前用 _soften() 兜底抹掉。
#   原因：用户看到「B / C」会误以为「不值得剪」，从而错过好内容。
# ============================================================

import contextlib
import io
import json
import re
import sys
import traceback
from pathlib import Path

import streamlit as st

import config
import pipeline
from errors import (
    ProcessError,
    STAGE_ASR_EMPTY,
    STAGE_ASR_INFERENCE,
    STAGE_AUDIO_EXTRACT,
    STAGE_DEPENDENCY,
    STAGE_FFMPEG,
    STAGE_MEDIA_UNREADABLE,
    STAGE_MODEL_LOAD,
    STAGE_MODEL_MISSING,
    STAGE_NO_AUDIO,
    STAGE_UNKNOWN,
)

# v2 分析流程（延迟导入的部分在函数里，这里只拿轻量的）
from analysis import analyze_transcript_v2
from analysis.event_scanner import AVAILABLE_TYPES

# Windows 控制台默认 GBK，日志里的 ¥ 等字符会炸，强制 UTF-8 + 容错
for _stream in (sys.stdout, sys.stderr):
    if _stream and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# ---------- 页面基本设置 ----------
st.set_page_config(page_title="AI 直播切片助手", page_icon="🎬", layout="wide")

st.title("🎬 AI 直播切片助手")
st.caption("直播录像 → 语音识别 → AI 理解内容结构 → 挑出值得剪的高光片段")

# 钥匙文件位置（和 analysis/deepseek_client.py 里约定的是同一个）
KEY_FILE = Path(__file__).parent / "api_key.txt"

# ---------- 评级 / 推荐文案（V0.4.3：界面不露 S/A/B/C/D 字母，D-044） ----------
# 内部 grade 仍是 S/A/B/C/D；展示层用 config.GRADE_UI 模糊成「高光内容 / 有看点」两档，
# 避免用户看到 B/C 就以为「不值得剪」而错过好内容。
GRADE_BADGE = dict(config.GRADE_UI)            # grade → 展示徽章（D 为空 = 不显示）
GRADE_SORT = dict(config.GRADE_RANK)           # 仅内部排序用，不展示
TIER_BADGE = dict(config.RECOMMEND_TIER_LABEL)  # 推荐层级 → 展示徽章
_GRADE_FALLBACK = "—"                          # 无评级（如没有匹配到高光的 Story）时的中性占位

# V0.4.3（D-044）：AI 文案可能残留等级字母（历史结果缓存 / 模型偶发不听话），
# 展示层再做一道兜底，把「B级」「A 级」这类字样抹掉，避免用户误判「不值得剪」。
_GRADE_LETTER_RE = re.compile(r"[SABCD]\s*级(?:别)?")

# ---------- V0.4.5：本地 ASR 失败时，按「出错在哪一层」给不同提示 ----------
# 以前所有失败都显示同一句「视频处理失败，请换一个文件试试」——
# 正常视频（模型加载被代理拦成 502）也被当成"视频坏了"，用户无从下手。
# 现在 pipeline / asr 会抛出带 stage 的 ProcessError，这里逐条映射成：
#   (标题, 该怎么做)
_ASR_ERROR_UI = {
    STAGE_MEDIA_UNREADABLE: (
        "媒体文件无法读取",
        "这个文件不是有效的视频，或者已经损坏。请先用播放器确认能正常播放，再换一个 MP4 重试。",
    ),
    STAGE_NO_AUDIO: (
        "未检测到音轨",
        "视频能正常打开，但里面**没有声音轨道**（常见于无声录屏、或音轨被剥离的文件）。"
        "请换一个有声音的视频（换文件需要重启识别）。",
    ),
    STAGE_AUDIO_EXTRACT: (
        "音频提取失败",
        "文件能被识别，但 FFmpeg 没能抽出音频，可能是文件部分损坏或编码异常。"
        "可以先在播放器里拖到中段确认能正常播放，再换文件重试。",
    ),
    STAGE_FFMPEG: (
        "FFmpeg 不可用",
        "本地没找到 ffmpeg 程序。请用项目自带的 Python 启动网页版："
        "`.\\\\.venv\\\\Scripts\\\\python -m streamlit run ui.py`；"
        "若仍失败，重装：`.\\\\.venv\\\\Scripts\\\\python -m pip install imageio-ffmpeg`。",
    ),
    STAGE_DEPENDENCY: (
        "缺少依赖库",
        "本地语音识别所需的库没装好（还没轮到这个视频本身有问题）。"
        "安装：`.\\\\.venv\\\\Scripts\\\\python -m pip install faster-whisper`。",
    ),
    STAGE_MODEL_MISSING: (
        "本地模型未安装",
        "本地没有这个 Whisper 模型，自动下载也没成功（当前网络可能访问不了 HuggingFace）。"
        "解决：联网后重跑一次识别会自动下载；或按开发者信息里的目录手动放入模型文件。",
    ),
    STAGE_MODEL_LOAD: (
        "模型加载失败",
        "模型文件在本地，但加载不了（可能损坏或版本不匹配）。"
        "按开发者信息里的缓存目录删掉该模型文件夹，再重跑一次识别即可重新下载。",
    ),
    STAGE_ASR_INFERENCE: (
        "语音识别推理失败",
        "模型加载成功，但在识别这段音频时出错。请把下方开发者信息里的原始报错发出来。",
    ),
    STAGE_ASR_EMPTY: (
        "没有识别出内容",
        "音频能读、模型也跑通了，但整段几乎没有人声（可能是纯静音 / 纯 BGM / 纯环境音）。",
    ),
    STAGE_UNKNOWN: (
        "视频处理失败",
        "发生了未预期的错误。请展开下方开发者信息，把 traceback 发出来方便定位。",
    ),
}


def _asr_error_ui(stage):
    """stage → (标题, 怎么做)。未知 stage 走兜底文案。"""
    return _ASR_ERROR_UI.get(stage, _ASR_ERROR_UI[STAGE_UNKNOWN])



def _soften(text):
    """抹掉文案里的等级字母（展示用兜底；数据本身不改）。"""
    if not text or not isinstance(text, str):
        return text
    return _GRADE_LETTER_RE.sub("", text).replace("  ", " ").strip()



def load_saved_key():
    """读取已保存的钥匙，没有就返回空字符串。"""
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    return ""


def _snapshot_for(h: dict) -> dict:
    """存下片段当时的客观样子（feedback.json 的 snapshot 用）。

    记录的是「片段的特征」，不随用户态度变——将来回答「你喜欢的片段到底有什么共同点」。
    """
    return {
        "title": h.get("title", ""),
        "start_time": h.get("start_time", ""),
        "end_time": h.get("end_time", ""),
        "recommended_duration": h.get("recommended_duration"),
        "grade": h.get("grade", ""),
        "score": h.get("score"),
        "event_id": h.get("event_id", ""),
        "highlight_type": h.get("highlight_type", ""),
    }


def _clip_span(h: dict) -> str:
    """优先用 AI 推荐的剪辑范围；没有就退回事件边界。"""
    if h.get("recommended_start") and h.get("recommended_end"):
        dur = h.get("recommended_duration")
        tail = f"（{dur} 秒）" if dur else ""
        return f"✂️ 建议剪 {h['recommended_start']} - {h['recommended_end']}{tail}"
    return f"⏱ {h.get('start_time', '?')} - {h.get('end_time', '?')}"


def _dims_line(dims: dict) -> str:
    """把「三秒吸引力（权重30%）: 8」这种键名压成一行可读文本。"""
    if not dims:
        return ""
    parts = []
    for k, v in dims.items():
        name = str(k).split("（")[0]
        parts.append(f"{name} {v}分")
    return "  ".join(parts)


def _grade_badge(grade, fallback: str = "") -> str:
    """grade → 展示徽章（V0.4.3：不露字母；D 返回空串 = 不显示）。"""
    text = GRADE_BADGE.get(grade or "", "")
    return text or fallback


def _tier_badge(tier: str) -> str:
    """推荐层级 → 展示徽章（V0.4.3：不露字母）。"""
    return TIER_BADGE.get(tier or "", "")


def _story_by_id(chapters_list, story_id):
    """在内容结构里按 story_id 找 Story，返回带 chapter_title 的扁平视图（供推荐卡片标注来源）。"""
    if not story_id:
        return None
    for ch in chapters_list:
        for s in ch.get("stories", []):
            if s.get("story_id") == story_id:
                return {
                    "chapter_title": ch.get("title") or ch.get("chapter_id", ""),
                    "chapter_id": ch.get("chapter_id", ""),
                    "story_title": s.get("title", ""),
                    "start_time": s.get("start_time", ""),
                    "end_time": s.get("end_time", ""),
                }
    return None



def _render_feedback(h: dict):
    """👍/👎 反馈按钮（写 feedback.json，攒数据给 v0.5 学用户口味）。"""
    cid = h.get("clip_id")
    if not cid:
        return
    from analysis.feedback import save_feedback, get_feedback
    existing = get_feedback(cid)
    fc1, fc2 = st.columns(2)
    with fc1:
        if st.button("👍 值得剪", key=f"fb_like_{cid}", use_container_width=True,
                     type="secondary" if existing and existing.get("user_choice") == "喜欢" else "primary"):
            save_feedback(cid, "喜欢", reason="", snapshot=_snapshot_for(h))
            st.toast(f"已记：喜欢 {cid}")
            st.rerun()
    with fc2:
        if st.button("👎 不值得剪", key=f"fb_dislike_{cid}", use_container_width=True,
                     type="secondary" if existing and existing.get("user_choice") == "不喜欢" else "primary"):
            save_feedback(cid, "不喜欢", reason="", snapshot=_snapshot_for(h))
            st.toast(f"已记：不喜欢 {cid}")
            st.rerun()


# ============================================================
# 侧边栏：分析设置 + API Key 管理
# ============================================================
with st.sidebar:
    st.header("分析设置")

    # ---- 设置 1：直播类型（决定扫描词库和 AI 评分侧重）----
    live_type = st.selectbox(
        "直播类型",
        AVAILABLE_TYPES,
        index=AVAILABLE_TYPES.index(config.LIVE_TYPE_DEFAULT)
        if config.LIVE_TYPE_DEFAULT in AVAILABLE_TYPES else 0,
        help="不同类型用不同的信号词库和评分侧重，选错会明显影响判断",
    )

    # ---- 设置 2：分析模式（快速/标准/精细，UI 不露 token 数字，D-005）----
    token_mode = st.radio(
        "分析模式",
        list(config.TOKEN_MODES),
        index=list(config.TOKEN_MODES).index(config.TOKEN_MODE_DEFAULT),
        format_func=lambda m: f"{m} —— {config.TOKEN_MODES[m]['desc']}",
        help="模式决定分析的仔细程度和成本",
    )

    # ---- 设置 3：数量模式 ----
    quantity_mode = st.radio(
        "输出数量",
        config.QUANTITY_MODES,
        index=config.QUANTITY_MODES.index(config.QUANTITY_MODE_DEFAULT),
        help="自动精选=系统直接给出推荐清单；候选池=把所有候选都给出来自己挑；"
             "自定义=按分数取前 N 个",
    )
    custom_count = None
    if quantity_mode == "自定义数量":
        custom_count = st.number_input("想要几个高光", 1, 50, config.DEFAULT_CUSTOM_COUNT)

    st.divider()

    # ---- API Key 管理 ----
    st.subheader("🔑 DeepSeek API Key")
    saved_key = load_saved_key()

    if saved_key:
        # 只露头尾，中间打码，避免别人瞄屏幕时看到完整钥匙
        masked = f"{saved_key[:3]}{'*' * 8}{saved_key[-4:]}"
        st.success(f"已保存：`{masked}`")

    col_save, col_del = st.columns(2)
    with col_save:
        if st.button("💾 保存", use_container_width=True):
            new_key = st.session_state.get("key_input", "").strip()
            if not new_key:
                st.error("先在下面输入框里粘贴钥匙")
            elif not new_key.startswith("sk-"):
                st.error("钥匙应该以 sk- 开头，检查一下有没有复制完整")
            else:
                KEY_FILE.write_text(new_key, encoding="utf-8")
                st.success("保存成功！")
                st.rerun()
    with col_del:
        if saved_key and st.button("🗑 删除", use_container_width=True):
            KEY_FILE.unlink()
            st.rerun()

    st.text_input(
        "粘贴 API Key（sk- 开头）",
        type="password",
        key="key_input",
        placeholder="sk-...",
        help="钥匙保存在本机的 api_key.txt 里，不会上传 GitHub。获取地址：platform.deepseek.com",
    )
    if not saved_key:
        st.caption("还没设置钥匙：语音识别不受影响，但「AI 高光分析」跑不了")
    st.divider()
    st.caption("命令行版依然可用：`python main.py` / `python analyze_v2.py`")
    st.caption("🎨 开发者：**夜雨声烦**")


# ============================================================
# 第一步：准备文字稿（两种来源：已有稿 / 上传新视频识别）
# ============================================================
st.header("① 准备文字稿")

# transcripts/ 里已有的稿子，按修改时间倒序（最新的排最前）
pipeline.TRANSCRIPT_DIR.mkdir(exist_ok=True)
existing = sorted(
    pipeline.TRANSCRIPT_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True
)
selected_transcript = existing[0] if existing else None

tab_old, tab_new = st.tabs(["📁 用已有文字稿", "🎬 上传新视频识别"])

with tab_old:
    if not existing:
        st.info("还没有文字稿——先切到右边「上传新视频识别」生成一份")
    else:
        names = [p.name for p in existing]
        picked = st.selectbox("选择文字稿", names, index=0)
        selected_transcript = existing[names.index(picked)]
        st.caption(
            f"已选：{selected_transcript.name}（{selected_transcript.stat().st_size / 1024:.0f} KB）"
        )

with tab_new:
    uploaded = st.file_uploader("上传 MP4 视频", type=["mp4"])
    if uploaded is None:
        st.caption("👆 建议先用几分钟的短视频试水")
    else:
        # 把上传的视频存进 videos/ 文件夹（pipeline 从这里读取）
        pipeline.VIDEO_DIR.mkdir(exist_ok=True)
        video_path = pipeline.VIDEO_DIR / uploaded.name
        video_path.write_bytes(uploaded.getvalue())
        st.success(f"已收到：{uploaded.name}（{uploaded.size / 1024 / 1024:.1f} MB）")

        if st.button("🎙️ 开始识别（本地，不花钱）", type="primary"):
            # V0.4.5：不再用一个 action 兜住所有异常、也不再返回 None 让上层猜。
            # process_video 会抛带 stage 的 ProcessError，这里按 stage 给不同提示，
            # 并把完整 traceback / 原始日志放进开发者折叠区（不再吞掉底层异常）。
            error_info = None
            error_tb = ""
            console_buf = io.StringIO()
            with st.status("正在识别……", expanded=True) as status_box:
                try:
                    with contextlib.redirect_stdout(console_buf), \
                            contextlib.redirect_stderr(console_buf):
                        result = pipeline.process_video(video_path)
                except ProcessError as e:
                    error_info, error_tb = e, traceback.format_exc()
                    status_box.update(label="❌ 识别失败", state="error")
                except BaseException as e:      # 完全没预料到的错误也不要吞掉
                    error_info = ProcessError(STAGE_UNKNOWN, f"{type(e).__name__}: {e}")
                    error_tb = traceback.format_exc()
                    status_box.update(label="❌ 识别出错", state="error")
                else:
                    status_box.update(label="✅ 识别完成", state="complete")

            console_text = console_buf.getvalue().strip()

            if error_info is not None:
                title, hint = _asr_error_ui(error_info.stage)
                st.error(f"**{title}**\n\n{hint}")
                st.caption(f"出错环节：`{error_info.stage}`　|　原始错误：{error_info}")
                with st.expander("🔧 开发者：完整错误信息（traceback / 原始日志）", expanded=False):
                    st.markdown(f"**stage**：`{error_info.stage}`")
                    st.markdown(f"**错误**：`{type(error_info).__name__}: {error_info}`")
                    if error_info.detail:
                        st.markdown("**底层原始信息**")
                        st.code(error_info.detail, language=None)
                    st.markdown("**traceback**")
                    st.code(error_tb or "(无 traceback，错误由返回值表达)", language="python")
                    if console_text:
                        st.markdown("**捕获到的控制台输出**")
                        st.code(console_text, language=None)
            else:
                if console_text:
                    with st.expander("🖥️ 处理日志"):
                        st.code(console_text, language=None)
                # 识别完刷新页面：新稿子会出现在「已有文字稿」列表最上面
                st.rerun()


# ============================================================
# 第二步：预算预估 + AI 高光分析
# ============================================================
if selected_transcript is None:
    st.info("先在上面准备一份文字稿（识别一个视频，或等识别完成）")
    st.stop()

st.header("② AI 高光分析")

# ---- 预算预估（本地计算，不花钱；运行前给用户看大概花多少，D-015）----
@st.cache_data(show_spinner=False)
def estimate_budget(transcript_path_str, live_type, token_mode):
    """本地算一遍：解析 → 扫描 → 分区 → 估 token。不算 AI 海选/复审的输出，只是近似。"""
    from analysis import transcript_parser, event_scanner, chunker, budget

    segments = transcript_parser.parse_transcript_file(transcript_path_str)
    if not segments:
        return None
    duration = transcript_parser.total_duration(segments)
    buckets = event_scanner.scan(segments, live_type)
    chunks = chunker.build_chunks(buckets, segments)
    max_cand = config.TOKEN_MODES[token_mode]["max_candidates_per_chunk"]
    est_tokens = budget.estimate_total(chunks, max_cand)
    return {
        "duration": chunker.format_time(duration),
        "chunks": len(chunks),
        "tokens": est_tokens,
        "cost": est_tokens * config.PRICE_INPUT_PER_MTOKEN / 1_000_000,
        "over_budget": est_tokens > config.TOKEN_MODES[token_mode]["budget"],
    }


est = estimate_budget(str(selected_transcript), live_type, token_mode)

if est:
    col1, col2, col3 = st.columns(3)
    col1.metric("时长 / 区块", f"{est['duration']} / {est['chunks']} 块")
    col2.metric("预计消耗", f"约 {est['tokens']:,} token")
    col3.metric("预计费用", f"¥{est['cost']:.2f}")
    if est["over_budget"]:
        st.warning("超出所选模式预算，运行时会自动降级（普通区合并粗切 / 限制每区块候选数）。长直播建议选「精细」模式。")

st.caption(
    f"当前设置：直播类型 **{live_type}** · 模式 **{token_mode}** · 输出 **{quantity_mode}**"
    + (f"（{custom_count} 个）" if custom_count else "")
    + " —— 都在左侧边栏改"
)

if not load_saved_key():
    st.info("👆 还没设置 DeepSeek API Key：先看左侧边栏，粘贴钥匙 → 点「💾 保存」")
    st.stop()

if st.button("🚀 开始 AI 高光分析", type="primary"):
    with st.status("AI 正在看完整场直播……（海选 → 质检 → 事件聚合 → 复审，要几分钟）",
                   expanded=True) as status_box:
        console_buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(console_buf), \
                    contextlib.redirect_stderr(console_buf):
                result_v2 = analyze_transcript_v2(
                    selected_transcript,
                    live_type=live_type,
                    token_mode=token_mode,
                    quantity_mode=quantity_mode,
                    custom_count=custom_count,
                )
        except SystemExit as e:
            status_box.update(label="❌ 分析失败", state="error")
            st.error(f"分析没跑成：{e}")
            st.stop()
        except Exception as e:
            status_box.update(label="❌ 分析出错", state="error")
            st.error(f"分析出错：{e}")
            st.stop()

        status_box.update(label="✅ 分析完成", state="complete")
        console_text = console_buf.getvalue().strip()
        if console_text:
            with st.expander("🖥️ 分析日志（每区块海选、质检、成本都在这）"):
                st.code(console_text, language=None)

    st.session_state["v2_result"] = result_v2
    st.session_state["v2_transcript"] = selected_transcript.name


# ============================================================
# 第三步：结果展示（V0.4.2 新 UI）
#   顶部信息 → ⭐ 推荐剪辑 → 🧭 直播内容结构 → 🔧 开发者视图
# ============================================================
if "v2_result" not in st.session_state:
    st.stop()

v2 = st.session_state["v2_result"]
meta = v2.get("meta", {})
cost = v2.get("cost", {})
highlights = v2.get("highlights", [])
rejected = v2.get("rejected", [])
structure = v2.get("structure") or {"chapters": [], "stats": {}}
chapters = structure.get("chapters", [])
structure_stats = structure.get("stats", {}) or {}

# 事件 id → 完整条目（推荐剪辑和结构区都要用）
by_event = {}
for item in highlights + rejected:
    key = item.get("event_id") or item.get("clip_id")
    if key:
        by_event[key] = item

# 推荐剪辑 = 产品层筛选结果（不是全部 highlight，也不是"所有 A"）
# 排序：先按推荐层级（重点推荐 → 推荐 → 值得一看 → 备选参考），同层内按分数降序
_TIER_ORDER = {"S": 0, "A": 1, "B_fill": 2, "C_fallback": 3, "": 4}
recommended = [h for h in highlights if h.get("recommended")]
recommended.sort(key=lambda h: (_TIER_ORDER.get(h.get("recommend_tier", ""), 9),
                                -h.get("score", 0)))
# 结构区用来标"这个 Story 贡献了几条推荐"
rec_ids = {h.get("event_id") or h.get("clip_id") for h in recommended}

# 内容分布按「展示档」统计（V0.4.3：不露 S/A/B/C/D 字母，只分成高光内容 / 有看点两类）
display_counts = {}
for h in highlights:
    label = _grade_badge(h.get("grade"), _GRADE_FALLBACK)
    display_counts[label] = display_counts.get(label, 0) + 1


# ---------------- 顶部：视频基本信息 ----------------
st.divider()
st.header("📺 视频信息")
st.markdown(f"### 《{st.session_state.get('v2_transcript', '未知文件')}》")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("时长", meta.get("duration", "?"))
m2.metric("内容结构", f"{len(chapters)} 章 / {structure_stats.get('story_count', 0)} 故事")
m3.metric("候选 → 最终", f"{meta.get('candidate_count', '?')} → {len(highlights)}")
m4.metric("推荐剪辑", f"{len(recommended)} 条")
m5.metric("实际花费", f"¥{cost.get('cost_yuan', 0):.4f}")

badge_txt = " · ".join(f"{label} {n}" for label, n in display_counts.items())
st.caption(
    f"内容分布：{badge_txt or '无'}　|　未进推荐清单 {len(rejected)} 条　|　"
    f"直播类型 **{meta.get('live_type', '?')}** · 模式 **{meta.get('token_mode', '?')}** · "
    f"输出 **{meta.get('quantity_mode', '?')}**　|　API 调用 {cost.get('calls', '?')} 次"
)
if meta.get("degrade_level"):
    st.warning(
        f"本次分析触发了预算降级（level {meta['degrade_level']}）："
        "长直播建议改用「精细」模式，覆盖更完整。"
    )

# 累计反馈统计（feedback.json 已记了多少条）
try:
    from analysis.feedback import feedback_stats
    fb_stat = feedback_stats()
    if fb_stat and fb_stat != "还没有反馈记录":
        st.caption(f"📊 {fb_stat}")
except Exception:
    pass

# ---- AI 分析报告（帮用户快速理解"这场直播发生了什么"）----
report = v2.get("report", {}) or {}
report_bits = [
    ("本场总结", _soften(report.get("summary", ""))),
    ("最强传播点", _soften(report.get("best_spread_point", ""))),
    ("整体评价", _soften(report.get("overall", ""))),
    ("为什么不推荐更多", _soften(report.get("why_not_more", ""))),
]
if any(text for _, text in report_bits):
    with st.expander("📋 AI 分析报告", expanded=True):
        for label, text in report_bits:
            if text:
                st.markdown(f"**{label}**：{text}")


# ---------------- 主区域：⭐ 推荐剪辑 ----------------
st.divider()
st.header(f"⭐ 推荐剪辑（{len(recommended)} 条）")
st.caption(
    "系统从全场高质量内容中筛出的「优先看 / 优先剪」清单。"
    "**评分只描述内容质量**，是否进这份清单还要看数量策略与重复度——"
    "所以评分稍低的片段可能在高质量内容不足时补位入选，评分高的片段也可能因名额已满而落选。"
)

if not recommended:
    st.info("本次没有产生推荐剪辑（所有内容都没到质量线）。可切换到「候选池」模式查看全部候选。")
else:
    for rank, h in enumerate(recommended, 1):
        with st.container(border=True):
            head_l, head_m, head_r = st.columns([3.4, 1.1, 0.9])
            with head_l:
                st.markdown(f"#### {rank}. {_soften(h.get('title')) or '无标题'}")
                chips = [x for x in (_tier_badge(h.get("recommend_tier")),
                                     _grade_badge(h.get("grade"))) if x]
                st.markdown("　·　".join(chips + [f"`{h.get('clip_id', '?')}`"]))
            with head_m:
                st.metric("内容评分", f"{h.get('score', '?')}/100")
            with head_r:
                st.metric("爆款概率", h.get("viral_probability", "?"))

            st.markdown(f"{_clip_span(h)}　·　类型：{h.get('highlight_type', '?')}")

            # 关联：这条推荐来自哪个 Story
            sid = h.get("story_id", "")
            story = _story_by_id(chapters, sid) if sid else None
            if story:
                st.markdown(
                    f"🧭 **来自** `{story['chapter_title']}` → "
                    f"*{story['story_title']}*（{story['start_time']} - {story['end_time']}）"
                )
            elif sid:
                st.caption(f"🧭 来自 Story `{sid}`")

            st.markdown(f"**讲了什么**：{_soften(h.get('summary') or h.get('reason', ''))}")

            with st.expander("为什么值得剪 / 评分依据 / 剪辑建议"):
                dims_text = _dims_line(h.get("dims") or {})
                if dims_text:
                    st.progress(min(1.0, (h.get("score") or 0) / 100), text=dims_text)
                st.markdown(f"**为什么值得剪**：{_soften(h.get('why_cut') or h.get('reason', ''))}")
                if h.get("duration_reason") and h["duration_reason"] != "（推荐点偏离事件过远，按事件边界）":
                    st.caption(f"⏱ 为什么是这个长度：{_soften(h['duration_reason'])}")
                if h.get("editing_advice"):
                    st.caption(f"✂️ 剪辑建议：{_soften(h['editing_advice'])}")
                if h.get("risk"):
                    st.caption(f"⚠️ 最大风险：{_soften(h['risk'])}")
                if h.get("negative_flags"):
                    st.warning(
                        f"命中「不值得剪」规则：{'、'.join(_soften(x) for x in h['negative_flags'])} → 内容评级已被下调，建议人工复核"
                    )
                if h.get("forced_keep"):
                    st.warning("召回优先保留的候选（全场无高分时的兜底），请人工复核")

            st.caption("▶️ 播放　⏱ 时间轴定位　✂️ 一键剪出 —— 入口已预留，后续版本接入")
            _render_feedback(h)


# ---------------- 🧭 直播内容结构 ----------------
st.divider()
st.header("🧭 直播内容结构")
st.caption(
    "**Chapter** = 整场直播的几个大内容阶段；**Story** = Chapter 内一段相对完整、连续的活动/过程。"
    "Story 是理解这场直播的主要单位；评分同样只描述内容质量，不代表是否进推荐清单。"
)

if not chapters:
    st.info(
        "这份结果没有 Chapter / Story 结构（本次 Chapter/Story 分割失败或被关闭）。"
        "推荐剪辑与下面的开发者视图不受影响，仍可正常查看。"
    )
else:
    for ch in chapters:
        ch_grade = ch.get("grade")
        ch_score = ch.get("score")
        ch_badge = _grade_badge(ch_grade)
        head = (
            f"{ch.get('chapter_id', '?')} · {ch.get('title') or '（未命名章节）'}"
            f"　[{ch.get('start_time', '?')} - {ch.get('end_time', '?')}]"
            + (f"　{ch_badge}" if ch_badge else "")
            + (f" {ch_score}/100" if ch_score is not None else "")
            + f"　·　{ch.get('story_count', 0)} 个 Story"
        )
        with st.expander(head, expanded=False):
            if ch.get("summary"):
                st.markdown(f"**本章概要**：{_soften(ch['summary'])}")
            if ch.get("boundary_reason"):
                st.caption(f"章节划分依据：{_soften(ch['boundary_reason'])}")

            for s in ch.get("stories", []):
                s_grade = s.get("grade")
                s_score = s.get("score")
                with st.container(border=True):
                    top_l, top_r = st.columns([3, 1])
                    with top_l:
                        st.markdown(f"**{_soften(s.get('title')) or '（未命名故事）'}**")
                        st.caption(f"⏱ {s.get('start_time', '?')} - {s.get('end_time', '?')}"
                                   f"　·　{s.get('story_id', '')}")
                    with top_r:
                        if s_score is not None:
                            st.metric("内容评分", f"{s_score}/100",
                                      label_visibility="collapsed")
                            s_badge = _grade_badge(s_grade)
                            if s_badge:
                                st.markdown(s_badge)
                        else:
                            st.caption("暂无高光候选")

                    if s.get("summary"):
                        st.markdown(f"{_soften(s['summary'])}")

                    # 这个 Story 里有没有进推荐清单的片段（关联闭环）
                    s_rec = [e for e in s.get("events", [])
                             if (e.get("event_id") or "") in rec_ids]
                    if s_rec:
                        names = "、".join(
                            _soften(e.get("title")) or e.get("event_id", "") for e in s_rec
                        )
                        st.markdown(f"⭐ **含 {len(s_rec)} 条推荐剪辑**：{names}")
                    elif s.get("events"):
                        st.caption(f"本 Story 有 {s['event_count']} 条内容，但未进推荐清单")
                    else:
                        st.caption("本 Story 未匹配到高光事件")

                    # 「必要时展示为什么得到这个评分」+ Story 内事件明细，合并成一个折叠区
                    best_id = s.get("best_event_id")
                    best = by_event.get(best_id) if best_id else None
                    with st.expander(
                        f"评分依据与内容明细（{s['event_count']} 条内容）"
                        + (f" · 依据最强片段 {best_id}" if best_id else "")
                    ):
                        if best:
                            dims_text = _dims_line(best.get("dims") or {})
                            if dims_text:
                                st.progress(min(1.0, (best.get("score") or 0) / 100),
                                            text=dims_text)
                            st.markdown(f"**最强片段**：{_soften(best.get('title'))}")
                            st.markdown(
                                f"**为什么值得剪**：{_soften(best.get('why_cut') or best.get('reason', ''))}"
                            )
                            if best.get("risk"):
                                st.caption(f"⚠️ 最大风险：{_soften(best['risk'])}")
                        elif not s.get("events"):
                            st.caption("本 Story 未匹配到高光事件，暂无评分依据。")

                        if s.get("events"):
                            st.markdown("---")
                            for e in s["events"]:
                                flag = "⭐ " if (e.get("event_id") or "") in rec_ids else ""
                                badge = _grade_badge(e.get("grade"), _GRADE_FALLBACK)
                                st.markdown(
                                    f"- {flag}`{e.get('event_id', '?')}` {badge} "
                                    f"{e.get('score', '?')}/100 "
                                    f"`{e.get('start_time', '?')} - {e.get('end_time', '?')}` "
                                    f"{_soften(e.get('title') or '')[:40]}"
                                )

                    if s.get("reason"):
                        st.caption(f"Story 划分依据：{_soften(s['reason'])}")


# ---------------- 🔧 开发者视图（保留原有 debug 能力） ----------------
st.divider()
with st.expander("🔧 开发者视图（原始高光列表 / 被拒候选 / 分析审计 / 下载）"):
    st.caption(
        "这里是内部分析层的原始数据：Event / Cluster / Judge / 五维子分 / 成本。"
        "普通使用不需要看这里，排查问题或做回归对比时用。"
    )

    tab_h, tab_r, tab_m, tab_d = st.tabs(
        ["全部内容条目", "被拒候选", "分析审计", "下载"]
    )

    with tab_h:
        st.markdown(f"**全部内容条目 {len(highlights)} 条**（含未进推荐清单的）")
        st.caption("⚠️ 这里是内部原始数据：`grade` 是内部分级字母（S/A/B/C/D），"
                   "只在开发者视图出现，普通界面已模糊化展示。")
        for h in sorted(highlights, key=lambda x: (GRADE_SORT.get(x.get("grade"), 9),
                                                   -x.get("score", 0))):
            rec = "⭐ 已推荐" if h.get("recommended") else "— 未推荐"
            st.markdown(
                f"- `{h.get('clip_id', '?')}` "
                f"`grade={h.get('grade', '?')}` "
                f"{h.get('score', '?')}/100　{rec}"
                f"（tier={h.get('recommend_tier') or '-'}）　"
                f"`{h.get('start_time', '?')} - {h.get('end_time', '?')}` "
                f"{(h.get('title') or '')[:42]}"
            )
            detail = (
                f"event_id={h.get('event_id', '-')} · cluster={h.get('cluster_id', '-')} · "
                f"story={h.get('story_id', '-')} · 海选初分={h.get('first_round_score', '-')} · "
                f"来源候选={h.get('source_count', 1)} · 置信度={h.get('confidence', '-')} · "
                f"ai_recommend={h.get('ai_recommend')}"
            )
            st.caption(detail)

    with tab_r:
        if not rejected:
            st.caption("没有被拒候选。")
        else:
            st.markdown(f"**未进推荐清单的内容 {len(rejected)} 条**（不认同可以点 👍 翻案——"
                        "以后反馈会记入 feedback.json）")
            for r in sorted(rejected, key=lambda x: -x.get("score", 0)):
                reasons = "；".join(r.get("reject_reason", [])) or "未进入展示范围"
                st.markdown(
                    f"- `{r.get('clip_id', '?')}` `grade={r.get('grade', '?')}` "
                    f"{r.get('score', '?')}/100　"
                    f"`{r.get('start_time', '?')} - {r.get('end_time', '?')}` "
                    f"**{(r.get('title') or '')[:40]}**\n  - 拒绝理由：{reasons}"
                )

    with tab_m:
        st.markdown("**meta**")
        st.json(meta)
        st.markdown("**结构统计**")
        st.json(structure_stats)
        st.markdown("**成本**")
        st.json(cost)

    with tab_d:
        st.download_button(
            "⬇️ 下载完整结果（含结构层，highlights_v2.json）",
            data=json.dumps(v2, ensure_ascii=False, indent=2),
            file_name="highlights_v2.json",
            mime="application/json",
        )
