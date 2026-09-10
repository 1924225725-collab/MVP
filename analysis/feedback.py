# ============================================================
# 人工反馈记录（v0.4 新增）—— 把用户的判断攒下来
# ============================================================
# AI 现在的判断还达不到人工剪辑师的水平，但用户的每一次
# 「喜欢 / 不喜欢」都是最真实的训练素材。
#
# v0.4 只做一件事：老老实实记在本地 feedback.json 里。
#   - 不上传服务器（用户明确要求）
#   - 不做分析、不做模型训练（那是 v0.5 / v1.0 的事）
#   - 但要把「当时那个片段长什么样」一起存下来（snapshot），
#     将来才能回答：用户喜欢的片段，到底有什么共同点？
#
# 文件在项目根目录：feedback.json
# ============================================================

import json
from datetime import datetime
from pathlib import Path

# 项目根目录（本文件在 analysis/ 里，往上两级）
BASE_DIR = Path(__file__).resolve().parent.parent


def feedback_path():
    """反馈文件的路径（读 config 里的文件名，默认 feedback.json）。"""
    try:
        from config import FEEDBACK_FILE
        return BASE_DIR / FEEDBACK_FILE
    except ImportError:
        return BASE_DIR / "feedback.json"


def _default_choices():
    """反馈选项（优先读 config，读不到就用这两个）。"""
    try:
        from config import FEEDBACK_CHOICES
        return list(FEEDBACK_CHOICES)
    except ImportError:
        return ["喜欢", "不喜欢"]


def _target(path=None):
    """确定要读写哪个文件（不传就用默认路径；测试时可以指向临时文件）。"""
    return Path(path) if path else feedback_path()


def _empty_records(path=None):
    """把坏掉的文件挪到旁边，然后重新开始记（不能因为文件坏了就丢反馈功能）。"""
    target = _target(path)
    if target.exists():
        backup = target.with_suffix(".corrupt.json")
        try:
            target.replace(backup)
            print(f"[反馈] {target.name} 格式坏了，已备份为 {backup.name}，重新记录")
        except OSError:
            pass
    return []


def load_feedback(path=None):
    """读出所有反馈记录（列表）。文件不存在或坏了 → 返回空列表。"""
    target = _target(path)
    if not target.exists():
        return []

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return _empty_records(path)

    if not isinstance(data, list):
        return _empty_records(path)
    return [r for r in data if isinstance(r, dict)]


def save_feedback(clip_id, user_choice, reason="", snapshot=None, path=None):
    """记一条反馈，返回写入后的记录内容。

    参数：
        clip_id     —— 片段身份证（v0.3 起每个高光都带，事件化之后就是事件 id）
        user_choice —— 「喜欢」或「不喜欢」
        reason      —— 原因（太普通 / 很好笑 / 缺上下文 …，可以自定义）
        snapshot    —— 可选，片段当时的信息（标题/时间/分数/等级），
                       将来分析「用户喜欢什么样的片段」要用

    同一个 clip_id 再反馈一次 → 覆盖旧记录（用户改主意了，以最新判断为准）。
    """
    target = _target(path)
    records = load_feedback(target)

    record = {
        "clip_id": str(clip_id),
        "user_choice": str(user_choice),
        "reason": str(reason or "").strip(),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    if snapshot and isinstance(snapshot, dict):
        record["snapshot"] = snapshot

    # 同 clip_id 覆盖：找到就替换，找不到就追加
    for i, old in enumerate(records):
        if old.get("clip_id") == record["clip_id"]:
            # snapshot 是片段的客观信息（标题/时间/分数），不随用户改主意而变。
            # 用户第二次反馈时往往只改态度、不带片段信息——这里把旧的继承下来，
            # 否则将来分析「用户喜欢什么样的片段」时会缺数据。
            if "snapshot" not in record and old.get("snapshot"):
                record["snapshot"] = old["snapshot"]
            records[i] = record
            break
    else:
        records.append(record)

    try:
        target.write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        print(f"[反馈] 写入失败（{e}），这条反馈没记上")
        return None

    return record


def feedback_stats(path=None):
    """一句人话的统计，给界面显示用：「已记录 12 条反馈（喜欢 8 / 不喜欢 4）」。"""
    records = load_feedback(path)
    if not records:
        return "还没有反馈记录"

    liked = sum(1 for r in records if r.get("user_choice") == "喜欢")
    disliked = len(records) - liked
    return f"已记录 {len(records)} 条反馈（喜欢 {liked} / 不喜欢 {disliked}）"


def get_feedback(clip_id, path=None):
    """查某个片段有没有被反馈过（界面上要把按钮状态显示出来）。"""
    for r in load_feedback(path):
        if r.get("clip_id") == str(clip_id):
            return r
    return None
