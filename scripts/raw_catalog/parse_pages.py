# -*- coding: utf-8 -*-
import json, datetime

def fmt_ts(ms):
    if not ms:
        return ''
    try:
        return datetime.datetime.fromtimestamp(ms/1000, datetime.timezone.utc).strftime('%Y-%m-%d')
    except Exception:
        return str(ms)

def fmt_size(b):
    if not b:
        return ''
    for unit in ['B', 'KB', 'MB', 'GB']:
        if b < 1024:
            return f'{b:.1f}{unit}'
        b /= 1024
    return f'{b:.1f}TB'

all_items = []
seen = set()
for p in range(1, 10):
    try:
        d = json.load(open(f'D:/Project/fuwai/lake_data_tmp/c23_p{p}.json', encoding='utf-8'))
    except Exception as e:
        print(f'page {p} error: {e}')
        continue
    for it in d.get('op_read', {}).get('data', []):
        g = it['guid']
        if g in seen:
            continue
        seen.add(g)
        it['_page'] = p
        all_items.append(it)

print(f'TOTAL unique datasets: {len(all_items)}')

taihu = [it for it in all_items if '太湖' in (it.get('title') or '') or (it.get('placeName') or '') == '太湖']

with open('D:/Project/fuwai/lake_data_tmp/all_130.txt', 'w', encoding='utf-8') as f:
    for it in all_items:
        f.write(f"p{it['_page']} | {it['guid']} | {it['title']} | {it.get('placeName') or ''} | {fmt_ts(it.get('dataStartTime'))}~{fmt_ts(it.get('dataEndTime'))} | {fmt_size(it.get('filesize'))} | online={it.get('online')} | docId={it.get('docId')}\n")

with open('D:/Project/fuwai/lake_data_tmp/taihu_only.txt', 'w', encoding='utf-8') as f:
    for it in taihu:
        f.write(f"p{it['_page']} | guid={it['guid']} | {it['title']} | 时间:{fmt_ts(it.get('dataStartTime'))}~{fmt_ts(it.get('dataEndTime'))} | 大小:{fmt_size(it.get('filesize'))} | online={it.get('online')} | docId={it.get('docId')} | 负责人:{it.get('ownerName')} | 单位:{it.get('ownerOrganization')}\n")

print(f'TAIHU datasets: {len(taihu)}')
for it in taihu:
    print(f"p{it['_page']} | {it['guid']} | {it['title']} | {fmt_size(it.get('filesize'))} | {fmt_ts(it.get('dataStartTime'))}~{fmt_ts(it.get('dataEndTime'))}")
