from __future__ import annotations

"""P08-03 issue return for the read-only water-station preflight.

The report is deliberately a *reporting* step.  It reads the preflight
inventory, row-level quality issues and (when available) the original input
files; it never cleans, repairs, copies or publishes station observations.
Every returned issue has a file and field location, or an explicit
``authorization`` location when no authorized delivery exists.
"""

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .provenance import manifest_root
from .sources.common import PACKAGE_ROOT
from .sources.local_files import _as_time, _canonical, _first, _key, _load_alias_map, _read_rows
from .sources.water_station import DEFAULT_UNITS
from .time_contract import parse_time


SUPPORTED_SUFFIXES = {".json", ".csv", ".tsv", ".xlsx"}
DEFAULT_PREFLIGHT_ROOT = PACKAGE_ROOT / "storage" / "runs" / "waterstation_preflight"
DEFAULT_REPORT = PACKAGE_ROOT / "storage" / "reports" / "waterstation_preflight_issues.csv"
DEFAULT_SUMMARY = PACKAGE_ROOT / "storage" / "reports" / "waterstation_preflight_issues_summary.json"

REPORT_FIELDS = [
    "issue_id",
    "severity",
    "gate",
    "issue_type",
    "input_path",
    "source_row",
    "station_id",
    "variable_code",
    "observed_at",
    "field",
    "value",
    "message",
    "impact",
    "likely_cause",
    "recommended_action",
    "evidence_source",
]


ISSUE_SPECS: dict[str, dict[str, str]] = {
    "authorization_gap": {
        "severity": "critical",
        "gate": "P0",
        "field": "authorization",
        "message": "授权交付缺口",
        "impact": "无法验证真实水站数据，禁止进入正式数据库",
        "action": "取得书面授权和交付清单后重新预检",
    },
    "file_parse_failed": {
        "severity": "critical",
        "gate": "P0",
        "field": "file",
        "message": "文件解析失败",
        "impact": "该文件没有可用标准观测行",
        "action": "修复文件格式/编码后重新预检",
    },
    "file_unreadable": {
        "severity": "critical",
        "gate": "P0",
        "field": "file",
        "message": "原始文件不可读或已丢失",
        "impact": "无法复核文件内容和质量问题",
        "action": "恢复原始交付文件并保持其SHA-256不变",
    },
    "empty_or_unmapped_file": {
        "severity": "critical",
        "gate": "P0",
        "field": "schema",
        "message": "文件为空或没有映射出标准观测行",
        "impact": "字段覆盖和P0变量覆盖无法成立",
        "action": "补充标准表头/变量别名或提供非空原始导出",
    },
    "duplicate_file": {
        "severity": "high",
        "gate": "P1",
        "field": "sha256",
        "message": "文件内容哈希重复，已跳过",
        "impact": "重复文件不能作为独立批次计数",
        "action": "保留一份原始文件并记录交付关系；不要重复入库",
    },
    "coordinate_error": {
        "severity": "high",
        "gate": "P0",
        "field": "longitude/latitude",
        "message": "坐标缺陷：非数值或超出经纬度范围",
        "impact": "无法进行站点空间匹配和遥感像元配对",
        "action": "核对坐标顺序、CRS和单位后重新预检",
    },
    "missing_required_field": {
        "severity": "critical",
        "gate": "P0",
        "field": "variable_code/value",
        "message": "缺少标准变量或数值字段",
        "impact": "该行无法进入标准观测表",
        "action": "补充长表变量/数值列或可识别的宽表指标列",
    },
    "no_valid_rows": {
        "severity": "critical",
        "gate": "P0",
        "field": "records",
        "message": "没有形成有效标准观测行",
        "impact": "正式数据库没有可用水站记录",
        "action": "处理文件级和字段级问题后重新预检",
    },
    "preflight_issue": {
        "severity": "high",
        "gate": "P0",
        "field": "record",
        "message": "预检问题",
        "impact": "该记录不能无条件进入正式数据库",
        "action": "核对原始文件和字段契约后重新预检",
    },
    "missing_or_invalid_time": {
        "severity": "critical",
        "gate": "P0",
        "field": "observed_at",
        "message": "观测时间缺失、格式非法或缺少时区",
        "impact": "无法进行时间对齐、频率覆盖和防未来信息泄漏检查",
        "action": "补充ISO-8601时间和明确时区；修正后重新预检",
    },
    "missing_station_id": {
        "severity": "critical",
        "gate": "P0",
        "field": "station_id",
        "message": "站点标识缺失",
        "impact": "无法建立站点级时间序列、空间匹配和站点覆盖矩阵",
        "action": "补充授权站点编号，或提供独立站点映射表后重新预检",
    },
    "missing_or_invalid_value": {
        "severity": "critical",
        "gate": "P0",
        "field": "value",
        "message": "观测值缺失或不可解析为数值",
        "impact": "该观测不能进入标准值表或质量统计",
        "action": "保留原始缺测码，补正合法数值或按缺测规则标记后重新预检",
    },
    "unit_mismatch": {
        "severity": "critical",
        "gate": "P0",
        "field": "unit",
        "message": "单位与变量契约不一致",
        "impact": "直接换算会造成量纲错误并污染机理特征",
        "action": "提供原始单位和换算规则，或修正单位后重新预检",
    },
    "unsupported_variable": {
        "severity": "critical",
        "gate": "P0",
        "field": "variable_code",
        "message": "变量编码无法映射到标准字段",
        "impact": "该变量不会进入P0目标/驱动覆盖判断",
        "action": "补充字段别名或变量字典映射后重新预检",
    },
    "out_of_range": {
        "severity": "high",
        "gate": "P0",
        "field": "value",
        "message": "数值超出配置的物理范围",
        "impact": "可能是单位、传感器或录入错误，不能直接用于训练",
        "action": "核对原始质量码、单位和传感器量程；不要静默删除",
    },
    "duplicate_key": {
        "severity": "high",
        "gate": "P1",
        "field": "record_key",
        "message": "同一来源、站点、时间和变量出现重复记录",
        "impact": "会改变频率统计并造成训练样本重复权重",
        "action": "保留原值，确认更新/更正语义后按规则去重",
    },
}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _float_coordinate(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _spec(code: str) -> dict[str, str]:
    return ISSUE_SPECS.get(
        code,
        {
            "severity": "high",
            "gate": "P0",
            "field": "record",
            "message": f"预检问题：{code}",
            "impact": "该记录不能无条件进入正式数据库",
            "action": "核对原始文件和字段契约后重新预检",
        },
    )


def _issue_row(
    number: int,
    *,
    issue_type: str,
    input_path: Any = None,
    source_row: Any = None,
    station_id: Any = None,
    variable_code: Any = None,
    observed_at: Any = None,
    field: str | None = None,
    value: Any = None,
    message: str | None = None,
    impact: str | None = None,
    likely_cause: str | None = None,
    recommended_action: str | None = None,
    evidence_source: str = "preflight",
) -> dict[str, Any]:
    spec = _spec(issue_type)
    return {
        "issue_id": f"P08-03-{number:05d}",
        "severity": spec["severity"],
        "gate": spec["gate"],
        "issue_type": issue_type,
        "input_path": _text(input_path),
        "source_row": _text(source_row),
        "station_id": _text(station_id),
        "variable_code": _text(variable_code),
        "observed_at": _text(observed_at),
        "field": field or spec["field"],
        "value": _text(value),
        "message": message or spec["message"],
        "impact": impact or spec["impact"],
        "likely_cause": likely_cause or "需要根据原始文件和授权交付说明复核",
        "recommended_action": recommended_action or spec["action"],
        "evidence_source": evidence_source,
    }


def _split_issue_codes(value: Any) -> list[str]:
    return [item.strip() for item in _text(value).split(",") if item.strip()]


def _raw_schema_issues(path: Path, add: Callable[..., None]) -> None:
    """Add row-level time/station/coordinate/schema findings from the source file."""

    try:
        rows = _read_rows(path)
    except Exception as exc:
        add(
            issue_type="file_unreadable",
            input_path=path,
            field="file",
            value=str(exc),
            likely_cause="文件编码、压缩结构或格式损坏",
            evidence_source="raw_file_audit",
        )
        return
    if not rows:
        add(
            issue_type="empty_or_unmapped_file",
            input_path=path,
            field="schema",
            likely_cause="文件为空，或表头未映射到水站观测字段",
            evidence_source="raw_file_audit",
        )
        return

    aliases = _load_alias_map()
    for row_number, raw in enumerate(rows, start=2):
        time_value = _first(raw, "observed_at", aliases) or _first(raw, "acquisition_at", aliases)
        time_status = parse_time(time_value).get("status")
        if time_status != "accepted":
            add(
                issue_type="missing_or_invalid_time",
                input_path=path,
                source_row=row_number,
                field="observed_at",
                value=time_value,
                likely_cause="原始时间为空、格式非法或未提供时区",
                evidence_source="raw_file_audit",
            )
        station = _first(raw, "station_id", aliases)
        if station in (None, ""):
            add(
                issue_type="missing_station_id",
                input_path=path,
                source_row=row_number,
                field="station_id",
                likely_cause="原始表缺少站点编号或该行为空",
                evidence_source="raw_file_audit",
            )

        for coordinate_field, low, high in (("longitude", -180.0, 180.0), ("latitude", -90.0, 90.0)):
            raw_coordinate = _first(raw, coordinate_field, aliases)
            if raw_coordinate in (None, ""):
                continue
            coordinate = _float_coordinate(raw_coordinate)
            if coordinate is None or not (low <= coordinate <= high):
                add(
                    issue_type="coordinate_error",
                    input_path=path,
                    source_row=row_number,
                    field=coordinate_field,
                    value=raw_coordinate,
                    likely_cause="坐标不是数值、超出经纬度范围或坐标列发生错位",
                    evidence_source="raw_file_audit",
                )

        variable_value = _first(raw, "variable_code", aliases)
        known_wide_variables = [
            _canonical(header, aliases)
            for header in raw
            if _canonical(header, aliases) in DEFAULT_UNITS
        ]
        if variable_value in (None, "") and not known_wide_variables:
            add(
                issue_type="missing_required_field",
                input_path=path,
                source_row=row_number,
                field="variable_code/value",
                likely_cause="既不是标准长表，也没有可识别的宽表指标列",
                evidence_source="raw_file_audit",
            )


def run_water_station_issue_report(
    preflight_root: Path | str = DEFAULT_PREFLIGHT_ROOT,
    *,
    input_root: Path | str | None = None,
    output_path: Path | str = DEFAULT_REPORT,
    summary_path: Path | str = DEFAULT_SUMMARY,
    manifest_path: Path | str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Create the auditable P08-03 issue return from one preflight run."""

    preflight_root = Path(preflight_root)
    inventory_path = preflight_root / "preflight_inventory.csv"
    preflight_issues_path = preflight_root / "preflight_issues.csv"
    preflight_summary_path = preflight_root / "preflight_summary.json"
    summary: dict[str, Any] = {}
    if preflight_summary_path.exists():
        summary = json.loads(preflight_summary_path.read_text(encoding="utf-8"))
    if input_root is None:
        input_root = PACKAGE_ROOT / "storage" / "raw" / "authorized_waterstation" / "inbox"
    input_root = Path(input_root)

    inventory = _read_csv(inventory_path)
    preflight_issues = _read_csv(preflight_issues_path)
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add(**kwargs: Any) -> None:
        key = (
            _text(kwargs.get("issue_type")),
            _text(kwargs.get("input_path")),
            _text(kwargs.get("source_row")),
            _text(kwargs.get("field")),
            _text(kwargs.get("value")),
        )
        if key in seen:
            return
        seen.add(key)
        rows.append(_issue_row(len(rows) + 1, **kwargs))

    for item in inventory:
        path = item.get("input_path") or ""
        status = _text(item.get("status"))
        if status == "parse_failed":
            add(issue_type="file_parse_failed", input_path=path, field="file", value=item.get("error"), likely_cause="文件无法按支持的格式解析", evidence_source="preflight_inventory")
        elif status == "duplicate_hash_skipped":
            add(issue_type="duplicate_file", input_path=path, field="sha256", value=item.get("sha256"), likely_cause=item.get("error") or "内容哈希与已处理文件相同", evidence_source="preflight_inventory")
        elif status == "parsed_empty":
            add(issue_type="empty_or_unmapped_file", input_path=path, field="schema", likely_cause="文件可读但未产生标准水站观测行", evidence_source="preflight_inventory")
        if status in {"parsed", "parsed_empty"} and path:
            source_path = Path(path)
            if source_path.exists():
                _raw_schema_issues(source_path, add)
            else:
                add(issue_type="file_unreadable", input_path=path, field="file", value="file_not_found", likely_cause="预检后原始文件被移动或删除", evidence_source="preflight_inventory")

    for item in preflight_issues:
        codes = _split_issue_codes(item.get("issues")) or ["preflight_issue"]
        for code in codes:
            spec = _spec(code)
            add(
                issue_type=code,
                input_path=item.get("source_file") or "",
                source_row=item.get("source_row"),
                station_id=item.get("station_id"),
                variable_code=item.get("variable_code"),
                observed_at=item.get("observed_at"),
                field=spec["field"],
                value=item.get("observed_value") if code in {"missing_or_invalid_value", "out_of_range"} else item.get("unit") if code == "unit_mismatch" else None,
                likely_cause=f"预检行质量标记：{code}",
                evidence_source="preflight_issues.csv",
            )

    preflight_status = _text(summary.get("status")) or "missing_preflight_summary"
    files_discovered = int(summary.get("files_discovered") or 0)
    if preflight_status == "blocked_no_valid_files" and files_discovered == 0:
        add(
            issue_type="authorization_gap",
            input_path=input_root,
            field="authorization",
            message="授权投递区没有发现可预检的水站/浮标文件",
            impact="无法验证字段、站点、时间、单位和质量覆盖；禁止进入正式数据库",
            likely_cause="P08-01尚未收到真实授权delivery，或文件未放入inbox/<delivery_id>/",
            recommended_action="取得书面授权和交付清单，将原始文件放入授权隔离目录后重新运行P08-02",
            evidence_source="preflight_summary.json",
        )
    elif preflight_status == "blocked_no_valid_files" and not rows:
        add(
            issue_type="no_valid_rows",
            input_path=input_root,
            field="records",
            message="发现输入文件但没有形成有效标准观测行",
            impact="正式数据库没有可用水站记录",
            likely_cause="文件解析失败、表头未映射或全部记录被质量门禁拦截",
            recommended_action="先处理文件级和字段级问题，再重新运行P08-02",
            evidence_source="preflight_summary.json",
        )

    output_file = Path(output_path)
    summary_file = Path(summary_path)
    _write_csv(output_file, rows)
    issue_counts = Counter(row["issue_type"] for row in rows)
    gate_counts = Counter(row["gate"] for row in rows)
    result_status = "ready" if preflight_status == "ready" and not rows else "blocked"
    report_summary = {
        "task_id": "P08-03",
        "status": result_status,
        "preflight_status": preflight_status,
        "preflight_root": str(preflight_root),
        "input_root": str(input_root),
        "files_discovered": files_discovered,
        "issue_rows": len(rows),
        "issue_counts": dict(issue_counts),
        "gate_counts": dict(gate_counts),
        "blocking_issue_count": sum(1 for row in rows if row["gate"] == "P0"),
        "report": str(output_file),
        "next_action": "fix all P0 issues and rerun waterstation-preflight" if rows else "no issues; retain report with the ready preflight manifest",
    }
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(report_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = PACKAGE_ROOT
    manifest_file = Path(manifest_path) if manifest_path else manifest_root(root) / f"waterstation_preflight_issues_{stamp}.json"
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id or f"waterstation_preflight_issues_{stamp}",
        "task_id": "P08-03",
        "status": result_status,
        "data_truth": "derived_from_preflight_artifacts",
        "preflight_status": preflight_status,
        "files": {"report": str(output_file), "summary": str(summary_file), "preflight_inventory": str(inventory_path), "preflight_issues": str(preflight_issues_path)},
        "summary": report_summary,
        "manifest": str(manifest_file),
    }
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "report": str(output_file), "summary_path": str(summary_file), "issue_rows": rows}


__all__ = ["DEFAULT_PREFLIGHT_ROOT", "DEFAULT_REPORT", "DEFAULT_SUMMARY", "run_water_station_issue_report"]
