"""字段字典与标签字典生成 (设计 §12 contract/)."""

from __future__ import annotations

import pandas as pd

from .schema import SCHEMAS, TASK_GRAIN_MATRIX, TASK_GRAIN_OBSERVATION_EXTRA
from .enums import TASK_METRICS, TASK_UNITS, HORIZONS


def build_field_dictionary() -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for table, fields in SCHEMAS.items():
        for spec in fields:
            rows.append(
                {
                    "table": table,
                    "field": spec.name,
                    "dtype": spec.dtype,
                    "unit": spec.unit,
                    "nullable": str(spec.nullable),
                    "enum": "|".join(map(str, spec.enum)) if spec.enum else "",
                    "description": spec.description,
                }
            )
    rows.append(
        {
            "table": "task_grain_matrix",
            "field": "task_id",
            "dtype": "str",
            "unit": "",
            "nullable": "False",
            "enum": "|".join(f"{task}:{'+'.join(grains)}" for task, grains in TASK_GRAIN_MATRIX.items()),
            "description": "DG-008 任务×粒度契约矩阵（仿真真值粒度；T3/T4/T5 另有 station 观测标签粒度）",
        }
    )
    return pd.DataFrame(rows)


def build_label_dictionary() -> pd.DataFrame:
    rows = []
    for task_id, metric in TASK_METRICS.items():
        grains = TASK_GRAIN_MATRIX[task_id] + TASK_GRAIN_OBSERVATION_EXTRA.get(task_id, ())
        rows.append(
            {
                "task_id": task_id,
                "target_metric": metric,
                "label_unit": TASK_UNITS[task_id],
                "horizons_days": "|".join(map(str, HORIZONS)),
                "grains": "|".join(grains),
                "label_status_enum": "observed_positive|observed_negative|unknown|simulation_positive|simulation_negative|simulation_observed_positive|simulation_observed_negative|measured_value",
                "description": _TASK_DESCRIPTIONS[task_id],
            }
        )
    return pd.DataFrame(rows)


_TASK_DESCRIPTIONS = {
    "T1": "水华发生（网格/湖区/全湖二值，阈值见 label_thresholds.yaml）",
    "T2": "水华面积/覆盖率（湖区与全湖 km2，网格为覆盖率）",
    "T3": "蓝藻密度（万cells/L，站点/湖区）",
    "T4": "蓝藻生物量（mg/L，站点/湖区）",
    "T5": "叶绿素a（ug/L，站点/湖区）",
    "T6": "风险等级（阈值规则派生，只读不入特征）",
    "T7": "空间范围（正网格集合与几何交叠面积）",
}
