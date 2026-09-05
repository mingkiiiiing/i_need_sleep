"""Build the reproducible audit companion notebook with nbformat."""

from pathlib import Path

import nbformat as nbf


HERE = Path(__file__).resolve().parent
notebook = nbf.v4.new_notebook()
notebook["metadata"]["kernelspec"] = {
    "display_name": "Python 3",
    "language": "python",
    "name": "python3",
}
notebook["metadata"]["language_info"] = {"name": "python", "version": "3"}
notebook["cells"] = [
    nbf.v4.new_markdown_cell(
        "# 太湖数据工厂 SIM-V1 独立质量审计\n\n"
        "## tl;dr\n\n"
        "当前 `mvp_meiliangwan_2024` 可以运行并生成结构化 SIM-V1 数据，35 个定向测试通过、发布文件哈希无错误；"
        "但独立审计发现 4 个 Critical、8 个 High、2 个 Medium 问题，因此不能进入正式实验。"
        "最严重的问题是全湖记录其实复制梅梁湾、部分校准分支读取训练截止日之后的数据、仿真卫星观测被重标为非合成观测标签，以及水位 100% 落在硬下界。"
    ),
    nbf.v4.new_markdown_cell(
        "## Context & Methods\n\n"
        "本笔记本只读取现有运行目录和发布包，不重跑或修改生成器。审计粒度包括：冻结网格、逐日网格潜在状态、任务标签、训练样本、观测层、校准参数、切分和发布包。\n\n"
        "### Key Assumptions\n\n"
        "- 正式实验目标以用户提供的 V1.0 清单为准；当前输出按 MVP 单年梅梁湾范围评估。\n"
        "- `is_synthetic`、`is_ground_truth` 和 `label_status` 必须从上游证据不可逆传递。\n"
        "- 时间切分要求所有生成器校准输入不晚于 2024-08-28。"
    ),
    nbf.v4.new_markdown_cell("## Data\n\n读取已落盘的 SIM-V1 运行产物，并调用同目录的独立审计脚本。"),
    nbf.v4.new_code_cell(
        "from pathlib import Path\n"
        "import sys\n"
        "import pandas as pd\n\n"
        "audit_dir = Path.cwd()\n"
        "if not (audit_dir / 'audit_data_generation.py').exists():\n"
        "    audit_dir = Path(r'D:/Project/fuwai/项目完整汇总_2026-08-31/01_我们的开发/reports/data-generation-audit-2026-09-04')\n"
        "sys.path.insert(0, str(audit_dir))\n"
        "from audit_data_generation import run_audit\n\n"
        "metrics, findings, details, extra = run_audit()\n"
        "extra['summary']"
    ),
    nbf.v4.new_markdown_cell("## Results\n\n### 1. 分级问题\n\n下表是独立复算后的问题，不采信内部质量报告的总 PASS 作为结论。"),
    nbf.v4.new_code_cell(
        "severity_order = pd.CategoricalDtype(['Critical', 'High', 'Medium', 'Low'], ordered=True)\n"
        "findings_view = findings.copy()\n"
        "findings_view['severity'] = findings_view['severity'].astype(severity_order)\n"
        "findings_view.sort_values(['severity', 'issue_id'])[['issue_id', 'severity', 'finding', 'evidence']]"
    ),
    nbf.v4.new_markdown_cell("### 2. 关键量化证据"),
    nbf.v4.new_code_cell(
        "wanted = [\n"
        "    'simulation_area_share', 'whole_lake_equals_meiliang_bay',\n"
        "    'ground_truth_wq_rows_after_fit_cutoff', 'water_level_rows_after_fit_cutoff',\n"
        "    'synthetic_satellite_observation_rows', 'satellite_labels_marked_non_synthetic',\n"
        "    'station_observation_rows', 'water_level_at_bounds',\n"
        "    'chlorophyll_a_summer_vs_winter', 'degenerate_binary_task_split_groups',\n"
        "    'formal_contract_files_missing', 'row_lineage_rows',\n"
        "    'mee_rows_with_no_year_in_timestamp', 'release_hash_failures'\n"
        "]\n"
        "metrics[metrics['metric'].isin(wanted)].set_index('metric').loc[wanted].reset_index()"
    ),
    nbf.v4.new_markdown_cell("### 3. 边界钳位和二分类切分"),
    nbf.v4.new_code_cell(
        "clipping = details[details['table'].eq('clipping')][['variable', 'rows', 'at_lower_bound', 'at_upper_bound', 'bound_share']]\n"
        "date_balance = details[details['table'].eq('date_balance')][['target_metric', 'spatial_type', 'split', 'samples', 'positives', 'positive_rate']]\n"
        "display(clipping)\n"
        "display(date_balance)"
    ),
    nbf.v4.new_markdown_cell(
        "## Takeaways\n\n"
        "1. 当前产物适合作为工程原型，不适合作为正式算法训练或效果证明数据。\n"
        "2. 必须先修复训练截止日过滤、仿真身份传递、全湖聚合和水位参数错误，再重新生成。\n"
        "3. 训练特征必须来自可见观测/预报层，而不是直接读取潜在真值。\n"
        "4. 重新运行至少五年全湖数据后，再按真实日期事件检查每个 split 的正负样本。\n"
        "5. 发布门禁应分为结构完整性、仿真可信度和正式训练就绪度，不能只给一个总 PASS。"
    ),
]

target = HERE / "数据生成独立质量审计.ipynb"
nbf.write(notebook, target)
print(target)
