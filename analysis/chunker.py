# ============================================================
# chunker —— 智能分区层（v0.3 阶段 1）
#
# 职责：顺着时间轴把整场直播装箱打包：
#   热区（信号分高的分钟段）→ 细切，每片最多 3 分钟，AI 看得仔细
#   普通区                  → 粗切，每片最多 10 分钟，省 token
#
# 铁律：时间轴 100% 覆盖。
#   从第 0 秒到最后一秒，每一秒都必须属于某一个区块。
#   绝不允许出现「这段没意思，跳过」——
#   有没有意思是 Phase 2 AI 海选的裁判权，这一层无权判死刑。
# ============================================================

import config


def format_time(seconds: int) -> str:
    """秒 → 人看的时间。83 → '01:23'；3612 → '01:00:12'（够 1 小时就带小时）。"""
    seconds = int(seconds)
    if seconds >= 3600:
        hours, rest = divmod(seconds, 3600)
        minutes, sec = divmod(rest, 60)
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    minutes, sec = divmod(seconds, 60)
    return f"{minutes:02d}:{sec:02d}"


def _merge_hot_regions(buckets: list) -> list:
    """把热区中间的短暂冷场也算进热区。

    直播里爆点不是精确卡分钟的：第 3 分钟很炸、第 4 分钟缓一口气、
    第 5 分钟又炸——这三分钟应该当成一整片热区处理，
    不然会被冷场分钟切成两半，两边都看不全。
    """
    n = len(buckets)
    hot = [b["hot"] for b in buckets]   # 先抄一份，别改动原数据

    i = 0
    while i < n:
        if not hot[i]:
            # 找出从 i 开始的连续冷场段 [i, j)
            j = i
            while j < n and not hot[j]:
                j += 1
            gap = j - i
            # 冷场前后都是热区、且冷场很短（<= 桥接分钟数）→ 填成热区
            if 0 < i and j < n and gap <= config.BRIDGE_MINUTES:
                for k in range(i, j):
                    hot[k] = True
            i = j
        else:
            i += 1
    return hot


def build_chunks(buckets: list, segments: list, hot_seconds: int = None, normal_seconds: int = None):
    """把分钟格子装箱成区块（chunk），返回区块列表。

    hot_seconds / normal_seconds 可以覆盖 config 里的默认切法
    （Token 超预算时的「降级 1：粗切」就靠它们把普通区切得更大、区块数更少）。
    不传就用 config.py 的默认值——老代码的调用方式完全不受影响。

    每个区块是一个 dict：
        {"start", "end"      —— 区块起止（秒）
         "hot"               —— 是否热区（热区细切、普通区粗切）
         "score"             —— 区块内信号分总和（以后给 AI 报参考热度用）
         "speech_start/end"  —— 区块内实际第一句/最后一句台词的时间
         "char_count"        —— 区块内台词总字数（Phase 2 控 token 用）
         "segments"          —— 区块内的台词列表
         "text"              —— 区块台词拼成的带时间戳文本（直接可以发给 AI）}
    """
    if not buckets or not segments:
        return []

    hot_max = hot_seconds or config.HOT_CHUNK_SECONDS
    normal_max = normal_seconds or config.NORMAL_CHUNK_SECONDS

    total = max(s["end"] for s in segments)
    hot_flags = _merge_hot_regions(buckets)

    # ---------- 第 1 步：顺着时间轴装箱 ----------
    chunks = []
    current = None
    for bucket, is_hot in zip(buckets, hot_flags):
        max_len = hot_max if is_hot else normal_max

        # 需要开新箱的三种情况：还没开箱 / 冷热属性变了 / 再装就超长了
        if (
            current is None
            or current["hot"] != is_hot
            or bucket["end"] - current["start"] > max_len
        ):
            if current is not None:
                chunks.append(current)
            current = {
                "hot": is_hot,
                "start": bucket["start"],
                "end": bucket["end"],
                "score": 0,
            }
        else:
            current["end"] = bucket["end"]

        current["score"] += bucket["score"]

    if current is not None:
        chunks.append(current)

    # 最后一箱的结尾可能因为「整分钟对齐」超出真实时长，夹回去
    chunks[-1]["end"] = min(chunks[-1]["end"], total)

    # ---------- 第 2 步：给每个箱子装上台词 ----------
    for chunk in chunks:
        segs = [
            s for s in segments
            if s["start"] < chunk["end"] and s["end"] > chunk["start"]
        ]
        chunk["segments"] = segs
        chunk["speech_start"] = segs[0]["start"] if segs else chunk["start"]
        chunk["speech_end"] = segs[-1]["end"] if segs else chunk["end"]
        chunk["text"] = "\n".join(
            f"[{format_time(s['start'])} - {format_time(s['end'])}] {s['text']}"
            for s in segs
        )
        chunk["char_count"] = len(chunk["text"].replace("\n", ""))

    return chunks


def check_coverage(chunks: list, total_seconds: int) -> list:
    """验收铁律：区块必须不多、不少、不重叠地盖住 [0, 总时长]。

    返回问题列表；空列表 = 100% 覆盖，验收通过。
    """
    problems = []
    position = 0   # 时间轴上的"游标"：到目前为止已经盖到哪了

    for chunk in chunks:
        if chunk["start"] > position:
            problems.append(f"漏盖了 {format_time(position)} - {format_time(chunk['start'])}")
        elif chunk["start"] < position:
            problems.append(f"重叠了 {format_time(chunk['start'])} 附近")
        position = chunk["end"]

    if position < total_seconds:
        problems.append(f"结尾漏盖了 {format_time(position)} - {format_time(total_seconds)}")
    if position > total_seconds:
        problems.append(f"区块总长超出真实时长：{format_time(position)} > {format_time(total_seconds)}")

    return problems
