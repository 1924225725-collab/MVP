# ============================================================
# stages.py —— 处理阶段定义 + 真实进度事件（V0.5.2）
#
# 【为什么需要】
#   以前 progress 回调只传一句"语音识别"，界面只能显示一个转圈的不定进度条。
#   用户看不出程序是在跑还是卡死了 —— 一场 51 分钟直播要识别十几分钟，
#   这段时间里界面毫无信息，很容易以为软件死了。
#
# 【做法】
#   把「处理到哪一步了」变成结构化事件：
#       {"stage": "asr", "title": "正在语音识别",
#        "percent": 45.2, "detail": "23:10 / 51:00　已识别 312 句",
#        "index": 4, "total_steps": 6}
#
#   percent 是**真实算出来的**，不是假动画：
#     - 语音识别：已处理音频时间 / 总时长（faster-whisper 每吐一句，
#       都带这句话在音频里的结束时间，拿它当分子）
#     - AI 分析 ：已扫描区块数 / 总区块数
#   算不出来的阶段（VAD 检测、音频提取）percent 就是 None，
#   界面显示"进行中"而不是编一个百分比糊弄人。
#
# 【边界】
#   只加"上报进度"这一件事，不改任何算法与阶段划分。
# ============================================================

# ---------------- 六个阶段（面向用户） ----------------

STAGE_VIDEO_READ = "video_read"        # 1 读取视频（可读性检查 + 媒体探测）
STAGE_AUDIO_EXTRACT = "audio_extract"  # 2 提取音频（ffmpeg → mp3）
STAGE_VAD = "vad"                      # 3 VAD 人声检测（挑出有人说话的片段）
STAGE_ASR = "asr"                      # 4 语音识别（有真实百分比）
STAGE_AI = "ai_analyze"                # 5 AI 分析（内容理解 + 挑高光）
STAGE_FINALIZE = "finalize"            # 6 生成结果（写文件 / 落项目）

STAGE_ORDER = (
    STAGE_VIDEO_READ,
    STAGE_AUDIO_EXTRACT,
    STAGE_VAD,
    STAGE_ASR,
    STAGE_AI,
    STAGE_FINALIZE,
)

# 阶段 → 标题（界面上的大字）
STAGE_TITLES = {
    STAGE_VIDEO_READ: "读取视频",
    STAGE_AUDIO_EXTRACT: "提取音频",
    STAGE_VAD: "VAD 人声检测",
    STAGE_ASR: "语音识别",
    STAGE_AI: "AI 分析",
    STAGE_FINALIZE: "生成结果",
}

# 进行中的说法（界面上的第二行）
STAGE_RUNNING_TEXT = {
    STAGE_VIDEO_READ: "正在检查视频文件…",
    STAGE_AUDIO_EXTRACT: "正在把声音从视频里提取出来…",
    STAGE_VAD: "正在检测哪里有人说话…",
    STAGE_ASR: "正在语音识别",
    STAGE_AI: "正在用 AI 理解这场直播…",
    STAGE_FINALIZE: "正在整理结果…",
}


def stage_index(stage: str) -> int:
    """这个阶段是第几步（1-based，认不出来就返回 0）。"""
    try:
        return STAGE_ORDER.index(stage) + 1
    except ValueError:
        return 0


def total_steps() -> int:
    return len(STAGE_ORDER)


def make_event(stage, percent=None, detail="", title=None) -> dict:
    """构造一个进度事件。"""
    # 防御：万一有人把整个事件当"阶段名"又传进来（套多层包装），
    # 这里用字符串兜一下，绝不让进度上报把主流程搞崩。
    stage_key = stage if isinstance(stage, str) else str(stage)
    pct = None
    if percent is not None:
        try:
            pct = max(0.0, min(100.0, float(percent)))
        except (TypeError, ValueError):
            pct = None
    return {
        "stage": stage_key,
        "title": title or STAGE_TITLES.get(stage_key, stage_key),
        "running_text": STAGE_RUNNING_TEXT.get(stage_key, ""),
        "percent": pct,
        "detail": str(detail or ""),
        "index": stage_index(stage_key),
        "total_steps": total_steps(),
    }


# ---------------- 时间格式化 ----------------

def fmt_clock(seconds) -> str:
    """秒 → mm:ss（超过一小时自动变 h:mm:ss）。"""
    try:
        sec = float(seconds)
    except (TypeError, ValueError):
        return ""
    if sec < 0:
        sec = 0
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ---------------- 进度上报（节流 + 兼容旧回调） ----------------

def _detect_mode(cb) -> str:
    """判断一个进度回调能不能吃结构化事件。

    只有一个位置参数的（比如 `def on_progress(msg)`）→ 降级成"只发一句话"；
    其余的（Qt 信号 emit、带默认参数、*args）→ 结构化。
    """
    try:
        import inspect
        sig = inspect.signature(cb)
    except (TypeError, ValueError):
        return "structured"          # 内建函数/信号 emit：拿不到签名，按结构化处理
    params = list(sig.parameters.values())
    positional = [p for p in params
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    has_var_kw = any(p.kind == p.VAR_KEYWORD for p in params)
    if len(positional) == 1 and not has_var_kw:
        p = positional[0]
        if p.default is inspect.Parameter.empty:
            return "simple"
    return "structured"


class ProgressSink:
    """把"上报进度"包装成一个安全、带节流的调用。

    用法（流水线内部）：
        report = ProgressSink(progress)
        report(STAGE_ASR, 45.2, "23:10 / 51:00")

    特点：
      1. **兼容旧回调**：外面传进来的可能还是 `progress("语音识别")` 那种
         只吃字符串的函数（网页版/命令行）。这时自动降级成只发阶段标题，
         不会因为签名不同而报错。
      2. **节流**：语音识别每秒可能吐出好几条句子，全发给界面会把主线程淹掉。
         默认同一个阶段内，百分比变化小于 0.5% 且间隔小于 0.15 秒的事件直接丢掉。
      3. **绝不抛错**：进度上报出问题不能连累正在干活的主流程。
      4. 阶段切换、100% 完成这类关键事件**一定**发出去。
    """

    __slots__ = ("_cb", "_mode", "_last_t", "_last_pct", "_last_stage", "_min_dt",
                 "_min_dpct", "_clock", "last_event")

    def __init__(self, callback=None, min_dt=0.15, min_dpct=0.5, structured=None):
        """
        min_dt   —— 最短间隔（秒）。**设为 0 等于不按时间节流（几乎每条都发）**，
                    想单独验证"按百分比节流"要把它设大。
        min_dpct —— 同一阶段内，百分比变化小于它且间隔又太短的事件会被丢掉。
        structured —— 回调是否能吃结构化事件。
                      None = 自动判断（单个必填参数的函数视为只吃字符串）；
                      True/False = 调用方明确指定（桌面版一律显式 True）。
        """
        self._cb = callback
        self._last_t = -1e9
        self._last_pct = -1e9
        self._last_stage = ""
        self._min_dt = float(min_dt)
        self._min_dpct = float(min_dpct)
        self._clock = None
        self.last_event = None
        if callback is None:
            self._mode = "none"
        elif structured is True:
            self._mode = "structured"
        elif structured is False:
            self._mode = "simple"
        else:
            self._mode = _detect_mode(callback)

    # ---- 对外主入口 ----

    def __call__(self, stage, percent=None, detail="", force=False):
        if self._cb is None:
            return
        ev = make_event(stage, percent, detail)
        if not self._should_emit(ev, force):
            return
        self.last_event = ev
        try:
            self._emit(ev)
        except Exception:                       # noqa: BLE001
            pass                                # 进度上报失败绝不打断主流程

    def raw(self, payload, force=False):
        """直接发一个已经构造好的事件（或旧的字符串）。"""
        if self._cb is None:
            return
        if isinstance(payload, str):
            self(stage=STAGE_ASR, detail=payload, force=force)
            return
        if isinstance(payload, dict):
            ev = dict(payload)
            ev.setdefault("index", stage_index(ev.get("stage", "")))
            ev.setdefault("total_steps", total_steps())
            ev.setdefault("running_text", STAGE_RUNNING_TEXT.get(ev.get("stage", ""), ""))
            if not self._should_emit(ev, force):
                return
            self.last_event = ev
            try:
                self._emit(ev)
            except Exception:                   # noqa: BLE001
                pass
            return
        self(force=force)

    def done(self, detail="", stage=None):
        """把当前/指定阶段标成 100% 完成（一定会发出去）。"""
        self(stage or self._last_stage or STAGE_FINALIZE, 100.0, detail, force=True)

    # ---- 内部 ----

    def _should_emit(self, ev, force) -> bool:
        stage = ev.get("stage", "")
        pct = ev.get("percent")
        if force:
            return True
        if stage != self._last_stage:
            return True                          # 换阶段一定要让用户看见
        if pct is None:
            return True                          # 没有百分比的阶段不节流（本来就很少）
        if pct >= 100.0 and self._last_pct < 100.0:
            return True                          # 完成那一刻一定要发
        now = self._now()
        if (now - self._last_t) < self._min_dt and abs(pct - self._last_pct) < self._min_dpct:
            return False
        return True

    def _now(self) -> float:
        if self._clock is None:
            import time
            self._clock = time.monotonic
        return self._clock()

    def _emit(self, ev):
        """真正调用外部回调（模式在构造时已经定好）。"""
        if self._mode == "simple":
            self._cb(self._simple_text(ev))
        else:
            self._cb(ev)
        # 记录节流状态
        self._last_t = self._now()
        self._last_pct = ev.get("percent") if ev.get("percent") is not None else -1e9
        self._last_stage = ev.get("stage", "")

    @staticmethod
    def _simple_text(ev) -> str:
        """给只会显示一行字的旧界面：把阶段和详情拼成一句人话。"""
        text = ev.get("running_text") or ev.get("title") or ""
        pct = ev.get("percent")
        detail = ev.get("detail") or ""
        if pct is not None:
            text = f"{text}　{pct:.0f}%"
        if detail:
            text = f"{text}　{detail}"
        return text.strip()
