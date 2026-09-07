"""Provider 边界：观测与预测的唯一数据来源抽象。

当前仅实现 simulated。通过环境变量选择：
  OBSERVATION_PROVIDER / PREDICTION_PROVIDER（默认 simulated）

配置为 cleaned / member_c 等尚未实现的值时，工厂直接抛出 ProviderConfigError，
导致应用启动失败——禁止任何形式的静默回退 simulated。
"""
from __future__ import annotations

import csv
import json
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .contracts import (
    CLAIM_BOUNDARY,
    DATA_MODE,
    GRID_COLUMNS,
    GRID_ROWS,
    OBSERVED_DATA_MODE,
    OBSERVATION_VERSION,
    PREDICTION_RUN_ID,
    PREDICTION_VERSION,
    REALTIME_VERSION,
    RISK_THRESHOLDS,
    risk_level,
)

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample-data"

OBSERVATION_PROVIDER_ENV = "OBSERVATION_PROVIDER"
PREDICTION_PROVIDER_ENV = "PREDICTION_PROVIDER"


class ProviderConfigError(RuntimeError):
    """Provider 配置指向未实现的实现时抛出，应用必须启动失败而非回退。"""


class ObservationProvider(ABC):
    """观测侧数据源：演示分区目录、模拟观测序列、质量摘要。"""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def dataset_version(self) -> str: ...

    @abstractmethod
    def zones(self) -> list[dict[str, Any]]: ...

    def zone(self, entity_id: str) -> dict[str, Any] | None:
        return next((item for item in self.zones() if item["id"] == entity_id), None)

    @abstractmethod
    def observations(self, entity_id: str, variable_code: str | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def quality(self, entity_id: str) -> dict[str, Any]: ...


class PredictionProvider(ABC):
    """预测侧数据源：分区预测、预测解释、演示风险格网。"""

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def dataset_version(self) -> str: ...

    @abstractmethod
    def prediction_run_id(self) -> str: ...

    @abstractmethod
    def forecast(self, entity_id: str, horizon_days: int) -> dict[str, Any] | None: ...

    @abstractmethod
    def explanation(self, forecast_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def risk_grid(self, horizon_days: int) -> dict[str, Any]: ...


class SimulatedObservationProvider(ObservationProvider):
    """读取 backend/sample-data 固定样本，不访问任何外部数据现场。"""

    def __init__(self) -> None:
        self._fixture = json.loads((SAMPLE_DIR / "simulated_api_fixture_v1.json").read_text(encoding="utf-8"))
        with (SAMPLE_DIR / "simulated_observations_v1.csv").open(encoding="utf-8", newline="") as file:
            self._observations = list(csv.DictReader(file))

    def name(self) -> str:
        return "simulated"

    def dataset_version(self) -> str:
        return OBSERVATION_VERSION

    def zones(self) -> list[dict[str, Any]]:
        return self._fixture["zones"]

    def observations(self, entity_id: str, variable_code: str | None = None) -> list[dict[str, Any]]:
        rows = [dict(row) for row in self._observations if row["spatial_entity_id"] == entity_id]
        if variable_code:
            rows = [row for row in rows if row["variable_code"] == variable_code]
        result = []
        for row in rows:
            result.append(
                {
                    "spatial_entity_id": row["spatial_entity_id"],
                    "observed_at": row["observed_at"],
                    "variable_code": row["variable_code"],
                    "clean_value": float(row["clean_value"]),
                    "unit": row["unit"],
                    "value_origin": row["value_origin"],
                    "quality_status": row["quality_status"],
                    "is_imputed": row["is_imputed"].lower() == "true",
                    # 气温是驱动代理变量，非水温实测，必须逐行披露
                    "proxy_flag": row["variable_code"] == "air_temperature",
                    "data_mode": DATA_MODE,
                    "dataset_version": OBSERVATION_VERSION,
                }
            )
        return result

    def quality(self, entity_id: str) -> dict[str, Any]:
        return {
            "spatial_entity_id": entity_id,
            "status": "warning",
            "freshness": "simulated",
            "observed_count": len(self.observations(entity_id)),
            "source_count": 1,
            "is_imputed": False,
            "value_origin": "simulated",
            "proxy_flag": True,
            "limitations": ["P0 simulated data; not for operational decisions"],
        }


class SimulatedPredictionProvider(PredictionProvider):
    """确定性规则推演：固定种子语义、固定公式，不表示任何算法模型输出。"""

    HORIZON_SCORE_OFFSET = {1: 0, 3: 3, 7: 7, 15: 13, 30: 20}
    GRID_SHIFT = {1: 0, 3: 3, 7: 7, 15: 12, 30: 18}

    def __init__(self, zones: list[dict[str, Any]]) -> None:
        self._zones = zones

    def name(self) -> str:
        return "simulated"

    def dataset_version(self) -> str:
        return PREDICTION_VERSION

    def prediction_run_id(self) -> str:
        return PREDICTION_RUN_ID

    def zone(self, entity_id: str) -> dict[str, Any] | None:
        return next((item for item in self._zones if item["id"] == entity_id), None)

    def forecast(self, entity_id: str, horizon_days: int) -> dict[str, Any] | None:
        zone = self.zone(entity_id)
        if not zone:
            return None
        base = {"high": 84, "mid": 61, "low": 28}[zone["risk"]]
        score = max(10, base - self.HORIZON_SCORE_OFFSET[horizon_days])
        return {
            "id": f"demo-forecast-{entity_id}-{horizon_days}d",
            "spatial_entity_id": entity_id,
            "prediction_run_id": PREDICTION_RUN_ID,
            "horizon_days": horizon_days,
            "target_metric": "bloom_risk",
            "risk_score": score,
            "risk_level": risk_level(score),
            "provider_type": "simulation",
            "model_version": "DEMO-RULE-V1",
            "claim_boundary": CLAIM_BOUNDARY,
            "uncertainty": {
                "lower": max(0, score - 10),
                "upper": min(100, score + 10),
                "method": "demo_rule_band",
            },
            "quality_gate": {
                "status": "warning",
                "decision": "candidate_assessment_only",
                "reason": "simulated data cannot trigger a real warning",
            },
        }

    def explanation(self, forecast_id: str) -> dict[str, Any] | None:
        parts = forecast_id.removeprefix("demo-forecast-").rsplit("-", 1)
        if len(parts) != 2 or not self.zone(parts[0]):
            return None
        horizon_text = parts[1].removesuffix("d")
        if not horizon_text.isdigit() or int(horizon_text) not in self.HORIZON_SCORE_OFFSET:
            return None
        return {
            "forecast_id": forecast_id,
            "prediction_run_id": PREDICTION_RUN_ID,
            "dataset_version": PREDICTION_VERSION,
            "method": "demo_rule_contribution",
            "claim_boundary": CLAIM_BOUNDARY,
            "features": [
                {"name": "air_temperature", "contribution": 0.34, "direction": "positive", "label": "气温（情景驱动）"},
                {"name": "wind_speed", "contribution": 0.24, "direction": "negative", "label": "风速（情景驱动）"},
                {"name": "total_phosphorus", "contribution": 0.20, "direction": "positive", "label": "总磷（情景驱动）"},
            ],
        }

    def risk_grid(self, horizon_days: int) -> dict[str, Any]:
        shift = self.GRID_SHIFT[horizon_days]
        # 公式在数学上恒为整数，浮点仅产生 1e-14 量级尾差；显式取整保证契约值精确
        values = [
            [
                int(round(max(5, min(95, 90 - abs(column - 4 - shift / 3) * 9 - abs(row - 3) * 11))))
                for column in range(GRID_COLUMNS)
            ]
            for row in range(GRID_ROWS)
        ]
        return {
            "prediction_run_id": PREDICTION_RUN_ID,
            "horizon_days": horizon_days,
            "data_mode": DATA_MODE,
            "dataset_version": PREDICTION_VERSION,
            "grid": values,
            "rows": GRID_ROWS,
            "columns": GRID_COLUMNS,
            "resolution": {"rows": GRID_ROWS, "columns": GRID_COLUMNS, "unit": "risk_score"},
            "thresholds": RISK_THRESHOLDS,
            "claim_boundary": CLAIM_BOUNDARY,
        }


# ---- 实时观测轨：MEE 国控站点（data-cleaning silver/mee_realtime 三层结构） ----

REALTIME_CATALOG_ENV = "TAIHU_REALTIME_CATALOG_DIR"
_DEFAULT_REALTIME_DIR = Path(__file__).resolve().parents[2] / "data-cleaning" / "storage" / "silver" / "mee_realtime"
REALTIME_SOURCE_ID = "mee_surface_water_realtime"
# 展示新鲜度分带（小时）：≤6 正常 / ≤12 延迟 / >12 严重过期；无成功快照 → unavailable
FRESHNESS_NORMAL_H = 6.0
FRESHNESS_DELAYED_H = 12.0


class RealtimeDataUnavailable(RuntimeError):
    """实时观测数据不可用（从未成功抓取或目录缺失）。禁止回退 simulated。"""


def _freshness_band(lag_h: float | None) -> str:
    if lag_h is None:
        return "unavailable"
    if lag_h <= FRESHNESS_NORMAL_H:
        return "normal"
    if lag_h <= FRESHNESS_DELAYED_H:
        return "delayed"
    return "severely_overdue"


class MeeRealtimeObservationProvider:
    """实时观测轨 Provider：站点集合完全由最新成功快照决定。

    只读 data-cleaning 构建的三层结构（stations.json / observations.parquet /
    snapshots.json / status.json）；无数据时抛 RealtimeDataUnavailable，
    不回退 simulated、不返回伪造空列表。构造不加载，首次访问才加载并缓存。
    """

    def __init__(self, catalog_dir: Path | str | None = None) -> None:
        raw = os.environ.get(REALTIME_CATALOG_ENV, "").strip()
        self._catalog_dir = Path(catalog_dir) if catalog_dir else (Path(raw) if raw else _DEFAULT_REALTIME_DIR)
        self._loaded = False
        self._stations: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._status: dict[str, Any] = {}
        self._observations: Any = None  # pandas DataFrame
        self._catalog_signature: tuple[int, int] | None = None
        self._load_lock = threading.RLock()

    def name(self) -> str:
        return "mee_realtime"

    def dataset_version(self) -> str:
        return REALTIME_VERSION

    # ---- 加载 ----

    def _catalog_exists(self) -> bool:
        return (self._catalog_dir / "stations.json").exists() and (self._catalog_dir / "status.json").exists()

    def _current_catalog_signature(self) -> tuple[int, int] | None:
        try:
            stat = (self._catalog_dir / "status.json").stat()
        except FileNotFoundError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _ensure_loaded(self) -> None:
        signature = self._current_catalog_signature()
        if self._loaded and signature == self._catalog_signature:
            return
        with self._load_lock:
            signature = self._current_catalog_signature()
            if self._loaded and signature == self._catalog_signature:
                return
            if not self._catalog_exists():
                raise RealtimeDataUnavailable(
                    f"实时观测目录不存在或为空: {self._catalog_dir}（从未成功抓取；禁止回退模拟数据）"
                )
            import pandas as pd

            try:
                stations = json.loads((self._catalog_dir / "stations.json").read_text(encoding="utf-8"))["stations"]
                snapshots = json.loads((self._catalog_dir / "snapshots.json").read_text(encoding="utf-8"))["snapshots"]
                status = json.loads((self._catalog_dir / "status.json").read_text(encoding="utf-8"))
                obs_path = self._catalog_dir / "observations.parquet"
                observations = pd.read_parquet(obs_path) if obs_path.exists() else pd.DataFrame()
                published_latest = status.get("latest_snapshot_id")
                loaded_latest = snapshots[-1].get("snapshot_id") if snapshots else None
                if published_latest != loaded_latest:
                    raise RuntimeError(
                        f"realtime catalog publication mismatch: status={published_latest}, snapshots={loaded_latest}"
                    )
            except Exception:
                # A previous coherent bundle is safer than exposing a transient
                # publish/read race.  The next request retries the reload.
                if self._loaded:
                    return
                raise
            self._stations = stations
            self._snapshots = snapshots
            self._status = status
            self._observations = observations
            self._catalog_signature = signature
            self._loaded = True

    def _require_loaded(self) -> None:
        self._ensure_loaded()
        if not self._stations:
            raise RealtimeDataUnavailable("实时观测目录存在但站点目录为空（从未成功抓取）")

    # ---- 状态（/realtime/status；永不抛错） ----

    def status(self) -> dict[str, Any]:
        import pandas as pd

        if not self._catalog_exists():
            return {
                "source": REALTIME_SOURCE_ID,
                "dataset_version": REALTIME_VERSION,
                "available": False,
                "collection_status": "unavailable",
                "freshness_status": "unavailable",
                "snapshot_count": 0,
                "active_station_count": 0,
                "latest_station_count": None,
                "latest_observed_at": None,
                "observed_lag_h": None,
                "as_of": None,
                "last_attempt_at": None,
                "last_success_at": None,
                "last_error": None,
                "last_error_code": None,
                "note": "实时观测目录不存在：从未成功抓取；页面必须显式提示不可用，禁止回退模拟数据",
            }
        self._ensure_loaded()
        status = dict(self._status)
        status["available"] = status.get("collection_status") == "completed" and bool(self._stations)
        status["dataset_version"] = REALTIME_VERSION
        # 新鲜度按当前时刻重算（status.json 是构建时刻口径）
        latest_observed = status.get("latest_observed_at")
        lag_h = None
        if latest_observed:
            observed_ts = pd.Timestamp(latest_observed)
            now_cn = pd.Timestamp.now(tz="Asia/Shanghai")
            observed_ts = observed_ts.tz_localize("Asia/Shanghai") if observed_ts.tzinfo is None else observed_ts.tz_convert("Asia/Shanghai")
            lag_h = (now_cn - observed_ts).total_seconds() / 3600.0
        status["observed_lag_h"] = round(lag_h, 2) if lag_h is not None else None
        status["freshness_status"] = _freshness_band(lag_h) if latest_observed else "unavailable"
        return status

    def as_of(self) -> str:
        try:
            return self.status().get("as_of") or ""
        except Exception:  # noqa: BLE001 — as_of 仅用于 meta 展示
            return ""

    # ---- 站点目录 ----

    def _station_counts(self, entity_id: str) -> dict[str, int]:
        counts = {"ok": 0, "missing": 0, "qc_rejected": 0, "parse_failed": 0}
        if self._observations is None or self._observations.empty or not self._snapshots:
            return counts
        latest_id = self._snapshots[-1]["snapshot_id"]
        sub = self._observations[
            (self._observations["station_entity_id"] == entity_id)
            & (self._observations["snapshot_id"] == latest_id)
        ]
        for status_key, count in sub["observation_status"].value_counts().items():
            counts[status_key] = int(count)
        return counts

    def _station_view(self, entity: dict[str, Any]) -> dict[str, Any]:
        counts = self._station_counts(entity["entity_id"])
        location = entity.get("location") or {"lon": None, "lat": None, "location_status": "missing", "registry_source": None}
        return {
            "id": entity["entity_id"],
            "entity_type": "monitoring_station",
            "source_id": entity.get("source_id", REALTIME_SOURCE_ID),
            "source_station_name": entity["source_station_name"],
            "display_name": entity["source_station_name"],
            "aliases": entity.get("aliases", []),
            "province": entity.get("province"),
            "basin": entity.get("basin"),
            "location": {
                "lon": location.get("lon"),
                "lat": location.get("lat"),
                "location_status": location.get("location_status", "missing"),
                "registry_source": location.get("registry_source"),
            },
            "active_in_latest_snapshot": bool(entity.get("active_in_latest_snapshot")),
            "first_seen_at": entity.get("first_seen_at"),
            "last_seen_at": entity.get("last_seen_at"),
            "latest_observed_at": entity.get("latest_observed_at"),
            "latest_snapshot_id": entity.get("latest_snapshot_id"),
            "latest_water_quality_level": entity.get("latest_water_quality_level"),
            "available_variable_count": counts["ok"],
            "qc_rejected_variable_count": counts["qc_rejected"],
            "missing_variable_count": counts["missing"] + counts["parse_failed"],
            "data_mode": OBSERVED_DATA_MODE,
            "dataset_version": REALTIME_VERSION,
        }

    def stations(
        self,
        *,
        active: str | None = None,
        province: str | None = None,
        location_status: str | None = None,
    ) -> list[dict[str, Any]]:
        self._require_loaded()
        views = [self._station_view(entity) for entity in self._stations]
        if active == "latest":
            views = [view for view in views if view["active_in_latest_snapshot"]]
        if province:
            views = [view for view in views if view["province"] == province]
        if location_status:
            views = [view for view in views if view["location"]["location_status"] == location_status]
        return views

    def station(self, entity_id: str) -> dict[str, Any] | None:
        self._require_loaded()
        entity = next((item for item in self._stations if item["entity_id"] == entity_id), None)
        return self._station_view(entity) if entity else None

    # ---- 观测 ----

    def observations(
        self,
        entity_id: str,
        *,
        window: str = "latest",
        start: str | None = None,
        end: str | None = None,
        variables: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        import pandas as pd

        self._require_loaded()
        if self.station(entity_id) is None:
            return None
        frame = self._observations
        if frame is None or frame.empty:
            return []
        sub = frame[frame["station_entity_id"] == entity_id]
        if window == "latest" and self._snapshots:
            sub = sub[sub["snapshot_id"] == self._snapshots[-1]["snapshot_id"]]
        elif window == "range":
            if start:
                sub = sub[pd.to_datetime(sub["observed_at"], utc=True) >= pd.Timestamp(start, tz="UTC")]
            if end:
                sub = sub[pd.to_datetime(sub["observed_at"], utc=True) <= pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
        else:
            raise ValueError(f"unsupported observation window: {window}")
        if variables:
            sub = sub[sub["variable_code"].isin(variables)]
        rows = []

        def _clean(value: Any) -> Any:
            """pandas NaN → None：联合响应模型不接受 NaN 冒充缺失。"""
            if value is None:
                return None
            if isinstance(value, float) and value != value:
                return None
            try:
                if pd.isna(value):
                    return None
            except (TypeError, ValueError):
                pass
            return value

        for row in sub.to_dict("records"):
            value = _clean(row.get("value"))
            rows.append(
                {
                    "station_entity_id": row["station_entity_id"],
                    "snapshot_id": row["snapshot_id"],
                    "observed_at": _clean(row.get("observed_at")),
                    "retrieved_at": _clean(row.get("retrieved_at")),
                    "variable_code": row["variable_code"],
                    "value": float(value) if value is not None else None,
                    "unit": _clean(row.get("unit")),
                    "observation_status": row["observation_status"],
                    "missing_reason": _clean(row.get("missing_reason")),
                    "source_quality_note": _clean(row.get("source_quality_note")),
                    "qc_status": row.get("qc_status"),
                    "evidence_level": row.get("evidence_level"),
                    "verification_state": row.get("verification_state"),
                    "is_ground_truth": bool(row.get("is_ground_truth", False)),
                    "data_mode": OBSERVED_DATA_MODE,
                    "dataset_version": REALTIME_VERSION,
                }
            )
        rows.sort(key=lambda item: (item["observed_at"] or "", item["variable_code"]))
        return rows

    # ---- 全湖汇总（驾驶舱） ----

    SUMMARY_VARIABLES = (
        "chlorophyll_a",
        "dissolved_oxygen",
        "total_phosphorus",
        "total_nitrogen",
        "ammonia_nitrogen",
        "water_temperature",
    )
    # 蓝藻筛查阈值（μg/L）：≥10 轻度关注，≥25 中度预警；页面必须披露为筛查口径
    CHLA_LIGHT = 10.0
    CHLA_MODERATE = 25.0

    def _latest_rows(self, snapshot_id: str) -> Any:
        import pandas as pd

        sub = self._observations[self._observations["snapshot_id"] == snapshot_id]
        if sub.empty:
            return sub
        return sub.sort_values("observed_at").groupby(["station_entity_id", "variable_code"], as_index=False).tail(1)

    def _mean_of(self, frame: Any, code: str) -> tuple[float | None, int]:
        if frame is None or frame.empty:
            return None, 0
        values = frame[(frame["variable_code"] == code) & (frame["observation_status"] == "ok")]["value"]
        return (round(float(values.mean()), 4) if len(values) else None), int(len(values))

    def _snapshot_stats(self, snapshot_id: str) -> list[dict[str, Any]]:
        snap = next((s for s in self._snapshots if s["snapshot_id"] == snapshot_id), None)
        return list(snap.get("station_stats") or []) if snap else []

    def snapshot_timeline(self) -> dict[str, Any]:
        """快照时间轴：每个成功快照的聚合状态（回放时间轴数据源）。"""
        self._require_loaded()
        items = []
        for snap in self._snapshots:
            stats = snap.get("station_stats") or []
            level_counts: dict[str, int] = {}
            chla_values: list[float] = []
            for item in stats:
                if item.get("level"):
                    level_counts[str(item["level"])] = level_counts.get(str(item["level"]), 0) + 1
                if item.get("chla") is not None:
                    chla_values.append(float(item["chla"]))
            class_total = sum(level_counts.values())
            compliance = sum(v for k, v in level_counts.items() if int(k) <= 3)
            items.append(
                {
                    "snapshot_id": snap["snapshot_id"],
                    "retrieved_at_utc": snap["retrieved_at_utc"],
                    "latest_observed_at": snap.get("latest_observed_at"),
                    "station_count": len(stats),
                    "class_counts": level_counts,
                    "class_compliance": {"num": compliance, "den": class_total},
                    "warning_count": sum(1 for v in chla_values if v >= self.CHLA_LIGHT),
                    "moderate_count": sum(1 for v in chla_values if v >= self.CHLA_MODERATE),
                    "chla_report_stations": len(chla_values),
                    "chla_mean": round(sum(chla_values) / len(chla_values), 3) if chla_values else None,
                }
            )
        return {
            "source": REALTIME_SOURCE_ID,
            "dataset_version": REALTIME_VERSION,
            "latest_snapshot_id": self._snapshots[-1]["snapshot_id"] if self._snapshots else None,
            "warning_thresholds": {"light": self.CHLA_LIGHT, "moderate": self.CHLA_MODERATE},
            "snapshots": items,
        }

    def summary(self, snapshot_id: str | None = None) -> dict[str, Any]:
        """全湖实时汇总（可按快照回放）：全部指标由 observed 数据计算，口径/权重/阈值随响应披露。"""
        import pandas as pd

        self._require_loaded()
        if self._observations is None or self._observations.empty or not self._snapshots:
            raise RealtimeDataUnavailable("无可用快照")
        latest_id = self._snapshots[-1]["snapshot_id"]
        target_id = snapshot_id or latest_id
        if target_id not in {s["snapshot_id"] for s in self._snapshots}:
            raise KeyError(f"snapshot not found: {target_id}")
        idx = next(i for i, s in enumerate(self._snapshots) if s["snapshot_id"] == target_id)
        prev_id = self._snapshots[idx - 1]["snapshot_id"] if idx >= 1 else None
        lat = self._latest_rows(target_id)
        prv = self._latest_rows(prev_id) if prev_id else pd.DataFrame()

        means: dict[str, Any] = {}
        trends: dict[str, Any] = {}
        for code in self.SUMMARY_VARIABLES:
            value, count = self._mean_of(lat, code)
            means[code] = {"value": value, "count": count, "unit": ""}
            prev_value, prev_count = self._mean_of(prv, code) if prev_id else (None, 0)
            delta_pct = None
            if value is not None and prev_value not in (None, 0):
                delta_pct = round((value - prev_value) / prev_value * 100.0, 1)
            direction = "flat" if delta_pct is None or abs(delta_pct) < 3.0 else ("up" if delta_pct > 0 else "down")
            trends[code] = {"delta_pct": delta_pct, "direction": direction, "prev_value": prev_value}

        info_by_id = {e["entity_id"]: e for e in self._stations}

        # 水质类别（上游发布类别，非本系统判定）——按所选快照
        stats = self._snapshot_stats(target_id)
        level_counts: dict[str, int] = {}
        level_by_station: dict[str, Any] = {}
        chla_by_station: dict[str, float] = {}
        for item in stats:
            if item.get("level"):
                level_counts[str(item["level"])] = level_counts.get(str(item["level"]), 0) + 1
                level_by_station[item["entity_id"]] = item["level"]
            if item.get("chla") is not None:
                chla_by_station[item["entity_id"]] = float(item["chla"])
        class_total = sum(level_counts.values())
        compliance_num = sum(v for k, v in level_counts.items() if int(k) <= 3)

        # 蓝藻筛查预警
        warnings: list[dict[str, Any]] = []
        algae_num = 0
        for entity_id, value in chla_by_station.items():
            if value >= self.CHLA_LIGHT:
                algae_num += 1
                info = info_by_id.get(entity_id, {})
                location = info.get("location") or {}
                warnings.append(
                    {
                        "station_id": entity_id,
                        "station_name": info.get("source_station_name"),
                        "chla": round(float(value), 2),
                        "band": "moderate" if value >= self.CHLA_MODERATE else "light",
                        "lon": location.get("lon"),
                        "lat": location.get("lat"),
                        "location_status": location.get("location_status", "missing"),
                    }
                )
        warnings.sort(key=lambda item: item["chla"], reverse=True)
        chla_den = len(chla_by_station)

        # 数据完整度（所选快照 ok 行占比）
        total_rows = int(len(lat)) if not lat.empty else 0
        ok_rows = int((lat["observation_status"] == "ok").sum()) if not lat.empty else 0

        # 健康分：透明加权（达标率 40% + 蓝藻正常率 30% + 完整度 30%）；权重缺失项按剩余权重归一
        compliance_rate = (compliance_num / class_total) if class_total else None
        algae_rate = ((chla_den - algae_num) / chla_den) if chla_den else None
        completeness_rate = (ok_rows / total_rows) if total_rows else None
        parts = [
            (0.4, compliance_rate),
            (0.3, algae_rate),
            (0.3, completeness_rate),
        ]
        used = [(w, v) for w, v in parts if v is not None]
        score = round(sum(w * v for w, v in used) / sum(w for w, _ in used) * 100.0, 1) if used else None
        grade = "excellent" if score is not None and score >= 85 else "good" if score is not None and score >= 70 else "fair" if score is not None and score >= 50 else "poor"

        markers = []
        # 悬停指标卡数据源：所选快照内每站各指标最新 ok 值
        metrics_by_station: dict[str, dict[str, float]] = {}
        if not lat.empty:
            metric_ok_rows = lat[lat["observation_status"] == "ok"]
            for entity_id, grp in metric_ok_rows.groupby("station_entity_id"):
                metrics_by_station[entity_id] = {
                    str(row.variable_code): round(float(row.value), 3)
                    for row in grp.itertuples(index=False)
                    if row.variable_code in self.SUMMARY_VARIABLES
                    or row.variable_code in ("pH", "turbidity", "cod_mn")
                }
        for e in self._stations:
            location = e.get("location") or {}
            # 与 /spatial-entities 地图规则一致：仅 verified/metadata_only 生成地图点位
            if location.get("location_status") not in ("verified", "metadata_only"):
                continue
            if location.get("lon") is None or location.get("lat") is None:
                continue
            chla_value = chla_by_station.get(e["entity_id"])
            markers.append(
                {
                    "id": e["entity_id"],
                    "name": e.get("source_station_name"),
                    "province": e.get("province"),
                    "basin": e.get("basin"),
                    "lon": location.get("lon"),
                    "lat": location.get("lat"),
                    "location_status": location.get("location_status", "missing"),
                    "chla": round(chla_value, 2) if chla_value is not None else None,
                    "water_level": level_by_station.get(e["entity_id"]),
                    "metrics": metrics_by_station.get(e["entity_id"], {}),
                    "observed_at": next(
                        (r.observed_at for r in lat.itertuples(index=False) if r.station_entity_id == e["entity_id"] and r.observed_at),
                        None,
                    ) if not lat.empty else None,
                }
            )

        status = self.status()
        dominant = max(level_counts.items(), key=lambda kv: kv[1])[0] if level_counts else None
        is_latest = target_id == latest_id
        return {
            "source": REALTIME_SOURCE_ID,
            "dataset_version": REALTIME_VERSION,
            "as_of": status.get("as_of") if is_latest else next(s["retrieved_at_utc"] for s in self._snapshots if s["snapshot_id"] == target_id),
            "freshness_status": status.get("freshness_status", "unavailable") if is_latest else "historical",
            "observed_lag_h": status.get("observed_lag_h") if is_latest else None,
            "latest_snapshot_id": latest_id,
            "selected_snapshot_id": target_id,
            "is_latest": is_latest,
            "retrieved_at": next(s["retrieved_at_utc"] for s in self._snapshots if s["snapshot_id"] == target_id),
            "latest_observed_at": status.get("latest_observed_at") if is_latest else next(
                (s.get("latest_observed_at") for s in self._snapshots if s["snapshot_id"] == target_id), None
            ),
            "station_total": len(self._stations),
            "class_counts": level_counts,
            "class_total": class_total,
            "dominant_class": dominant,
            "class_iii_rate": round(compliance_num / class_total, 4) if class_total else None,
            "class_compliance": {"num": compliance_num, "den": class_total},
            "chla_report_stations": chla_den,
            "warnings": warnings,
            "warning_thresholds": {"light": self.CHLA_LIGHT, "moderate": self.CHLA_MODERATE},
            "means": means,
            "trends": trends,
            "health": {
                "score": score,
                "grade": grade,
                "subscores": {
                    "class_compliance": {"rate": compliance_rate, "num": compliance_num, "den": class_total},
                    "algae_normal": {"rate": algae_rate, "num": chla_den - algae_num, "den": chla_den},
                    "completeness": {"rate": completeness_rate, "num": ok_rows, "den": total_rows},
                },
                "definition": "健康分=达标率×40%+蓝藻正常率×30%+数据完整度×30%（缺失项按剩余权重归一）；"
                "达标=上游水质类别≤III类；蓝藻筛查阈值 chla 10/25 μg/L；均为官方观测的派生指标，非监管判定",
            },
            "markers": markers,
        }

    def quality(self, entity_id: str) -> dict[str, Any] | None:
        self._require_loaded()
        view = self.station(entity_id)
        if view is None:
            return None
        import pandas as pd

        status = self.status()
        counts = self._station_counts(entity_id)
        total_variables = sum(counts.values()) or 11
        sub_all = self._observations[self._observations["station_entity_id"] == entity_id]
        missing_latest = sorted(
            sub_all[(sub_all["snapshot_id"] == self._snapshots[-1]["snapshot_id"]) & (sub_all["observation_status"].isin(["missing", "parse_failed"]))]["variable_code"].unique().tolist()
        ) if self._snapshots else []
        qc_rejected_latest = sorted(
            sub_all[(sub_all["snapshot_id"] == self._snapshots[-1]["snapshot_id"]) & (sub_all["observation_status"] == "qc_rejected")]["variable_code"].unique().tolist()
        ) if self._snapshots else []
        snapshot_count = len(self._snapshots)
        limitations: list[str] = []
        if counts["missing"] / total_variables >= 0.5:
            limitations.append("最新快照缺测指标过半（上游叶绿素a/藻密度覆盖普遍偏低），缺测如实披露，不得补模拟值")
        if view["location"]["location_status"] in ("suspicious", "missing"):
            limitations.append("站点坐标不可信（shared/missing），不得生成地图点位")
        elif view["location"]["location_status"] == "metadata_only":
            limitations.append("站点坐标来自注册表元数据，未经官方核验（位置待核验）")
        limitations.append("官方接口观测未经跨源验证：is_ground_truth=false，不得用作模型真值")
        return {
            "station_entity_id": entity_id,
            "status": status.get("freshness_status", "unavailable"),
            "observed_lag_h": status.get("observed_lag_h"),
            "retrieval_lag_h": None
            if not status.get("last_success_at")
            else round((pd.Timestamp.now(tz="UTC") - pd.Timestamp(status["last_success_at"])).total_seconds() / 3600.0, 2),
            "variable_coverage": {**counts, "total": total_variables},
            "coverage_ratio": round(counts["ok"] / total_variables, 4),
            "missing_variables": missing_latest,
            "qc_rejected_variables": qc_rejected_latest,
            "snapshot_count": snapshot_count,
            "location_status": view["location"]["location_status"],
            "is_ground_truth": False,
            "verification_state": "not_cross_validated",
            "suitability": {
                "display": True,
                "trend": snapshot_count >= 2 and counts["ok"] > 0,
                "model_use": False,
            },
            "limitations": limitations,
            "data_mode": OBSERVED_DATA_MODE,
            "dataset_version": REALTIME_VERSION,
        }


def _configured_provider(env_key: str) -> str:
    raw = os.environ.get(env_key, "").strip().lower()
    return raw or "simulated"


def create_observation_provider() -> ObservationProvider:
    name = _configured_provider(OBSERVATION_PROVIDER_ENV)
    if name == "simulated":
        return SimulatedObservationProvider()
    raise ProviderConfigError(
        f"{OBSERVATION_PROVIDER_ENV}={name!r} 的实现尚未提供，拒绝静默回退 simulated：请改回 'simulated' 或先实现对应 Provider"
    )


def create_prediction_provider(observation_provider: ObservationProvider) -> PredictionProvider:
    name = _configured_provider(PREDICTION_PROVIDER_ENV)
    if name == "simulated":
        return SimulatedPredictionProvider(observation_provider.zones())
    raise ProviderConfigError(
        f"{PREDICTION_PROVIDER_ENV}={name!r} 的实现尚未提供，拒绝静默回退 simulated：请改回 'simulated' 或先实现对应 Provider"
    )


def create_realtime_observation_provider() -> MeeRealtimeObservationProvider:
    """实时观测轨 Provider（双轨之一）：始终构建，数据可用性在请求时判定。

    目录缺失/为空不阻断启动——/realtime/status 必须能如实返回 unavailable；
    数据端点在无数据时抛 RealtimeDataUnavailable，禁止回退 simulated。
    """
    return MeeRealtimeObservationProvider()
