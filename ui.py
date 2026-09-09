# ============================================================
# AI 直播切片助手 —— 网页版入口（v0.3.2 全面升级：接入 v2 分析流程 + 判断体系 v3）
#
# 用法（在 live_clipper 文件夹里）：
#   .\.venv\Scripts\streamlit run ui.py
# 然后浏览器会自动打开 http://localhost:8501
#
# 本文件只负责"界面"。真正干活的是：
#   pipeline.py（视频 → 音频 → 文字稿，本地免费）
#   analysis/（v2 流程：扫描 → 分区 → 海选 → 质检 → 复审，调 DeepSeek）
#
# v0.3.2 界面变化：
#   - 文字稿和 AI 分析拆成两步：识别过的稿子可以直接重跑分析，不用重复识别
#   - 侧边栏新增三个设置：直播类型 / 分析模式 / 数量模式
#   - 运行前显示预算预估（预计 token 和费用，D-015）
#   - 结果改成 S/A/B/C 分级卡片 + 五维判决书（三秒吸引力/反差/表现力/独立/完整）
#     + 为什么值得剪 / 最大风险 + 三类高光标记 + 剪辑建议 + AI 分析报告
# ============================================================

import contextlib
import io
import json
import sys
from pathlib import Path

import streamlit as st

import config
import pipeline

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
st.caption("直播录像 → 语音识别 → AI 分级挑出值得剪的高光片段")

# 钥匙文件位置（和 analysis/deepseek_client.py 里约定的是同一个）
KEY_FILE = Path(__file__).parent / "api_key.txt"


def load_saved_key():
    """读取已保存的钥匙，没有就返回空字符串。"""
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    return ""


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
        help="自动精选=只看 S/A 级（AI 盖章值得剪）；候选池=S/A/B/C 全给；自定义=按分数取前 N 个",
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
            with st.status("正在识别……", expanded=True) as status_box:
                console_buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(console_buf), \
                            contextlib.redirect_stderr(console_buf):
                        result = pipeline.process_video(video_path)
                except Exception as e:
                    status_box.update(label="❌ 识别失败", state="error")
                    st.error(f"视频处理失败：{e}")
                    result = None

            if result is None:
                st.error("视频处理失败，请换一个文件试试（损坏的视频或没有音轨的视频会这样）")
            else:
                status_box.update(label="✅ 识别完成", state="complete")
                console_text = console_buf.getvalue().strip()
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
    with st.status("AI 正在看完整场直播……（海选 → 质检 → 复审，要几分钟）", expanded=True) as status_box:
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
# 第三步：结果展示（S/A/B/C 分级卡片 + AI 分析报告 + 被拒候选）
# ============================================================
if "v2_result" not in st.session_state:
    st.stop()

v2 = st.session_state["v2_result"]
meta = v2["meta"]
cost = v2["cost"]

st.header("③ 结果")
st.success(
    f"《{st.session_state['v2_transcript']}》：候选 {meta['candidate_count']} 个 → "
    f"最终高光 {len(v2['highlights'])} 个，被拒 {len(v2['rejected'])} 个 · "
    f"API 调用 {cost['calls']} 次，实际花费约 ¥{cost['cost_yuan']:.4f}"
)

# ---- AI 分析报告（本场总结等四字段）----
report = v2.get("report", {})
report_bits = [
    ("本场总结", report.get("summary", "")),
    ("最强传播点", report.get("best_spread_point", "")),
    ("整体评价", report.get("overall", "")),
    ("为什么不推荐更多", report.get("why_not_more", "")),
]
if any(text for _, text in report_bits):
    with st.expander("📋 AI 分析报告", expanded=True):
        for label, text in report_bits:
            if text:
                st.markdown(f"**{label}**：{text}")

# ---- 分级卡片（v0.3.2：S/A/B/C 四级 + 五维判决书） ----
GRADE_BADGE = {
    "S": "🚀 S 级 · 爆款候选",
    "A": "🌟 A 级 · 强推荐",
    "B": "✅ B 级 · 测试素材",
    "C": "📦 C 级 · 备用素材",
}
GRADE_SORT = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}

highlights_sorted = sorted(
    v2["highlights"],
    key=lambda h: (GRADE_SORT.get(h.get("grade"), 9), -h.get("score", 0)),
)

st.subheader(f"🏆 高光片段（{len(highlights_sorted)} 个）")

for h in highlights_sorted:
    grade = h.get("grade", "?")
    with st.container(border=True):
        col1, col2, col3 = st.columns([1.5, 1.1, 4])
        col1.markdown(f"### {GRADE_BADGE.get(grade, grade)}")
        col2.metric("评分", f"{h.get('score', '?')}/10")
        col3.subheader(h.get("title", "无标题"))
        col3.write(f"⏱ `{h['start_time']} - {h['end_time']}` · "
                   f"类型：{h.get('highlight_type', '?')} · "
                   f"爆款概率：{h.get('viral_probability', '?')} · "
                   f"置信度 {int((h.get('confidence') or 0) * 100)}%")
        # 五维判决书（v0.3.2 核心：这个分数是怎么来的，全摊开给你看）
        dims = h.get("dims") or {}
        if dims:
            # 键形如「三秒吸引力（权重30%）」，只取括号前的维度名
            dims_text = "  ".join(f"{k.split('（')[0]} {v}分" for k, v in dims.items())
            st.progress(min(1.0, (h.get("score") or 0) / 10), text=dims_text)
        st.markdown(f"**为什么值得剪**：{h.get('why_cut') or h.get('reason', '')}")
        if h.get("risk"):
            st.caption(f"⚠️ 最大风险：{h['risk']}")
        if h.get("negative_flags"):
            st.warning(f"命中「不值得剪」规则：{'、'.join(h['negative_flags'])}"
                       f" → 已封顶 B 级，仅作测试素材")
        if h.get("editing_advice"):
            st.caption(f"✂️ 剪辑建议：{h['editing_advice']}")
        if h.get("forced_keep"):
            st.warning("召回优先保留的候选（全场无高分时的兜底），请人工复核")
        st.caption(f"编号：`{h.get('clip_id', '?')}` · 海选初分 {h.get('first_round_score', '?')}"
                   f"（反馈功能即将上线，记这个号）")

# ---- 被拒候选（供用户翻案）----
if v2["rejected"]:
    with st.expander(f"🗑 被拒候选（{len(v2['rejected'])} 个，点击展开）"):
        st.caption("这些片段 AI 认为不值得剪，理由列在下面——不认同的话可以翻案，以后反馈按钮会记录")
        for r in sorted(v2["rejected"], key=lambda x: -x.get("score", 0)):
            reasons = "；".join(r.get("reject_reason", [])) or "未进入展示范围"
            st.markdown(
                f"- `{r['start_time']} - {r['end_time']}` {r.get('grade', '?')}级 "
                f"{r.get('score', '?')}分 **{r.get('title', '')}**"
                f"（{r.get('clip_id', '?')}）\n  - 拒绝理由：{reasons}"
            )

# ---- 下载完整结果 ----
st.download_button(
    "⬇️ 下载完整结果（highlights_v2.json）",
    data=json.dumps(v2, ensure_ascii=False, indent=2),
    file_name="highlights_v2.json",
    mime="application/json",
)
