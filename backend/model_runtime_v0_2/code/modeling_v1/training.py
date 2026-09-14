"""Resumable validation-only model selection and frozen-test evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .contracts import (
    BINARY_MIN_RECALL,
    CLAIM_BOUNDARY,
    DATA_VERSION,
    DECISION_THRESHOLD_POLICY,
    MODEL_FEATURE_COLUMNS,
    ROLLING_WINDOWS,
    RunSpec,
    WindowSpec,
    target_column,
)
from .data import BatchSource, fit_preprocessor, transform_batch, sample_frames
from .fusion import candidate_factories
from .metrics import choose_decision_threshold, evaluate_predictions
from .predict import ModelBundle, save_bundle


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"required file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _frame_digest(frame: pd.DataFrame, *, seed: int = 20260907) -> str:
    if frame.empty:
        return hashlib.sha256(b"empty").hexdigest()
    sorted_columns = sorted(frame.columns)
    working = frame.loc[:, sorted_columns].copy()
    values = pd.util.hash_pandas_object(working, index=False)
    return hashlib.sha256(values.to_numpy(np.uint64).tobytes()).hexdigest()


def _collect_split(
    source: BatchSource,
    split: str,
    feature_columns: Sequence[str],
    *,
    max_rows: int | None,
    seed: int,
) -> pd.DataFrame:
    requested = list(dict.fromkeys((*feature_columns, "actual")))
    audit_columns = []
    if hasattr(source, 'base'):
        audit_columns = [name for name in ('date', 'grid_id', 'experimental_zone_id') if name in source.base.schema_columns]
    combined = sample_frames(source.iter_batches(split, list(dict.fromkeys([*requested, *audit_columns]))), max_rows, seed=seed)
    if combined.empty:
        raise ValueError(f"no {split} rows were returned by the task source")
    if 'date' in audit_columns:
        dates = pd.to_datetime(combined.date)
        source.last_collection_audit = {
            'rows': len(combined), 'sampling_method': 'global_uniform_priority_v2',
            'issue_start': str(dates.min()), 'issue_end': str(dates.max()),
            'year_counts': {str(k): int(v) for k,v in dates.dt.year.value_counts().sort_index().items()},
            'month_counts': {str(k): int(v) for k,v in dates.dt.month.value_counts().sort_index().items()},
            'grid_count': int(combined.grid_id.nunique()),
            'zone_counts': combined.experimental_zone_id.value_counts().to_dict() if 'experimental_zone_id' in combined else {},
            'sample_key_sha256': _frame_digest(combined[audit_columns]),
        }
    return combined.loc[:, requested]


def _higher_is_better(primary_metric: str) -> bool:
    return primary_metric in {"pr_auc", "roc_auc", "macro_f1", "area_weighted_iou", "iou"}


def _select_best(
    validation_metrics: dict[str, dict], spec_primary_metric: str
) -> str:
    scored = [
        (name, metrics.get("primary_metric"))
        for name, metrics in validation_metrics.items()
        if metrics.get("primary_metric") is not None
        and not (
            isinstance(metrics.get("primary_metric"), float)
            and np.isnan(metrics["primary_metric"])
        )
    ]
    if not scored:
        raise ValueError("no candidate produced a usable validation primary metric")
    if _higher_is_better(spec_primary_metric):
        return max(scored, key=lambda item: float(item[1]))[0]
    return min(scored, key=lambda item: float(item[1]))[0]


def _attach_spatial_columns(
    predicted: pd.DataFrame,
    features: pd.DataFrame,
) -> pd.DataFrame:
    for column in ("centroid_x_m", "centroid_y_m", "water_area_m2"):
        if column in features.columns and column not in predicted.columns:
            predicted[column] = features[column].reset_index(drop=True)
    return predicted


def train_run(
    run_spec: RunSpec,
    source: BatchSource,
    output_dir: str | Path,
    *,
    stop_after: str = "full",
    feature_columns: Sequence[str] = MODEL_FEATURE_COLUMNS,
    max_train_rows: int | None = 200_000,
    max_validation_rows: int | None = 100_000,
    max_test_rows: int | None = 100_000,
    seed: int | None = None,
) -> dict[str, object]:
    """Fit all candidates, select on validation, and optionally evaluate test."""
    if stop_after not in {"selection", "full"}:
        raise ValueError("stop_after must be 'selection' or 'full'")
    run_seed = run_spec.seed if seed is None else int(seed)
    task_feature_columns = list(feature_columns)
    if run_spec.task.problem_type == "spatial":
        for column in ("centroid_x_m", "centroid_y_m"):
            if column not in task_feature_columns:
                task_feature_columns.append(column)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    run_config = {
        "run_id": run_spec.run_id,
        "task_id": run_spec.task.task_id,
        "variant": run_spec.task.variant,
        "target_column": target_column(
            run_spec.task.target_family, run_spec.horizon_days
        ),
        "horizon_days": run_spec.horizon_days,
        "problem_type": run_spec.task.problem_type,
        "primary_metric": run_spec.task.primary_metric,
        "seed": run_seed,
        "data_version": DATA_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    _write_json(run_config, output / "run_config.json")

    preprocessor = fit_preprocessor(
        source,
        task_feature_columns,
        split="train",
        max_rows=max_train_rows,
    )
    train = _collect_split(
        source,
        "train",
        task_feature_columns,
        max_rows=max_train_rows,
        seed=run_seed,
    )
    validation = _collect_split(
        source,
        "validation",
        task_feature_columns,
        max_rows=max_validation_rows,
        seed=run_seed,
    )
    train_features = transform_batch(
        preprocessor, train.loc[:, task_feature_columns]
    )
    train_features["actual"] = train["actual"].reset_index(drop=True)
    validation_features = transform_batch(
        preprocessor, validation.loc[:, task_feature_columns]
    )
    validation_features["actual"] = validation["actual"].reset_index(drop=True)
    data_digest = {
        "train_rows": int(len(train_features)),
        "validation_rows": int(len(validation_features)),
        "train_sha256": _frame_digest(
            train_features.sort_values("actual", kind="mergesort"), seed=run_seed
        ),
        "validation_sha256": _frame_digest(
            validation_features.sort_values("actual", kind="mergesort"), seed=run_seed
        ),
        "feature_columns": list(preprocessor.output_columns),
    }
    _write_json(data_digest, output / "data_digest.json")

    factories = candidate_factories(
        run_spec.task,
        seed=run_seed,
        horizon_days=run_spec.horizon_days,
    )
    if run_spec.task.problem_type == "ordinal":
        factories.pop("residual", None)
        factories.pop("mechanism_feature", None)
    validation_metrics: dict[str, dict] = {}
    validation_predictions: dict[str, pd.DataFrame] = {}
    for name, factory in factories.items():
        if name in {"simple_baseline", "random_forest", "xgboost", "mechanism"}:
            candidate = factory(train_features)
        else:
            candidate = factory(train_features, validation_features)
        predicted = candidate.predict_frame(
            validation_features.loc[:, list(preprocessor.output_columns)]
        )
        predicted["actual"] = validation_features["actual"].reset_index(drop=True)
        if run_spec.task.problem_type == "spatial":
            predicted = _attach_spatial_columns(predicted, validation_features)
        metrics = evaluate_predictions(run_spec.task, predicted)
        validation_metrics[name] = {str(key): value for key, value in metrics.items()}
        validation_predictions[name] = predicted
        output.joinpath("candidates", name).mkdir(parents=True, exist_ok=True)
        predicted.to_csv(
            output / "candidates" / name / "validation_predictions.csv",
            index=False,
        )
        _write_json(
            validation_metrics[name],
            output / "candidates" / name / "validation_metrics.json",
        )

    selected = _select_best(validation_metrics, run_spec.task.primary_metric)
    selection_payload = {
        "run_id": run_spec.run_id,
        "selected_family": selected,
        "task_id": run_spec.task.task_id,
        "variant": run_spec.task.variant,
        "horizon_days": run_spec.horizon_days,
        "target_column": run_config["target_column"],
        "validation_primary_metric": run_spec.task.primary_metric,
        "validation_value": validation_metrics[selected].get("primary_metric"),
        "validation_metrics_by_family": validation_metrics,
        "decision_threshold": 0.5,
        "feature_columns": list(preprocessor.output_columns),
        "feature_sha256": _sha256_text(
            json.dumps(list(preprocessor.output_columns), sort_keys=True)
        ),
        "train_sha256": data_digest["train_sha256"],
        "validation_sha256": data_digest["validation_sha256"],
        "seed": run_seed,
        "data_version": DATA_VERSION,
        "policy_version": "taihu-modeling-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(selection_payload, output / "selection_manifest.json")

    result: dict[str, object] = {
        "run_id": run_spec.run_id,
        "stop_after": stop_after,
        "selected_family": selected,
        "validation_value": validation_metrics[selected].get("primary_metric"),
        "validation_rows": int(len(validation_features)),
        "selection_manifest": str(output / "selection_manifest.json"),
    }
    if stop_after == "selection":
        return result

    test = _collect_split(
        source,
        "test",
        task_feature_columns,
        max_rows=max_test_rows,
        seed=run_seed,
    )
    test_features = transform_batch(
        preprocessor, test.loc[:, task_feature_columns]
    )
    test_metrics_by_family: dict[str, dict] = {}
    selected_test_frame: pd.DataFrame | None = None
    for name, factory in factories.items():
        if name in {"simple_baseline", "random_forest", "xgboost", "mechanism"}:
            candidate = factory(train_features)
        else:
            candidate = factory(train_features, validation_features)
        family_predicted = candidate.predict_frame(
            test_features.loc[:, list(preprocessor.output_columns)]
        )
        family_predicted["actual"] = test["actual"].reset_index(drop=True)
        if run_spec.task.problem_type == "spatial":
            family_predicted = _attach_spatial_columns(
                family_predicted, test_features
            )
        family_metrics = evaluate_predictions(run_spec.task, family_predicted)
        test_metrics_by_family[name] = {
            str(key): value for key, value in family_metrics.items()
        }
        if name == selected:
            selected_test_frame = family_predicted.copy()
    _write_json(test_metrics_by_family, output / "test_metrics_by_family.json")
    test_metrics = test_metrics_by_family[selected]
    _write_json(
        {str(key): value for key, value in test_metrics.items()},
        output / "test_metrics.json",
    )
    if selected_test_frame is None:
        raise RuntimeError("selected candidate test predictions were not produced")
    selected_test_frame.to_csv(output / "test_predictions.csv", index=False)
    evaluation_id = _sha256_text(
        json.dumps(
            {
                "selection": selection_payload,
                "test_rows": int(len(test_features)),
                "test_sha256": _frame_digest(test_features, seed=run_seed),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    _write_json(
        {
            "evaluation_id": evaluation_id,
            "run_id": run_spec.run_id,
            "test_rows": int(len(test_features)),
            "claim_boundary": CLAIM_BOUNDARY,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        output / "evaluation_manifest.json",
    )
    result.update(
        {
            "test_rows": int(len(test_features)),
            "test_primary_metric": run_spec.task.primary_metric,
            "test_value": test_metrics.get("primary_metric"),
            "evaluation_manifest": str(output / "evaluation_manifest.json"),
        }
    )
    return result


def _aggregate_window_metrics(
    metric_list: list[dict],
    primary_metric: str,
) -> dict[str, object]:
    if not metric_list:
        return {}
    values = [
        float(metric.get("primary_metric"))
        for metric in metric_list
        if metric.get("primary_metric") is not None
    ]
    primary = float(np.median(values)) if values else None
    return {
        "primary_metric": primary,
        "median_primary_metric": primary,
        "min_primary_metric": float(np.min(values)) if values else None,
        "max_primary_metric": float(np.max(values)) if values else None,
        "window_count": len(metric_list),
        "per_window": metric_list,
    }


def _fit_family(
    name: str,
    factory,
    train: pd.DataFrame,
    validation: pd.DataFrame | None = None,
    *, frozen_weight: float | None = None,
):
    if name == 'constrained_blend' and frozen_weight is not None:
        return factory(train, frozen_weight=frozen_weight)
    if name in {"simple_baseline", "random_forest", "xgboost", "mechanism"}:
        return factory(train)
    if validation is None:
        return factory(train)
    return factory(train, validation)


def _inner_calibration_window(window: WindowSpec) -> WindowSpec:
    """Reserve the final calendar year of outer TRAIN for weight calibration."""
    end = pd.Timestamp(window.train_end)
    calibration_start = pd.Timestamp(year=end.year, month=1, day=1)
    train_end = calibration_start - pd.Timedelta(days=1)
    if train_end < pd.Timestamp(window.train_start):
        raise ValueError('outer training period too short for temporal calibration')
    return WindowSpec(window.window_id + '_CAL', window.train_start, str(train_end.date()), str(calibration_start.date()), window.train_end)


def _calibrate_blend_weight(window, source_builder, factory, columns, sample_rows, validation_rows, seed):
    inner = _inner_calibration_window(window)
    source = source_builder(inner)
    preprocessor = fit_preprocessor(source, columns, max_rows=sample_rows)
    train = _collect_split(source, 'train', columns, max_rows=sample_rows, seed=seed)
    train_audit = getattr(source, 'last_collection_audit', {})
    calibration = _collect_split(source, 'validation', columns, max_rows=validation_rows, seed=seed)
    calibration_audit = getattr(source, 'last_collection_audit', {})
    x = transform_batch(preprocessor, train[columns]).assign(actual=train.actual.to_numpy())
    c = transform_batch(preprocessor, calibration[columns]).assign(actual=calibration.actual.to_numpy())
    candidate = factory(x, c)
    return float(candidate.weight), {'window': asdict(inner), 'train': train_audit, 'calibration': calibration_audit}


def _calibrate_selected_thresholds(
    run_spec: RunSpec,
    source_builder,
    factories,
    selected: str,
    blend_weights: list[float],
    feature_columns: Sequence[str],
    sample_rows: int,
    validation_rows: int,
    seed: int,
) -> list[dict]:
    """Tune the binary operating threshold on each inner temporal calibration year."""
    audits: list[dict] = []
    for window, blend_weight in zip(ROLLING_WINDOWS, blend_weights):
        inner = _inner_calibration_window(window)
        source = source_builder(inner)
        preprocessor = fit_preprocessor(
            source,
            feature_columns,
            split="train",
            max_rows=sample_rows,
        )
        train = _collect_split(
            source,
            "train",
            feature_columns,
            max_rows=sample_rows,
            seed=seed,
        )
        calibration = _collect_split(
            source,
            "validation",
            feature_columns,
            max_rows=validation_rows,
            seed=seed,
        )
        train_features = transform_batch(
            preprocessor, train.loc[:, feature_columns]
        )
        train_features["actual"] = train["actual"].reset_index(drop=True)
        calibration_features = transform_batch(
            preprocessor, calibration.loc[:, feature_columns]
        )
        calibration_features["actual"] = calibration["actual"].reset_index(
            drop=True
        )
        frozen_weight = (
            float(blend_weight)
            if selected == "constrained_blend"
            else None
        )
        candidate = _fit_family(
            selected,
            factories[selected],
            train_features,
            frozen_weight=frozen_weight,
        )
        predicted = candidate.predict_frame(
            calibration_features.loc[:, list(preprocessor.output_columns)]
        )
        predicted["actual"] = calibration["actual"].reset_index(drop=True)
        scores = (
            predicted["probability"].to_numpy(dtype=float)
            if "probability" in predicted.columns
            else predicted["prediction"].to_numpy(dtype=float)
        )
        tuning = choose_decision_threshold(
            predicted["actual"].to_numpy(dtype=float),
            scores,
            min_recall=BINARY_MIN_RECALL,
        )
        audits.append(
            {
                **tuning,
                "window_id": window.window_id,
                "calibration_window": asdict(inner),
                "selected_family": selected,
                "calibration_rows": int(len(calibration)),
            }
        )
    return audits


def train_run_rolling(
    run_spec: RunSpec,
    source_builder,
    test_source,
    output_dir: str | Path,
    *,
    feature_columns: Sequence[str] = MODEL_FEATURE_COLUMNS,
    sample_rows: int = 200_000,
    validation_rows: int = 100_000,
    test_rows: int = 100_000,
    seed: int | None = None,
    stop_after: str = 'full',
) -> dict[str, object]:
    """Rolling-window candidate selection followed by one frozen test run."""
    run_seed = run_spec.seed if seed is None else int(seed)
    if stop_after not in {'selection', 'full'}:
        raise ValueError('stop_after must be selection or full')
    existing = Path(output_dir)
    if existing.exists() and any(existing.iterdir()):
        raise FileExistsError('rolling runs require a new output directory to avoid stale artifacts')
    task_feature_columns = list(feature_columns)
    if run_spec.task.problem_type == "spatial":
        for column in ("centroid_x_m", "centroid_y_m"):
            if column not in task_feature_columns:
                task_feature_columns.append(column)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    run_config = {
        "run_id": run_spec.run_id,
        "task_id": run_spec.task.task_id,
        "variant": run_spec.task.variant,
        "target_column": target_column(
            run_spec.task.target_family, run_spec.horizon_days
        ),
        "horizon_days": run_spec.horizon_days,
        "problem_type": run_spec.task.problem_type,
        "primary_metric": run_spec.task.primary_metric,
        "seed": run_seed,
        "mode": "rolling_window_v1",
        "data_version": DATA_VERSION,
        "claim_boundary": CLAIM_BOUNDARY,
        "sampling_version": "global_uniform_priority_v2",
        "fusion_validation": "inner_temporal_calibration_frozen_refit",
    }
    _write_json(run_config, output / "run_config.json")

    factories = candidate_factories(
        run_spec.task,
        seed=run_seed,
        horizon_days=run_spec.horizon_days,
    )
    if run_spec.task.problem_type == "ordinal":
        factories.pop("residual", None)
        factories.pop("mechanism_feature", None)

    aggregated_metrics: dict[str, dict] = {}
    window_row_counts: dict[str, dict[str, int]] = {}
    blend_weights: list[float] = []
    window_audits: dict[str, dict] = {}
    window_out = output / "rolling"
    for window in ROLLING_WINDOWS:
        source = source_builder(window)
        preprocessor = fit_preprocessor(
            source,
            task_feature_columns,
            split="train",
            max_rows=sample_rows,
        )
        train = _collect_split(
            source,
            "train",
            task_feature_columns,
            max_rows=sample_rows,
            seed=run_seed,
        )
        train_audit = getattr(source, 'last_collection_audit', {})
        validation = _collect_split(
            source,
            "validation",
            task_feature_columns,
            max_rows=validation_rows,
            seed=run_seed,
        )
        validation_audit = getattr(source, 'last_collection_audit', {})
        train_features = transform_batch(
            preprocessor, train.loc[:, task_feature_columns]
        )
        train_features["actual"] = train["actual"].reset_index(drop=True)
        validation_features = transform_batch(
            preprocessor, validation.loc[:, task_feature_columns]
        )
        validation_features["actual"] = validation["actual"].reset_index(drop=True)
        weight, calibration_audit = _calibrate_blend_weight(window, source_builder, factories['constrained_blend'], task_feature_columns, sample_rows, validation_rows, run_seed)
        blend_weights.append(weight)
        window_audits[window.window_id] = {'train': train_audit, 'validation': validation_audit, 'blend_calibration': calibration_audit, 'frozen_blend_weight': weight}

        window_metrics: dict[str, dict] = {}
        window_dir = window_out / window.window_id
        for name, factory in factories.items():
            candidate = _fit_family(name, factory, train_features, frozen_weight=weight if name == 'constrained_blend' else None)
            predicted = candidate.predict_frame(
                validation_features.loc[:, list(preprocessor.output_columns)]
            )
            predicted["actual"] = validation_features["actual"].reset_index(drop=True)
            if run_spec.task.problem_type == "spatial":
                predicted = _attach_spatial_columns(predicted, validation_features)
            metrics = evaluate_predictions(run_spec.task, predicted)
            window_metrics[name] = {str(key): value for key, value in metrics.items()}
            (window_dir / "candidates" / name).mkdir(parents=True, exist_ok=True)
            predicted.to_csv(
                window_dir / "candidates" / name / "validation_predictions.csv",
                index=False,
            )
            _write_json(
                window_metrics[name],
                window_dir / "candidates" / name / "validation_metrics.json",
            )
            aggregated_metrics.setdefault(name, []).append(window_metrics[name])
        window_row_counts[window.window_id] = {
            "train_rows": int(len(train_features)),
            "validation_rows": int(len(validation_features)),
        }
        _write_json(
            {
                "window_id": window.window_id,
                "train_rows": int(len(train_features)),
                "validation_rows": int(len(validation_features)),
                "validation_metrics": window_metrics,
                "sampling_and_calibration": window_audits[window.window_id],
            },
            window_dir / "window_manifest.json",
        )

    summary_metrics = {
        name: _aggregate_window_metrics(metric_list, run_spec.task.primary_metric)
        for name, metric_list in aggregated_metrics.items()
    }
    _write_json(summary_metrics, output / "validation_metrics.json")
    selected = _select_best(summary_metrics, run_spec.task.primary_metric)
    selected_validation = summary_metrics[selected].get("primary_metric")
    median_blend_weight = (
        float(np.median(blend_weights)) if blend_weights else 0.5
    )
    threshold_audits = None
    decision_threshold = None
    if run_spec.task.problem_type == "binary":
        threshold_audits = _calibrate_selected_thresholds(
            run_spec,
            source_builder,
            factories,
            selected,
            blend_weights,
            task_feature_columns,
            sample_rows,
            validation_rows,
            run_seed,
        )
        decision_threshold = float(
            np.median(
                [audit["decision_threshold"] for audit in threshold_audits]
            )
        )

    selection_payload = {
        "run_id": run_spec.run_id,
        "selected_family": selected,
        "task_id": run_spec.task.task_id,
        "variant": run_spec.task.variant,
        "horizon_days": run_spec.horizon_days,
        "target_column": run_config["target_column"],
        "validation_primary_metric": run_spec.task.primary_metric,
        "validation_value": selected_validation,
        "mode": "rolling_window_v1",
        "windows": [
            {
                "window_id": window.window_id,
                "train_start": window.train_start,
                "train_end": window.train_end,
                "validation_start": window.validation_start,
                "validation_end": window.validation_end,
            }
            for window in ROLLING_WINDOWS
        ],
        "decision_policy": (
            DECISION_THRESHOLD_POLICY
            if run_spec.task.problem_type == "binary"
            else "not_applicable"
        ),
        "decision_min_recall": (
            BINARY_MIN_RECALL
            if run_spec.task.problem_type == "binary"
            else None
        ),
        "decision_threshold": decision_threshold,
        "decision_threshold_by_window": threshold_audits,
        "feature_sha256": _sha256_text(
            json.dumps(list(task_feature_columns), sort_keys=True)
        ),
        "seed": run_seed,
        "data_version": DATA_VERSION,
        "policy_version": "taihu-modeling-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "frozen_blend_weight": median_blend_weight,
        "blend_weight_policy": "median_of_inner_temporal_calibration_weights",
    }
    _write_json(selection_payload, output / "selection_manifest.json")
    _write_json(
        {
            "mode": "rolling_window_v1",
            "window_row_counts": window_row_counts,
            "window_audits": window_audits,
        },
        output / "data_digest.json",
    )
    if stop_after == 'selection':
        return {'run_id': run_spec.run_id, 'mode': 'rolling_window_v1', 'selected_family': selected, 'validation_value': selected_validation, 'test_evaluated': False}

    final_window = WindowSpec(
        window_id="FINAL",
        train_start="2005-01-01",
        train_end="2021-12-31",
        validation_start="2022-01-01",
        validation_end="2022-12-31",
    )
    final_source = source_builder(final_window)
    final_preprocessor = fit_preprocessor(
        final_source,
        task_feature_columns,
        split="train",
        max_rows=sample_rows,
    )
    final_train = _collect_split(
        final_source,
        "train",
        task_feature_columns,
        max_rows=sample_rows,
        seed=run_seed,
    )
    final_train_features = transform_batch(
        final_preprocessor, final_train.loc[:, task_feature_columns]
    )
    final_train_features["actual"] = final_train["actual"].reset_index(drop=True)

    test = _collect_split(
        test_source,
        "test",
        task_feature_columns,
        max_rows=test_rows,
        seed=run_seed,
    )
    test_features = transform_batch(
        final_preprocessor, test.loc[:, task_feature_columns]
    )
    test_metrics_by_family: dict[str, dict] = {}
    selected_test_frame: pd.DataFrame | None = None
    test_decision_threshold = (
        float(selection_payload["decision_threshold"])
        if selection_payload.get("decision_threshold") is not None
        else 0.5
    )
    for name, factory in factories.items():
        candidate = _fit_family(
            name,
            factory,
            final_train_features,
            frozen_weight=selection_payload['frozen_blend_weight'] if name == 'constrained_blend' else None,
        )
        family_predicted = candidate.predict_frame(
            test_features.loc[:, list(final_preprocessor.output_columns)]
        )
        family_predicted["actual"] = test["actual"].reset_index(drop=True)
        if (
            run_spec.task.problem_type == "binary"
            and "probability" in family_predicted.columns
        ):
            family_predicted["prediction"] = (
                family_predicted["probability"] >= test_decision_threshold
            ).astype("int8")
        if run_spec.task.problem_type == "spatial":
            family_predicted = _attach_spatial_columns(
                family_predicted, test_features
            )
        family_metrics = evaluate_predictions(
            run_spec.task,
            family_predicted,
            decision_threshold=(
                test_decision_threshold
                if run_spec.task.problem_type == "binary"
                else 0.5
            ),
        )
        test_metrics_by_family[name] = {
            str(key): value for key, value in family_metrics.items()
        }
        if name == selected:
            selected_test_frame = family_predicted.copy()
            selected_bundle = ModelBundle(
                model=candidate,
                preprocessor=final_preprocessor,
                feature_columns=tuple(final_preprocessor.feature_columns),
                feature_units={},
                target=run_config["target_column"],
                horizon_days=run_spec.horizon_days,
                task_id=run_spec.task.task_id,
                data_version=DATA_VERSION,
                claim_boundary=CLAIM_BOUNDARY,
                decision_threshold=(
                    test_decision_threshold
                    if run_spec.task.problem_type == "binary"
                    else None
                ),
            )
            save_bundle(selected_bundle, output)
    _write_json(test_metrics_by_family, output / "test_metrics_by_family.json")
    selected_test_metrics = test_metrics_by_family[selected]
    _write_json(
        {str(key): value for key, value in selected_test_metrics.items()},
        output / "test_metrics.json",
    )
    if selected_test_frame is None:
        raise RuntimeError("selected rolling candidate did not produce test outputs")
    selected_test_frame.to_csv(output / "test_predictions.csv", index=False)
    evaluation_id = _sha256_text(
        json.dumps(
            {
                "selection": selection_payload,
                "test_rows": int(len(test_features)),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    _write_json(
        {
            "evaluation_id": evaluation_id,
            "run_id": run_spec.run_id,
            "test_rows": int(len(test_features)),
            "claim_boundary": CLAIM_BOUNDARY,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        output / "evaluation_manifest.json",
    )
    return {
        "run_id": run_spec.run_id,
        "mode": "rolling_window_v1",
        "selected_family": selected,
        "validation_value": selected_validation,
        "test_rows": int(len(test_features)),
        "test_value": selected_test_metrics.get("primary_metric"),
    }


def verify_run(output_dir: str | Path) -> dict[str, object]:
    """Verify one completed run has selection, digest, and evaluation artifacts."""
    output = Path(output_dir)
    required = [
        "run_config.json",
        "data_digest.json",
        "selection_manifest.json",
        "evaluation_manifest.json",
        "test_metrics.json",
        "test_metrics_by_family.json",
        "test_predictions.csv",
    ]
    missing = [name for name in required if not (output / name).is_file()]
    if missing:
        raise ValueError(f"run missing artifacts: {missing}")
    selection = _read_json(output / "selection_manifest.json")
    evaluation = _read_json(output / "evaluation_manifest.json")
    if selection.get("run_id") != evaluation.get("run_id"):
        raise ValueError("selection and evaluation run ids disagree")
    config = _read_json(output / "run_config.json")
    if (
        config.get("mode") == "rolling_window_v1"
        and config.get("problem_type") == "binary"
        and not selection.get("decision_threshold_by_window")
    ):
        raise ValueError(
            "rolling binary run is missing frozen decision-threshold calibration"
        )
    return {
        "status": "PASS",
        "run_id": selection.get("run_id"),
        "selected_family": selection.get("selected_family"),
        "test_rows": evaluation.get("test_rows"),
        "claim_boundary": selection.get("claim_boundary")
        or evaluation.get("claim_boundary"),
    }
