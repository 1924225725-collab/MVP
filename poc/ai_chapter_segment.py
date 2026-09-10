"""
AI Chapter Segmentation 实验
不修改主流程，仅用现有 transcript 跑一次 AI 分析
"""
import json, sys, os, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# 加载 transcript
transcript_path = 'transcripts/测试视频2.txt'
segments = []
with open(transcript_path, encoding='utf-8') as f:
    for line in f:
        m = re.match(r'\[(\d+:\d\d(?:–|\-)\s*(\d+:\d\d))\]\s*(.*)', line.strip())
        if not m:
            m = re.match(r'\[(\d+:\d\d)\s*-\s*(\d+:\d\d)\]\s*(.*)', line.strip())
        if m:
            start_str, end_str, text = m.group(1), m.group(2), m.group(3).strip()
            # 解析时间
            def ts2s(t):
                p = t.split(':')
                return int(p[0])*60 + int(p[1]) if len(p)==2 else int(p[0])*3600+int(p[1])*60+int(p[2])
            segments.append({
                'start': ts2s(start_str),
                'end': ts2s(end_str),
                'text': text,
                'start_str': start_str,
                'end_str': end_str
            })

print(f"已加载 {len(segments)} 条台词，时长 0:00 - {segments[-1]['end_str']} ({segments[-1]['end']}s)")

# 构建用于 AI 分析的文本（按时间分组，每30秒一段）
print("\n构建 AI 分析文本...")
group_size = 30  # 30秒一组
groups = []
for i in range(0, len(segments), 50):  # 每50条台词一组做摘要
    chunk = segments[i:i+50]
    if not chunk:
        continue
    start_s = chunk[0]['start']
    end_s = chunk[-1]['end']
    texts = [s['text'] for s in chunk if s['text'].strip()]
    group_text = ' '.join(texts[:30])  # 取前30条避免过长
    groups.append({
        'start_sec': start_s,
        'end_sec': end_s,
        'time_range': f"{start_s//60:02d}:{start_s%60:02d}-{end_s//60:02d}:{end_s%60:02d}",
        'text': group_text[:500]  # 截断到500字
    })

# 构建 prompt
prompt_text = """请分析这场直播的内容结构，划分 Chapter（大环节/节目部分）。

直播总时长：约 51 分钟
内容概要：主播在测评各种军粮（美军、俄军、乌军）和罐头食品，期间有互动、整活、吃晚餐等环节。

请按内容结构（而非固定时间）划分 Chapter，每个 Chapter 应代表一个相对独立的直播环节。

请输出如下格式的 JSON（不要 markdown，直接输出 JSON）：
{
  "chapters": [
    {
      "chapter_id": "ch-01",
      "start_time": "00:00",
      "end_time": "12:30",
      "chapter_title": "开场互动与咖啡测评",
      "chapter_summary": "主播与观众互动，开始测评美军口粮中的咖啡产品，发现包装难撕、冲泡问题等",
      "boundary_reason": "从聊天互动过渡到正式测评环节，以咖啡产品为中心"
    }
  ]
}

划分原则：
1. 按内容主题/活动变化划分，不是按固定时长
2. 一个 Chapter 内应有相对连贯的主题或活动
3. 边界处应有明显的主题转换（如从A产品换到B产品、从测评换到聊天等）
4. 宁可多划几个短 Chapter，也不要一个 Chapter 太长（避免超过20分钟）
5. 如果某段内容重复前面主题，可以考虑合并或作为子段落

请直接输出 JSON，不需要其他文字。
"""

# 构建带上下文的完整 prompt
full_prompt = f"""直播文字稿（共 {len(segments)} 条，按时间顺序）：

{"\n".join([f"[{s['start_str']}-{s['end_str']}] {s['text']}" for s in segments[:200]])}
...（省略中间部分）...
{"\n".join([f"[{s['start_str']}-{s['end_str']}] {s['text']}" for s in segments[-100:]])}

{prompt_text}
"""

print(f"\nPrompt 字符数: {len(full_prompt)}")
print("调用 DeepSeek API...")

# 调用 API
from analysis.deepseek_client import call_deepseek
try:
    reply, usage = call_deepseek(
        full_prompt,
        system="你是一名直播内容分析师，擅长识别直播的结构化章节。",
        max_tokens=2000
    )
    print(f"API 调用成功，token 使用: {usage}")
except Exception as e:
    print(f"API 调用失败: {e}")
    sys.exit(1)

# 解析结果
print("\n解析 AI 返回结果...")
try:
    # 提取 JSON
    json_match = re.search(r'\{[\s\S]*"chapters"[\s\S]*\}', reply)
    if json_match:
        result = json.loads(json_match.group(0))
    else:
        result = json.loads(reply)
    
    chapters = result.get('chapters', [])
    print(f"\nAI 划分出 {len(chapters)} 个 Chapter:")
    for ch in chapters:
        print(f"  {ch['chapter_id']}: {ch['chapter_title']} ({ch['start_time']}-{ch['end_time']})")
        print(f"    摘要: {ch['chapter_summary'][:60]}...")
        print(f"    边界理由: {ch.get('boundary_reason', 'N/A')[:50]}...")
    
    # 保存结果
    with open('poc/ai_chapters_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("\n结果已保存到 poc/ai_chapters_result.json")
    
except Exception as e:
    print(f"解析失败: {e}")
    print("原始回复:")
    print(reply[:1000])
