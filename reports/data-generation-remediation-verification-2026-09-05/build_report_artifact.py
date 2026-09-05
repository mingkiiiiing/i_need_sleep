from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
metrics = pd.read_csv(HERE / "verification_metrics.csv").fillna("")
matrix = pd.read_csv(HERE / "dg_001_014_verification.csv").fillna("")
residuals = pd.read_csv(HERE / "residual_findings.csv").fillna("")
summary = json.loads((HERE / "verification_summary.json").read_text(encoding="utf-8"))


def records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", force_ascii=False))


headline_names = [
    "release_hash_failures", "fit_families_at_or_before_cutoff", "satellite_labels",
    "feature_observed_ratio_mean", "water_level_bound_share", "total_phosphorus_bound_share",
    "chlorophyll_a_summer_winter_ratio", "single_class_binary_groups", "row_lineage_rows",
    "station_observation_rows", "mee_rows", "mee_rows_mapped_to_grid",
]
headline = metrics[metrics.metric.isin(headline_names)]
status_counts = matrix.groupby("verdict").size().rename("items").reset_index()

comparison = [
    {"item": "卫星标签身份违规", "before": "70", "after": "0", "assessment": "已修复；70 条均为 synthetic + simulation_observed_*"},
    {"item": "水位硬边界命中", "before": "100%", "after": "0%", "assessment": "已修复；2.820–3.825 m"},
    {"item": "Chl-a 夏/冬比", "before": "1.008", "after": "1.833", "assessment": "已达到当前门槛 ≥1.5"},
    {"item": "MEE 无年份时间", "before": "1,414", "after": "0", "assessment": "年份与 +08:00 已修复"},
    {"item": "正式契约缺文件", "before": "6", "after": "0", "assessment": "已补齐并纳入 45 项哈希清单"},
    {"item": "row_lineage", "before": "8（文件级）", "after": "378,396（样本级）", "assessment": "样本 ID 覆盖 100%；文件级另存 8 行"},
]

artifact = {
    "surface": "report",
    "manifest": {
        "version": 1,
        "surface": "report",
        "title": "SIM-V1.1 数据生成整改独立复核",
        "description": "对 DG-001—014、发布包、提交、哈希、测试与剩余使用边界进行只读复算。",
        "generatedAt": "2026-09-05T02:00:00+08:00",
        "cards": [],
        "charts": [
            {"id": "verdict_chart", "title": "14 项整改复核结论分布", "subtitle": "按逐项 verdict 计数；带括号的通过项仍保留范围或用途边界", "type": "bar", "dataset": "status_counts", "sourceId": "verification_source", "valueFormat": "number", "encodings": {
                "x": {"field": "verdict", "type": "nominal", "label": "复核结论"},
                "y": {"field": "items", "type": "quantitative", "label": "审计项数"},
                "tooltip": [{"field": "items", "type": "quantitative", "label": "审计项数"}],
            }}
        ],
        "tables": [
            {"id": "comparison", "title": "整改前后关键指标", "subtitle": "同一审计口径的独立复算；数值改善不等同于真实预测精度", "dataset": "comparison", "sourceId": "verification_source", "columns": [
                {"field": "item", "label": "指标", "type": "text"}, {"field": "before", "label": "整改前", "type": "text"},
                {"field": "after", "label": "当前", "type": "text"}, {"field": "assessment", "label": "复核结论", "type": "text"},
            ]},
            {"id": "dg_matrix", "title": "DG-001—014 逐项复核", "subtitle": "“通过（契约裁决/范围显式化）”表示边界已明确，并不表示缺失能力已实现", "dataset": "matrix", "sourceId": "verification_source", "columns": [
                {"field": "issue_id", "label": "审计项", "type": "text"}, {"field": "verdict", "label": "结论", "type": "text"},
                {"field": "claim", "label": "整改目标", "type": "text"}, {"field": "evidence", "label": "独立证据", "type": "text"},
                {"field": "residual_risk", "label": "保留边界", "type": "text"},
            ]},
            {"id": "metrics", "title": "关键复算指标", "subtitle": "mvp_meiliangwan_2024 / baseline / seed 20260904", "dataset": "headline", "sourceId": "verification_source", "columns": [
                {"field": "metric", "label": "指标", "type": "text"}, {"field": "value", "label": "值", "type": "text"},
                {"field": "unit", "label": "单位", "type": "text"}, {"field": "result", "label": "判定", "type": "text"},
                {"field": "evidence", "label": "说明", "type": "text"},
            ]},
            {"id": "residuals", "title": "复核中新发现的接入缺口", "subtitle": "不影响当前 2024 SIM 包运行，但会影响未来真实接口直接接入", "dataset": "residuals", "sourceId": "verification_source", "columns": [
                {"field": "id", "label": "编号", "type": "text"}, {"field": "severity", "label": "严重度", "type": "text"},
                {"field": "finding", "label": "发现", "type": "text"}, {"field": "evidence", "label": "证据", "type": "text"},
                {"field": "impact", "label": "影响", "type": "text"}, {"field": "required_action", "label": "要求", "type": "text"},
            ]},
        ],
        "sources": [
            {"id": "verification_source", "label": "独立整改复核", "path": "verify_remediation.py", "query": {"engine": "python/pandas", "language": "sql", "sql": "SELECT * FROM release_and_run_outputs CROSS CHECK code, manifests, hashes, tests", "description": "直接读取发布 Parquet/CSV/JSON、Git 状态和生成器契约，独立复算。", "executed_at": "2026-09-05T02:00:00+08:00"}},
            {"id": "test_source", "label": "数据工厂测试复跑", "path": "test_results.txt", "query": {"engine": "pytest", "language": "sql", "sql": "pytest test_data_factory_contracts test_data_factory_simulation test_data_factory_assembly test_data_factory_audit_fixes", "description": "51 passed, 1 Python 日期解析弃用警告。", "executed_at": "2026-09-05T02:00:00+08:00"}},
        ],
        "blocks": [
            {"id": "title", "type": "markdown", "body": "# SIM-V1.1 数据生成整改独立复核"},
            {"id": "summary", "type": "markdown", "body": "## 技术结论：可以批准为仿真专用发布包，但仍不能作为正式实验数据\n\n- **DG-001—014 已按获批方案落地。** 其中 DG-007 是明确保留的单类组合警告；DG-001 和 DG-008 属于范围/契约裁决，不是全湖或全任务网格能力已经补齐。\n- **工程证据闭环成立。** 当前 HEAD 与发布 `code_commit` 均为 `52c9ec5`；数据工厂路径无该提交之后的差异；45/45 项 SHA-256 匹配；51 个数据工厂测试全部通过。\n- **三段结论应严格解释。** packaging=PASS、simulation_fidelity=PASS、training_readiness=WARNING。`quality_summary` 顶部的总体 PASS 只能解释为“允许发布 SIM 包”，不能写成“正式训练/测试就绪”。\n- **真实接口仍不能直接并入训练。** MEE 的 708 行时间已修复，但全部尚无 `grid_id`，同时处于 `observation_candidate` 又被标为 ground truth；模拟站点观测的单位和站名也为空。"},
            {"id": "before_after_heading", "type": "markdown", "body": "## 六个核心缺陷的量化结果已明显改善\n\n卫星身份、水位边界、季节性、MEE 时间、交付缺项和样本血缘均能从实际文件复算得到；这些结果支持整改完成，但不产生任何真实预测精度证明。"},
            {"id": "before_after", "type": "table", "tableId": "comparison"},
            {"id": "matrix_heading", "type": "markdown", "body": "## 14 项没有发现与获批整改方案相冲突的未完成项\n\n逐项结论区分了“代码/数据修复”“范围显式化”“契约裁决”和“保留警告”。旧审计脚本继续报 2 Critical + 4 High 的原因可以确认：DG-011、DG-012 是无条件静态 finding；DG-001、DG-002、DG-008 使用旧判定口径；DG-007 则是真实保留限制。"},
            {"id": "verdict_chart", "type": "chart", "chartId": "verdict_chart"},
            {"id": "matrix", "type": "table", "tableId": "dg_matrix"},
            {"id": "metrics_heading", "type": "markdown", "body": "## 关键门禁通过，但只覆盖当前单年梅梁湾 SIM 运行\n\n拟合族截止日、合成身份、观测特征比例、物理边界、哈希和血缘均通过独立复算。A13 的 4 个单类组合仍使训练就绪为 WARNING。"},
            {"id": "metrics", "type": "table", "tableId": "metrics"},
            {"id": "scope", "type": "markdown", "body": "## 范围、定义与方法\n\n对象为 `SIM-V1 / mvp_meiliangwan_2024 / df-0.2.0 / baseline / seed 20260904`。复核读取最终发布包、运行目录、数据工厂代码和 Git 历史，独立复算日期截止、身份字段、物理分布、类平衡、任务粒度、哈希、样本血缘和实时观测状态；没有重跑生成器，也没有改动旧审计脚本。`通过` 表示满足本轮获批方案，`正式实验可用` 还要求真实连续标签、跨年时序、独立测试集和足够正负事件。"},
            {"id": "residual_heading", "type": "markdown", "body": "## 两个新增缺口必须在真实接口接入前解决\n\n它们没有污染当前 2024 SIM 训练样本，因此不阻断仿真包归档和算法管线运行；但如果下一步要把 MEE 实时数据用于真实训练或监督标签，这两个问题会变成阻断项。"},
            {"id": "residuals", "type": "table", "tableId": "residuals"},
            {"id": "limitations", "type": "markdown", "body": "## 限制、稳健性与不能声称的结论\n\n当前仅有一个年度、一个情景、一个随机种子和梅梁湾 20.83% 空间覆盖。`TAIHU_WHOLE` 数值仍等于梅梁湾，只是身份已显式标为 partial domain；T3/T4/T6/T7 仍没有 grid 粒度，只是契约已批准其当前粒度；4 个二分类任务/粒度/切分组合仍是单类。因缺少连续真实水华标签，本报告不能验证生成分布与真实事件的一致性，也不能支持任何真实模型精度或全太湖结论。"},
            {"id": "next", "type": "markdown", "body": "## 建议的下一步\n\n1. 保留当前 `SIM-V1.1`，明确标注 `simulation_only`，可用于算法跑通、消融和工程压力测试。\n2. 在接入 MEE 前完成站点坐标映射、候选到正式观测的 QC 状态机，以及站点单位/名称回填。\n3. 启动全湖 × 至少五年数据阶段，重新构造含多次正负事件的时间隔离验证/测试窗口，届时才能关闭 DG-007。\n4. 给旧审计脚本增加版本声明或另建 df-0.2.0 复核脚本；不要修改历史审计结果本身。"},
            {"id": "questions", "type": "markdown", "body": "## 仍需确认的问题\n\n- MEE 记录通过哪些 QC 条件后才从 `observation_candidate` 升级为 ground truth？\n- `TAIHU_WHOLE` 在前后端和算法接口中是否都会展示 20.83% coverage，而不是只在数据表中保留字段？\n- 全湖五年阶段是否继续保留当前 TASK_GRAIN_MATRIX，还是补齐 T3/T4/T6/T7 的网格监督任务？"},
        ],
    },
    "snapshot": {
        "version": 1,
        "generatedAt": "2026-09-05T02:00:00+08:00",
        "status": "partial",
        "datasets": {"comparison": comparison, "matrix": records(matrix), "headline": records(headline), "residuals": records(residuals), "status_counts": records(status_counts)},
        "accessIssues": [
            {"id": "no_real_ground_truth_validation", "dataset": "REAL-V1", "message": "缺少连续真实水华标签，不能验证真实预测精度。"},
            {"id": "single_year_partial_domain", "dataset": "SIM-V1", "message": "当前仅 2024 年梅梁湾，湖级 coverage=20.83%。"},
        ],
    },
    "sources": [
        {"id": "verification_source", "path": "verify_remediation.py", "description": "独立复算脚本与 CSV 证据。"},
        {"id": "test_source", "path": "test_results.txt", "description": "51 项 pytest 复跑结果。"},
    ],
}

(HERE / "artifact.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
print(HERE / "artifact.json")
