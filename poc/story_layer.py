"""
Story Layer + Chapter 层级架构离线验证原型（不修改主流程）

层级结构：
  整场直播 (51分钟)
    → Chapter 1: 开场互动+美军口粮测评 (~0-10min)
    → Chapter 2: 俄军/乌军口粮测评 (~10-35min)
    → Chapter 3: 晚餐+微波炉事件 (~35-51min)

    每个Chapter内：
      → Story 1: 拆包→发现→试吃→反应 (完整事件链)
      → Story 2: 下一个测评对象...

    每个Story内：
      → Event Discovery (现有event_cluster逻辑)
      → Event Judge (现有AI判断)
      → Event → Highlight (现有复审逻辑)

核心改进：
  1. Chapter提供"直播活动结构"上下文，让AI知道"我们在测哪个系列"
  2. Story提供"连续活动"语义，聚合时能识别"这是同一活动的延续"
  3. 软边界设计：跨Chapter取上下文不受限，只建议不强制
"""

import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ============== 配置 ==============
CHAPTER_WINDOW_MINUTES = 15  # 初步划分窗口（软边界）
STORY_GAP_SECONDS = 120       # Story内候选间隔阈值（秒）


# ============== 数据解析 ==============
def parse_transcript(path: str) -> List[Dict]:
    """解析文字稿为结构化segment列表"""
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
                if text:  # 跳过纯语气词
                    segments.append({
                        'start': h1*60+m1+s1,
                        'end': h2*60+m2+s2,
                        'text': text,
                        'line': ln.strip()
                    })
    return segments


def parse_candidates(highlights_json: str) -> List[Dict]:
    """从highlights.json提取所有候选（含被拒）"""
    with open(highlights_json, encoding='utf-8') as f:
        d = json.load(f)
    allh = d['highlights'] + d['rejected']
    candidates = []
    for h in allh:
        def ts2s(t):
            p = t.split(':')
            return int(p[0])*60+int(p[1]) if len(p)==2 else int(p[0])*3600+int(p[1])*60+int(p[2])
        candidates.append({
            'event_id': h.get('event_id'),
            'grade': h.get('grade'),
            'score': h.get('score'),
            'start': ts2s(h['start_time']),
            'end': ts2s(h['end_time']),
            'duration': h.get('duration', ts2s(h['end_time'])-ts2s(h['start_time'])),
            'title': h.get('title', ''),
            'summary': h.get('summary', ''),
            'source_count': h.get('source_count', 1),
            'split': h.get('split_by_ai', False),
        })
    return candidates


# ============== Chapter 划分 ==============
def identify_chapters(segments: List[Dict], candidates: List[Dict]) -> List[Dict]:
    """
    基于时间结构和候选分布识别Chapter边界。
    
    策略：
    1. 找时间密集区（候选聚集）
    2. 找对话主题切换点（通过关键词/话题）
    3. 强制最大窗口约束
    
    返回: [{"id": "ch-1", "start": s, "end": e, "theme": "...", "candidates": [...]}]
    """
    if not candidates:
        return []
    
    # 按时间排序候选
    sorted_cands = sorted(candidates, key=lambda x: x['start'])
    
    # 策略1: 基于候选密度找间隙（>5分钟无候选可能是Chapter边界）
    gaps = []
    for i in range(1, len(sorted_cands)):
        gap = sorted_cands[i]['start'] - sorted_cands[i-1]['end']
        if gap > 300:  # 5分钟空白
            gaps.append({
                'time': sorted_cands[i-1]['end'],
                'before': sorted_cands[i-1]['title'][:30],
                'after': sorted_cands[i]['title'][:30]
            })
    
    # 策略2: 基于时间段软划分（15分钟窗口）
    dur = max(c['end'] for c in sorted_cands)
    chapter_size = CHAPTER_WINDOW_MINUTES * 60
    
    chapters = []
    ch_start = 0
    ch_idx = 1
    
    while ch_start < dur:
        ch_end = ch_start + chapter_size
        ch_cands = [c for c in sorted_cands if ch_start <= c['start'] < ch_end]
        
        if ch_cands:
            # 尝试找主题（取该Chapter内候选的common keywords）
            theme = _detect_theme(ch_cands, segments)
            chapters.append({
                'id': f'ch-{ch_idx:02d}',
                'start': ch_start,
                'end': min(ch_end, dur),
                'theme': theme,
                'candidates': ch_cands,
            })
            ch_idx += 1
        
        ch_start = ch_end
    
    return chapters


def _detect_theme(candidates: List[Dict], segments: List[Dict]) -> str:
    """基于候选title和附近text检测Chapter主题"""
    # 收集该Chapter内的text
    ch_text = ' '.join([
        s['text'] for s in segments 
        if any(c['start']-30 <= s['start'] <= c['end']+30 for c in candidates)
    ])
    
    # 关键词检测
    keywords = {
        '美军口粮': ['美军', '美军口粮', 'single ration'],
        '俄军口粮': ['俄军', '俄军口粮', '俄罗斯'],
        '乌军口粮': ['乌军', '乌军口粮', '乌克兰'],
        '罐头测评': ['罐头', '牛肉罐头', '午餐肉'],
        '咖啡测评': ['咖啡', '美式', '奶精'],
        '晚餐/微波炉': ['米饭', '微波炉', '蛋糕', '牛腩', ' dinner'],
        '互动/抽奖': ['抽奖', '关注', '礼物', '粉丝'],
    }
    
    scores = {}
    for theme, words in keywords.items():
        score = sum(1 for w in words if w in ch_text or w in ' '.join(c['title'] for c in candidates))
        if score > 0:
            scores[theme] = score
    
    if scores:
        return max(scores, key=scores.get)
    return '直播互动'


# ============== Story 划分 ==============
def identify_stories(chapter: Dict, segments: List[Dict]) -> List[Dict]:
    """
    在Chapter内划分Story（连续活动）。
    
    策略：
    1. 找时间间隙（>STORY_GAP_SECONDS = 120s 可能是Story边界）
    2. 找话题切换（通过text关键词）
    3. 合并碎片（把相邻短事件合并成Story）
    """
    cands = chapter['candidates']
    if not cands:
        return []
    
    sorted_cands = sorted(cands, key=lambda x: x['start'])
    
    stories = []
    current_story = [sorted_cands[0]]
    
    for i in range(1, len(sorted_cands)):
        prev = sorted_cands[i-1]
        curr = sorted_cands[i]
        
        gap = curr['start'] - prev['end']
        
        # 如果间隙大且话题不同，可能是新Story
        if gap > STORY_GAP_SECONDS:
            stories.append({
                'chapter_id': chapter['id'],
                'candidates': current_story,
                'start': current_story[0]['start'],
                'end': current_story[-1]['end'],
                'duration': current_story[-1]['end'] - current_story[0]['start'],
            })
            current_story = [curr]
        else:
            current_story.append(curr)
    
    # 最后一个Story
    if current_story:
        stories.append({
            'chapter_id': chapter['id'],
            'candidates': current_story,
            'start': current_story[0]['start'],
            'end': current_story[-1]['end'],
            'duration': current_story[-1]['end'] - current_story[0]['start'],
        })
    
    return stories


# ============== 离线验证 ==============
def run_offline_experiment(transcript_path: str, highlights_path: str, output_path: str):
    """运行Story Layer离线实验"""
    print("=" * 70)
    print("Story Layer + Chapter 层级架构 - 离线验证")
    print("=" * 70)
    
    # 解析数据
    print("\n[1] 解析transcript和候选...")
    segments = parse_transcript(transcript_path)
    candidates = parse_candidates(highlights_path)
    print(f"    Transcript: {len(segments)} 段台词")
    print(f"    Candidates: {len(candidates)} 个事件")
    
    # 识别Chapter
    print("\n[2] 识别Chapter...")
    chapters = identify_chapters(segments, candidates)
    for ch in chapters:
        print(f"    {ch['id']}: {ch['start']//60:02d}:{ch['start']%60:02d}-{ch['end']//60:02d}:{ch['end']%60:02d} "
              f"({ch['end']-ch['start']//60}min) | 主题: {ch['theme']} | 候选: {len(ch['candidates'])}个")
    
    # 识别Story
    print("\n[3] 在Chapter内识别Story...")
    all_stories = []
    for ch in chapters:
        stories = identify_stories(ch, segments)
        all_stories.extend(stories)
        for st in stories:
            print(f"    {st['chapter_id']}/{st['start']//60:02d}-{st['end']//60:02d} "
                  f"({st['duration']}s) | 候选: {len(st['candidates'])}个")
    
    # 对比分析
    print("\n[4] 对比分析：当前B1 vs Story Layer构想")
    print("-" * 70)
    
    # 统计当前B1的碎片情况
    singles = [c for c in candidates if c['source_count'] == 1]
    small = [c for c in singles if c['duration'] <= 28]
    
    print(f"\n当前B1结果:")
    print(f"  总事件: {len(candidates)}")
    print(f"  单候选事件: {len(singles)}/{len(candidates)} ({len(singles)/len(candidates)*100:.0f}%)")
    print(f"  ≤28s碎片: {len(small)}/{len(candidates)}")
    print(f"  >60s完整事件: {sum(1 for c in candidates if c['duration'] > 60)}")
    
    # 统计Story Layer构想下的预期效果
    print(f"\nStory Layer构想:")
    print(f"  Chapter数: {len(chapters)}")
    print(f"  Story数: {len(all_stories)}")
    
    # 计算"Story内候选聚合率"
    merged_in_stories = sum(1 for st in all_stories if len(st['candidates']) > 1)
    print(f"  多候选Story: {merged_in_stories}/{len(all_stories)} ({merged_in_stories/len(all_stories)*100:.0f}%)")
    
    # 保存结果
    result = {
        'transcript_segments': len(segments),
        'total_candidates': len(candidates),
        'chapters': chapters,
        'stories': all_stories,
        'current_b1_stats': {
            'total_events': len(candidates),
            'single_candidate': len(singles),
            'small_frags_le28': len(small),
            'gt60_events': sum(1 for c in candidates if c['duration'] > 60),
        }
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n[5] 结果已保存到: {output_path}")
    print("\n" + "=" * 70)
    print("验证完成")
    print("=" * 70)
    return result


# ============== 主入口 ==============
if __name__ == '__main__':
    transcript_file = 'transcripts/测试视频2.txt'
    highlights_file = 'highlights_v2.json'
    output_file = 'poc/story_layer_result.json'
    
    run_offline_experiment(transcript_file, highlights_file, output_file)
