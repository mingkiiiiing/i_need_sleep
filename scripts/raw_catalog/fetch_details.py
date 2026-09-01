# -*- coding: utf-8 -*-
import json, glob, subprocess, time, datetime

def fmt_ts(ms):
    if not ms:
        return ''
    return datetime.datetime.fromtimestamp(ms/1000, datetime.timezone.utc).strftime('%Y-%m-%d')

def fmt_size(b):
    if not b:
        return ''
    b = float(b)
    for u in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f'{b:.1f}{u}'
        b /= 1024
    return f'{b:.1f}TB'

taihu = []
seen = set()
for f in sorted(glob.glob('D:/Project/fuwai/lake_data_tmp/c23_p*.json')):
    d = json.load(open(f, encoding='utf-8'))
    for it in d.get('op_read', {}).get('data', []):
        if it['guid'] in seen:
            continue
        if '太湖' in (it.get('title') or ''):
            seen.add(it['guid'])
            taihu.append(it)

print('fetching details for', len(taihu), 'datasets...')
results = []
for it in taihu:
    g = it['guid']
    try:
        out = subprocess.run(
            ['curl', '-s', f'https://lake.geodata.cn/service/scidata/entry/{g}',
             '-H', 'User-Agent: Mozilla/5.0', '-H', 'Accept: application/json'],
            capture_output=True, text=True, encoding='utf-8', timeout=60)
        d = json.loads(out.stdout)
        op = d.get('op_read', {})
        results.append(op)
    except Exception as e:
        print(f'  ERROR {g}: {e}')
        results.append({'guid': g, 'title': it['title'], '_err': str(e)})

with open('D:/Project/fuwai/lake_data_tmp/taihu_details.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=1)

lines = []
for r in results:
    lines.append('=' * 100)
    lines.append(f"标题: {r.get('title')}")
    lines.append(f"dataguid: {r.get('guid')}")
    lines.append(f"DOI: {r.get('doi')}")
    lines.append(f"关键词: {r.get('keywords')}")
    lines.append(f"数据时间: {fmt_ts(r.get('dataStartTime'))} ~ {fmt_ts(r.get('dataEndTime'))}")
    lines.append(f"数据量: {fmt_size(r.get('filesize'))}")
    lines.append(f"空间范围: {r.get('placeName')}")
    lines.append(f"数据格式: {r.get('dataFormat') or r.get('descProjection') or ''}")
    lines.append(f"共享方式/在线: online={r.get('online')} opened={r.get('opened')}")
    lines.append(f"负责人: {r.get('ownerName')} ({r.get('ownerOrganization')})")
    desc = (r.get('description') or '').strip()
    lines.append(f"描述: {desc[:600]}")
    src = (r.get('descDataSource') or '').strip()
    if src:
        lines.append(f"数据来源: {src[:300]}")
    method = (r.get('descMethod') or '').strip()
    if method:
        lines.append(f"方法: {method[:300]}")

with open('D:/Project/fuwai/lake_data_tmp/taihu_details.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('done, wrote', len(results), 'records')
