# -*- coding: utf-8 -*-
import json, io, sys

out = open('lake_data_tmp/cattree.txt', 'w', encoding='utf-8')
d = json.load(open('lake_data_tmp/lakecat.json', encoding='utf-8'))

def walk(n, depth=0):
    name = n.get('categoryName')
    if name:
        out.write('  ' * depth + name + ' | id=' + str(n.get('categoryId')) + ' | code=' + str(n.get('categoryCode')) + ' | hits=' + str(n.get('hits')) + '\n')
        for c in (n.get('childrenTrees') or []):
            walk(c, depth + 1)

walk(d['op_read'])
out.close()
print('done')
