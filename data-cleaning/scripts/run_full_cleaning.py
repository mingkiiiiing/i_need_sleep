# -*- coding: utf-8 -*-
"""太湖蓝藻数据集 — 全流程一键运行入口（可重复运行，输出幂等覆盖）。

顺序:
  0) 原始数据扫描/归档(可选 --no-archive 跳过; 已归档文件自动跳过)
  1) 水质清洗  2) 气象清洗  3) 水文清洗  4) 现场样本  5) 静态特征  6) 遥感(索引+月度全湖)
  7) 统一长表  8) 机器学习月度宽表  9) 质量报告  10) 清洗总结(中文 markdown)

用法:
  python scripts/run_full_cleaning.py [--no-archive] [--no-remote]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

STEPS = [
    ("archive_raw_data.py", "原始数据归档与清单"),
    ("clean_water_quality.py", "水质清洗"),
    ("clean_meteorology.py", "气象清洗"),
    ("clean_hydrology.py", "水文清洗"),
    ("clean_field_samples.py", "现场样本清洗"),
    ("clean_static_features.py", "静态特征清洗"),
    ("build_remote_sensing.py", "遥感索引与月度统计"),
    ("clean_latest_public_data.py", "最新CLMS/C3S/GFS清洗与代理训练表"),
    ("build_long_table.py", "统一长表"),
    ("build_model_dataset.py", "机器学习月度宽表"),
    ("build_quality_report.py", "质量报告"),
    ("write_cleaning_summary.py", "清洗总结(中文)"),
]

SKIP_SWITCHES = {
    "archive_raw_data.py": ("--no-archive", "跳过归档"),
    "build_remote_sensing.py": ("--no-remote", "跳过遥感处理(使用已有缓存)"),
}


def main() -> int:
    args = set(sys.argv[1:])
    for script, label in STEPS:
        skip_flag, skip_label = SKIP_SWITCHES.get(script, (None, ""))
        if skip_flag and skip_flag in args:
            print(f"\n===== [跳过] {script} ({skip_label}) =====")
            continue
        print(f"\n===== [执行] {script} — {label} =====")
        r = subprocess.run([sys.executable, str(HERE / script)], capture_output=False)
        if r.returncode != 0:
            print(f"!!!! 步骤失败: {script} (exit {r.returncode})")
            return r.returncode
    print("\n===== 全部步骤完成 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
