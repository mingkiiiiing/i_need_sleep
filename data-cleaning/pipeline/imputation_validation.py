from __future__ import annotations

"""Masked-value validation for the Taihu imputation policies.

The experiment starts from rows that are complete in the selected source
series, masks a deterministic 5/10/20 percent sample, runs the production
imputer, and scores only the masked values.  It never replaces the real
production data and keeps policy-blocked/insufficient series explicit in the
report instead of collapsing them into one aggregate score.
"""

import csv
import json
import math
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .impute import _parse_time, impute_short_gaps


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PACKAGE_ROOT / "storage" / "runs" / "p10_05_wind_uv_imputation" / "processed_observations.csv"
DEFAULT_OUTPUT = PACKAGE_ROOT / "storage" / "reports" / "imputation_validation.csv"
DEFAULT_SUMMARY = PACKAGE_ROOT / "storage" / "reports" / "imputation_validation_summary.json"
DEFAULT_DATABASE = PACKAGE_ROOT / "storage" / "reports" / "imputation_validation.sqlite"
DEFAULT_MASK_RATES = (0.05, 0.10, 0.20)
PROTECTED_VARIABLES = {"chlorophyll_a", "algae_density", "bloom_area_km2"}
WIND_VARIABLES = {"wind_speed", "wind_direction"}


def _number(value: Any) -> float | None:
    if value in (None, "", "None", "null", "nan", "NaN"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y", "t"}


def _flags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, "", "[]"):
        return []
    try:
        decoded = json.loads(str(value))
        return [str(item) for item in decoded] if isinstance(decoded, list) else [str(decoded)]
    except (TypeError, ValueError, json.JSONDecodeError):
        return [str(value)]


def read_observations(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for index, raw in enumerate(csv.DictReader(handle), start=1):
            row = dict(raw)
            for key in ("clean_value", "observed_value", "raw_value", "wind_u_component", "wind_v_component"):
                row[key] = _number(row.get(key))
            row["is_imputed"] = _bool(row.get("is_imputed"))
            row["observed_flag"] = int(_bool(row.get("observed_flag"))) if row.get("observed_flag") not in (None, "") else 1
            row["imputation_flag"] = int(_bool(row.get("imputation_flag")))
            row["quality_flags"] = _flags(row.get("quality_flags"))
            row["_validation_id"] = f"{row.get('source_id','')}|{row.get('source_row','')}|{index}"
            rows.append(row)
    return rows


def _series_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (row.get("source_id"), row.get("station_id"), row.get("scene_id"), row.get("variable_code"))


def _group_rows(rows: Iterable[dict[str, Any]]) -> dict[tuple[Any, ...], list[dict[str, Any]]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if _parse_time(row.get("observed_at")) is not None:
            groups[_series_key(row)].append(row)
    for members in groups.values():
        members.sort(key=lambda item: _parse_time(item.get("observed_at")) or datetime.max.replace(tzinfo=timezone.utc))
    return groups


def _variable_inventory(rows: list[dict[str, Any]], min_series_length: int) -> dict[str, dict[str, int]]:
    inventory: dict[str, dict[str, int]] = {}
    groups = _group_rows(rows)
    variables = sorted({str(row.get("variable_code") or "") for row in rows if row.get("variable_code")})
    for variable in variables:
        variable_groups = [members for key, members in groups.items() if key[-1] == variable]
        complete_groups = [members for members in variable_groups if len(members) >= min_series_length and all(_number(item.get("clean_value")) is not None for item in members)]
        inventory[variable] = {
            "series_count": len(variable_groups),
            "complete_series_count": len(complete_groups),
            "row_count": sum(len(members) for members in variable_groups),
            "complete_row_count": sum(len(members) for members in complete_groups),
            "short_series_count": sum(1 for members in variable_groups if len(members) < min_series_length),
            "incomplete_series_count": sum(1 for members in variable_groups if len(members) >= min_series_length and not all(_number(item.get("clean_value")) is not None for item in members)),
        }
    return inventory


def _complete_rows_for_variable(rows: list[dict[str, Any]], variable: str, min_series_length: int) -> list[dict[str, Any]]:
    groups = _group_rows([row for row in rows if str(row.get("variable_code") or "") == variable])
    selected: list[dict[str, Any]] = []
    for members in groups.values():
        if len(members) >= min_series_length and all(_number(item.get("clean_value")) is not None for item in members):
            selected.extend(members)
    return selected


def _mask_seed(variable: str, rate: float, seed: int) -> int:
    stable_variable_code = sum((position + 1) * ord(char) for position, char in enumerate(variable))
    return seed + stable_variable_code + int(round(rate * 1000))


def _copy_for_trial(rows: list[dict[str, Any]], target_variable: str, rate: float, seed: int, min_series_length: int) -> tuple[list[dict[str, Any]], dict[str, float], int]:
    """Return trial rows, truth by validation id and target mask count."""

    base = [dict(row) for row in rows]
    # Wind vector reconstruction needs both speed and direction rows in the
    # trial, while scoring remains limited to the requested target variable.
    trial_variables = WIND_VARIABLES if target_variable in WIND_VARIABLES else {target_variable}
    trial_rows = [row for row in base if str(row.get("variable_code") or "") in trial_variables]
    targets = _complete_rows_for_variable(base, target_variable, min_series_length)
    target_ids = [str(row["_validation_id"]) for row in targets]
    mask_count = max(1, int(round(len(target_ids) * rate))) if target_ids else 0
    rng = random.Random(_mask_seed(target_variable, rate, seed))
    selected_ids = set(rng.sample(target_ids, min(mask_count, len(target_ids)))) if target_ids else set()
    truth: dict[str, float] = {}
    for row in trial_rows:
        row_id = str(row["_validation_id"])
        if row_id in selected_ids:
            value = _number(row.get("clean_value"))
            if value is not None:
                truth[row_id] = value
                row["clean_value"] = None
                row["observed_value"] = None
                row["raw_value"] = None
                row["is_imputed"] = False
                row["value_origin"] = "masked_validation"
                row["imputation_method"] = None
                # This is a validation mask, not a source-mechanism claim.
                # The production imputer still rechecks bracketing donors and
                # the <=3-step rule; the explicit tag avoids repeating the
                # O(n^2) mechanism search for every artificially masked row.
                row["missing_mechanism"] = "temporal_gap_short"
                row["imputation_flag"] = 0
                row["observed_flag"] = 0
                row["quality_flags"] = list(dict.fromkeys([*row.get("quality_flags", []), "Q_MASK_TEST"]))
    return trial_rows, truth, len(selected_ids)


def _score_trial(
    *,
    rows: list[dict[str, Any]],
    truth: dict[str, float],
    target_variable: str,
    rate: float,
    inventory: dict[str, int],
    method: str,
    seed: int,
) -> dict[str, Any]:
    masked_count = len(truth)
    if not truth:
        return {
            "variable_code": target_variable, "mask_rate": rate, "method": method, "status": "skipped_no_complete_series",
            "masked_count": 0, "imputed_count": 0, "blocked_count": 0, "coverage": None, "mae": None, "rmse": None,
            "series_count": inventory.get("series_count", 0), "complete_series_count": inventory.get("complete_series_count", 0),
            "complete_row_count": inventory.get("complete_row_count", 0), "seed": seed, "notes": "no complete high-frequency series met the minimum length",
        }
    if method == "policy_blocked":
        return {
            "variable_code": target_variable, "mask_rate": rate, "method": method, "status": "policy_blocked",
            "masked_count": masked_count, "imputed_count": 0, "blocked_count": masked_count, "coverage": 0.0, "mae": None, "rmse": None,
            "series_count": inventory.get("series_count", 0), "complete_series_count": inventory.get("complete_series_count", 0),
            "complete_row_count": inventory.get("complete_row_count", 0), "seed": seed, "notes": "production policy forbids automatic imputation for this variable",
        }
    result = impute_short_gaps(rows, max_gap_steps=3, step_minutes=60, method="linear_time")
    predicted: dict[str, float] = {}
    for row in rows:
        row_id = str(row.get("_validation_id"))
        if row_id not in truth:
            continue
        value = _number(row.get("clean_value"))
        if value is not None and (_bool(row.get("is_imputed")) or str(row.get("value_origin") or "").casefold() == "imputed"):
            predicted[row_id] = value
    def _error(predicted_value: float, truth_value: float) -> float:
        if target_variable == "wind_direction":
            # Directions are circular; 359° versus 1° is a 2° error, not
            # a 358° error.
            return ((predicted_value - truth_value + 180.0) % 360.0) - 180.0
        return predicted_value - truth_value

    errors = [_error(predicted[row_id], truth[row_id]) for row_id in truth if row_id in predicted]
    imputed_count = len(errors)
    coverage = imputed_count / masked_count if masked_count else None
    mae = sum(abs(error) for error in errors) / imputed_count if errors else None
    rmse = math.sqrt(sum(error * error for error in errors) / imputed_count) if errors else None
    methods_seen = sorted({str(row.get("imputation_method")) for row in result.get("imputed", []) if row.get("_validation_id") in truth and row.get("imputation_method")})
    return {
        "variable_code": target_variable, "mask_rate": rate,
        "method": methods_seen[0] if len(methods_seen) == 1 else method,
        "status": "evaluated" if imputed_count else "no_coverage",
        "masked_count": masked_count, "imputed_count": imputed_count, "blocked_count": masked_count - imputed_count,
        "coverage": round(coverage, 9) if coverage is not None else None,
        "mae": round(mae, 9) if mae is not None else None,
        "rmse": round(rmse, 9) if rmse is not None else None,
        "series_count": inventory.get("series_count", 0), "complete_series_count": inventory.get("complete_series_count", 0),
        "complete_row_count": inventory.get("complete_row_count", 0), "seed": seed,
        "notes": "scores use only masked rows successfully reconstructed by the production imputer" + ("; wind_direction uses circular shortest-angle error" if target_variable == "wind_direction" else ""),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "variable_code", "mask_rate", "method", "status", "masked_count", "imputed_count", "blocked_count",
        "coverage", "mae", "rmse", "series_count", "complete_series_count", "complete_row_count", "seed", "notes",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_sqlite(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE IF EXISTS imputation_validation")
        connection.execute(
            """CREATE TABLE imputation_validation (
                variable_code TEXT, mask_rate REAL, method TEXT, status TEXT,
                masked_count INTEGER, imputed_count INTEGER, blocked_count INTEGER,
                coverage REAL, mae REAL, rmse REAL, series_count INTEGER,
                complete_series_count INTEGER, complete_row_count INTEGER, seed INTEGER, notes TEXT
            )"""
        )
        columns = [
            "variable_code", "mask_rate", "method", "status", "masked_count", "imputed_count", "blocked_count",
            "coverage", "mae", "rmse", "series_count", "complete_series_count", "complete_row_count", "seed", "notes",
        ]
        connection.executemany(
            f"INSERT INTO imputation_validation ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            [tuple(row.get(column) for column in columns) for row in rows],
        )
        connection.commit()
    finally:
        connection.close()


def run_imputation_validation(
    input_path: Path = DEFAULT_INPUT,
    output_path: Path = DEFAULT_OUTPUT,
    *,
    summary_path: Path = DEFAULT_SUMMARY,
    database: Path | None = DEFAULT_DATABASE,
    mask_rates: Iterable[float] = DEFAULT_MASK_RATES,
    seed: int = 20260819,
    min_series_length: int = 10,
) -> dict[str, Any]:
    if min_series_length < 2:
        raise ValueError("min_series_length must be at least 2")
    rates = tuple(float(rate) for rate in mask_rates)
    if not rates or any(rate <= 0 or rate >= 1 for rate in rates):
        raise ValueError("mask_rates must be between 0 and 1")
    rows = read_observations(Path(input_path))
    inventory = _variable_inventory(rows, min_series_length)
    result_rows: list[dict[str, Any]] = []
    for variable in sorted(inventory):
        selected_method = "policy_blocked" if variable in PROTECTED_VARIABLES else "uv_linear_interpolation" if variable in WIND_VARIABLES else "linear_time"
        for rate in rates:
            trial_rows, truth, _ = _copy_for_trial(rows, variable, rate, seed, min_series_length)
            result_rows.append(
                _score_trial(
                    rows=trial_rows, truth=truth, target_variable=variable, rate=rate,
                    inventory=inventory[variable], method=selected_method,
                    seed=_mask_seed(variable, rate, seed),
                )
            )
    _write_csv(Path(output_path), result_rows)
    if database is not None:
        _write_sqlite(Path(database), result_rows)
    summary = {
        "run_id": f"imputation_validation_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "status": "completed",
        "task_id": "P10-10",
        "input": str(input_path),
        "output": str(output_path),
        "database": str(database) if database else None,
        "input_rows": len(rows),
        "variables": inventory,
        "mask_rates": list(rates),
        "min_series_length": min_series_length,
        "seed": seed,
        "result_rows": len(result_rows),
        "data_truth": "real complete source sequences with deterministic artificial masks; production input is never overwritten; metrics are variable-specific and score only masked truth rows",
        "policy": "linear_time for eligible high-frequency scalar series; uv_linear_interpolation for wind; protected algae variables remain policy_blocked; insufficient/low-frequency series remain explicit",
        "outputs": {"validation_csv": str(output_path), "summary": str(summary_path), "database": str(database) if database else None},
    }
    Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
    Path(summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
