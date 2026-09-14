"""Partition discovery, task batch views, and train-only preprocessing."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Protocol, Sequence

import numpy as np
import pandas as pd

from .contracts import (
    CLAIM_BOUNDARY,
    DATA_VERSION,
    HORIZONS,
    MODEL_FEATURE_COLUMNS,
    HISTORY_FEATURE_COLUMNS,
    HISTORY_STATE_COLUMNS,
    RunSpec,
    SEASONAL_COLUMNS,
    SPLITS,
    WindowSpec,
    target_column,
    validate_feature_columns,
)
from .history_features import add_history_features


def _canonical_json(value) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def sample_frames(batches, max_rows: int | None, *, seed: int = 20260907) -> pd.DataFrame:
    """Uniform priority reservoir over ALL eligible batches, bounded by k + one batch.

    Priorities depend on row traversal and seed, not requested feature columns.
    No early exit is permitted: late years and zones must have equal opportunity.
    """
    if max_rows is not None and max_rows <= 0:
        raise ValueError('max_rows must be positive or None')
    rng = np.random.default_rng(seed)
    kept = None
    priorities = np.empty(0)
    uncapped = []
    for batch in batches:
        if not isinstance(batch, pd.DataFrame):
            raise TypeError('task source must yield pandas DataFrames')
        if max_rows is None:
            uncapped.append(batch)
            continue
        incoming = rng.random(len(batch))
        kept = batch.reset_index(drop=True) if kept is None else pd.concat([kept, batch], ignore_index=True)
        priorities = np.concatenate([priorities, incoming])
        if len(kept) > max_rows:
            selected = np.argpartition(priorities, max_rows - 1)[:max_rows]
            kept = kept.iloc[selected].reset_index(drop=True)
            priorities = priorities[selected]
    if max_rows is None:
        return pd.concat(uncapped, ignore_index=True) if uncapped else pd.DataFrame()
    if kept is None:
        return pd.DataFrame()
    return kept.iloc[np.argsort(priorities)].reset_index(drop=True)


def read_ready_metadata(package_dir: str | Path) -> dict[str, object]:
    ready_path = Path(package_dir) / "READY.json"
    if not ready_path.is_file():
        raise ValueError(f"READY.json missing: {ready_path}")
    try:
        value = json.loads(ready_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"READY.json is not valid JSON: {ready_path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"READY.json must contain an object: {ready_path}")
    return value


def discover_partitions(package_dir: str | Path) -> tuple[tuple[str, ...], dict[str, object]]:
    """Return partition-relative paths plus READY metadata for a V0.4 package."""
    root = Path(package_dir)
    if not root.is_dir():
        raise ValueError(f"data package directory missing: {root}")
    ready = read_ready_metadata(root)
    if ready.get("data_version") != DATA_VERSION:
        raise ValueError(
            f"unexpected data version: {ready.get('data_version')!r}"
        )
    partitions = tuple(
        str(path.relative_to(root)).replace("\\", "/")
        for path in sorted((root / "partitions").rglob("*.parquet"))
    )
    expected_partitions = int(ready.get("partition_count", 0))
    if expected_partitions and len(partitions) != expected_partitions:
        raise ValueError(
            f"partition count mismatch: expected {expected_partitions}, "
            f"found {len(partitions)}"
        )
    return partitions, ready


def verify_package_layout(package_dir: str | Path) -> dict[str, object]:
    """Lightweight frozen-package schema check used before reading task views."""
    root = Path(package_dir)
    partitions, ready = discover_partitions(root)
    expected_horizons = [int(value) for value in ready.get("horizons", [])]
    if tuple(expected_horizons) != HORIZONS:
        raise ValueError("unexpected V0.4 horizon contract")
    if ready.get("claim_boundary") != CLAIM_BOUNDARY:
        raise ValueError("invalid claim boundary")
    if ready.get("row_count", 0) <= 0 or ready.get("column_count", 0) <= 0:
        raise ValueError("READY.json row/column counts are invalid")
    first = next(
        (root / "partitions").rglob("*.parquet"),
        None,
    )
    if first is None:
        raise ValueError("data package contains no parquet partitions")
    try:
        schema = pd.read_parquet(first, engine="pyarrow").columns
    except Exception as exc:
        raise ValueError(f"cannot read partition schema: {first}") from exc
    required = {
        "grid_id",
        "date",
        "dataset_split",
        *(
            name
            for name in MODEL_FEATURE_COLUMNS
            if name not in SEASONAL_COLUMNS
        ),
    }
    missing = sorted(required - set(schema))
    if missing:
        raise ValueError(f"partition schema missing required columns: {missing}")
    return {
        "status": "PASS",
        "data_version": ready.get("data_version"),
        "partition_count": len(partitions),
        "row_count": int(ready.get("row_count", 0)),
        "claim_boundary": ready.get("claim_boundary"),
    }


_SPLIT_YEARS = {
    "train": frozenset(range(2005, 2018)),
    "validation": frozenset(range(2018, 2022)),
    "test": frozenset(range(2022, 2026)),
}


class BatchSource(Protocol):
    """Protocol shared by the real Parquet source and deterministic spies."""

    def iter_batches(
        self, split: str, columns: Sequence[str]
    ) -> Iterator[pd.DataFrame]: ...


class ParquetTaskSource:
    """Yield projected V0.4 grid-day batches for one frozen temporal split."""

    def __init__(self, package_dir: str | Path):
        self.package_dir = Path(package_dir)
        self.partitions, self.ready = discover_partitions(self.package_dir)
        self._schema: tuple[str, ...] | None = None

    @property
    def schema_columns(self) -> tuple[str, ...]:
        if self._schema is None:
            import pyarrow.parquet as pq
            first = next((self.package_dir / "partitions").rglob("*.parquet"))
            self._schema = tuple(pq.read_schema(first).names)
        return self._schema

    def _partition_paths(self, split: str) -> list[Path]:
        if split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}: {split!r}")
        years = _SPLIT_YEARS[split]
        paths = []
        for path in self.partitions:
            relative = Path(path)
            year_part = next(
                (part for part in relative.parts if part.startswith("year=")),
                None,
            )
            if year_part is None:
                raise ValueError(f"partition path has no year directory: {path}")
            if int(year_part.split("=", 1)[1]) in years:
                paths.append(self.package_dir / path)
        return paths

    def _files_for_year_range(
        self, start_date, end_date
    ) -> list[Path]:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        if start > end:
            raise ValueError("date range start must not exceed end")
        years = set(range(int(start.year), int(end.year) + 1))
        paths = []
        for path in self.partitions:
            relative = Path(path)
            year_part = next(
                (part for part in relative.parts if part.startswith("year=")),
                None,
            )
            if year_part is not None and int(year_part.split("=", 1)[1]) in years:
                paths.append(self.package_dir / path)
        return paths

    def iter_projection_range(
        self, start_date, end_date, columns: Sequence[str]
    ) -> Iterator[pd.DataFrame]:
        """Read a contiguous date range without fixed split-year filtering."""
        if not columns:
            raise ValueError("columns must not be empty")
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        ordered_columns = list(columns)
        extra = {"grid_id", "date", "dataset_split"}
        seasonal_requested = set(ordered_columns) & set(SEASONAL_COLUMNS)
        read_columns = sorted((set(ordered_columns) - seasonal_requested) | extra)
        for path in self._files_for_year_range(start, end):
            frame = pd.read_parquet(path, columns=read_columns, engine="pyarrow")
            dates = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.loc[
                dates.ge(start) & dates.le(end)
            ].copy()
            if seasonal_requested:
                dates = pd.to_datetime(frame["date"], errors="coerce")
                day_of_year = dates.dt.dayofyear.astype(float)
                day_of_week = dates.dt.dayofweek.astype(float)
                frame["calendar_day_of_year_sin"] = np.sin(
                    2.0 * np.pi * day_of_year / 365.25
                )
                frame["calendar_day_of_year_cos"] = np.cos(
                    2.0 * np.pi * day_of_year / 365.25
                )
                frame["calendar_day_of_week_sin"] = np.sin(
                    2.0 * np.pi * day_of_week / 7.0
                )
                frame["calendar_day_of_week_cos"] = np.cos(
                    2.0 * np.pi * day_of_week / 7.0
                )
            yield frame.loc[:, ordered_columns].reset_index(drop=True)

    def iter_projections(
        self, split: str, columns: Sequence[str]
    ) -> Iterator[pd.DataFrame]:
        if split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}: {split!r}")
        if not columns:
            raise ValueError("columns must not be empty")
        ordered_columns = list(columns)
        extra = {"grid_id", "date", "dataset_split"}
        missing_in_schema = [
            name
            for name in (*ordered_columns, *extra)
            if name not in set(self.schema_columns) | set(SEASONAL_COLUMNS)
        ]
        if missing_in_schema:
            raise ValueError(
                "requested columns missing from V0.4 schema: "
                + ", ".join(sorted(missing_in_schema))
            )
        seasonal_requested = set(ordered_columns) & set(SEASONAL_COLUMNS)
        read_columns = sorted((set(ordered_columns) - seasonal_requested) | extra)
        for path in self._partition_paths(split):
            frame = pd.read_parquet(path, columns=read_columns, engine="pyarrow")
            if not frame.empty and frame["dataset_split"].iloc[0] != split:
                # Partition-year naming is authoritative in a frozen package; the
                # guard exists so a malformed package cannot silently mix splits.
                raise ValueError(f"split disagreement in partition: {path}")
            if seasonal_requested:
                dates = pd.to_datetime(frame["date"], errors="coerce")
                if dates.isna().any():
                    raise ValueError(f"invalid date values in partition: {path}")
                day_of_year = dates.dt.dayofyear.astype(float)
                day_of_week = dates.dt.dayofweek.astype(float)
                frame["calendar_day_of_year_sin"] = np.sin(
                    2.0 * np.pi * day_of_year / 365.25
                )
                frame["calendar_day_of_year_cos"] = np.cos(
                    2.0 * np.pi * day_of_year / 365.25
                )
                frame["calendar_day_of_week_sin"] = np.sin(
                    2.0 * np.pi * day_of_week / 7.0
                )
                frame["calendar_day_of_week_cos"] = np.cos(
                    2.0 * np.pi * day_of_week / 7.0
                )
            yield frame.loc[:, ordered_columns].reset_index(drop=True)

    def iter_batches(
        self, split: str, columns: Sequence[str]
    ) -> Iterator[pd.DataFrame]:
        """Feature-safe view used by preprocessing and task-level consumers."""
        validate_feature_columns(columns)
        yield from self.iter_projections(split, columns)


class V04TaskSource:
    """Expose one task/horizon's known labels together with feature batches."""

    def __init__(
        self,
        package_dir: str | Path,
        run_spec: RunSpec,
        *,
        sample_rows: int | None = None,
        window: WindowSpec | None = None,
        history_days: int = 0,
    ):
        self.package_dir = Path(package_dir)
        self.run_spec = run_spec
        self.sample_rows = sample_rows
        self.window = window
        self.history_days = int(history_days)
        self.base = ParquetTaskSource(self.package_dir)
        self.target_name = target_column(
            run_spec.task.target_family, run_spec.horizon_days
        )
        self.embargo_name = f"target_embargo_{run_spec.horizon_days}d"
        self.target_date_name = f"target_date_{run_spec.horizon_days}d"
        metadata_path = Path(__file__).with_name("grid_coordinates_V0.1.csv")
        self.grid_metadata = (
            pd.read_csv(metadata_path)
            if metadata_path.is_file()
            else None
        )

    def iter_batches(
        self, split: str, columns: Sequence[str]
    ) -> Iterator[pd.DataFrame]:
        """Sample across the complete eligible population, then expose requested fields."""
        uses_history = (
            self.history_days > 0
            and any(name in HISTORY_FEATURE_COLUMNS for name in columns)
        )
        batch_source = (
            self._history_eligible_batches
            if uses_history
            else self._eligible_batches
        )
        if self.sample_rows is None:
            yield from batch_source(split, columns)
            return
        audit_columns = ['date', 'grid_id']
        if 'experimental_zone_id' in self.base.schema_columns:
            audit_columns.append('experimental_zone_id')
        requested = list(dict.fromkeys([*columns, *audit_columns]))
        sampled = sample_frames(
            batch_source(split, requested),
            self.sample_rows,
            seed=self.run_spec.seed,
        )
        if sampled.empty:
            return
        dates = pd.to_datetime(sampled['date'])
        self.last_sampling_audit = {
            'method': 'global_uniform_priority_v2', 'rows': len(sampled),
            'issue_start': str(dates.min()), 'issue_end': str(dates.max()),
            'year_counts': {str(k): int(v) for k,v in dates.dt.year.value_counts().sort_index().items()},
            'month_counts': {str(k): int(v) for k,v in dates.dt.month.value_counts().sort_index().items()},
            'grid_count': int(sampled.grid_id.nunique()),
            'zone_counts': sampled.experimental_zone_id.value_counts().to_dict() if 'experimental_zone_id' in sampled else {},
        }
        yield sampled.loc[:, list(dict.fromkeys([*columns, 'actual']))]

    def _actual_range(self, split: str) -> tuple[pd.Timestamp, pd.Timestamp]:
        if self.window is not None and split in {"train", "validation"}:
            start = pd.Timestamp(
                self.window.validation_start
                if split == "validation"
                else self.window.train_start
            )
            end = pd.Timestamp(
                self.window.validation_end
                if split == "validation"
                else self.window.train_end
            )
            return start, end
        years = sorted(_SPLIT_YEARS[split])
        return pd.Timestamp(year=years[0], month=1, day=1), pd.Timestamp(
            year=years[-1], month=12, day=31
        )

    def _history_eligible_batches(
        self,
        split: str,
        columns: Sequence[str],
    ) -> Iterator[pd.DataFrame]:
        """Yield label rows enriched with pre-issue lag/rolling features."""
        if split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}: {split!r}")
        requested = [
            name for name in columns if name not in {"actual", "dataset_split"}
        ]
        start, end = self._actual_range(split)
        history_start = start - pd.Timedelta(days=self.history_days + 1)
        read_columns = list(
            dict.fromkeys(
                (
                    *[
                        name
                        for name in requested
                        if name not in HISTORY_FEATURE_COLUMNS
                        and name not in SEASONAL_COLUMNS
                    ],
                    *HISTORY_STATE_COLUMNS,
                    self.target_name,
                    self.embargo_name,
                    self.target_date_name,
                    "date",
                    "grid_id",
                )
            )
        )
        spatial_requested = {
            "centroid_x_m",
            "centroid_y_m",
        } & set(requested)
        if spatial_requested:
            read_columns.append("grid_id")
        if "experimental_zone_id" in self.base.schema_columns:
            read_columns = list(
                dict.fromkeys((*read_columns, "experimental_zone_id"))
            )
        paths = sorted(
            self.base._files_for_year_range(history_start, end),
            key=lambda path: (str(path),),
        )
        zones: dict[str, list[Path]] = {}
        for path in paths:
            zone = next(
                (
                    part.split("=", 1)[1]
                    for part in path.parts
                    if part.startswith("experimental_zone_id=")
                ),
                "UNKNOWN",
            )
            zones.setdefault(zone, []).append(path)
        for zone, zone_paths in zones.items():
            frames = []
            for path in zone_paths:
                frames.append(
                    pd.read_parquet(path, columns=read_columns, engine="pyarrow")
                )
            raw = pd.concat(frames, ignore_index=True)
            dates = pd.to_datetime(raw["date"], errors="coerce")
            raw = raw.loc[
                dates.ge(history_start) & dates.le(end)
            ].copy()
            if raw.empty:
                continue
            seasonal_requested = set(requested) & set(SEASONAL_COLUMNS)
            if seasonal_requested:
                dates = pd.to_datetime(raw["date"], errors="coerce")
                day_of_year = dates.dt.dayofyear.astype(float)
                day_of_week = dates.dt.dayofweek.astype(float)
                raw["calendar_day_of_year_sin"] = np.sin(
                    2.0 * np.pi * day_of_year / 365.25
                )
                raw["calendar_day_of_year_cos"] = np.cos(
                    2.0 * np.pi * day_of_year / 365.25
                )
                raw["calendar_day_of_week_sin"] = np.sin(
                    2.0 * np.pi * day_of_week / 7.0
                )
                raw["calendar_day_of_week_cos"] = np.cos(
                    2.0 * np.pi * day_of_week / 7.0
                )
            raw = add_history_features(raw)
            issue_dates = pd.to_datetime(raw["date"], errors="coerce")
            raw = raw.loc[
                issue_dates.ge(start) & issue_dates.le(end)
            ].copy()
            if raw.empty:
                continue
            embargo = pd.to_numeric(raw[self.embargo_name], errors="coerce")
            if self.run_spec.task.problem_type == "ordinal":
                actual = raw[self.target_name].astype(str)
                clean = actual.str.strip().str.lower()
                valid = (
                    clean.ne("")
                    & clean.ne("<na>")
                    & clean.ne("nan")
                    & clean.ne("unknown")
                    & embargo.eq(0)
                )
            else:
                actual = pd.to_numeric(raw[self.target_name], errors="coerce")
                valid = actual.notna() & embargo.eq(0)
            raw = raw.loc[valid].copy()
            if raw.empty:
                continue
            target_dates = pd.to_datetime(raw[self.target_date_name], errors="coerce")
            window_valid = target_dates.notna() & target_dates.le(end)
            raw = raw.loc[window_valid].copy()
            if spatial_requested:
                if self.grid_metadata is None:
                    raise ValueError(
                        "grid coordinate metadata is missing for spatial tasks"
                    )
                raw = raw.merge(
                    self.grid_metadata.loc[
                        :, ["grid_id", "centroid_x_m", "centroid_y_m"]
                    ],
                    on="grid_id",
                    how="left",
                    sort=False,
                )
            if self.run_spec.task.problem_type == "ordinal":
                raw["actual"] = raw[self.target_name].astype(str)
            else:
                raw["actual"] = pd.to_numeric(raw[self.target_name]).astype(float)
            output_columns = list(dict.fromkeys((*requested, "actual")))
            raw = raw.loc[:, output_columns].reset_index(drop=True)
            if not raw.empty:
                yield raw

    def _eligible_batches(
        self, split: str, columns: Sequence[str]
    ) -> Iterator[pd.DataFrame]:
        """Yield feature/actual rows, dropping embargoed or unknown labels."""
        if split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}: {split!r}")
        requested = [name for name in columns if name != "actual"]
        read_columns = list(
            dict.fromkeys(
                (
                    *requested,
                    self.target_name,
                    self.embargo_name,
                    "date",
                    self.target_date_name,
                )
            )
        )
        spatial_requested = {
            "centroid_x_m",
            "centroid_y_m",
        } & set(requested)
        if spatial_requested:
            read_columns = list(dict.fromkeys((*read_columns, "grid_id")))
        rows_seen = 0
        base_read_columns = [
            name for name in read_columns if name not in spatial_requested
        ]
        if self.window is not None and split in {"train", "validation"}:
            if split == "train":
                range_start = self.window.train_start
                range_end = self.window.train_end
            else:
                range_start = self.window.validation_start
                range_end = self.window.validation_end
            base_iter = self.base.iter_projection_range(
                range_start, range_end, base_read_columns
            )
        else:
            base_iter = self.base.iter_projections(split, base_read_columns)
        for raw in base_iter:
            embargo = pd.to_numeric(raw[self.embargo_name], errors="coerce")
            if self.run_spec.task.problem_type == "ordinal":
                actual = raw[self.target_name].astype(str)
                clean = actual.str.strip().str.lower()
                valid = (
                    clean.ne("")
                    & clean.ne("<na>")
                    & clean.ne("nan")
                    & clean.ne("unknown")
                    & embargo.eq(0)
                )
            else:
                actual = pd.to_numeric(raw[self.target_name], errors="coerce")
                valid = actual.notna() & embargo.eq(0)
            raw = raw.loc[valid].copy()
            if raw.empty:
                continue
            if self.window is not None and split in {"train", "validation"}:
                issue_dates = pd.to_datetime(raw["date"], errors="coerce")
                target_dates = pd.to_datetime(
                    raw[self.target_date_name], errors="coerce"
                )
                if split == "train":
                    segment_start = pd.Timestamp(self.window.train_start)
                    segment_end = pd.Timestamp(self.window.train_end)
                else:
                    segment_start = pd.Timestamp(self.window.validation_start)
                    segment_end = pd.Timestamp(self.window.validation_end)
                window_valid = (
                    issue_dates.ge(segment_start)
                    & issue_dates.le(segment_end)
                    & target_dates.notna()
                    & target_dates.le(segment_end)
                )
                raw = raw.loc[window_valid].copy()
                if raw.empty:
                    continue
            if spatial_requested:
                if self.grid_metadata is None:
                    raise ValueError(
                        "grid coordinate metadata is missing for spatial tasks"
                    )
                raw = raw.merge(
                    self.grid_metadata.loc[
                        :, ["grid_id", "centroid_x_m", "centroid_y_m"]
                    ],
                    on="grid_id",
                    how="left",
                    sort=False,
                )
            rows_seen += len(raw)
            if self.run_spec.task.problem_type == "ordinal":
                raw["actual"] = raw[self.target_name].astype(str)
            else:
                raw["actual"] = pd.to_numeric(raw[self.target_name]).astype(float)
            output_columns = list(dict.fromkeys((*requested, "actual")))
            yield raw.loc[:, output_columns].reset_index(drop=True)


def iter_task_batches(
    package_dir: str | Path, split: str, columns: Sequence[str]
) -> Iterator[pd.DataFrame]:
    """Iterate projected V0.4 batches for one split and column set."""
    source = ParquetTaskSource(package_dir)
    yield from source.iter_batches(split, columns)


def _missing_column_name(column: str) -> str:
    return column if column.endswith("_missing") else f"{column}_missing"


@dataclass(frozen=True)
class LearnedPreprocessor:
    """Median imputer plus explicit missing indicators fit on train only."""

    feature_columns: tuple[str, ...]
    medians: pd.Series
    missing_columns: tuple[str, ...]
    output_columns: tuple[str, ...]
    fit_split: str = "train"

    @classmethod
    def create(
        cls,
        feature_columns: Sequence[str],
        medians: pd.Series,
    ) -> "LearnedPreprocessor":
        columns = tuple(feature_columns)
        missing_columns = tuple(
            _missing_column_name(name)
            for name in columns
            if not name.endswith("_missing")
        )
        output_columns = tuple(
            dict.fromkeys((*columns, *missing_columns))
        )
        return cls(
            feature_columns=columns,
            medians=medians.copy(),
            missing_columns=missing_columns,
            output_columns=output_columns,
        )

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        return transform_batch(self, frame)


def fit_preprocessor(
    source: BatchSource,
    feature_columns: Sequence[str],
    *,
    split: str = "train",
    max_rows: int | None = 500_000,
) -> LearnedPreprocessor:
    """Fit median imputation and missing masks from train batches only."""
    if split != "train":
        raise ValueError("fit_preprocessor accepts train batches only")
    validate_feature_columns(feature_columns)
    columns = list(feature_columns)
    frame = sample_frames(source.iter_batches(split, columns), max_rows, seed=getattr(getattr(source, 'run_spec', None), 'seed', 20260907))
    if frame.empty:
        raise ValueError("preprocessor fit received no training batches")
    frame = frame.loc[:, columns].apply(pd.to_numeric, errors='raise')
    medians = frame.median(axis=0, numeric_only=True).fillna(0.0)
    return LearnedPreprocessor.create(columns, medians)


def transform_batch(
    preprocessor: LearnedPreprocessor, frame: pd.DataFrame
) -> pd.DataFrame:
    """Impute with fitted train medians and append explicit missing indicators."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("transform_batch requires a pandas DataFrame")
    validate_feature_columns(frame.columns)
    missing = [
        name
        for name in preprocessor.feature_columns
        if name not in frame.columns
    ]
    if missing:
        raise ValueError(f"input frame missing feature columns: {missing}")
    result = pd.DataFrame(index=frame.index)
    for name in preprocessor.feature_columns:
        result[name] = pd.to_numeric(frame[name], errors="raise")
    for name in preprocessor.missing_columns:
        if name.endswith("_missing"):
            result[name] = result[name.removesuffix("_missing")].isna().astype("int8")
    for name in preprocessor.feature_columns:
        median = float(preprocessor.medians.get(name, 0.0))
        result[name] = result[name].fillna(median)
    return result.loc[:, list(preprocessor.output_columns)].reset_index(drop=True)
