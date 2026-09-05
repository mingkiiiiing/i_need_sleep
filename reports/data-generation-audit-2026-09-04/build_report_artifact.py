"""Build canonical Data Analytics artifact.json for the audit report."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
findings = pd.read_csv(HERE / "audit_findings.csv").fillna("")
metrics = pd.read_csv(HERE / "audit_metrics.csv").fillna("")
summary = json.loads((HERE / "audit_summary.json").read_text(encoding="utf-8"))["summary"]

severity_order = ["Critical", "High", "Medium", "Low"]
severity_counts = (
    findings.groupby("severity").size().reindex(severity_order, fill_value=0).rename("findings").reset_index()
)
severity_counts = severity_counts[severity_counts["findings"] > 0]

metric_lookup = dict(zip(metrics["metric"], metrics["value"]))
key_metric_names = [
    "simulation_days",
    "simulation_grid_cells",
    "frozen_grid_cells",
    "simulation_area_share",
    "training_samples",
    "ground_truth_wq_rows_after_fit_cutoff",
    "water_level_rows_after_fit_cutoff",
    "synthetic_satellite_observation_rows",
    "satellite_labels_marked_non_synthetic",
    "station_observation_rows",
    "water_level_at_bounds",
    "chlorophyll_a_summer_vs_winter",
    "degenerate_binary_task_split_groups",
    "formal_contract_files_missing",
    "row_lineage_rows",
    "mee_rows_with_no_year_in_timestamp",
    "release_hash_failures",
]
key_metrics = metrics[metrics["metric"].isin(key_metric_names)].copy()

comparison = [
    {"check": "定向自动测试", "internal_result": "35/35 通过", "independent_result": "确认通过", "interpretation": "证明局部函数行为，不覆盖整体数据可信性"},
    {"check": "发布文件完整性", "internal_result": "missing=[]", "independent_result": "正式契约缺 6 类产物", "interpretation": "内部 required-list 不完整"},
    {"check": "发布哈希", "internal_result": "已生成 hashes.sha256", "independent_result": "0 个哈希不匹配", "interpretation": "文件未损坏，但不证明生成逻辑正确"},
    {"check": "总体质量", "internal_result": "PASS，A13 warning", "independent_result": "正式实验不可用", "interpretation": "质量门禁没有覆盖身份、截断前分布和完整时空范围"},
]

remediation = [
    {"priority": "P0-1", "action": "修复所有校准分支的训练截止过滤", "acceptance": "每个参数族记录 max_input_time 且不晚于 split train_end"},
    {"priority": "P0-2", "action": "修复仿真卫星标签身份传递", "acceptance": "仿真观测派生标签始终 is_synthetic=true，observed_* 只来自真实证据"},
    {"priority": "P0-3", "action": "修复全湖聚合与水位参数", "acceptance": "partial_domain 不再输出 TAIHU_WHOLE；水位硬边界命中率降至审定阈值"},
    {"priority": "P1", "action": "用观测/预报层装配特征并扩展到至少五年全湖", "acceptance": "七任务粒度获批，验证/测试均含多个正负事件且 feature availability 可审计"},
    {"priority": "P2", "action": "补全发布契约与代码版本", "acceptance": "参数集、来源登记、变换日志、泄漏报告、动态特征与 code_commit 齐全"},
]

def records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", force_ascii=False))


artifact = {
    "surface": "report",
    "manifest": {
        "version": 1,
        "surface": "report",
        "title": "太湖数据工厂 SIM-V1 独立质量审计",
        "description": "对现有数据生成代码、校准、观测层、标签、样本、切分、血缘和发布包进行只读复算。",
        "generatedAt": "2026-09-04T20:00:00+08:00",
        "cards": [],
        "charts": [
            {
                "id": "severity_chart",
                "title": "独立审计问题数量",
                "subtitle": "mvp_meiliangwan_2024，按严重程度计数",
                "type": "bar",
                "dataset": "severity_counts",
                "sourceId": "findings_query",
                "valueFormat": "number",
                "encodings": {
                    "x": {"field": "severity", "type": "nominal", "label": "严重程度"},
                    "y": {"field": "findings", "type": "quantitative", "label": "问题数"},
                    "tooltip": [{"field": "findings", "type": "quantitative", "label": "问题数"}],
                },
            }
        ],
        "tables": [
            {
                "id": "findings_table",
                "title": "完整问题清单",
                "subtitle": "代码与现有运行产物交叉复算；Critical 优先修复",
                "dataset": "findings",
                "sourceId": "findings_query",
                "columns": [
                    {"field": "issue_id", "label": "编号", "type": "text"},
                    {"field": "severity", "label": "严重度", "type": "text"},
                    {"field": "finding", "label": "发现", "type": "text"},
                    {"field": "evidence", "label": "证据", "type": "text"},
                    {"field": "impact", "label": "影响", "type": "text"},
                    {"field": "remediation", "label": "修复要求", "type": "text"},
                ],
            },
            {
                "id": "metrics_table",
                "title": "关键复算指标",
                "subtitle": "单年梅梁湾 SIM-V1；比例按实际记录粒度计算",
                "dataset": "key_metrics",
                "sourceId": "metrics_query",
                "columns": [
                    {"field": "metric", "label": "指标", "type": "text"},
                    {"field": "value", "label": "值", "type": "number"},
                    {"field": "unit", "label": "单位", "type": "text"},
                    {"field": "interpretation", "label": "解释", "type": "text"},
                ],
            },
            {
                "id": "comparison_table",
                "title": "内部 PASS 与独立审计的差异",
                "subtitle": "区分局部实现、文件完整性和正式实验可信度",
                "dataset": "comparison",
                "sourceId": "comparison_query",
                "columns": [
                    {"field": "check", "label": "检查", "type": "text"},
                    {"field": "internal_result", "label": "项目报告", "type": "text"},
                    {"field": "independent_result", "label": "独立复算", "type": "text"},
                    {"field": "interpretation", "label": "如何解释", "type": "text"},
                ],
            },
            {
                "id": "remediation_table",
                "title": "建议修复顺序",
                "subtitle": "先消除身份与泄漏问题，再扩大规模",
                "dataset": "remediation",
                "sourceId": "design_source",
                "columns": [
                    {"field": "priority", "label": "优先级", "type": "text"},
                    {"field": "action", "label": "动作", "type": "text"},
                    {"field": "acceptance", "label": "完成标准", "type": "text"},
                ],
            },
        ],
        "sources": [
            {"id": "findings_query", "label": "独立审计问题表", "path": "audit_findings.csv", "query": {"engine": "python/pandas", "language": "sql", "sql": "SELECT severity, COUNT(*) AS findings FROM audit_findings GROUP BY severity", "description": "audit_data_generation.py 对代码和落盘产物的交叉检查。", "executed_at": "2026-09-04T20:00:00+08:00"}},
            {"id": "metrics_query", "label": "独立复算指标", "path": "audit_metrics.csv", "query": {"engine": "python/pandas", "language": "sql", "sql": "SELECT * FROM audit_metrics", "description": "从网格、潜在状态、标签、样本、参数、血缘和发布包复算。", "executed_at": "2026-09-04T20:00:00+08:00"}},
            {"id": "comparison_query", "label": "内部质量报告与独立复算对照", "query": {"engine": "python/pandas", "language": "sql", "sql": "SELECT * FROM internal_checks_vs_independent_audit", "description": "对 35 个测试、21 项验收、12 项否决和 SHA-256 的解释边界。", "executed_at": "2026-09-04T20:00:00+08:00"}},
            {"id": "design_source", "label": "修复建议与验收口径", "path": "source_notes.md", "query": {"engine": "python", "language": "sql", "sql": "SELECT priority, action, acceptance FROM remediation_plan", "description": "由审计问题依赖关系形成的修复顺序。", "executed_at": "2026-09-04T20:00:00+08:00"}},
            {"id": "notebook_source", "label": "可复跑审计笔记本", "path": "数据生成独立质量审计.ipynb"},
        ],
        "blocks": [
            {"id": "title", "type": "markdown", "body": "# 太湖数据工厂 SIM-V1 独立质量审计"},
            {"id": "technical_summary", "type": "markdown", "body": "## 技术结论：能运行，但目前不能进入正式实验\n\n- **工程骨架已经成立。** 当前生成器完成了 2024 年梅梁湾 536 个网格、366 天、363,140 条 SIM-V1 训练样本；35 个定向测试通过，发布文件哈希 0 个不匹配。\n- **正式实验门禁必须拒绝。** 独立审计发现 4 个 Critical、8 个 High、2 个 Medium 问题；内部 `PASS` 只证明既定检查通过，不能证明仿真可信、无泄漏或满足全量契约。\n- **四个问题必须先修。** 当前全湖结果实际复制梅梁湾；校准分支读取了训练截止日之后的数据；仿真卫星观测被重标为非合成观测标签；水位 366/366 天处在硬边界。\n- **当前正确定位是工程 MVP。** 可继续用于接口和管线调试，但不得用于真实模型精度、正式对比实验或全太湖结论。"},
            {"id": "severity_heading", "type": "markdown", "body": "## 风险集中在身份、时空范围和校准有效性\n\n高严重度问题占绝大多数。这不是文件损坏，而是生成逻辑和质量门禁的定义不足，因此重新下载或只增加样本量无法解决。"},
            {"id": "severity", "type": "chart", "chartId": "severity_chart"},
            {"id": "critical_heading", "type": "markdown", "body": "## 四个严重问题使当前总 PASS 失效\n\n**范围错误：** SIM 只覆盖冻结全湖面积的 20.83%，但 `TAIHU_WHOLE` 的 366 天结果与 `TAIHU_ML` 完全相同。**切分错误：** 水质有 15 条、水位有 3 条训练截止日之后的真实记录可进入未过滤的校准分支。**身份错误：** 36,448 条合成卫星观测派生出的 70 个标签被写为 `is_synthetic=false` 和 `observed_negative`。**物理错误：** 水位 366/366 天落在 2 m 硬下界，TN 还有 38.10% 网格日命中 12 mg/L 上界。"},
            {"id": "metrics", "type": "table", "tableId": "metrics_table"},
            {"id": "findings_heading", "type": "markdown", "body": "## 完整问题清单同时指出影响和最小修复\n\n除四个严重问题外，训练特征直接读取潜在真值、Chl-a 夏冬差仅 0.81%、六个二分类任务/粒度/切分组合为单一类别、网格粒度只覆盖 T1/T2/T5、正式发布契约缺六类关键产物。"},
            {"id": "findings", "type": "table", "tableId": "findings_table"},
            {"id": "definitions", "type": "markdown", "body": "## 审计范围与口径\n\n本次对象是 `mvp_meiliangwan_2024 / baseline / seed 20260904 / SIM-V1`。检查单位包括冻结网格、逐日网格潜在状态、观测层、任务标签、预测样本、校准参数、时间切分、文件血缘和发布包。`正式实验可用` 要求不仅能读和能复跑，还必须保证训练期拟合、身份不可逆、输入在起报时可获得、空间名称与真实覆盖一致、验证/测试可计算目标指标。"},
            {"id": "method", "type": "markdown", "body": "## 方法：不采信清单式 PASS，直接交叉复算\n\n审计读取现有 Parquet/CSV/JSON/GeoJSON 和生成代码，独立计算面积覆盖、日期范围、边界命中、标签身份、切分后类平衡、截止日后校准输入、任务粒度和发布缺项；再运行三个 Data Factory 测试文件并复核 `hashes.sha256`。生成器未被重跑，因此没有改变现有数据。"},
            {"id": "comparison_heading", "type": "markdown", "body": "## 自动测试和哈希通过仍然有价值，但证明范围有限\n\n测试表明局部公式、确定性 RNG、标签装配和契约函数按作者预期运行；哈希表明交付文件没有被篡改或损坏。它们没有验证作者预期本身是否符合真实数据边界。"},
            {"id": "comparison", "type": "table", "tableId": "comparison_table"},
            {"id": "limitations", "type": "markdown", "body": "## 限制与不确定性\n\n这是对单个已完成 MVP 运行的只读审计，没有比较多个种子、多个情景或多年重复运行；没有真实连续水华标签，因此不能计算仿真与真实事件的一致性；也没有验证外部 MEE 接口的法律授权。实时表的 1,414 行时间字符串均缺年份，虽然可结合抓取时间推断，但当前代码已提前标为 ground truth/pass，仍不满足正式观测契约。"},
            {"id": "next_heading", "type": "markdown", "body": "## 修复顺序：先纠正真实性，再扩展五年全湖\n\n不建议现在直接扩大全湖生成，否则会把同样的身份和参数错误放大到更多数据。完成 P0 后应删除旧运行的正式可用标识、使用新版本号重跑，并由独立门禁确认旧批次不能混入。"},
            {"id": "remediation", "type": "table", "tableId": "remediation_table"},
            {"id": "questions", "type": "markdown", "body": "## 还需要项目方确认\n\n- T3/T4/T6/T7 是否必须提供 1 km 网格标签；当前代码只生成湖区/湖级。\n- `TAIHU_WHOLE` 是否允许在局部 MVP 中存在；建议禁止。\n- 实时接口数据通过哪些站点身份、时间、范围和许可检查后才能升级为 ground truth。\n- 正式实验的最低仿真真实性阈值由谁审批，包括边界命中率、季节差、事件持续性和多变量联合分布。"},
        ],
    },
    "snapshot": {
        "version": 1,
        "generatedAt": "2026-09-04T20:00:00+08:00",
        "status": "partial",
        "datasets": {
            "severity_counts": records(severity_counts),
            "findings": records(findings),
            "key_metrics": records(key_metrics),
            "comparison": comparison,
            "remediation": remediation,
        },
        "accessIssues": [
            {"id": "no_real_event_validation", "dataset": "REAL-V1", "message": "缺少连续真实水华事件标签，无法验证仿真事件真实性或真实预测精度。"},
            {"id": "single_run_scope", "dataset": "SIM-V1", "message": "本次仅审计一个年度、一个湖区、一个基线种子。"},
        ],
    },
    "sources": [
        {"id": "findings_query", "path": "audit_findings.csv", "description": "独立审计分级问题。"},
        {"id": "metrics_query", "path": "audit_metrics.csv", "description": "独立复算指标。"},
        {"id": "comparison_query", "description": "内部检查与独立审计边界对照。"},
        {"id": "design_source", "path": "source_notes.md", "description": "代码位置、方法和图表说明。"},
        {"id": "notebook_source", "path": "数据生成独立质量审计.ipynb", "description": "已执行的可复跑审计笔记本。"},
    ],
}

(HERE / "artifact.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
print(HERE / "artifact.json")
