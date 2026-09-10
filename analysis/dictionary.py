# ============================================================
# 词库纠错（v0.4 新增）—— ASR 听错了，我们给它改回来
# ============================================================
# 语音识别（Whisper）不认识主播的名字、游戏名、品牌、网络热词，
# 经常把「伏特加」听成「福岛」，把主播名听成别的字。
# 词库纠错就是在识别完之后，按一张「错词 → 正确词」的对照表做替换。
#
# 这是 v0.4 的「基础版本」：只做纯字符串替换，不调用 AI。
# 用户说得很清楚——"暂不做复杂 AI 纠错"。
# 好处：零成本、零延迟、结果完全可预测（改了什么一眼能看到）。
#
# 词库文件在项目根目录：custom_dictionary.json
# ============================================================

import json
import re
from pathlib import Path

# V0.5：工作区根目录（开发态 = 项目根；桌面版 = %LOCALAPPDATA%\AILiveClipper）
import app_paths

BASE_DIR = app_paths.workspace_root()

# 词库默认分类（用户可以自己加分类，代码不限定死）
DEFAULT_CATEGORIES = ["主播名字", "游戏名称", "品牌", "网络热词", "其他"]

# 一行文字稿的样子：[00:12 - 00:15] 这句话的内容
# 分成两组：第 1 组是时间戳（含方括号），第 2 组是台词
_LINE_RE = re.compile(r"^(\[[^\]]*\])(.*)$")


def dictionary_path():
    """词库文件的路径（读 config 里的文件名，默认 custom_dictionary.json）。"""
    try:
        from config import CUSTOM_DICTIONARY_FILE
        return BASE_DIR / CUSTOM_DICTIONARY_FILE
    except ImportError:
        return BASE_DIR / "custom_dictionary.json"


def load_dictionary(path=None):
    """读词库文件 → 扁平对照表 {错词: 正确词}。

    词库文件是按分类分组的（主播名字 / 游戏名称 / 品牌 / 网络热词 / 其他），
    这里把所有分类摊平成一张表，用起来简单。

    容错原则（和项目其他地方一致：一个文件翻车不能带崩整场分析）：
      - 文件不存在 → 返回空表（等于不纠错）
      - JSON 写坏了 → 返回空表，并把原因打印出来
      - 以 _ 开头的键（比如 "_说明"）是给人看的注释，跳过
    """
    path = Path(path) if path else dictionary_path()
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"[词库] {path.name} 读不出来（{e}），本次不纠错")
        return {}

    if not isinstance(data, dict):
        print(f"[词库] {path.name} 格式不对（应该是分类 → 词条 的结构），本次不纠错")
        return {}

    mapping = {}
    for key, value in data.items():
        if str(key).startswith("_"):
            continue                      # 注释字段，跳过
        if isinstance(value, dict):
            # 正常情况：一个分类下面是「错词: 正确词」
            for wrong, right in value.items():
                if str(wrong).startswith("_"):
                    continue
                wrong = str(wrong).strip()
                right = str(right).strip()
                if wrong and right:
                    mapping[wrong] = right
        elif isinstance(value, str):
            # 也兼容扁平写法（不分分类，直接 错词: 正确词）
            wrong = str(key).strip()
            right = value.strip()
            if wrong and right:
                mapping[wrong] = right
    return mapping


def apply_correction(text, mapping=None):
    """按对照表替换一段文字，返回替换后的结果。

    细节：先替换长的词，再替换短的词。
    否则「伏特加」和「伏特加酒」同时存在时，短词会先把长词咬掉一半。
    """
    if not text:
        return text
    if mapping is None:
        mapping = load_dictionary()
    if not mapping:
        return text

    for wrong in sorted(mapping.keys(), key=len, reverse=True):
        if wrong in text:
            text = text.replace(wrong, mapping[wrong])
    return text


def correct_segments(segments, mapping=None):
    """纠正一组识别结果（Segment 对象或 dict 都支持），原地修改 text。

    返回一共改了几处（0 表示词库没命中任何东西）。
    支持两种输入，是因为流程里有两种形态：
      - ASR 刚出来的是 Segment 对象（asr/base.py 定义）
      - 从文字稿解析出来的是 dict（analysis/transcript_parser.py 定义）
    """
    if mapping is None:
        mapping = load_dictionary()
    if not mapping or not segments:
        return 0

    hits = 0
    for seg in segments:
        if isinstance(seg, dict):
            old = seg.get("text", "")
            new = apply_correction(old, mapping)
            if new != old:
                seg["text"] = new
                hits += 1
        else:
            old = getattr(seg, "text", "")
            new = apply_correction(old, mapping)
            if new != old:
                seg.text = new
                hits += 1
    return hits


def correct_transcript_file(path, mapping=None):
    """纠正一个已存在的文字稿文件：只改台词，时间戳一个字都不动。

    返回一共改了几行（0 表示没有命中）。

    为什么必须按行拆开处理：
    文字稿每行是「[00:12 - 00:15] 台词」，如果整篇直接替换，
    万一某个词库条目刚好和时间格式沾边，时间轴就毁了。
    拆开后只对台词部分动手，安全。
    """
    path = Path(path)
    if mapping is None:
        mapping = load_dictionary()
    if not mapping or not path.exists():
        return 0

    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        print(f"[词库] 文字稿读不出来（{e}），跳过纠错")
        return 0

    changed_lines = 0
    out_lines = []
    for line in content.splitlines():
        m = _LINE_RE.match(line)
        if m:
            stamp, speech = m.group(1), m.group(2)
            fixed = apply_correction(speech, mapping)
            if fixed != speech:
                changed_lines += 1
            out_lines.append(stamp + fixed)
        else:
            # 不是标准格式的行（空行、标题行之类），整行替换
            fixed = apply_correction(line, mapping)
            if fixed != line:
                changed_lines += 1
            out_lines.append(fixed)

    if changed_lines:
        path.write_text("\n".join(out_lines), encoding="utf-8")
    return changed_lines


def create_dictionary_template(path=None):
    """在指定位置生成一份带说明的词库模板（文件已存在就不动它）。

    返回 True 表示新生成了文件。
    """
    path = Path(path) if path else dictionary_path()
    if path.exists():
        return False

    template = {
        "_说明": (
            "ASR 纠错词库：左边是语音识别容易听错的词，右边是正确的词。"
            "按分类整理只是为了好管理，程序会把所有分类摊平使用。"
            "改完保存，下次识别新视频、或对已有文字稿执行纠错时就会生效。"
            "（以 _ 开头的键是注释，不会被当成词条）"
        ),
        "主播名字": {
            "_提示": "主播、连麦嘉宾、常提到的朋友的名字",
        },
        "游戏名称": {
            "和平经营": "和平精英",
            "英雄连门": "英雄联盟",
        },
        "品牌": {
            "福岛": "伏特加",
        },
        "网络热词": {
            "_提示": "直播间常用梗、缩写、口癖，识别经常写错的",
        },
        "其他": {
            "_提示": "上面分类放不下的都写这里",
        },
    }
    path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return True


def dictionary_stats(mapping=None):
    """返回一句人话的统计，给日志/界面用：「共 3 条纠错规则」。"""
    if mapping is None:
        mapping = load_dictionary()
    return f"共 {len(mapping)} 条纠错规则"
