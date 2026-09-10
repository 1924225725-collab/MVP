import sys; sys.path.insert(0, \".\")
"""
Story Segmentation PoC - 基于Chapter划分Story
目标：在每个Chapter内识别"连续活动/因果链"，而非机械切分
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analysis.deepseek_client import call_deepseek

print("=" * 70)
print("Story Segmentation PoC - Chapter内划分连续活动")
print("=" * 70)
print()

# 加载数据
with open('highlights_v2.json', encoding='utf-8') as f:
    b1 = json.load(f)
with open('poc/fixtures/ai_chapter_result.json', encoding='utf-8') as f:
    chapters = json.load(f)

events = b1['highlights'] + b1['rejected']

def ts2s(t):
    p = t.split(':')
    return int(p[0])*60+int(p[1])

# 为每个Chapter构造prompt，让AI划分Story
all_stories = []

for ch in chapters['chapters']:
    ch_id = ch['chapter_id']
    ch_start = ts2s(ch['start_time'])
    ch_end = ts2s(ch['end_time'])
    
    # 获取该Chapter内的事件
    ch_events = [e for e in events if ch_start <= ts2s(e['start_time']) < ch_end]
    
    if not ch_events:
        print(f"{ch_id}: 无事件，跳过")
        continue
    
    # 构造事件列表
    event_lines = []
    for e in sorted(ch_events, key=lambda x: x['start_time']):
        s = ts2s(e['start_time'])
        end = ts2s(e['end_time'])
        dur = end - s
        title = e.get('title', '')[:30]
        summary = e.get('summary', '')[:50]
        event_lines.append(f"  {e['event_id']} [{e['grade']}] {e['start_time']}-{e['end_time']} ({dur}s)\n    {title}\n    摘要: {summary}")
    
    event_text = "\n\n".join(event_lines)
    
    prompt = f"""你是一名直播内容分析师。以下是{ch['chapter_title']}章节内的{len(ch_events)}个事件：

{event_text}

请根据"连续活动/因果链"原则，将这些事件划分为若干个Story。

Story划分原则：
1. Story是"连续活动"，不是关键词主题
2. 同一Story内的事件应该有因果关系或时间连续性
3. 不要把每个物品/一句话机械切成Story
4. 一个Story可以包含多个事件（如"拆包装→试吃→评价"）

输出JSON格式：
{{"stories": [{{"story_id": "st-01", "name": "故事标题", "start_time": "MM:SS", "end_time": "MM:SS", "event_ids": ["ev-xxx"], "summary": "故事摘要(30字内)", "reason": "为什么这样划分(20字内)"}}]}}"""
    
    print(f"处理 {ch_id}: {ch['chapter_title']} ({len(ch_events)} 个事件)")
    
    try:
        reply, usage = call_deepseek(prompt, system="你是直播内容分析专家，擅长识别连续活动和因果链", max_tokens=2000)
        result = json.loads(reply)
        
        if 'stories' in result:
            for st in result['stories']:
                st['chapter_id'] = ch_id
                all_stories.append(st)
            print(f"  → {len(result['stories'])} 个Story")
        else:
            print(f"  → 解析失败，使用默认划分")
            all_stories.append({
                'story_id': f'st-{ch_id[-2]}',
                'chapter_id': ch_id,
                'name': ch['chapter_title'],
                'start_time': ch['start_time'],
                'end_time': ch['end_time'],
                'event_ids': [e['event_id'] for e in ch_events],
                'summary': ch.get('chapter_summary', '')[:50],
                'reason': '未划分，整个Chapter作为一个Story'
            })
    except Exception as e:
        print(f"  → API错误: {e}")
        # 降级：整个Chapter作为一个Story
        all_stories.append({
            'story_id': f'st-{ch_id[-2]}',
            'chapter_id': ch_id,
            'name': ch['chapter_title'],
            'start_time': ch['start_time'],
            'end_time': ch['end_time'],
            'event_ids': [e['event_id'] for e in ch_events],
            'summary': ch.get('chapter_summary', '')[:50],
            'reason': 'API错误，降级为单Story'
        })

# 保存结果
output = {
    'method': 'story_segmentation_v2',
    'total_chapters': len(chapters['chapters']),
    'total_stories': len(all_stories),
    'stories': all_stories
}

with open('poc/fixtures/story_segmentation_result.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print()
print("=" * 70)
print("Story Segmentation 完成")
print("=" * 70)
print(f"Chapter数: {len(chapters['chapters'])}")
print(f"Story数: {len(all_stories)}")
print()
print("Story列表:")
for st in all_stories:
    print(f"  {st['story_id']} ({st['chapter_id']}): {st['name'][:30]}")
    print(f"    时间: {st['start_time']}-{st['end_time']}")
    print(f"    事件: {', '.join(st['event_ids'])}")
    print(f"    原因: {st.get('reason', '')[:40]}")
    print()

print("结果已保存到 poc/story_segmentation_result.json")
