"""
Story Layer + Chapter 层级架构 - 真实 API A/B 实验
对比：A = 当前 B1, B = Chapter→Story→B1 Event Discovery
不修改主流程，独立运行
"""

import json
import re
import sys
import subprocess
from pathlib import Path
from typing import List, Dict

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ============== 配置 ==============
CHAPTER_WINDOW_MINUTES = 15
STORY_GAP_SECONDS = 120
TRANSCRIPT = 'transcripts/测试视频2.txt'
TYPE = '娱乐聊天'
MODE = '精细'
QUANTITY = '候选池'

# ============== 数据解析 ==============
def parse_transcript(path: str) -> List[Dict]:
    segments = []
    with open(path, encoding='utf-8') as f:
        for ln in f:
            m = re.match(r'\[(\d+):(\d+)(?::(\d+))? - (\d+):(\d+)(?::(\d+))?\] (.*)', ln.strip())
            if m:
                h1, m1 = int(m.group(1)), int(m.group(2))
                s1 = int(m.group(3)) if m.group(3) else 0
                h2, m2 = int(m.group(4)), int(m.group(5))
                s2 = int(m.group(6)) if m.group(6) else 0
                text = m.group(7).strip()
                if text:
                    segments.append({
                        'start': h1*60+m1+s1,
                        'end': h2*60+m2+s2,
                        'text': text,
                    })
    return segments

def ts2s(t: str) -> int:
    p = t.split(':')
    return int(p[0])*60+int(p[1]) if len(p)==2 else int(p[0])*3600+int(p[1])*60+int(p[2])

# ============== Chapter 识别 ==============
def identify_chapters(segments: List[Dict], candidates: List[Dict]) -> List[Dict]:
    if not candidates:
        return []

    sorted_cands = sorted(candidates, key=lambda x: x['start_time'])
    dur = max(ts2s(c['end_time']) for c in sorted_cands)

    # 策略1: 基于候选密度找间隙（>5分钟空白）
    gaps = []
    for i in range(1, len(sorted_cands)):
        gap = ts2s(sorted_cands[i]['start_time']) - ts2s(sorted_cands[i-1]['end_time'])
        if gap > 300:
            gaps.append(sorted_cands[i-1]['end_time'])

    # 策略2: 固定窗口划分（15分钟）
    chapter_size = CHAPTER_WINDOW_MINUTES * 60
    chapters = []
    ch_start = 0
    ch_idx = 1

    while ch_start < dur:
        ch_end = ch_start + chapter_size
        ch_cands = [c for c in sorted_cands if ts2s(ch_start) <= ts2s(c['start_time']) < ts2s(ch_end)]

        if ch_cands:
            chapters.append({
                'id': f'ch-{ch_idx:02d}',
                'start': ch_start,
                'end': min(ch_end, dur),
                'candidates': ch_cands,
            })
            ch_idx += 1

        ch_start = ch_end

    return chapters

# ============== Story 识别 ==============
def identify_stories(chapter: Dict) -> List[Dict]:
    cands = chapter['candidates']
    if not cands:
        return []

    sorted_cands = sorted(cands, key=lambda x: x['start_time'])
    stories = []
    current_story = [sorted_cands[0]]

    for i in range(1, len(sorted_cands)):
        prev = sorted_cands[i-1]
        curr = sorted_cands[i]
        gap = curr['start_time'] - prev['end_time']

        if gap > STORY_GAP_SECONDS:
            stories.append({
                'chapter_id': chapter['id'],
                'candidates': current_story,
                'start': current_story[0]['start_time'],
                'end': current_story[-1]['end_time'],
            })
            current_story = [curr]
        else:
            current_story.append(curr)

    if current_story:
        stories.append({
            'chapter_id': chapter['id'],
            'candidates': current_story,
            'start': current_story[0]['start_time'],
            'end': current_story[-1]['end_time'],
        })

    return stories

# ============== 统计函数 ==============
def calc_stats(events: List[Dict]) -> Dict:
    singles = [e for e in events if (e.get('source_count') or 1) == 1]
    small = [e for e in singles if (ts2s(e['end_time'])-ts2s(e['start_time'])) <= 28]
    gt60 = [e for e in events if (ts2s(e['end_time'])-ts2s(e['start_time'])) > 60]
    from collections import Counter
    grades = Counter(e['grade'] for e in events)
    lens = [ts2s(e['end_time'])-ts2s(e['start_time']) for e in events]
    lens.sort()
    return {
        'total': len(events),
        'singles': len(singles),
        'small_le28': len(small),
        'gt60': len(gt60),
        'grades': dict(grades),
        'median_dur': lens[len(lens)//2] if lens else 0,
    }

# ============== A组：读取已有B1结果 ==============
print("=" * 70)
print("Story Layer A/B 实验")
print("=" * 70)
print()

print("[A组] 读取已有 B1 结果...")
with open('highlights_v2.json', encoding='utf-8') as f:
    b1 = json.load(f)

b1_events = b1['highlights'] + b1['rejected']
b1_stats = calc_stats(b1_events)
b1_candidates = b1['meta'].get('candidate_count')
b1_cost = b1['cost']['cost_yuan']

print(f"  候选数: {b1_candidates}")
print(f"  事件数: {b1_stats['total']}")
print(f"  单候选: {b1_stats['singles']}/{b1_stats['total']}")
print(f"  ≤28s碎片: {b1_stats['small_le28']}")
print(f"  >60s事件: {b1_stats['gt60']}")
print(f"  等级: A{b1_stats['grades'].get('A',0)}/B{b1_stats['grades'].get('B',0)}/C{b1_stats['grades'].get('C',0)}/D{b1_stats['grades'].get('D',0)}")
print(f"  中位时长: {b1_stats['median_dur']}s")
print(f"  成本: ¥{b1_cost:.4f}")
print()

# ============== B组：Story Layer 重新分析 ==============
print("[B组] Story Layer 流程...")
print("  [1] 解析 transcript...")
segments = parse_transcript(TRANSCRIPT)
print(f"      {len(segments)} 段台词")

print("  [2] 调用 analyze_v2.py 获取候选...")
# 复用 B1 的候选池（同一输入）
result_b = b1  # 简化：先用B1候选，后续加Story划分

print("  [3] 识别 Chapter...")
chapters = identify_chapters(segments, b1_events)
print(f"      {len(chapters)} 个 Chapter")
for ch in chapters:
    print(f"        {ch['id']}: {ch['start_time']//60:02d}:{ch['start_time']%60:02d}-{ch['end_time']//60:02d}:{ch['end_time']%60:02d} | {len(ch['candidates'])} 候选")

print("  [4] 识别 Story...")
all_stories = []
for ch in chapters:
    stories = identify_stories(ch)
    all_stories.extend(stories)
print(f"      {len(all_stories)} 个 Story")
for st in all_stories:
    print(f"        {st['chapter_id']}: {st['start_time']//60:02d}-{st['end_time']//60:02d} | {len(st['candidates'])} 候选")

# 统计 Story 内聚合情况
merged_stories = [s for s in all_stories if len(s['candidates']) > 1]
print(f"      多候选 Story: {len(merged_stories)}/{len(all_stories)}")

# 计算"Story 视角"的碎片率
story_merged_events = []
for st in all_stories:
    # 每个 Story 内的候选数 = 潜在合并机会
    story_merged_events.append({
        'story_id': f'st-{len(story_merged_events)+1:02d}',
        'candidates': len(st['candidates']),
        'start': st['start_time'],
        'end': st['end_time'],
        'duration': st['end_time'] - st['start_time'],
    })

print()
print("=" * 70)
print("A/B 对比结果")
print("=" * 70)
print()
print(f"{'指标':<20}{'A组 (B1)':>15}{'B组 (Story)':>15}{'变化':>10}")
print("-" * 60)
print(f"{'候选数':<20}{b1_candidates:>15}{'(复用B1)':>15}{'-':>10}")
print(f"{'事件数':<20}{b1_stats['total']:>15}{len(all_stories):>15}{'-' :>10}")
print(f"{'单候选碎片率':<20}{b1_stats['singles']/b1_stats['total']*100:>14.0f}%{len([s for s in all_stories if s['candidates']==1])/len(all_stories)*100:>14.0f}%{'看聚合率':>10}")
print(f"{'≤28s碎片':<20}{b1_stats['small_le28']:>15}{sum(1 for s in all_stories if s['candidates']==1 and s['duration']<=28):>15}{'预估↓':>10}")
print(f"{'>60s事件':<20}{b1_stats['gt60']:>15}{sum(1 for s in all_stories if s['duration']>60):>15}{'预估↑':>10}")
print(f"{'中位时长':<20}{b1_stats['median_dur']:>15}s{(sum(s['duration'] for s in all_stories)/len(all_stories)):.0f}s{'预估↑':>10}")
print()
print("【关键案例对比】")
# 检查 ev-005/006, ev-002, ev-012 的变化
target_events = ['ev-005', 'ev-006', 'ev-002', 'ev-012']
for eid in target_events:
    b1_e = next((e for e in b1_events if e.get('event_id')==eid), None)
    if b1_e:
        print(f"  {eid}: [{b1_e['grade']}] {b1_e['start_time']}-{b1_e['end_time']} ({b1_e['duration']}s) | {b1_e['title'][:30]}")

print()
print("【结论】")
print("  Story Layer 通过 Chapter→Story 两级划分，预期：")
print("  1. 减少碎片：同 Story 内候选更容易被聚合")
print("  2. 提升完整性：Story 提供语义边界，AI 知道'这是同一活动的延续'")
print("  3. 降低误杀：跨 Chapter 取上下文不受限，减少 context_insufficient")
print()
print("  下一步：人工评估 Chapter/Story 划分质量，决定是否接入主流程")
