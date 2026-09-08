# ============================================================
# AI 直播切片助手 —— 网页版入口（v0.2 新增）
#
# 用法（在 live_clipper 文件夹里）：
#   .\.venv\Scripts\streamlit run ui.py
# 然后浏览器会自动打开 http://localhost:8501
#
# 本文件只负责"界面"：上传按钮、进度显示、结果卡片。
# 真正干活的是 pipeline.py，和命令行版（main.py）共用同一套代码。
# ============================================================

import contextlib
import io
import json
from pathlib import Path

import streamlit as st

import pipeline

# ---------- 页面基本设置 ----------
st.set_page_config(page_title="AI 直播切片助手", page_icon="🎬", layout="wide")

st.title("🎬 AI 直播切片助手")
st.caption("上传直播录像 → 自动语音识别 → AI 挑出值得做切片的高光片段")

# 钥匙文件位置（和 analysis/deepseek_client.py 里约定的是同一个）
KEY_FILE = Path(__file__).parent / "api_key.txt"


def load_saved_key():
    """读取已保存的钥匙，没有就返回空字符串。"""
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip()
    return ""


# ---------- 侧边栏：配置 + API Key 管理 ----------
with st.sidebar:
    st.header("当前配置")
    st.write("识别引擎：本地 Whisper（small）")
    st.write("高光分析：DeepSeek")
    st.caption("想换引擎？改 config.py 后重启页面即可")
    st.divider()

    # ---- API Key 管理（v0.2.1 新增：网页里就能填，不用碰 PowerShell）----
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
                st.success("保存成功！现在可以直接点「开始分析」了")
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
        st.caption("还没设置钥匙：不影响语音识别，但「高光分析」这一步会跳过")
    st.divider()
    st.caption("命令行版依然可用：`python main.py`")
    st.caption("🎨 开发者：**夜雨声烦**")


# ---------- 分析流程的任务清单（v0.2.2 新增） ----------
# 四个步骤 + 每步完成时进度条走到百分之多少
STEPS = [
    ("提取音频", 25),
    ("语音识别", 65),
    ("生成文字稿", 75),
    ("AI 高光分析", 100),
]


def render_checklist(checklist_placeholder, bar_placeholder, done_count, running):
    """把任务清单画到页面上（用 placeholder 原地刷新，不越叠越长）。

    done_count：已完成几步（0~4）
    running：正在进行第几步的下标（没有进行中的就传 None）
    """
    lines = []
    for i, (name, percent) in enumerate(STEPS):
        if i < done_count:
            lines.append(f"✅ 第 {i + 1} 步：{name} —— 完成")
        elif i == running:
            lines.append(f"🔄 第 {i + 1} 步：{name}……")
        else:
            lines.append(f"⬜ 第 {i + 1} 步：{name}（等待中）")

    # 按当前进度算百分比：进行中的步按它自己的百分比先垫上
    if running is not None:
        percent = STEPS[running][1] - 10 if STEPS[running][1] > 10 else 5
    else:
        percent = STEPS[done_count - 1][1] if done_count > 0 else 0

    checklist_placeholder.markdown("\n\n".join(lines))
    bar_placeholder.progress(percent, text=f"总进度 {percent}%")


# ---------- 上传 MP4 ----------
uploaded = st.file_uploader("上传 MP4 视频", type=["mp4"])

if uploaded is None:
    st.info("👆 先上传一个 MP4 视频试试（建议先用几分钟的短视频）")
    st.stop()

# 把上传的视频存进 videos/ 文件夹（pipeline 从这里读取）
pipeline.VIDEO_DIR.mkdir(exist_ok=True)
video_path = pipeline.VIDEO_DIR / uploaded.name
video_path.write_bytes(uploaded.getvalue())
st.success(f"已收到：{uploaded.name}（{uploaded.size / 1024 / 1024:.1f} MB）")


# ---------- 点击开始分析 ----------
if st.button("🚀 开始分析", type="primary"):

    with st.status("正在分析……", expanded=True) as status_box:
        # 任务清单 + 进度条（placeholder 可以原地刷新，清单不会越叠越长）
        checklist_box = st.empty()
        bar_box = st.progress(0.0, text="总进度 0%")
        render_checklist(checklist_box, bar_box, done_count=0, running=0)

        # 终端输出捕获：把原来打印在黑窗口里的文字（模型加载、成本报表等）
        # 先接住，跑完显示在页面上
        console_buf = io.StringIO()

        # 步骤名 → 清单下标的对照表（pipeline 汇报的进度只有前两步的名字）
        stage_index = {STEPS[0][0]: 0, STEPS[1][0]: 1}

        def report(stage):
            render_checklist(checklist_box, bar_box, done_count=stage_index[stage], running=stage_index[stage])

        # ---- 前半程：视频 → 音频 → 文字稿（本地完成，不花钱）----
        with contextlib.redirect_stdout(console_buf), contextlib.redirect_stderr(console_buf):
            result = pipeline.process_video(video_path, progress=report)

        if result is None:
            render_checklist(checklist_box, bar_box, done_count=0, running=None)
            status_box.update(label="❌ 处理失败", state="error")
            st.error("视频处理失败，请换一个文件试试（损坏的视频或没有音轨的视频会这样）")
            st.stop()

        # 前三步完成
        render_checklist(checklist_box, bar_box, done_count=3, running=3)

        # ---- 第 4 步：AI 高光分析 ----
        highlights = None
        try:
            with contextlib.redirect_stdout(console_buf), contextlib.redirect_stderr(console_buf):
                highlights = pipeline.analyze_highlights(result["transcript"])
        except SystemExit:
            # analysis 模块在缺 API Key 时会想直接退出程序，网页里拦下来好好说
            status_box.update(label="⚠️ 文字稿已生成，但高光分析没跑成", state="error")
            st.error(
                "还没有设置 DeepSeek API Key。\n\n"
                "👉 看**左侧边栏**：粘贴钥匙 → 点「💾 保存」→ 再点一次「开始分析」即可。\n\n"
                "钥匙获取地址：https://platform.deepseek.com（API Keys 页面创建）"
            )
        except Exception as e:
            status_box.update(label="⚠️ 文字稿已生成，但高光分析出错", state="error")
            st.error(f"高光分析出错：{e}")

        if highlights is not None:
            render_checklist(checklist_box, bar_box, done_count=4, running=None)
            status_box.update(label="✅ 分析完成", state="complete")
        else:
            # 高光分析没跑成时，前三步的成果照样算完成
            render_checklist(checklist_box, bar_box, done_count=3, running=None)

        # 把黑窗口里的文字亮出来：模型加载提示、识别方式、成本报表都在这
        console_text = console_buf.getvalue().strip()
        if console_text:
            with st.expander("🖥️ 处理日志（黑窗口里原本打印的内容）"):
                st.code(console_text, language=None)

    # 把结果存进 session_state：页面上点别的东西时不会丢
    st.session_state["last_result"] = result
    st.session_state["last_highlights"] = highlights


# ---------- 展示结果（只要跑过一次就显示，刷新页面才消失） ----------
if "last_result" in st.session_state:
    result = st.session_state["last_result"]
    highlights = st.session_state.get("last_highlights")

    st.divider()

    # 文字稿（折叠起来，想看再点开）
    with st.expander(f"📜 文字稿：{len(result['segments'])} 句（点击展开）"):
        for seg in result["segments"]:
            st.write(
                f"`[{pipeline.format_time(seg.start)} - "
                f"{pipeline.format_time(seg.end)}]` {seg.text}"
            )

    # 高光结果
    if highlights:
        st.header(f"🏆 高光片段（AI 挑出 {len(highlights)} 个）")

        # 按评分从高到低排
        highlights_sorted = sorted(highlights, key=lambda h: h["score"], reverse=True)

        for h in highlights_sorted:
            with st.container(border=True):
                col1, col2, col3 = st.columns([1, 2, 4])
                col1.metric("评分", f"{h['score']}/10")
                col2.write(f"⏱ {h['start_time']} - {h['end_time']}")
                col3.subheader(h["suggested_title"])
                st.caption(f"推荐理由：{h['reason']}")

        # 提供下载：把结果存成 highlights.json
        st.download_button(
            "⬇️ 下载 highlights.json",
            data=json.dumps(highlights, ensure_ascii=False, indent=2),
            file_name="highlights.json",
            mime="application/json",
        )
    elif highlights is not None:
        st.warning("AI 没有从这段直播里挑出高光片段（也许这期内容比较平淡？）")
    # highlights 为 None 时，前面已经显示过报错，这里不用再说话
