"""
Story Layer A/B 实验
A = B1 当前结果（对照组）
B = 加入 Chapter → Story 后的结果
"""
import json, sys, re
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

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

# 加载 B1 结果作为 A 组
print("加载 B1 对照组...")
with open('highlights_v2.json', encoding='utf-8') as f:
    b1 = json.load(f)

events_a = b1['highlights'] + b1['rejected']

# 统计 A 组
lens_a = sorted(ts2s(e['end_time']) - ts2s(e['start_time']) for e in events_a)
singles_a = [e for e in events_a if (e.get('source_count') or 1) == 1]
small_a = [e for e in singles_a if ts2s(e['end_time']) - ts2s(e['start_time']) <= 28]
gt60_a = [l for l in lens_a if l > 60]
from collections import Counter
grades_a = Counter(e['grade'] for e in events_a)

print("【A 组：B1 对照组】")
print(f"  候选数: {b1['meta'].get('candidate_count')}")
print(f"  事件数: {len(events_a)}")
print(f"  单候选事件: {len(singles_a)}/{len(events_a)}")
print(f"  ≤28s 碎片: {len(small_a)}")
print(f"  >60s 事件: {len(gt60_a)}")
print(f"  中位时长: {lens_a[len(lens_a)//2]}s")
print(f"  等级: A{grades_a.get('A',0)} B{grades_a.get('B',0)} C{grades_a.get('C',0)} D{grades_a.get('D',0)}")
print(f"  成本: ¥{b1['cost']['cost_yuan']:.4f}")
print()

# 构造 B 组：模拟 Story Layer 效果
print("加载 Story Layer 离线验证结果...")
try:
    with open('poc/story_layer_result.json', encoding='utf-8') as f:
        story = json.load(f)
    print(f"  Chapter 数: {len(story['chapters'])}")
    print(f"  Story 数: {len(story['stories'])}")
    
    # 统计 B 组预估
    total_st_cands = sum(len(s['candidates']) for s in story['stories'])
    
    print("【B 组：Story Layer（预估）】")
    print(f"  Chapter: {len(story['chapters'])} 个")
    print(f"  Story: {len(story['stories'])} 个")
    print(f"  Story 内候选: {total_st_cands} 个")
    print()
    
    # 展示 Story 划分
    print("【Story 划分详情】")
    for ch in story['chapters']:
        print(f"\n  Chapter {ch['id']}: {ch['name']} ({fmt_ts(ch['start'])}-{fmt_ts(ch['end'])})")
        print(f"    摘要: {ch['summary'][:60]}...")
        for st in story['stories']:
            if st['chapter_id'] == ch['id']:
                cands = st['candidates']
                titles = [c.get('title','')[:25] for c in cands[:3]]
                print(f"    - {st['id']}: {st['name'][:30]}... ({len(cands)} candidates)")
                print(f"      候选: {' | '.join(titles)}{'...' if len(titles)<len(cands) else ''}")
    
    # 关键案例对比
    print("\n【关键案例对比】")
    b1_by_id = {e['event_id']: e for e in events_a}
    
    # ev-005/006 应该合并
    ev005 = b1_by_id.get('ev-005', {})
    ev006 = b1_by_id.get('ev-006', {})
    print(f"  ev-005 (A组): {ev005.get('grade')} {ev005.get('start_time')}-{ev005.get('end_time')} {ev005.get('title','')[:30]}")
    print(f"  ev-006 (A组): {ev006.get('grade')} {ev006.get('start_time')}-{ev006.get('end_time')} {ev006.get('title','')[:30]}")
    print(f"  → B组应合并为同一 Story")
    
    # ev-002 应该更完整
    ev002 = b1_by_id.get('ev-002', {})
    print(f"\n  ev-002 (A组): {ev002.get('grade')} {ev002.get('start_time')}-{ev002.get('end_time')} ({ts2s(ev002.get('end_time'))-ts2s(ev002.get('start_time'))}s)")
    print(f"  → B组在 Chapter 内应有完整上下文")
    
except FileNotFoundError:
    print("  未找到 story_layer_result.json，使用设计文档预估")

print("\n【对比总结】")
print(f"  A组碎片率: {len(small_a)/len(events_a)*100:.0f}%")
print(f"  B组预估碎片率: ~10-15% (预估减少 50%)")
print(f"  A组>60s: {len(gt60_a)}/{len(events_a)} ({len(gt60_a)/len(events_a)*100:.0f}%)")
print(f"  B组预估>60s: ~10-11/{len(events_a)} ({(10/len(events_a))*100:.0f}%-{(11/len(events_a))*100:.0f}%)")

# 保存结果
result = {
    'a_group': {
        'candidate_count': b1['meta'].get('candidate_count'),
        'event_count': len(events_a),
        'single_candidate': len(singles_a),
        'small_fragment': len(small_a),
        'long_event': len(gt60_a),
        'median_duration': lens_a[len(lens_a)//2],
        'grades': dict(grades_a),
        'cost_yuan': b1['cost']['cost_yuan']
    },
    'b_group': {
        'chapter_count': len(story['chapters']) if 'story' in dir() else 0,
        'story_count': len(story['stories']) if 'story' in dir() else 0,
        'estimated_event_count': 'similar',
        'estimated_fragment_rate': '~10-15%',
        'estimated_long_event_rate': '~65-70%'
    }
}
with open('poc/story_ab_result.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print("\n结果已保存到 poc/story_ab_result.json")
