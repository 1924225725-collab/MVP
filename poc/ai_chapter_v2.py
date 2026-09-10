import sys; sys.path.insert(0, ".")
"""AI Chapter Segmentation - 基于事件摘要判断 Chapter 边界"""
import json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from analysis.deepseek_client import call_deepseek

# 加载 B1 结果
with open('highlights_v2.json', encoding='utf-8') as f:
    b1 = json.load(f)

events = b1['highlights'] + b1['rejected']

def ts2s(t):
    p = t.split(':')
    return int(p[0])*60+int(p[1]) if len(p)==2 else int(p[0])*3600+int(p[1])*60+int(p[2])

# 构造事件摘要
event_lines = []
for e in sorted(events, key=lambda x: x['start_time']):
    title = e.get('title', '')[:35]
    summary = e.get('summary', '')[:60]
    event_lines.append(f"{e['event_id']} [{e['grade']}] {e['start_time']}-{e['end_time']} | {title} | {summary}")

event_text = '\n'.join(event_lines)

prompt = f"""你是一名直播内容分析师。以下是一场 51 分钟直播的事件列表（已按时间排序）：

{event_text}

请根据事件的内容结构，将这些事件划分为若干个 Chapter（大环节/节目部分）。

Chapter 表示直播中的"大环节"，如不同测评主题、游戏环节、互动环节等。
边界应基于内容主题的切换，而非固定时间。

请输出合法 JSON，格式：
{{"chapters": [{{"chapter_id": "ch-01", "start_time": "MM:SS", "end_time": "MM:SS", "chapter_title": "标题", "chapter_summary": "摘要(50字内)", "boundary_reason": "边界原因(30字内)", "event_ids": ["ev-xxx"]}}]}}"""

print("调用 AI 进行 Chapter 分割...")
reply, usage = call_deepseek(prompt, system="你是直播内容分析专家", max_tokens=2000)
print(f"API 调用成功，tokens: {usage.get('total_tokens', 0)}")

result = json.loads(reply)
with open('poc/fixtures/ai_chapter_result.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"\nAI 划分结果：{len(result['chapters'])} 个 Chapter")
for ch in result['chapters']:
    print(f"  {ch['chapter_id']}: {ch['chapter_title']} ({ch['start_time']}-{ch['end_time']})")
    print(f"    原因: {ch['boundary_reason']}")
    print(f"    事件: {', '.join(ch['event_ids'])}")
