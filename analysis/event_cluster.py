# ============================================================
# 本地粗聚类（v0.4 步骤 2）—— 只提「可能是同一件事」，不替 AI 做决定
# ============================================================
# 这一层的职责边界非常明确（需求原文）：
#   1. 本地规则**只负责提出「可能属于同一事件」的候选分组**
#   2. AI 才负责最终判断两个候选是不是同一件事
#   3. 本地规则**不能**因为时间距离、关键词不同等原因直接删除候选
#   4. **不允许**「超过 X 秒就必须拆分」这种硬规则
#
# 所以这里做的是：给候选两两打一个「关联分」，分够高就连一条边，
# 最后取连通分量——A 和 B 相连、B 和 C 相连，ABC 就是一簇。
# 链式连接是关键：一个持续 10 分钟的事件，只要中间有连续的候选，
# 就能一路串起来，不会被某个固定时长硬生生切成好几段。
#
# 打分用的都是 soft signal（连续函数），没有任何一条能单独决定生死：
#   - 时间距离：越近越高，5 分钟外才衰减到 0（不是「超过 60 秒就断开」）
#   - 时间重叠：两个候选时间范围重叠得越多越可能是同一件事
#   - 主题相似：标题 + 理由抽中文二元组（不需要装分词库）算重叠系数
#   - 相邻加分：时间上紧挨着（中间没别的候选）的两个候选加分
# ============================================================

import re
from pathlib import Path

# ---------- 默认配置（config.py 里有 EVENT_CLUSTER 就用 config 的） ----------
DEFAULT_CONFIG = {
    # 关联分超过这个数就认为「可能是同一件事」，连一条边
    "merge_threshold": 0.42,
    # 时间距离的 soft 窗口（秒）：间隔达到这个数时时间分衰减到 0
    "soft_time_window": 300,
    # 三个信号的权重（加起来 = 1）
    "weights": {"time": 0.30, "overlap": 0.25, "topic": 0.30},
    # 时间上紧挨着（中间没有别的候选）的额外加分
    "adjacency_bonus": 0.15,
    # 主题相似只看标题和理由（AI 写的，主题集中；原文太吵）
    "use_context_for_topic": False,
}


def _get_config(override=None):
    """读配置：优先用调用方传的，其次 config.EVENT_CLUSTER，最后用默认值。"""
    cfg = dict(DEFAULT_CONFIG)
    try:
        from config import EVENT_CLUSTER
        if isinstance(EVENT_CLUSTER, dict):
            cfg.update(EVENT_CLUSTER)
    except ImportError:
        pass
    if override:
        cfg.update(override)
    # weights 要做一次深合并，否则只传一个键会把另外两个冲掉
    if override and "weights" in override:
        w = dict(DEFAULT_CONFIG["weights"])
        try:
            from config import EVENT_CLUSTER
            if isinstance(EVENT_CLUSTER, dict) and "weights" in EVENT_CLUSTER:
                w.update(EVENT_CLUSTER["weights"])
        except ImportError:
            pass
        w.update(override["weights"])
        cfg["weights"] = w
    return cfg


def _to_seconds(value):
    """'12:34' / '01:02:03' / 123 → 秒。不认识就返回 None。"""
    from .transcript_parser import _time_to_seconds
    if isinstance(value, (int, float)):
        return float(value)
    return _time_to_seconds(str(value))


# ---------- soft signal 1：时间距离 ----------

def _time_score(gap, window):
    """间隔越小越可能是同一件事——连续衰减，不是硬阈值。

    gap=0 → 1.0；gap=窗口一半 → 0.5；gap≥窗口 → 0。
    注意：这是「加分项」，单独低不会导致断开，只是相关度变小。
    """
    if gap is None or window <= 0:
        return 0.0
    if gap <= 0:
        return 1.0
    return max(0.0, 1.0 - gap / float(window))


# ---------- soft signal 2：时间范围重叠 ----------

def _overlap_score(a_start, a_end, b_start, b_end):
    """两个候选的时间范围重叠了多少（重叠系数，对小片段友好）。"""
    if None in (a_start, a_end, b_start, b_end):
        return 0.0
    overlap = min(a_end, b_end) - max(a_start, b_start)
    if overlap <= 0:
        return 0.0
    shorter = min(a_end - a_start, b_end - b_start)
    if shorter <= 0:
        # 有的候选是「瞬间」（起止相同），只要落在对方范围内就算完全重叠
        return 1.0
    return min(1.0, overlap / shorter)


# ---------- soft signal 3：主题相似 ----------

_NON_WORD_RE = re.compile(r"[^一-龥a-zA-Z0-9]")


def _bigrams(text):
    """中文二元组集合：'打开包装' → {'打开','开包','包装'}。

    不需要装分词库也能比较中文相似度。
    """
    if not text:
        return set()
    clean = _NON_WORD_RE.sub("", str(text))
    if not clean:
        return set()
    if len(clean) == 1:
        return {clean}
    return {clean[i:i + 2] for i in range(len(clean) - 1)}


def _topic_score(text_a, text_b):
    """主题重叠系数 = 交集 / 较小的那个集合（对短标题友好）。"""
    set_a, set_b = _bigrams(text_a), _bigrams(text_b)
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    if inter == 0:
        return 0.0
    return inter / min(len(set_a), len(set_b))


# ---------- 主流程 ----------

def _candidate_text(c, use_context=False):
    """拼出用于比较主题的文本（标题 + 理由，可选加原文）。"""
    parts = [str(c.get("title", "")), str(c.get("reason", ""))]
    if use_context:
        parts.append(str(c.get("context", "")))
    return " ".join(p for p in parts if p)


def build_clusters(candidates, config=None, story_groups=None):
    """把候选粗聚成若干簇，返回 cluster 列表。

    参数：
      candidates     —— 候选列表（每个候选应有 story_id 字段）
      config         —— 聚类配置（覆盖默认值）
      story_groups   —— {story_id: [候选下标列表]}，可选。
                        提供后：
                        · 同 Story 内候选配对 +0.25 关联分（强连续性先验）
                        · 跨 Story 候选配对 -0.15 关联分（软减速）
                        · __unknown__ 视为独立分群，与其他候选均视为跨 Story
                        不提供则行为与 v0.4 之前完全一致（不崩）。

    返回结构（每个 cluster）：
        {
          "cluster_id": "cluster-001",
          "members": [候选下标, ...],       # 指向原 candidates 列表
          "start": 秒, "end": 秒,           # 整簇覆盖的时间范围
          "links": [                         # 审计用：哪些配对因为什么连上了
              {"a": 0, "b": 1, "score": 0.62,
               "detail": {"time": 0.8, "overlap": 0.0, "topic": 0.55,
                          "adjacent": True, "same_story": True}}
          ]
        }

    铁律：每个候选必须且只能出现在一个簇里——一个都没删。
    哪怕它跟谁都不像，也会自成一簇（AI 那边再判断，本地不替它做决定）。
    """
    cfg = _get_config(config)
    weights = cfg["weights"]
    threshold = cfg["merge_threshold"]
    window = cfg["soft_time_window"]
    bonus = cfg["adjacency_bonus"]
    use_ctx = cfg["use_context_for_topic"]

    # v0.4.1：Story 强先验
    #   - 同 Story 内候选配对额外 +0.25（强连续性先验，默认倾向保持同一 Event）
    #   - 跨 Story 候选配对 -0.15（软减速，只有明确新事件证据才允许合并）
    #   - __unknown__ 视为独立分群，与其他所有候选均视为跨 Story
    story_bonus = 0.25 if story_groups is not None else 0.0
    cross_story_penalty = -0.15 if story_groups is not None else 0.0
    # 快速查找：候选下标 → story_id
    idx_to_story = {}
    if story_groups is not None:
        for sid, idxs in story_groups.items():
            for idx in idxs:
                idx_to_story[idx] = sid

    n = len(candidates)
    if n == 0:
        return []

    # 先把每个候选的时间换算成秒，算不出来就先记 None（后面当 0 分处理，不删候选）
    times = []
    for c in candidates:
        s = _to_seconds(c.get("start_time"))
        e = _to_seconds(c.get("end_time"))
        if s is not None and e is not None and e < s:
            s, e = e, s          # AI 偶尔会把起止写反，就地纠正不丢弃
        times.append((s, e))

    # 按开始时间排序，方便算「相邻」（中间有没有别的候选）
    order = sorted(range(n), key=lambda i: (times[i][0] is None, times[i][0] or 0))

    # 并查集：连边 → 合并
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    links = []
    for i in range(n):
        for j in range(i + 1, n):
            a_s, a_e = times[i]
            b_s, b_e = times[j]

            # 信号 1：时间距离（结束到开始之间的空白）
            if a_s is None or b_s is None:
                t_score = 0.0
            else:
                gap = max(b_s - (a_e if a_e is not None else a_s),
                          a_s - (b_e if b_e is not None else b_s))
                gap = max(gap, 0)          # 有重叠时间时 gap 为负，按 0 算（最亲近）
                t_score = _time_score(gap, window)

            # 信号 2：时间重叠
            o_score = _overlap_score(a_s, a_e, b_s, b_e)

            # 信号 3：主题相似
            k_score = _topic_score(_candidate_text(candidates[i], use_ctx),
                                   _candidate_text(candidates[j], use_ctx))

            # 信号 4：相邻（时间序上紧挨着，中间没有第三个候选）
            adjacent = False
            try:
                pi, pj = order.index(i), order.index(j)
                adjacent = abs(pi - pj) == 1
            except ValueError:
                adjacent = False

            # Story 关系信号：同 Story 加分，跨 Story 减速
            # __unknown__ 视为独立分群，不与任何候选建立连接
            story_signal = 0.0
            has_unknown = (i in idx_to_story and idx_to_story.get(i) == "__unknown__") or \
                          (j in idx_to_story and idx_to_story.get(j) == "__unknown__")
            if not has_unknown and story_bonus > 0 and i in idx_to_story and j in idx_to_story:
                si, sj = idx_to_story.get(i), idx_to_story.get(j)
                if si and sj and si == sj:
                    story_signal = story_bonus          # 同 Story：强先验 +0.25
                elif si and sj:
                    story_signal = cross_story_penalty   # 跨 Story：软减速 -0.15
            total = (weights.get("time", 0) * t_score
                     + weights.get("overlap", 0) * o_score
                     + weights.get("topic", 0) * k_score
                     + (bonus if adjacent else 0.0)
                     + story_signal)

            if total >= threshold:
                union(i, j)
                links.append({
                    "a": i, "b": j, "score": round(total, 3),
                    "detail": {
                        "time": round(t_score, 3),
                        "overlap": round(o_score, 3),
                        "topic": round(k_score, 3),
                        "adjacent": adjacent,
                        "same_story": (idx_to_story.get(i) == idx_to_story.get(j)
                                       and i in idx_to_story
                                       and idx_to_story.get(i) != "__unknown__"),
                        "cross_story_penalty": story_signal < 0,
                    },
                })

    # 按连通分量收拢成簇
    groups = {}
    for idx in range(n):
        groups.setdefault(find(idx), []).append(idx)

    clusters = []
    for root in sorted(groups, key=lambda r: min(groups[r])):
        members = sorted(groups[root])
        starts = [times[m][0] for m in members if times[m][0] is not None]
        ends = [times[m][1] for m in members if times[m][1] is not None]
        clusters.append({
            "cluster_id": f"cluster-{len(clusters) + 1:03d}",
            "members": members,
            "start": min(starts) if starts else None,
            "end": max(ends) if ends else None,
            "links": [l for l in links if l["a"] in members and l["b"] in members],
        })
    return clusters


# ---------- 上下文窗口（给 AI 判断用） ----------

def build_cluster_context(segments, cluster, before=90, after=90, char_limit=4000):
    """按簇的时间范围取上下文原文：往前 before 秒、往后 after 秒。

    返回带时间戳的原文（和文字稿同格式），AI 靠它看清前因后果。
    时间算不出来（AI 返回的时间格式异常）→ 退化成拼候选自己的 context，不崩。
    """
    start, end = cluster.get("start"), cluster.get("end")
    if start is None or end is None:
        return ""

    lo, hi = start - before, end + after
    lines, used = [], 0
    for seg in segments:
        if seg["start"] < hi and seg["end"] > lo:
            line = (f"[{_fmt(seg['start'])} - {_fmt(seg['end'])}] {seg['text']}")
            if used + len(line) > char_limit:
                break
            lines.append(line)
            used += len(line)
    return "\n".join(lines)


def _fmt(seconds):
    """秒 → mm:ss（超过 1 小时会显示成 mmm:ss，和文字稿现有格式一致）。"""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


# ---------- 审计 ----------

def cluster_stats(clusters):
    """一句人话统计，给日志/开发者模式用。"""
    if not clusters:
        return "没有候选，无需聚类"
    multi = [c for c in clusters if len(c["members"]) > 1]
    merged = sum(len(c["members"]) for c in multi)
    return (f"{len(clusters)} 簇（其中 {len(multi)} 簇含多个候选，"
            f"共涉及 {merged} 个候选）")
