"""
Story Segmentation PoC - 基于 Chapter 划分，识别每个 Chapter 内的连续活动/故事
不在主流程中运行，仅用于验证 Story Layer 的价值
"""
import json, sys, re, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../')
from analysis.deepseek_client import call_deepseek

def ts2s(t):
    """时间字符串转秒"""
    p = t.split(':')
    if len(p) == 2:
        return int(p[0]) * 60 + int(p[1])
    elif len(p) == 3:
        return int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
    return 0

def fmt_ts(s):
    """秒转时间字符串"""
    return f"{s//60:02d}:{s%60:02d}"

# 1. 加载 Chapter V3 结果
print("加载 Chapter V3 结果...")
with open('poc/ai_chapter_v3_result.json', encoding='utf-8') as f:
    chapters = json.load(f)

# 2. 加载 B1 事件
print("加载 B1 事件...")
with open('highlights_v2.json', encoding='utf-8') as f:
    b1 = json.load(f)
events = b1['highlights'] + b1['rejected']

# 3. 加载 transcript 并采样
print("加载 transcript...")
with open('transcripts/测试视频2.txt', encoding='utf-8') as f:
    all_lines = f.readlines()

# 4. 为每个 Chapter 提取内容并让 AI 识别 Story
results = []

for ch in chapters['chapters']:
    ch_start = ts2s(ch['start_time'])
    ch_end = ts2s(ch['end_time'])
    
    print(f"\n处理 Chapter: {ch['chapter_title']} ({ch['start_time']}-{ch['end_time']})")
    
    # 提取该 Chapter 范围内的 transcript 行（每2分钟取20行）
    chapter_text = []
    for minute in range(ch_start // 60, min(ch_end // 60 + 1, 52), 2):
        start_idx = None
        end_idx = None
        for i, line in enumerate(all_lines):
            m = re.match(r'\[(\d+):(\d+) - (\d+):(\d+)\]', line)
            if m:
                t = int(m.group(1)) * 60 + int(m.group(2))
                if t >= minute * 60 and t < (minute + 2) * 60:
                    if start_idx is None:
                        start_idx = i
                    end_idx = i
        if start_idx is not None and end_idx is not None:
            chunk = all_lines[start_idx:end_idx+1]
            chapter_text.extend(chunk[:20])  # 每2分钟最多20行
    
    # 提取该 Chapter 内的事件
    ch_events = []
    for e in events:
        e_start = ts2s(e['start_time'])
        e_end = ts2s(e['end_time'])
        if ch_start <= e_start <= ch_end or ch_start <= e_end <= ch_end:
            title = e.get('title', '')[:40]
            summary = e.get('summary', '')[:60]
            ch_events.append(f"{e['event_id']} [{e['grade']}] {e['start_time']}-{e['end_time']} | {title} | {summary}")
    
    # 构造 prompt
    text_sample = '\n'.join(chapter_text[:100])  # 最多100行
    event_list = '\n'.join(ch_events) if ch_events else "（无事件）"
    
    prompt = f"""你是一名直播内容分析师。以下是第 {ch['chapter_id']} 的内容采样和重要事件。

【Chapter】{ch['chapter_title']} ({ch['start_time']}-{ch['end_time']})
【本章摘要】{ch.get('chapter_summary', '')}

【内容采样】（每2分钟取20行，共{len(chapter_text)}行）：
{text_sample}
{'...' if len(chapter_text) > 100 else ''}

【本章内的事件】：
{event_list}

请根据内容的连续性，将本章划分为若干个 Story（连续活动/故事）。

Story 的定义：
- 围绕同一主题或因果链的连续活动
- 可以包含多个事件步骤（如：拆包→发现→试吃→评价）
- 不是单个物品或一句话，而是一个完整的故事单元

要求：
1. Story 之间应有明显的主题/活动切换
2. 同一 Story 内的内容应有因果或时间连续性
3. 不要过度细分（不要把每个物品都当成独立 Story）
4. 不要合并完全不同主题的内容

请输出 JSON：
{{"stories": [{{"story_id": "st-01", "name": "故事标题", "start_time": "MM:SS", "end_time": "MM:SS", "summary": "摘要(50字内)", "reason": "划分理由(30字内)", "event_ids": ["ev-xxx"]}}]}}
"""
    
    print(f"  调用 AI 识别 Story...")
    try:
        reply, usage = call_deepseek(prompt, 
            system="你是直播内容分析专家，擅长识别内容结构和故事线",
            max_tokens=2000)
        
        # 解析结果
        try:
            story_data = json.loads(reply)
        except json.JSONDecodeError:
            # 尝试提取 JSON
            m = re.search(r'\{.*\}', reply, re.DOTALL)
            if m:
                story_data = json.loads(m.group())
            else:
                print(f"  解析失败")
                continue
        
        stories = story_data.get('stories', [])
        results.append({
            'chapter_id': ch['chapter_id'],
            'chapter_title': ch['chapter_title'],
            'stories': stories
        })
        
        print(f"  识别到 {len(stories)} 个 Story")
        for st in stories:
            print(f"    - {st.get('story_id', '?')}: {st.get('name', '?')[:30]} ({st.get('start_time', '?')}-{st.get('end_time', '?')})")
            
    except Exception as e:
        print(f"  API 调用失败: {e}")
        continue

# 保存结果
output = {
    'chapters': chapters['chapters'],
    'results': results
}
with open('poc/fixtures/story_segmentation_result.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print("\n=== 完成 ===")
print(f"结果已保存到 poc/story_segmentation_result.json")
