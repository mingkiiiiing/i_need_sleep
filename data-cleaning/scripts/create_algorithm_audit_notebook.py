from pathlib import Path

import nbformat as nbf


STORAGE = Path(__import__("os").environ.get("TAIHU_STORAGE_ROOT") or (Path(__file__).resolve().parents[1] / "storage"))
OUTPUT = STORAGE / "reports" / "algorithm_audit_20260828" / "algorithm_requirements_audit.ipynb"

nb = nbf.v4.new_notebook()
nb["metadata"]["kernelspec"] = {
    "display_name": "Python 3",
    "language": "python",
    "name": "python3",
}
nb["cells"] = [
    nbf.v4.new_markdown_cell(
        "# 两个 storage 目录的算法要求审计\n\n"
        "## tl;dr\n\n"
        "截至2026-08-28的文件快照仍不满足严格蓝藻水华短临预测要求。"
        "决定性缺口是连续地面真值、同期实测水温和与真值重叠的发行时预报。"
        "现有大体量数据主要增加代理特征，并未消除这些P0缺口。"
    ),
    nbf.v4.new_markdown_cell(
        "## Context & Methods\n\n"
        "检查新旧两个 storage 的原始、清洗和发布层；文件存在不等于可训练。"
        "本审计依次核对文件覆盖、可读性、字段、时间关系、标签来源和清洗逻辑。\n\n"
        "### Key Assumptions\n\n"
        "严格要求采用算法方说明：标签必须有正负证据，水温需与标签同地点同时间，"
        "预测特征必须是预测起点当时已经发布的预报；遥感反演只作为proxy。"
    ),
    nbf.v4.new_code_cell(
        "from pathlib import Path\n"
        "import json, glob\n"
        "import pandas as pd\n\n"
        "NEW = Path(r'D:\\Project\\fuwai\\merged_data\\2026_sheng-fuwai-main-merge')\n"
        "OLD = Path(r'D:\\Project\\fuwai\\merged_data\\2026_sheng-fuwai')\n"
        "REPORT = NEW / 'reports' / 'algorithm_audit_20260828'\n"
        "audit = json.loads((REPORT / 'storage_algorithm_audit.json').read_text(encoding='utf-8'))\n"
        "audit['generated_at']"
    ),
    nbf.v4.new_markdown_cell("## Data\n\n### 1. 目录与关键表"),
    nbf.v4.new_code_cell(
        "pd.read_csv(REPORT / 'table_profile_summary.csv')["
        "['root','path','exists','readable','rows','columns_count','exact_duplicate_rows']]"
    ),
    nbf.v4.new_markdown_cell("### 2. 新版正式标签表"),
    nbf.v4.new_code_cell(
        "labels = pd.read_parquet(NEW / 'exports/latest_public_training/forecast_label_dataset.parquet')\n"
        "label_summary = []\n"
        "for horizon in ['h1_3d','h7_15d','h30_90d']:\n"
        "    c = f'{horizon}_target_bloom_proxy'\n"
        "    label_summary.append({\n"
        "        'horizon': horizon, 'rows': len(labels), 'nonnull_labels': int(labels[c].notna().sum()),\n"
        "        'positive': int((labels[c] == 1).sum()), 'negative': int((labels[c] == 0).sum()),\n"
        "        'label_type': labels['label_type'].iloc[0]\n"
        "    })\n"
        "pd.DataFrame(label_summary)"
    ),
    nbf.v4.new_markdown_cell("### 3. 旧版候选表是否真的满足短临要求"),
    nbf.v4.new_code_cell(
        "old_paths = {\n"
        " 'h1_3d': OLD/'releases/taihu_public_v1/tables/dataset_h1_3d.parquet',\n"
        " 'h7_15d': OLD/'releases/taihu_public_v1/tables/dataset_h7_15d.parquet',\n"
        " 'h30_90d': OLD/'releases/taihu_public_v1/tables/candidate_h30_90d.parquet'}\n"
        "old_rows=[]\n"
        "for horizon,path in old_paths.items():\n"
        "    d=pd.read_parquet(path)\n"
        "    old_rows.append({\n"
        "      'horizon':horizon,'rows':len(d),'target_variable':d.target_variable.iloc[0],\n"
        "      'target_start':d.target_time.min(),'target_end':d.target_time.max(),\n"
        "      'forecast_columns':sum('forecast' in c.lower() for c in d.columns),\n"
        "      'algae_density_nonnull':int(d.get('direct_algae_density',pd.Series(dtype=float)).notna().sum()),\n"
        "      'remote_source_rows':int((d.get('reliability_remote_sensing_source_count',0)>0).sum())\n"
        "    })\n"
        "pd.DataFrame(old_rows)"
    ),
    nbf.v4.new_markdown_cell("## Results\n\n### 4. 原始下载完整度快照"),
    nbf.v4.new_code_cell(
        "download_status = pd.DataFrame([\n"
        " {'dataset':'GFS 0-72h','observed_days':717,'expected_days':2010,'coverage':717/2010,'status':'未完成'},\n"
        " {'dataset':'GFS 168-360h','observed_days':140,'expected_days':1412,'coverage':140/1412,'status':'下载中'},\n"
        " {'dataset':'MODIS ocean color','observed_files':2223,'readable_files':2056,'coverage':2056/2223,'status':'下载中且历史断档'},\n"
        " {'dataset':'MODIS LST','observed_days':2043,'expected_days':2430,'coverage':2043/2430,'status':'日期不完整'},\n"
        " {'dataset':'ERA5 lake temp','observed_months':80,'expected_months':80,'coverage':1.0,'status':'完整但属于再分析'},\n"
        " {'dataset':'Sentinel-2 monthly raw','observed_months':80,'expected_months':80,'coverage':1.0,'status':'原始齐全；清洗仅56个月'},\n"
        "])\n"
        "download_status"
    ),
    nbf.v4.new_markdown_cell("### 5. 严格算法条件矩阵"),
    nbf.v4.new_code_cell(
        "requirements = pd.DataFrame([\n"
        " ['水华真值标签','不满足','新版0条地面真值；旧版目标为季度浮游植物生物量'],\n"
        " ['连续Chl-a/蓝藻密度','不满足','实测Chl-a仅41+1条；旧版蓝藻密度仅14/16条'],\n"
        " ['同期实测水温','不满足','41条星地样本有水温；ERA5为再分析，不是站点实测'],\n"
        " ['1-3天发行时预报+未来标签','不满足','新版1-3天标签全空；旧候选表无forecast字段'],\n"
        " ['7-15天发行时预报+未来标签','部分满足','GFS扩展下载中；现有标签仅26条代理0/1'],\n"
        " ['30-90天预报+未来标签','部分满足','C3S五变量已清洗；云量未并入；标签为遥感proxy'],\n"
        " ['遥感特征及质量掩膜','部分满足','CLMS V2和Sentinel-2可用；V1需另行反演；S3为空'],\n"
        " ['负样本证据','不满足','25条proxy负样本；日表大量0来自阈值及前向填充'],\n"
        " ['统一正式导出及SHA','部分满足','新版有四类导出，但无当前全量主库和SHA清单'],\n"
        "],columns=['要求','判定','证据'])\n"
        "requirements"
    ),
    nbf.v4.new_markdown_cell(
        "## Takeaways\n\n"
        "1. 不能采纳“所有下载已完成”的判断；审计时GFS扩展和MODIS仍在运行。\n"
        "2. `processed/training/training_table.csv`只能作为代理实验表，不能作为严格真值训练表。\n"
        "3. 旧版release结构完整但标签语义不符合本次蓝藻短临任务，不能用文件名替代内容审查。\n"
        "4. 下一步应先修复下载完整度和重新清洗，但最终严格门槛仍是连续自动站真值。"
    ),
]

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
nbf.write(nb, OUTPUT)
print(OUTPUT)
