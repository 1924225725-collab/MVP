"""Story Segmentation PoC - 基于Chapter划分Story"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, '.')
from analysis.deepseek_client import call_deepseek

print("=" * 70)
print("Story Segmentation PoC - Chapter内划分连续活动")
print("=" * 70)

# 加载数据
with open('highlights_v2.json', encoding='utf-8') as f:
    b1 = json.load(f)
with open('poc/fixtures/ai_chapter_result.json', encoding='utf-8') as f:
    chapters = json.load(f)

events = b1['highlights'] + b1['rejected']

def ts2s(t):
    p = t.split(':')
    return int(p[0])*60+int(p[1])

all_stories = []

for ch in chapters['chapters']:
    ch_id = ch['chapter_id']
    ch_start = ts2s(ch['start_time'])
    ch_end = ts2s(ch['end_time'])
    
    ch_events = [e for e in events if ch_start <= ts2s(e['start_time']) < ch_end]
    
    if not ch_events:
        print(f"{ch_id}: 无事件，跳过")
        continue
    
    event_lines = []
    for e in sorted(ch_events, key=lambda x: x['start_time']):
        s = ts2s(e['start_time'])
        end = ts2s(e['end_time'])
        dur = end - s
        title = e.get('title', '')[:30]
        summary = e.get('summary', '')[:50]
        event_lines.append(f"{e['event_id']} [{e['grade']}] {e['start_time']}-{e['end_time']} ({dur}s) | {title} | {summary}")
    
    event_text = "\n".join(event_lines)
    
    prompt = f"""你是一名直播内容分析师。以下是 Chapter {ch_id} 的事件列表（已按时间排序）：

{event_text}

请将这些事件划分为若干个 Story（连续活动/因果链）。

要求：
1. Story 应围绕同一连续活动、对象或因果链
2. 一个 Story 可以包含多个 Event
3. 不要把每个物品/一句话机械切成 Story
4. Story 是软边界，允许跨边界取上下文

请输出合法 JSON：
{{"stories": [{{"story_id": "st-01", "chapter_id": "{ch_id}", "start_time": "MM:SS", "end_time": "MM:SS", "story_title": "标题", "story_summary": "摘要(50字内)", "reason": "划分理由(30字内)", "event_ids": ["ev-xxx"]}}]}}"""

    print(f"\n处理 {ch_id} ({ch['chapter_title']})...")
    try:
        reply, usage = call_deepseek(prompt, system="你是直播内容分析专家，擅长识别连续活动和因果链", max_tokens=2000)
        result = json.loads(reply)
        for st in result['stories']:
            st['chapter_id'] = ch_id
            all_stories.append(st)
        print(f"  → {len(result['stories'])} 个 Story")
    except Exception as e:
        print(f"  错误: {e}")

# 保存结果
with open('poc/fixtures/story_segmentation_result.json', 'w', encoding='utf-8') as f:
    json.dump({'chapters': chapters['chapters'], 'stories': all_stories}, f, ensure_ascii=False, indent=2)

print("\n" + "=" * 70)
print("Story Segmentation 完成")
print("=" * 70)
print(f"总 Story 数: {len(all_stories)}")
for st in all_stories:
    print(f"  {st['story_id']}: {st['story_title']} ({st['start_time']}-{st['end_time']})")
    print(f"    事件: {', '.join(st['event_ids'])}")
