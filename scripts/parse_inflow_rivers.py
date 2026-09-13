"""江苏省控入湖河流逐月水质 · xlsx → 后端静态数据文件。

来源：江苏省提供的《太湖7个省控主要入湖河流2022年以来逐月数据.xlsx》，
原始件归档于 02_全部原始数据/01_当前主原始数据/jiangsu_inflow_rivers_monthly/
（与本仓库根目录同级，默认路径由脚本位置推导，换机器无需改代码）。
本脚本仅做格式转换（xlsx → JSON），不修改、不插补任何数值；
重复运行幂等（相同输入产出相同 JSON）。

用法（仓库根目录）：
    python scripts/parse_inflow_rivers.py --input <原始归档xlsx> [--output <输出JSON>]

不带参数时使用上述推导出的默认路径。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parents[1]
# 默认输入：仓库根的同级目录 ../02_全部原始数据/...（随 __file__ 推导，可移植）
DEFAULT_XLSX = (
    REPO_ROOT.parent
    / "02_全部原始数据"
    / "01_当前主原始数据"
    / "jiangsu_inflow_rivers_monthly"
    / "太湖7个省控主要入湖河流2022年以来逐月数据.xlsx"
)
# 默认输出：backend/app/data/inflow_rivers_monthly.json
DEFAULT_OUTPUT = REPO_ROOT / "backend" / "app" / "data" / "inflow_rivers_monthly.json"

# xlsx 列名 → JSON 字段名（与表头顺序一一对应）
PARAM_COLUMNS = {
    "水温(℃)": "temp_c",
    "pH(无量纲)": "ph",
    "溶解氧(mg/L)": "do",
    "高锰酸盐指数(mg/L)": "codmn",
    "化学需氧量(mg/L)": "cod",
    "五日生化需氧量(mg/L)": "bod5",
    "氨氮(mg/L)": "nh3n",
    "总磷(mg/L)": "tp",
}

MISSING_TOKENS = {"", "—", "-", "/", "无", "none", "null"}


def _num(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.lower() in MISSING_TOKENS:
        return None
    return float(text)


def parse(xlsx_path: Path) -> dict:
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["7个省控入湖断面"]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h is not None else "" for h in rows[0]]

    records: list[dict] = []
    sections: list[dict] = []
    seen_sections: set[str] = set()
    for row in rows[1:]:
        if row[3] is None:
            continue
        record = {
            "section": str(row[3]).strip(),
            "water": str(row[2]).strip(),
            "city": str(row[1]).strip(),
            "year": int(row[6]),
            "month": int(str(row[7]).replace("月", "")),
            "wq_class": str(row[8]).strip(),
            "record_source": str(row[0]).strip(),
        }
        for col_name, field in PARAM_COLUMNS.items():
            record[field] = _num(row[header.index(col_name)])
        record["ym"] = f"{record['year']:04d}-{record['month']:02d}"
        records.append(record)
        if record["section"] not in seen_sections:
            seen_sections.add(record["section"])
            sections.append(
                {"section": record["section"], "water": record["water"], "city": record["city"]}
            )

    records.sort(key=lambda r: r["ym"])  # 稳定排序：同月内保持原始断面顺序
    months = sorted({r["ym"] for r in records})
    return {
        "dataset_version": "JIANGSU_INFLOW_RIVERS_V1_20260913",
        "description": "太湖7个省控主要入湖河流断面逐月水质监测数据",
        "source": "江苏省提供的省级水环境例行监测数据（省内例行监测 / 省控融合终审）",
        "received_at": "2026-09-13",
        "cadence": "monthly",
        "start_month": months[0],
        "end_month": months[-1],
        "month_count": len(months),
        "parameters": {
            "temp_c": "水温(℃)",
            "ph": "pH(无量纲)",
            "do": "溶解氧(mg/L)",
            "codmn": "高锰酸盐指数(mg/L)",
            "cod": "化学需氧量(mg/L)",
            "bod5": "五日生化需氧量(mg/L)",
            "nh3n": "氨氮(mg/L)",
            "tp": "总磷(mg/L)",
        },
        "sections": sections,
        "records": records,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="江苏省控入湖河流逐月水质 xlsx → 后端静态数据 JSON（仅格式转换，不改数值）"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_XLSX,
        help=f"原始归档 xlsx 路径（默认：{DEFAULT_XLSX}）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"输出 JSON 路径（默认：{DEFAULT_OUTPUT}）",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    if not args.input.exists():
        raise SystemExit(f"找不到原始件：{args.input}（可用 --input 指定归档路径）")
    payload = parse(args.input)
    missing = sum(
        1 for r in payload["records"] for k in PARAM_COLUMNS.values() if r[k] is None
    )
    print(
        f"解析完成：{len(payload['records'])} 行 / {len(payload['sections'])} 断面 / "
        f"{payload['start_month']} ~ {payload['end_month']}（{payload['month_count']} 个月），参数缺失 {missing} 处"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"已写出：{args.output}")


if __name__ == "__main__":
    main()
