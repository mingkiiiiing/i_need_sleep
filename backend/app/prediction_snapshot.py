"""实测快照驱动的预测结果缓存与原子发布。

解决的问题：此前每个页面请求都会完整重跑一次推理（热启动约 4.6s），
进入预测页还会串行请求七个时效（合计约 28s），并且每分钟无条件重算一次。
本模块把数据链改为：

    MEE 定时采集
        ↓
    发布新的完整实测 snapshot_id
        ↓
    后台发现版本键变化 → 批量生成全部预测
        ↓
    校验完整性
        ↓
    原子发布 prediction_snapshot
        ↓
    页面读取现成结果，切换时效/指标不再运行模型

三条硬约束：

1. 版本键 = 实测 snapshot_id + 模型版本 + 特征合同版本 + 缓存结构版本。
   版本键不变就绝不重新推理——这是"打开即有结果"的前提。
2. 原子发布：结果先在临时目录生成并校验，再整体就位，最后才替换 status.json。
   页面只在最后一步之后切换快照。
3. 失败保留上一版：新一轮生成失败时，继续服务上一版成功预测并如实披露失败原因，
   绝不清空页面，也绝不回退为模拟数据。

生成分两阶段，让首屏尽快可用：

* 阶段 1（关键路径，秒级）：全湖 × 七个时效 —— 立即发布，页面即可用。
* 阶段 2（后台渐进）：全湖全部指标的解释、以及全部监测站的预测 —— 补齐后二次发布。
  阶段 2 未完成时站点读取回落到即时推理（该路径同样按实测快照缓存），并如实披露。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("uvicorn.error")

PREDICTION_CACHE_ENV = "TAIHU_PREDICTION_CACHE_DIR"
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / "prediction-cache"

# 缓存结构版本：生成口径或字段结构变化时必须递增，否则旧缓存会被误判为仍然有效。
# v2：新增模型响应性诊断（responsiveness）、区间自洽性标记、输入指纹与实体字段。
# v3：响应性拆为 numeric_variation / model_entity_response / comparison_usable 三态；
#     不确定性拆为 structural_valid / calibration_evidence / decision_usable 三层；
#     新增双指纹（observed + transformed）与模型产物摘要版本键。
# v5：指纹口径统一——derived risk_level 不再携带序数模型自身的输入指纹（批量与单条
#   同口径）；value_origin_counts 增加 derived_from_retrieval_field 独立桶。
# v4：2026-09-11 第二轮口径升级——全湖聚合层增加湖区分组/面积加权生物量；
# 水华面积切换为月度反演基底边界面积（derived_from_monthly_retrieval_field）；
# 站点载荷附带 lake_aggregate；chla/风险概率由公示代理标签重训后具备站点响应。
# v6：2026-09-11 第三轮口径闭环——聚合层升级为页面主结果合同：
# scope=lake_aggregate、station_total/reported、aggregation_method、快照双 ID、
# 概率 P90 与高风险站占比、全湖风险等级按冻结风险带对 chla 中位数重新判级。
# 教训：版本键只覆盖模型产物，看不见"代码口径"变更——结构/口径变化必须递增此版本。
CACHE_SCHEMA_VERSION = "prediction_snapshot_v6"

SNAPSHOT_HORIZONS: tuple[int, ...] = (1, 3, 7, 15, 30, 60, 90)

# 站点比较可用性的最小留出测试样本量：低于该值时模型判别力无统计意义，
# 即使数值随实体变化也只能用于研判展示。
MIN_COMPARISON_TEST_ROWS = 15

# 合成情景回退来源：数值差异只代表合成情景设定不同，绝不代表真实站点差异。
SYNTHETIC_ORIGINS = {"legacy_v0_2_synthetic_fallback"}

# 一次 predict_suite 内不随实体/时效变化的字段：抽出来单存一份，避免数百份冗余。
GLOBAL_FIELDS = ("acceptance", "retrieval_and_calibration", "model", "model_quality")

FOCUS_RESULT_KEY = {
    "risk": "probability",
    "chla": "chla",
    "area": "area",
    "biomass": "biomass",
    "density": "density",
}

# 预测页可切换的指标；用于后台补齐解释缓存。risk 是默认焦点，必须包含，
# 否则首次切换/首次进入该指标时仍要现算一次局部敏感性。
LAKE_EXPLAIN_METRICS: tuple[str, ...] = ("risk", "chla", "area", "biomass", "density")

# 全湖聚合层：全湖业务指标由 79 站预测分布聚合得出（中位数/四分位/风险站占比），
# 不再把"站点输入取均值后跑一次站点模型"的结果当作全湖预测。
LAKE_AGGREGATE_METRICS: tuple[str, ...] = ("probability", "chla", "biomass", "density")

# 水华风险站占比使用的叶绿素 a 阈值（μg/L）：与栅格场水华边界同一阈值口径。
CHLA_BLOOM_THRESHOLD_UG_L = 20.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _write_atomic(path: Path, text: str) -> None:
    """与 alert_center/history_review 相同的原子写：临时文件就位后整体替换。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def build_version_key(algorithm_status: dict[str, Any], source_snapshot_id: str | None) -> dict[str, Any]:
    """版本键：任一字段变化都意味着旧预测不再对应当前实测数据或模型。

    除实测快照 ID 外，必须覆盖「模型产物」本身：manifest 摘要、bundle 文件哈希集合、
    训练数据版本、预处理器版本。否则在同一 package_version 下替换 joblib 文件，
    旧预测快照不会自动失效，页面会继续展示用旧模型算出的结果。
    """
    artifacts = algorithm_status.get("model_artifacts") or {}
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "source_snapshot_id": source_snapshot_id,
        "model_version": algorithm_status.get("package_version"),
        "model_count": algorithm_status.get("model_count"),
        "feature_contract": algorithm_status.get("feature_contract"),
        "data_version": algorithm_status.get("data_version"),
        # ---- 模型产物层（本轮新增，防止"同版本号换模型文件"漏换代）----
        "manifest_sha256": artifacts.get("manifest_sha256"),
        "bundle_digest": artifacts.get("bundle_digest"),
        "bundle_hashes": artifacts.get("bundle_hashes") or {},
        "training_data_version": artifacts.get("training_data_version"),
        "preprocessor": artifacts.get("preprocessor"),
    }


def prediction_snapshot_id(key: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(key, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"PRED_{key.get('source_snapshot_id') or 'nosnapshot'}_{digest[:12]}"


def _strip_record(data: dict[str, Any]) -> dict[str, Any]:
    """落盘用的紧凑记录：剥离全局字段，并剥离与 focus_metric 绑定的解释。

    解释（局部单因素敏感性）只对聚焦任务生成，把它存进快照会造成"某个指标的解释
    被当成所有指标的解释"。因此快照只承载与指标无关的结果，解释由后端缓存按需提供。
    """
    record = {name: value for name, value in data.items() if name not in GLOBAL_FIELDS}
    results = record.get("results")
    if isinstance(results, dict):
        record["results"] = {
            task_key: {k: v for k, v in item.items() if k != "explainability"}
            for task_key, item in results.items()
        }
    return record


class PredictionSnapshotService:
    """预测快照的生成、发布与读取。所有公开方法都不抛异常给调用方以外的语义。"""

    def __init__(
        self,
        algorithm_v3: Any,
        realtime_provider: Any,
        cache_dir: Path | str | None = None,
        horizons: tuple[int, ...] = SNAPSHOT_HORIZONS,
        poll_interval_s: float = 30.0,
        station_sleep_s: float = 0.02,
        station_batch_size: int = 40,
    ) -> None:
        raw = os.environ.get(PREDICTION_CACHE_ENV, "").strip()
        self.cache_dir = Path(cache_dir) if cache_dir else (Path(raw) if raw else _DEFAULT_CACHE_DIR)
        self.algorithm = algorithm_v3
        self.realtime = realtime_provider
        self.horizons = tuple(horizons)
        self.poll_interval_s = poll_interval_s
        self.station_sleep_s = station_sleep_s
        # 站点按批次批量推理：同一 (task, variant, horizon) 一次推理多个站点，
        # 而不是「一站点 × 一时效 × 一指标」逐次运行。
        self.station_batch_size = max(1, int(station_batch_size))

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

        # 已发布快照的内存镜像（可从磁盘回填，因此后端重启后无需重新推理）。
        self._published: dict[str, Any] = {}
        self._state = "unavailable"
        self._last_error: str | None = None
        self._last_attempt_at: str | None = None
        self._pending_id: str | None = None
        self._pending_source_snapshot_id: str | None = None
        self._stations_total = 0
        self._stations_done = 0
        self._stations_ready = False
        # 解释缓存是内存态（解释与 focus_metric 绑定，不随快照落盘），重启后需重建；
        # 记录已预热过的快照 ID，避免重复预热。
        self._explain_warmed_for: str | None = None
        # 当前实测源对应的 prediction_snapshot_id 缓存：(source_id, 产物指纹, pred_id)
        self._live_key_cache: tuple[str, str, str] | None = None
        # 算法包状态短时缓存：(monotonic 时间, status)
        self._algorithm_status_cache: tuple[float, dict[str, Any]] | None = None
        self.ALGORITHM_STATUS_TTL_S = 2.0
        # 可观测性计数：快照成功发布次数 / 页面回落到即时推理的次数。
        # 审计口径「打开页面与切换选择不得触发推理」用 live_inference_fallbacks 证明。
        self._generation_count = 0
        self._live_fallback_count = 0
        # 管理员主动重算标记：由 request_rebuild() 置位，后台线程消费一次。
        self._force_requested = False

        self._load_published_from_disk()

    # ------------------------------------------------------------------ 状态

    def _realtime_source(self) -> Any:
        """快照必须对『算法实际使用的实时源』有效，而不是构造时记下的那个引用。

        否则测试或热替换把 v3.realtime 换掉后，快照会继续按旧源提供结果，
        造成"输入已变、结果没变"的假象。
        """
        return getattr(self.algorithm, "realtime", None) or self.realtime

    def _source_capability(self) -> bool:
        """当前实时源是否具备上报实测快照 ID 的能力（真实 MEE provider 具备）。"""
        return callable(getattr(self._realtime_source(), "status", None))

    def _current_source_snapshot_id(self) -> str | None:
        """当前最新实测快照 ID（读 status.json，不触发全湖 pandas 聚合）。"""
        try:
            return self._realtime_source().status().get("latest_snapshot_id")
        except Exception:  # noqa: BLE001 — 实测不可用时不生成预测，如实反映为 unavailable
            return None

    def _current_live_prediction_id(self) -> str | None:
        """当前实测快照 + 当前模型产物「本应」对应的 prediction_snapshot_id。"""
        source = self._current_source_snapshot_id()
        if not source:
            return None
        status = self._algorithm_status()
        artifacts = status.get("model_artifacts") or {}
        stamp = "|".join(str(item) for item in (
            artifacts.get("manifest_sha256"),
            artifacts.get("bundle_digest"),
            artifacts.get("training_data_version"),
            status.get("feature_contract"),
        ))
        cached = self._live_key_cache
        if cached is not None and cached[0] == source and cached[1] == stamp:
            return cached[2]
        pred_id = prediction_snapshot_id(build_version_key(status, source))
        self._live_key_cache = (source, stamp, pred_id)
        return pred_id

    def _serving_is_current(self) -> bool:
        """已发布快照是否允许作为「当前预测」服务。

        预测快照只在「同一实测源 + 同一模型产物」下有意义。把上一代结果当作当前预测
        展示，与展示 [0,0] 区间属同一类误导，因此这里显式设闸：

        * 当前实时源不具备上报快照 ID 的能力 → 无法核实同源关系，不服务快照，
          回落到即时推理（结果仍来自真实数据，只是不宣称"已缓存对齐"）；
        * 实测源暂时不可读（MEE 目录暂缺） → 继续服务上一版，由 status 字段如实披露
          （此时实时轨整体不可用，清空页面只会丢失已有信息）；
        * 版本键不一致 → 只在「正在为当前版本重算」时继续服务上一版；否则回落即时推理。
        """
        with self._lock:
            published = self._published
            state = self._state
            pending = self._pending_id
        if not published:
            return False
        if not self._source_capability():
            return False
        live_id = self._current_live_prediction_id()
        if live_id is None:
            return True
        if published.get("id") == live_id:
            return True
        return state == "updating" and pending == live_id

    def _algorithm_status(self) -> dict[str, Any]:
        try:
            return self.algorithm.status()
        except Exception:  # noqa: BLE001
            return {}

    def version_key(self) -> dict[str, Any]:
        return build_version_key(self._algorithm_status(), self._current_source_snapshot_id())

    def status(self) -> dict[str, Any]:
        """轻量状态：前端每次轮询只读这里，不触发任何推理。"""
        with self._lock:
            published = self._published
            payload = {
                "state": self._state,
                "schema": CACHE_SCHEMA_VERSION,
                "source_snapshot_id": published.get("key", {}).get("source_snapshot_id"),
                "prediction_snapshot_id": published.get("id"),
                "model_version": published.get("key", {}).get("model_version")
                or self._algorithm_status().get("package_version"),
                "feature_contract": published.get("key", {}).get("feature_contract"),
                "generated_at": published.get("manifest", {}).get("generated_at"),
                "horizons": list(self.horizons),
                "stations": {
                    "ready": self._stations_ready,
                    "done": self._stations_done,
                    "total": self._stations_total,
                },
                # 正在服务的是上一版成功预测（新一轮生成中或已失败）
                "using_previous_success": bool(published) and self._state in {"updating", "failed"},
                "pending_prediction_snapshot_id": self._pending_id,
                "pending_source_snapshot_id": self._pending_source_snapshot_id,
                "last_error": self._last_error,
                "last_attempt_at": self._last_attempt_at,
                "generation_count": self._generation_count,
                "live_inference_fallbacks": self._live_fallback_count,
                "cache_dir": str(self.cache_dir),
                "note": (
                    "state=ready 表示快照与当前实测数据同版本；updating/failed 且"
                    " prediction_snapshot_id 非空时，页面继续展示该版本并如实披露新数据状态。"
                ),
            }
            return payload

    def count_live_inference_fallback(self) -> None:
        """页面读取未命中快照、回落到即时推理时计数（可观测性，不影响服务）。"""
        with self._lock:
            self._live_fallback_count += 1

    def request_rebuild(self) -> dict[str, Any]:
        """管理员主动重算：唤醒后台线程并要求强制重新推理（版本键不变也重算）。

        用途：代码口径修复（如 CACHE_SCHEMA 教训）后，版本键看不见代码变更，
        唯一安全的重算入口就是显式的管理员指令。已有上一版时继续服务上一版，
        新结果完整生成并通过校验后才原子切换。
        """
        with self._lock:
            self._force_requested = True
        self._wake.set()
        return {
            "requested": True,
            "state": self._state,
            "published_prediction_snapshot_id": self._published.get("id"),
            "note": "重算在后台线程执行；期间继续服务当前已发布快照。",
        }

    # -------------------------------------------------------------- 磁盘回填

    def _snapshot_dir(self, pred_id: str) -> Path:
        return self.cache_dir / "snapshots" / pred_id

    def _status_path(self) -> Path:
        return self.cache_dir / "status.json"

    def _load_published_from_disk(self) -> None:
        """后端重启后直接加载磁盘上最近一次成功发布的预测，不需要重新跑完才能开页面。"""
        try:
            if not self._status_path().is_file():
                return
            status = json.loads(self._status_path().read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — 磁盘状态损坏时按"无缓存"启动，不阻断服务
            logger.warning("预测快照 status.json 读取失败，按无缓存启动: %s", exc)
            return
        pred_id = status.get("prediction_snapshot_id")
        if not pred_id:
            return
        try:
            self._load_snapshot_into_memory(pred_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("预测快照 %s 回填失败（将重新生成）: %s", pred_id, exc)
            return
        manifest = self._published.get("manifest", {})
        stations = manifest.get("stations") or {}
        self._stations_total = int(stations.get("total") or 0)
        self._stations_done = int(stations.get("done") or 0)
        self._stations_ready = bool(stations.get("ready"))
        # 全湖结果可用即视为 ready；站点层是否补齐由 stations 字段单独披露。
        self._state = "ready"
        logger.info(
            "预测快照已从磁盘加载: %s（source=%s, 站点 %s/%s）",
            pred_id,
            status.get("source_snapshot_id"),
            self._stations_done,
            self._stations_total,
        )

    def _load_snapshot_into_memory(self, pred_id: str) -> None:
        snapshot_dir = self._snapshot_dir(pred_id)
        manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
        common = json.loads((snapshot_dir / "common.json").read_text(encoding="utf-8"))
        lake = json.loads((snapshot_dir / "lake.json").read_text(encoding="utf-8"))
        stations: dict[str, Any] = {}
        stations_path = snapshot_dir / "stations.json"
        if stations_path.is_file():
            stations = json.loads(stations_path.read_text(encoding="utf-8")).get("stations", {})
        with self._lock:
            self._published = {
                "id": pred_id,
                "key": manifest.get("version_key") or {},
                "manifest": manifest,
                "common": common,
                "lake": lake.get("horizons", {}),
                "stations": stations,
            }
            stations_ready = bool((manifest.get("stations") or {}).get("ready"))
            self._stations_total = int((manifest.get("stations") or {}).get("total") or 0)
            self._stations_done = int((manifest.get("stations") or {}).get("done") or 0)
            self._stations_ready = stations_ready
        # 旧缓存（v3 之前的响应性结构，或完全没有诊断）就地补算三态诊断，
        # 避免沿用只含 entity_responsive 的旧结构造成"数值不同即可比"的过度结论。
        # 诊断口径升级（如接入门禁行状态）时，旧诊断缺少新字段也会就地重算。
        diag = manifest.get("responsiveness") or {}
        sample = None
        for horizon_diag in diag.values():
            for item in horizon_diag.values():
                sample = item
                break
            if sample:
                break
        sample_evidence = (sample or {}).get("comparison_evidence") or {}
        needs_diag = (
            not diag
            or (isinstance(sample, dict) and "comparison_usable" not in sample)
            or (isinstance(sample_evidence, dict) and "gate_status" not in sample_evidence)
        )
        if stations_ready and needs_diag:
            self._publish_responsiveness(pred_id)

    # ------------------------------------------------------------------ 读取

    def _published_entity(self, entity_id: str) -> dict[str, Any] | None:
        with self._lock:
            published = self._published
            if not published:
                return None
            if entity_id == "lake":
                return dict(published.get("lake") or {})
            stations = published.get("stations") or {}
            if entity_id in stations:
                return dict(stations[entity_id] or {})
            return None

    def has_entity(self, entity_id: str) -> bool:
        return bool(self._published_entity(entity_id))

    def assemble(self, entity_id: str, horizon_days: int, focus_metric: str = "risk") -> dict[str, Any] | None:
        """把快照记录组装成与原 /model/v3/predictions 完全一致的结构。

        解释字段（explainability）不与指标无关，因此不落在快照里：命中后端解释缓存时
        顺带附回，未命中时由调用方按需补齐，避免把别的指标的解释冒充成当前指标的解释。
        """
        if not self._serving_is_current():
            # 快照与当前实测源/模型产物不对应：不服务，交由调用方走即时推理。
            return None
        entity = self._published_entity(entity_id)
        if not entity:
            return None
        record = entity.get(str(horizon_days))
        if not record:
            return None
        with self._lock:
            common = dict(self._published.get("common") or {})
        data = dict(common)
        data.update(record)
        result_key = FOCUS_RESULT_KEY.get(focus_metric)
        data["analysis_focus"] = {"requested_metric": focus_metric, "result_key": result_key}
        data["entity_id"] = entity_id
        # 顶层指纹按当前焦点任务解析：落盘时顶层口径固定为 risk，serve 时必须换成
        # 焦点任务自己的模型输入矩阵指纹；合成回退 / 无真实 bundle 的任务显式置空并给原因，
        # 否则切指标后页面会拿别的任务（如 risk）的指纹冒充当前任务的模型输入。
        if result_key:
            per_task = data.get("transformed_model_input_fingerprints") or {}
            data["transformed_model_input_fingerprint"] = per_task.get(result_key)
            if per_task.get(result_key):
                data["transformed_model_input_fingerprint_unavailable_reason"] = None
            else:
                focus_item = (data.get("results") or {}).get(result_key) or {}
                focus_origin = focus_item.get("value_origin") or focus_item.get("status")
                data["transformed_model_input_fingerprint_unavailable_reason"] = {
                    "legacy_v0_2_synthetic_fallback": "synthetic_fallback_no_real_model_inputs",
                    "not_applicable": "no_real_bundle_for_task_horizon",
                }.get(focus_origin, "transformed_frame_not_recorded")
        # 当前指标在该时效上是否真的随实体变化——由快照层实测得出，供页面如实披露。
        diagnostics = (self._published.get("manifest") or {}).get("responsiveness") or {}
        horizon_diag = diagnostics.get(str(horizon_days)) or {}
        data["entity_diagnostic"] = horizon_diag.get(result_key) if result_key else None
        # 站点载荷附带全湖聚合层：页面"本站 vs 全湖中位"对比与右侧全湖汇总同源
        if entity_id != "lake":
            lake_agg = ((self._published.get("lake") or {}).get(str(horizon_days)) or {}).get("station_aggregate")
            if lake_agg:
                data["lake_aggregate"] = lake_agg
        explainability = self._cached_explainability(entity_id, horizon_days, result_key)
        if explainability is not None and isinstance(data.get("results"), dict):
            item = data["results"].get(result_key)
            if isinstance(item, dict):
                item["explainability"] = explainability
        data["snapshot_source"] = {
            "prediction_snapshot_id": self._published.get("id"),
            "source_snapshot_id": (self._published.get("key") or {}).get("source_snapshot_id"),
            "generated_at": (self._published.get("manifest") or {}).get("generated_at"),
            "served_from_snapshot": True,
        }
        return data

    def _cached_explainability(self, entity_id: str, horizon_days: int, result_key: str | None) -> Any:
        if not result_key:
            return None
        getter = getattr(self.algorithm, "_explain_cache", None)
        if not isinstance(getter, dict):
            return None
        try:
            month_offset = self.algorithm._runtime_imports()[2].month_offset(horizon_days)
        except Exception:  # noqa: BLE001
            return None
        return getter.get((result_key, entity_id, month_offset, horizon_days))

    def ensure_explainability(self, entity_id: str, horizon_days: int, focus_metric: str) -> Any:
        """按需补齐当前指标的局部敏感性解释。

        解释与 focus_metric 绑定，无法随快照落盘，因此在这里单独取：命中后端解释缓存
        则零推理返回，未命中才实际运行一次，随后即进入缓存。
        """
        result_key = FOCUS_RESULT_KEY.get(focus_metric)
        if not result_key:
            return None
        cached = self._cached_explainability(entity_id, horizon_days, result_key)
        if cached is not None:
            return cached
        try:
            data = self.algorithm.predict_suite(horizon_days, entity_id, focus_metric)
        except Exception as exc:  # noqa: BLE001 — 解释不可得不应使主结果失败
            logger.info("解释补齐失败（%s/%s/%s）: %s", entity_id, horizon_days, focus_metric, exc)
            return None
        item = (data.get("results") or {}).get(result_key) or {}
        return item.get("explainability")

    def snapshot_payload(self, entity_id: str = "lake", focus_metric: str = "risk") -> dict[str, Any] | None:
        """一次返回全部时效结果 + 趋势摘要 + 版本与状态，供前端一次读取。"""
        if not self._serving_is_current():
            return None
        entity = self._published_entity(entity_id)
        if not entity:
            return None
        horizons: dict[str, Any] = {}
        for horizon in self.horizons:
            assembled = self.assemble(entity_id, horizon, focus_metric)
            if assembled is not None:
                horizons[str(horizon)] = assembled
        if not horizons:
            return None
        with self._lock:
            manifest = dict(self._published.get("manifest") or {})
            status = {
                "state": self._state,
                "using_previous_success": bool(self._published) and self._state in {"updating", "failed"},
                "last_error": self._last_error,
                "stations": {
                    "ready": self._stations_ready,
                    "done": self._stations_done,
                    "total": self._stations_total,
                },
            }
        trend = self._trend_summary(horizons)
        # 指标级诊断摘要：三态独立汇总（数值差异 / 模型响应 / 可否用于站点比较）。
        responsiveness = (manifest.get("responsiveness") or {})
        metric_diagnostics: dict[str, Any] = {}
        for horizon_key, horizon_diag in responsiveness.items():
            for output_key, item in horizon_diag.items():
                entry = metric_diagnostics.setdefault(
                    output_key,
                    {
                        "numeric_variation": False,
                        "model_entity_response": False,
                        "comparison_usable": False,
                        "variation_horizons": [],
                        "responsive_horizons": [],
                        "comparable_horizons": [],
                        "non_responsive_horizons": [],
                        "model_family": item.get("model_family"),
                        "model_run_id": item.get("model_run_id"),
                        "value_origin": item.get("value_origin"),
                        "blocked_reasons": [],
                    },
                )
                try:
                    horizon_number = int(horizon_key)
                except (TypeError, ValueError):
                    continue
                if item.get("numeric_variation"):
                    entry["variation_horizons"].append(horizon_number)
                    entry["numeric_variation"] = True
                else:
                    entry["non_responsive_horizons"].append(horizon_number)
                if item.get("model_entity_response"):
                    entry["responsive_horizons"].append(horizon_number)
                    entry["model_entity_response"] = True
                if item.get("comparison_usable"):
                    entry["comparable_horizons"].append(horizon_number)
                    entry["comparison_usable"] = True
                reason = item.get("comparison_blocked_reason")
                if reason and reason not in entry["blocked_reasons"]:
                    entry["blocked_reasons"].append(reason)
        for entry in metric_diagnostics.values():
            for bucket_name in ("variation_horizons", "responsive_horizons", "comparable_horizons", "non_responsive_horizons"):
                entry[bucket_name] = sorted(entry[bucket_name])
        return {
            "entity_id": entity_id,
            "focus_metric": focus_metric,
            "horizons": horizons,
            "horizon_list": [h for h in self.horizons if str(h) in horizons],
            "trend": trend,
            "metric_diagnostics": metric_diagnostics,
            "prediction_snapshot_id": self._published.get("id"),
            "source_snapshot_id": (self._published.get("key") or {}).get("source_snapshot_id"),
            "generated_at": manifest.get("generated_at"),
            "model_version": (self._published.get("key") or {}).get("model_version"),
            "cache_schema": manifest.get("schema"),
            "status": status,
            # 顶层来源标注：页面据此显示"读取自预生成快照"（此前只有时效级记录带此字段）
            "snapshot_source": {
                "prediction_snapshot_id": self._published.get("id"),
                "source_snapshot_id": (self._published.get("key") or {}).get("source_snapshot_id"),
                "generated_at": manifest.get("generated_at"),
                "served_from_snapshot": True,
            },
        }

    def _trend_summary(self, horizons: dict[str, Any]) -> dict[str, Any]:
        """趋势图所需的最小摘要：每时效的风险得分与当前焦点指标值。"""
        points = []
        for horizon_key, data in horizons.items():
            results = data.get("results") or {}
            focus_key = (data.get("analysis_focus") or {}).get("result_key")
            focus_item = results.get(focus_key) or {}
            points.append(
                {
                    "horizon_days": int(horizon_key),
                    "risk_score": data.get("risk_score"),
                    "focus_value": focus_item.get("value"),
                    "focus_unit": focus_item.get("unit"),
                    "focus_status": focus_item.get("status"),
                    "issued_at": data.get("issued_at"),
                }
            )
        points.sort(key=lambda item: item["horizon_days"])
        return {"points": points}

    # ------------------------------------------------------------------ 生成

    def ensure_fresh(self, *, force: bool = False) -> None:
        """版本键变化才重新生成；调用方通常是后台线程。"""
        if self._stop.is_set():
            return
        key = self.version_key()
        if not key.get("source_snapshot_id"):
            with self._lock:
                if not self._published:
                    self._state = "unavailable"
                    self._last_error = "实测快照不可用：不生成预测，也不回退模拟数据"
            return
        pred_id = prediction_snapshot_id(key)
        with self._lock:
            same_version = self._published.get("id") == pred_id
            generating = self._pending_id is not None
        if generating:
            return
        if same_version and not force:
            # 版本未变化：绝不重新推理。但站点层与解释缓存都可能是未完成状态
            # （首次生成被中断、或服务重启后内存缓存为空），这里接着补齐。
            self._ensure_stations_complete(key, pred_id)
            self._ensure_lake_explainability(key, pred_id)
            return
        self._generate(key, pred_id, force=force)

    def _ensure_lake_explainability(self, key: dict[str, Any], pred_id: str) -> None:
        """确保全湖各指标的解释缓存已就绪（内存态，重启后必须重建）。"""
        with self._lock:
            if self._explain_warmed_for == pred_id:
                return
        self._warm_lake_explainability(key, pred_id)
        with self._lock:
            self._explain_warmed_for = pred_id

    def _ensure_stations_complete(self, key: dict[str, Any], pred_id: str) -> None:
        """站点层的续传补齐：已完成的不重算，缺哪个补哪个。

        注意：必须以「当前站点列表 vs 已落内存的实体」实测比对，绝不能只看
        stations.ready 标志。上一轮曾经在批次全失败时仍把 ready=True 落盘
        （done=0/total=79），只看标志会让续传逻辑误判为已完成而永不补齐。
        """
        station_ids = self._active_station_ids()
        if not station_ids:
            return
        missing = [entity_id for entity_id in station_ids if not self.has_entity(entity_id)]
        with self._lock:
            self._stations_total = len(station_ids)
            self._stations_done = len(station_ids) - len(missing)
        if not missing:
            self._ensure_lake_aggregate(pred_id)
            if not self._stations_ready:
                with self._lock:
                    self._stations_ready = True
                self._persist_stations(pred_id, ready=True)
                self._stamp_status_file()
                logger.info("预测快照 %s：站点层校验通过 %s/%s", pred_id, self._stations_done, self._stations_total)
            return
        logger.info("预测快照 %s 站点层待补齐 %s/%s", pred_id, len(missing), len(station_ids))
        self._generate_stations(key, pred_id, missing)

    def _generate(self, key: dict[str, Any], pred_id: str, *, force: bool = False) -> None:
        tmp_dir = self.cache_dir / f".tmp-{pred_id}"
        target_dir = self._snapshot_dir(pred_id)
        with self._lock:
            self._state = "updating" if not self._published else self._state
            if not self._published:
                self._state = "updating"
            self._pending_id = pred_id
            self._pending_source_snapshot_id = key.get("source_snapshot_id")
            self._last_attempt_at = _now_iso()
            self._last_error = None
        try:
            if target_dir.is_dir() and not force:
                # 该版本此前已完整生成过（例如进程重启后重新对齐）：直接加载，零推理。
                # force（管理员重算）不走此捷径：必须真实重新推理。
                self._load_snapshot_into_memory(pred_id)
                with self._lock:
                    self._state = "ready"
                    self._pending_id = None
                    self._pending_source_snapshot_id = None
                self._stamp_status_file()
                logger.info("预测快照已存在于磁盘，直接复用: %s", pred_id)
                return

            if target_dir.is_dir():
                # 管理员强制重算：版本键相同也要丢弃旧产物重新推理。
                # 已发布结果仍在内存中继续服务，不受磁盘删除影响。
                shutil.rmtree(target_dir, ignore_errors=True)

            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir.mkdir(parents=True, exist_ok=True)

            common: dict[str, Any] = {}
            lake_horizons: dict[str, Any] = {}
            for horizon in self.horizons:
                if self._stop.is_set():
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    return
                data = self.algorithm.predict_suite(horizon, "lake", "risk", explain=False)
                if not common:
                    common = {field: data.get(field) for field in GLOBAL_FIELDS}
                lake_horizons[str(horizon)] = _strip_record(data)
                if self._current_source_snapshot_id() != key.get("source_snapshot_id"):
                    # 生成途中实测数据已更新：放弃本轮，避免发布过期预测。
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    with self._lock:
                        self._pending_id = None
                        self._pending_source_snapshot_id = None
                    logger.info("预测快照 %s 生成中止：实测快照已更新，将按新版本重来", pred_id)
                    return

            missing = [h for h in self.horizons if str(h) not in lake_horizons]
            if missing:
                raise RuntimeError(f"预测快照不完整，缺失时效: {missing}")
            for horizon_key, record in lake_horizons.items():
                if not record.get("results"):
                    raise RuntimeError(f"预测快照时效 {horizon_key} 缺少 results")
                if record.get("prediction_run_id") is None:
                    raise RuntimeError(f"预测快照时效 {horizon_key} 缺少 prediction_run_id")

            station_ids = self._active_station_ids()
            manifest = {
                "prediction_snapshot_id": pred_id,
                "version_key": key,
                "schema": CACHE_SCHEMA_VERSION,
                "generated_at": _now_iso(),
                "horizons": list(self.horizons),
                "stations": {"ready": False, "done": 0, "total": len(station_ids)},
                "provenance": {
                    "generated_by": "PredictionSnapshotService",
                    "note": (
                        "由实测快照驱动的后台预生成结果；站点结果补齐前，站点读取回落到"
                        "即时推理（同样按实测快照缓存），页面如实披露。"
                    ),
                },
            }
            _write_atomic(tmp_dir / "common.json", _dumps(common))
            _write_atomic(tmp_dir / "lake.json", _dumps({"horizons": lake_horizons}))
            _write_atomic(tmp_dir / "manifest.json", _dumps(manifest))

            target_dir.parent.mkdir(parents=True, exist_ok=True)
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            tmp_dir.rename(target_dir)

            with self._lock:
                self._published = {
                    "id": pred_id,
                    "key": key,
                    "manifest": manifest,
                    "common": common,
                    "lake": lake_horizons,
                    "stations": {},
                }
                self._state = "ready"
                self._stations_total = len(station_ids)
                self._stations_done = 0
                self._stations_ready = not station_ids
                self._pending_id = None
                self._pending_source_snapshot_id = None
                self._last_error = None
                self._generation_count += 1
            self._stamp_status_file()
            logger.info(
                "预测快照已发布（阶段 1：全湖 %s 个时效）: %s，站点 %s 个待后台补齐",
                len(lake_horizons),
                pred_id,
                len(station_ids),
            )

            # ---- 阶段 2：后台渐进补齐 ----
            self._warm_lake_explainability(key, pred_id)
            with self._lock:
                self._explain_warmed_for = pred_id
            self._generate_stations(key, pred_id, station_ids)
        except Exception as exc:  # noqa: BLE001 — 生成失败必须保留上一版，绝不清空
            shutil.rmtree(tmp_dir, ignore_errors=True)
            with self._lock:
                self._pending_id = None
                self._pending_source_snapshot_id = None
                self._last_error = f"{type(exc).__name__}: {exc}"
                # 有上一版就继续服务上一版；没有则如实反映为不可用。
                self._state = "failed" if self._published else "unavailable"
            self._stamp_status_file()
            logger.warning("预测快照生成失败（保留上一版继续服务）: %s", exc, exc_info=True)

    def _active_station_ids(self) -> list[str]:
        try:
            stations = self._realtime_source().stations(active="latest")
        except Exception as exc:  # noqa: BLE001
            logger.warning("站点列表获取失败，本轮跳过站点预生成: %s", exc)
            return []
        # 站点视图的实体标识键是 id（_station_view 的对外字段），不叫 entity_id。
        ids = [item.get("id") or item.get("entity_id") for item in stations]
        return [entity_id for entity_id in ids if entity_id]

    def _warm_lake_explainability(self, key: dict[str, Any], pred_id: str) -> None:
        """把全湖各指标的解释算进后端缓存，使页面切换指标时解释面板也立即就绪。

        解释依赖 focus_metric，无法与结果一起随快照落盘，因此这里预填充缓存而不是存文件。
        """
        for metric in LAKE_EXPLAIN_METRICS:
            for horizon in self.horizons:
                if self._stop.is_set() or self._source_changed(key):
                    return
                try:
                    self.algorithm.predict_suite(horizon, "lake", metric)
                except Exception as exc:  # noqa: BLE001 — 解释预热失败不影响已发布快照
                    logger.info("全湖 %s 指标解释预热跳过（%sd）: %s", metric, horizon, exc)
        logger.info("预测快照 %s：全湖各指标解释缓存已预热", pred_id)

    def _generate_stations(self, key: dict[str, Any], pred_id: str, station_ids: list[str]) -> None:
        """站点预生成：按批次批量推理。

        批量推理把「一个站点 × 一个时效」的 N 次单行推理合并成一次 N 行推理，
        实测单行约 0.28s 而 20 行批量仅 0.20s，因此站点补齐由数十秒/站点降到毫秒级/站点。
        """
        if not station_ids:
            return
        for start in range(0, len(station_ids), self.station_batch_size):
            if self._stop.is_set() or self._source_changed(key):
                logger.info("预测快照 %s 站点补齐中止：实测快照已更新", pred_id)
                return
            chunk = station_ids[start:start + self.station_batch_size]
            for horizon in self.horizons:
                if self._stop.is_set() or self._source_changed(key):
                    logger.info("预测快照 %s 站点补齐中止：实测快照已更新", pred_id)
                    return
                try:
                    batch = self.algorithm.predict_suite_batch(horizon, chunk)
                except Exception as exc:  # noqa: BLE001 — 单批次失败不影响其余站点
                    logger.info("站点批次 %s.. 时效 %sd 预生成跳过: %s", chunk[0], horizon, exc)
                    continue
                with self._lock:
                    if self._published.get("id") != pred_id:
                        return
                    stations = self._published.setdefault("stations", {})
                    for entity_id, record in batch.items():
                        stations.setdefault(entity_id, {})[str(horizon)] = _strip_record(record)
                    # 以实际落内存的站点数为准，天然支持中断后续传而不重复计数。
                    self._stations_done = len(stations)
            self._persist_stations(pred_id, ready=False)
            self._stamp_status_file()
            if self.station_sleep_s:
                self._stop.wait(self.station_sleep_s)
        # 只有真的补齐到目标站点数才允许标记 ready。批次失败时保持 ready=False，
        # 让下一轮巡检继续续传——绝不把"本轮没做成功"写成"已完成"。
        with self._lock:
            complete = self._stations_done >= self._stations_total and self._stations_total > 0
        self._persist_stations(pred_id, ready=complete)
        with self._lock:
            self._stations_ready = complete
            if self._published.get("id") == pred_id:
                self._published["manifest"]["stations"] = {
                    "ready": complete,
                    "done": self._stations_done,
                    "total": self._stations_total,
                }
        if not complete:
            logger.warning(
                "预测快照 %s：站点层未补齐（%s/%s），下一轮继续续传，不标记 ready",
                pred_id, self._stations_done, self._stations_total,
            )
            self._stamp_status_file()
            return
        # 站点齐全后才能给出可信的响应性判定：此时才统计各 (时效, 指标) 的实体间离散度。
        self._publish_responsiveness(pred_id)
        # 站点齐全后同样才能给出全湖聚合层：全湖汇总 = 79 站预测分布，不是虚拟站点。
        self._publish_lake_aggregate(pred_id)
        self._stamp_status_file()
        logger.info("预测快照 %s：站点预测已补齐 %s/%s", pred_id, self._stations_done, self._stations_total)

    def _source_changed(self, key: dict[str, Any]) -> bool:
        return self._current_source_snapshot_id() != key.get("source_snapshot_id")

    # ------------------------------------------------------------ 响应性诊断

    # 判定"两个取值是否相同"的舍入位数：与页面展示精度一致，避免浮点尾差被误判为差异。
    RESPONSIVENESS_ROUND = 6

    def _model_quality_index(self) -> dict[str, Any]:
        with self._lock:
            common = self._published.get("common") or {}
        return common.get("model_quality") or {}

    def _gate_rows_index(self) -> dict[tuple[str, str, int], dict[str, Any]]:
        """10% 提升门禁行的索引（唯一来源：算法包 evaluation/gate_table.json）。"""
        getter = getattr(self.algorithm, "gate_rows_index", None)
        if not callable(getter):
            return {}
        try:
            return dict(getter()) or {}
        except Exception:  # noqa: BLE001 — 门禁证据不可用时按"无评估记录"收敛
            return {}

    @staticmethod
    def _comparison_usability(
        value_origin: str | None,
        model_family: str | None,
        model_run_id: str | None,
        numeric_variation: bool,
        model_quality: dict[str, Any],
        gate_row: dict[str, Any] | None,
        gate_available: bool,
    ) -> tuple[bool, str | None, dict[str, Any]]:
        """判定该 (时效, 指标) 的结果是否允许用于站点间比较。

        三层独立，禁止用"数值不同"直接推出"可用于比较"：
          ① numeric_variation     —— 不同实体数值是否不同（纯统计事实）
          ② model_entity_response —— 真实模型是否对实体输入有响应（排除合成情景）
          ③ comparison_usable     —— 来源 + 门禁 + 验证证据是否支持站点比较

        第③层必须消费 10% 提升门禁（唯一来源 evaluation/gate_table.json）的真实行状态：
        门禁 FAIL（未达标）或未可评估（N.A. / 无该任务时效的评估记录）时，
        即使留出证据形式上达标，也不得宣称"可用于站点比较"。
        """
        gate_status = (gate_row or {}).get("status")
        evidence: dict[str, Any] = {
            "value_origin": value_origin,
            "model_family": model_family,
            "model_run_id": model_run_id,
            "gate_status": gate_status,
            "gate_na_reason": (gate_row or {}).get("na_reason"),
            "gate_uplift": (gate_row or {}).get("uplift"),
        }
        if value_origin in SYNTHETIC_ORIGINS:
            return False, "synthetic_scenario_fallback_not_comparable", evidence
        if value_origin == "derived_from_chla_v0_3_risk_bands":
            return False, "derived_indicator_inherits_source_model_limits", evidence
        if value_origin != "v0_3_real_bundle":
            return False, "unknown_value_origin", evidence
        if not numeric_variation:
            return False, "constant_output_across_entities", evidence
        if model_family == "simple_baseline":
            return False, "static_baseline_model_does_not_use_entity_inputs", evidence

        # 10% 提升门禁行状态：真实接入门禁验收结论，防止"留出证据达标但门禁仍 FAIL"
        # 的任务被放行为"可用于站点比较"。
        if not gate_available:
            return False, "gate_evidence_unavailable", evidence
        if gate_row is None:
            return False, "gate_row_missing_for_task_horizon", evidence
        evidence["gate_status"] = gate_status
        if gate_status == "FAIL":
            return False, "gate_10pct_uplift_fail", evidence
        if gate_status != "PASS":
            return False, "gate_10pct_uplift_not_evaluable", evidence

        quality = (model_quality or {}).get(model_run_id or "") or {}
        metrics = quality.get("test_metrics") or {}
        test_n = metrics.get("n")
        roc_auc = metrics.get("roc_auc")
        r2 = metrics.get("r2")
        evidence.update({
            "test_n": test_n,
            "roc_auc": roc_auc,
            "r2": r2,
            "min_test_rows": MIN_COMPARISON_TEST_ROWS,
        })
        if not isinstance(test_n, (int, float)) or test_n < MIN_COMPARISON_TEST_ROWS:
            return False, "insufficient_holdout_evidence_for_entity_comparison", evidence
        if isinstance(roc_auc, (int, float)) and roc_auc <= 0.5:
            return False, "holdout_discrimination_not_better_than_chance", evidence
        if isinstance(r2, (int, float)) and r2 <= 0:
            return False, "holdout_r2_not_positive", evidence
        if roc_auc is None and r2 is None:
            return False, "no_holdout_discrimination_metric", evidence
        return True, None, evidence

    def _compute_responsiveness(self, pred_id: str) -> dict[str, Any] | None:
        """实测每个 (时效, 指标) 的模型是否真的对实体产生差异，并给出可比较性结论。

        做法是实测而非猜测：收齐全湖与全部站点的同一 (时效, 指标) 取值后统计离散度。
        只有出现 ≥ 2 个不同取值才说明"数值存在实体差异"；这只是统计事实，
        不代表模型对实体输入有响应，更不代表可用于站点比较——后两者见
        model_entity_response 与 comparison_usable。
        """
        with self._lock:
            if self._published.get("id") != pred_id:
                return None
            lake = {k: v for k, v in (self._published.get("lake") or {}).items()}
            stations = list((self._published.get("stations") or {}).values())
            stations_ready = self._stations_ready

        if not lake:
            return None

        model_quality = self._model_quality_index()
        gate_index = self._gate_rows_index()
        diag: dict[str, Any] = {}
        for horizon_key, lake_record in lake.items():
            horizon_results = lake_record.get("results") or {}
            horizon_diag: dict[str, Any] = {}
            for output_key in horizon_results:
                reference = horizon_results.get(output_key) or {}
                values: list[float] = []
                reference_value = reference.get("value")
                if isinstance(reference_value, (int, float)) and not isinstance(reference_value, bool):
                    values.append(float(reference_value))
                for record in stations:
                    item = ((record.get(horizon_key) or {}).get("results") or {}).get(output_key) or {}
                    value = item.get("value")
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        values.append(float(value))
                if not values:
                    continue
                distinct = {round(v, self.RESPONSIVENESS_ROUND) for v in values}
                within = max(values) - min(values)
                value_origin = reference.get("value_origin")
                model_family = reference.get("model_family")
                model_run_id = reference.get("model_run_id")
                # 该 (任务, 时效) 的 10% 提升门禁行：任务/时效从结果项回读，时效键为字符串。
                try:
                    gate_row = gate_index.get(
                        (reference.get("task_id"), reference.get("variant"), int(horizon_key))
                    )
                except (TypeError, ValueError):
                    gate_row = None
                # ① 纯统计事实：不同实体是否给出不同数值
                numeric_variation = bool(len(distinct) > 1)
                # ② 真实模型是否对实体输入有响应（合成情景回退不算）
                model_entity_response = bool(
                    numeric_variation and value_origin not in SYNTHETIC_ORIGINS
                    and value_origin == "v0_3_real_bundle"
                )
                # ③ 是否允许用于站点间比较（来源 + 门禁 + 留出验证证据）
                comparison_usable, comparison_reason, evidence = self._comparison_usability(
                    value_origin, model_family, model_run_id, numeric_variation,
                    model_quality, gate_row, bool(gate_index),
                )
                gate_status = (gate_row or {}).get("status") if gate_index else None
                horizon_diag[output_key] = {
                    "sampled_entities": len(values),
                    "distinct_values": len(distinct),
                    "min": min(values),
                    "max": max(values),
                    "within_entity_spread": within,
                    # 兼容字段：等价于 numeric_variation（旧前端仍可读）
                    "entity_responsive": numeric_variation,
                    # 三态结论
                    "numeric_variation": numeric_variation,
                    "model_entity_response": model_entity_response,
                    "comparison_usable": comparison_usable,
                    "comparison_blocked_reason": comparison_reason,
                    "constant_value": values[0] if len(distinct) == 1 else None,
                    "model_run_id": model_run_id,
                    "model_family": model_family,
                    "value_origin": value_origin,
                    "gate_status": gate_status,
                    "gate_na_reason": (gate_row or {}).get("na_reason"),
                    "comparison_evidence": evidence,
                    "stations_ready": stations_ready,
                }
            if horizon_diag:
                diag[horizon_key] = horizon_diag
        return diag or None

    def _publish_responsiveness(self, pred_id: str) -> None:
        """把响应性诊断写入已发布快照的 manifest 并落盘（幂等，可重复调用）。"""
        diag = self._compute_responsiveness(pred_id)
        if not diag:
            return
        with self._lock:
            if self._published.get("id") != pred_id:
                return
            manifest = dict(self._published.get("manifest") or {})
            manifest["responsiveness"] = diag
            self._published["manifest"] = manifest
        snapshot_dir = self._snapshot_dir(pred_id)
        if snapshot_dir.is_dir():
            try:
                _write_atomic(snapshot_dir / "manifest.json", _dumps(manifest))
            except Exception as exc:  # noqa: BLE001 — 落盘失败不影响内存服务
                logger.warning("响应性诊断落盘失败（内存服务不受影响）: %s", exc)

    def responsiveness(self) -> dict[str, Any]:
        """当前已发布快照的响应性诊断（可能为空：站点尚未补齐时）。"""
        with self._lock:
            return dict((self._published.get("manifest") or {}).get("responsiveness") or {})

    # ------------------------------------------------------------ 全湖聚合层

    _zone_index_cache: tuple[str, Any] | None = None

    def _zone_index(self) -> dict[str, Any] | None:
        """湖区归属映射（scripts/build_station_zones.py 预生成，公示口径）；缺失时返回 None。"""
        path = Path(__file__).resolve().parent / "data" / "mee_station_zones.json"
        try:
            stamp = str(path.stat().st_mtime_ns)
        except OSError:
            return None
        cached = self._zone_index_cache
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 映射缺失时湖区功能整体降级，不影响主结果
            return None
        self._zone_index_cache = (stamp, payload)
        return payload

    def _ensure_lake_aggregate(self, pred_id: str) -> None:
        """旧缓存（生成于聚合层上线前）的就地补齐：站点齐全但缺聚合层时补算一次。"""
        with self._lock:
            published = self._published
            if published.get("id") != pred_id or not published.get("lake"):
                return
            if published.get("manifest", {}).get("lake_aggregate") is True:
                return
            stations_ready = self._stations_ready
        if not stations_ready:
            return
        self._publish_lake_aggregate(pred_id)
        self._stamp_status_file()
        logger.info("预测快照 %s：全湖聚合层已就地补齐", pred_id)

    @staticmethod
    def _station_quantiles(values: list[float], *, with_p90: bool = False) -> dict[str, Any]:
        """站间分位数（线性插值口径，与 numpy 默认一致；偶数样本中位数取两值均值）。"""
        xs = sorted(values)
        n = len(xs)

        def q(p: float) -> float:
            pos = p * (n - 1)
            low = int(math.floor(pos))
            high = min(low + 1, n - 1)
            frac = pos - low
            return round(xs[low] * (1.0 - frac) + xs[high] * frac, 6)

        out = {
            "n": n,
            "median": q(0.5),
            "p25": q(0.25),
            "p75": q(0.75),
            "min": round(xs[0], 6),
            "max": round(xs[-1], 6),
        }
        if with_p90:
            out["p90"] = q(0.9)
        return out

    def _risk_bands(self) -> dict[str, tuple[float, float]] | None:
        """冻结风险带（risk_bands_ug_l）：全湖风险等级重新判级使用，与站级同源。

        唯一来源是算法交付包 contracts_real.RISK_BANDS_UG_L；包不可用时返回 None，
        全湖判级如实缺省，绝不用前端写死的阈值顶替。
        """
        getter = getattr(self.algorithm, "_runtime_imports", None)
        if not callable(getter):
            return None
        try:
            bands = getter()[6]
        except Exception:  # noqa: BLE001 — 算法包不可用时全湖判级降级缺省
            return None
        return bands if isinstance(bands, dict) and bands else None

    def _lake_risk_level(self, chla_median_ug: float | None) -> dict[str, Any] | None:
        """全湖风险等级 = 冻结风险带作用于全湖叶绿素中位数（不是站点等级平均）。"""
        if chla_median_ug is None:
            return None
        bands = self._risk_bands()
        if not bands:
            return {
                "value": None,
                "reason": "risk_bands_unavailable",
                "note": "算法包冻结风险带不可读，全湖判级缺省；不以站点等级平均或前端阈值顶替。",
            }
        for name, (low, high) in bands.items():
            if low <= chla_median_ug < high:
                return {
                    "value": name,
                    "rule": "冻结风险带 risk_bands_ug_l 作用于 79 站叶绿素 a 中位数",
                    "chla_median_ug_l": chla_median_ug,
                }
        return {
            "value": None,
            "reason": "chla_median_outside_bands",
            "chla_median_ug_l": chla_median_ug,
        }

    def _compute_lake_aggregate(self, pred_id: str) -> dict[str, dict[str, Any]] | None:
        """把全湖汇总从"虚拟站点"改为 79 站预测分布的聚合——这是全湖模式的唯一主结果。

        全湖风险概率/叶绿素 a/生物量/密度 = 站间中位数与四分位（概率另给 P90）；
        水华风险站占比 = 叶绿素 a ≥ 20 μg/L 的站点比例（与栅格场水华边界同阈值）；
        高风险站占比 = 风险概率 ≥ 0.5 的站点比例（与 T1 发生判据同阈值）；
        全湖风险等级 = 冻结风险带作用于全湖叶绿素中位数重新判级（不是站点等级平均）；
        水华面积/空间覆盖率不进本聚合——它们来自遥感反演口径，不从站点预测推导。
        站点尚未补齐时不产出（没有分布就谈不上聚合）。
        """
        with self._lock:
            if self._published.get("id") != pred_id:
                return None
            lake = {k: v for k, v in (self._published.get("lake") or {}).items()}
            stations = list((self._published.get("stations") or {}).values())
            source_snapshot_id = (self._published.get("key") or {}).get("source_snapshot_id")
        if not lake or not stations:
            return None

        out: dict[str, dict[str, Any]] = {}
        zone_index = self._zone_index() or {}
        assignments = zone_index.get("assignments") or {}
        zones_meta = zone_index.get("zones") or {}
        for horizon_key, lake_record in lake.items():
            results = lake_record.get("results") or {}
            metrics: dict[str, Any] = {}
            risk_levels: dict[str, int] = {}
            chla_values_ug: list[float] = []
            probability_values: list[float] = []
            # 湖区分组：chla 按分区中位数；生物量按分区面积加权（公示归一面积）
            zone_chla: dict[str, list[float]] = {}
            zone_biomass: dict[str, list[float]] = {}
            reported = 0
            for record in stations:
                horizon_record = record.get(horizon_key) or {}
                horizon_results = horizon_record.get("results") or {}
                entity_id = horizon_record.get("entity_id") or ""
                zone_code = (assignments.get(entity_id) or {}).get("zone_code")
                if any(
                    isinstance((horizon_results.get(key) or {}).get("value"), (int, float))
                    for key in LAKE_AGGREGATE_METRICS
                ):
                    reported += 1
                for output_key in LAKE_AGGREGATE_METRICS:
                    item = horizon_results.get(output_key) or {}
                    value = item.get("value")
                    if not isinstance(value, (int, float)) or isinstance(value, bool):
                        continue
                    stats = metrics.setdefault(output_key, {"values": [], "value_origin": item.get("value_origin")})
                    stats["values"].append(float(value))
                    if output_key == "probability":
                        probability_values.append(float(value))
                    if zone_code and output_key == "chla":
                        zone_chla.setdefault(zone_code, []).append(float(value))
                    if zone_code and output_key == "biomass":
                        zone_biomass.setdefault(zone_code, []).append(float(value))
                risk_value = (horizon_results.get("risk_level") or {}).get("value")
                if risk_value is not None:
                    key = str(risk_value)
                    risk_levels[key] = risk_levels.get(key, 0) + 1
                chla_item = horizon_results.get("chla") or {}
                chla_value = chla_item.get("value")
                if isinstance(chla_value, (int, float)) and not isinstance(chla_value, bool):
                    unit = str(chla_item.get("unit") or "")
                    factor = 1000.0 if unit in ("mg/L", "mg/l") else 1.0
                    chla_values_ug.append(float(chla_value) * factor)
            if not metrics and not risk_levels:
                continue
            chla_quantiles = self._station_quantiles(chla_values_ug) if chla_values_ug else None
            aggregate: dict[str, Any] = {
                "scope": "lake_aggregate",
                "station_total": len(stations),
                "station_reported": reported,
                "coverage": {"total": len(stations), "reported": reported},
                "prediction_snapshot_id": pred_id,
                "source_snapshot_id": source_snapshot_id,
                "aggregation_method": {
                    "probability": "station_median_p25_p75_p90（79 站预测分布）",
                    "chla": "station_median_p25_p75（79 站预测分布）",
                    "biomass": "station_median_p25_p75 + 分区面积加权均值并列披露",
                    "density": "station_median_p25_p75（79 站预测分布）",
                    "risk_level": "frozen_risk_bands_on_lake_chla_median（按全湖规则重新判级，非站点等级平均）",
                    "excluded": "area/coverage 不从站点预测推导：面积=月度遥感反演边界面积，覆盖率=遥感口径",
                },
                "metrics": {},
                "risk_level_distribution": dict(sorted(risk_levels.items())),
            }
            for output_key, stats in metrics.items():
                values = stats.pop("values")
                aggregate["metrics"][output_key] = {
                    **self._station_quantiles(values, with_p90=(output_key == "probability")),
                    **stats,
                }
            if chla_values_ug:
                num = sum(1 for v in chla_values_ug if v >= CHLA_BLOOM_THRESHOLD_UG_L)
                aggregate["chla_bloom_share"] = {
                    "threshold_ug_l": CHLA_BLOOM_THRESHOLD_UG_L,
                    "num": num,
                    "den": len(chla_values_ug),
                    "share": round(num / len(chla_values_ug), 6),
                }
            if probability_values:
                num = sum(1 for v in probability_values if v >= 0.5)
                aggregate["probability_high_share"] = {
                    "threshold": 0.5,
                    "num": num,
                    "den": len(probability_values),
                    "share": round(num / len(probability_values), 6),
                    "note": "风险概率 ≥ 0.5 的站点比例（与 T1 水华发生判据同阈值）",
                }
            if chla_quantiles:
                aggregate["risk_level_lake"] = self._lake_risk_level(chla_quantiles["median"])
            # 湖区分组（公示归属口径）：分区 chla 中位数 + 生物量分区面积加权均值
            if zone_chla:
                aggregate["zone_breakdown"] = {
                    code: {
                        "zone_name": (zones_meta.get(code) or {}).get("name") or code,
                        "n": len(vals),
                        "chla_median_ug_l": self._station_quantiles(vals)["median"],
                    }
                    for code, vals in sorted(zone_chla.items())
                }
            if zone_biomass and zones_meta:
                total_area = float(zone_index.get("lake_total_km2") or 0) or None
                if total_area:
                    weighted = 0.0
                    weight_used = 0.0
                    for code, vals in zone_biomass.items():
                        area = float((zones_meta.get(code) or {}).get("area_km2_normalized") or 0)
                        if area > 0 and vals:
                            weighted += (sum(vals) / len(vals)) * area
                            weight_used += area
                    if weight_used > 0:
                        aggregate["biomass_area_weighted"] = {
                            "value": round(weighted / weight_used, 6),
                            "unit": "mg/L",
                            "weight_basis": "zone_area_normalized_km2",
                            "zones_used": len(zone_biomass),
                            "note": "按湖区归一面积加权的分区均值（公示面积口径），与未加权站间中位数并列披露",
                        }
            aggregate["note"] = (
                "全湖汇总由站点预测分布聚合（中位数/四分位/风险站占比）；"
                "不是把站点输入取均值后运行站点模型的输出。"
            )
            out[horizon_key] = aggregate
        return out or None

    def _publish_lake_aggregate(self, pred_id: str) -> None:
        agg = self._compute_lake_aggregate(pred_id)
        if not agg:
            return
        with self._lock:
            if self._published.get("id") != pred_id:
                return
            lake = self._published.get("lake") or {}
            for horizon_key, payload in agg.items():
                record = lake.get(horizon_key)
                if isinstance(record, dict):
                    record["station_aggregate"] = payload
            manifest = dict(self._published.get("manifest") or {})
            manifest["lake_aggregate"] = True
            self._published["manifest"] = manifest
            lake_copy = {k: v for k, v in lake.items()}
            manifest_copy = dict(manifest)
        snapshot_dir = self._snapshot_dir(pred_id)
        if snapshot_dir.is_dir():
            try:
                _write_atomic(snapshot_dir / "lake.json", _dumps({"horizons": lake_copy}))
                _write_atomic(snapshot_dir / "manifest.json", _dumps(manifest_copy))
            except Exception as exc:  # noqa: BLE001 — 落盘失败不影响内存服务
                logger.warning("全湖聚合层落盘失败（内存服务不受影响）: %s", exc)

    # -------------------------------------------------- 快照驱动的站点空间场

    def station_field(self, horizon_days: int, metric: str = "risk") -> dict[str, Any] | None:
        """地图站点场：直接来自当前预测快照的站点层，与结果面板同一 prediction_snapshot_id。

        与 legacy /model/spatial-field（V0.2 合成站点场，仅 20 站）不同，本口径：
        * 覆盖分母 = 快照站点层总数（79），逐站给出数值或缺失原因；
        * 数值来自与右侧结果面板完全相同的 (时效, 指标) 记录；
        * 仅 missing verified/metadata_only 坐标的站不画点，但计入"有预测"覆盖并
          在 excluded 中给出原因。
        """
        if not self._serving_is_current():
            return None
        with self._lock:
            published = self._published
            if not published:
                return None
            lake_record = (published.get("lake") or {}).get(str(horizon_days))
            stations = dict(published.get("stations") or {})
            diagnostics = dict((published.get("manifest") or {}).get("responsiveness") or {})
            snapshot_id = published.get("id")
            source_snapshot_id = (published.get("key") or {}).get("source_snapshot_id")
        if not lake_record or not stations:
            return None
        result_key = FOCUS_RESULT_KEY.get(metric)
        if not result_key:
            return None
        focus_item = (lake_record.get("results") or {}).get(result_key) or {}
        value_origin = focus_item.get("value_origin")
        unit = focus_item.get("unit")
        diag = (diagnostics.get(str(horizon_days)) or {}).get(result_key) or {}
        realtime = self._realtime_source()
        points: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        with_prediction = 0
        for entity_id, horizons_map in stations.items():
            record = horizons_map.get(str(horizon_days)) or {}
            item = (record.get("results") or {}).get(result_key) or {}
            value = item.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                excluded.append({"entity_id": entity_id, "reason": "prediction_missing", "detail": "快照站点层缺少该时效/指标结果"})
                continue
            with_prediction += 1
            info: dict[str, Any] = {}
            try:
                info = realtime.station(entity_id) or {}
            except Exception:  # noqa: BLE001 — 站点目录暂不可读时按坐标缺失处理
                info = {}
            location = info.get("location") or {}
            lon, lat = location.get("lon"), location.get("lat")
            plottable = location.get("location_status") in ("verified", "metadata_only") and lon is not None and lat is not None
            if not plottable:
                excluded.append({
                    "entity_id": entity_id,
                    "name": info.get("source_station_name") or entity_id,
                    "reason": "missing_verified_coords",
                    "detail": f"坐标状态 {location.get('location_status') or 'missing'}，不绘制点位",
                })
                continue
            points.append({
                "entity_id": entity_id,
                "name": info.get("source_station_name") or entity_id,
                "lon": lon,
                "lat": lat,
                "value": round(float(value), 6),
                "risk_level": ((record.get("results") or {}).get("risk_level") or {}).get("value"),
            })
        scenario = horizon_days >= 30 or value_origin in SYNTHETIC_ORIGINS
        return {
            "prediction_snapshot_id": snapshot_id,
            "source_snapshot_id": source_snapshot_id,
            "horizon_days": horizon_days,
            "metric": metric,
            "result_key": result_key,
            "unit": unit,
            "value_origin": value_origin,
            "comparison_usable": bool(diag.get("comparison_usable")),
            "comparison_blocked_reason": diag.get("comparison_blocked_reason"),
            "compliance": {"label": "情景推演", "locked": True} if scenario else {"label": "短期预测（月度标签粒度）", "locked": False},
            "points": points,
            "excluded": excluded,
            "coverage": {
                "total": len(stations),
                "with_prediction": with_prediction,
                "plottable": len(points),
            },
            "note": (
                "站点场直接来自预测快照站点层，与结果面板同一 prediction_snapshot_id；"
                "数值随实体相同/不同的如实结论见 comparison_usable，不在地图上修饰。"
            ),
        }

    # ------------------------------------------------------ 全湖驱动因素分布

    def driver_distribution(self, horizon_days: int = 1) -> dict[str, Any] | None:
        """全湖驱动因素 = 79 站机理分解的分布，不是单个虚拟站点的几根条。

        机理分解（温度/光照/磷/氮适合度）是环境状态口径、与模型无关；
        分布按站间中位数/四分位给出，并统计限制因子构成与缺测/代理占比。
        """
        if not self._serving_is_current():
            return None
        with self._lock:
            published = self._published
            if not published:
                return None
            stations = list((published.get("stations") or {}).values())
            snapshot_id = published.get("id")
        if not stations:
            return None
        horizon_key = str(horizon_days)
        zone_index = self._zone_index() or {}
        assignments = zone_index.get("assignments") or {}
        zones_meta = zone_index.get("zones") or {}
        rows: list[dict[str, Any]] = []
        factor_values: dict[str, dict[str, Any]] = {}
        n_drivers = 0
        for record in stations:
            drivers = (record.get(horizon_key) or {}).get("mechanism_drivers")
            if not isinstance(drivers, dict):
                continue
            n_drivers += 1
            horizon_record = record.get(horizon_key) or {}
            chla_item = (horizon_record.get("results") or {}).get("chla") or {}
            chla_value = chla_item.get("value")
            row = {
                "zone_code": (assignments.get(horizon_record.get("entity_id") or "") or {}).get("zone_code"),
                "factors": {},
                "limiting": drivers.get("limiting_factor"),
                "rate": drivers.get("net_growth_rate_d"),
                "chla": float(chla_value)
                if isinstance(chla_value, (int, float)) and not isinstance(chla_value, bool)
                else None,
            }
            for factor in drivers.get("factors") or []:
                key = str(factor.get("key") or "")
                sv = factor.get("source_value")
                if not key:
                    continue
                meta = factor_values.setdefault(
                    key, {"label": factor.get("label") or key, "unit": factor.get("unit"), "values": [], "proxy": 0, "total": 0}
                )
                meta["total"] += 1
                if factor.get("proxy"):
                    meta["proxy"] += 1
                row["factors"][key] = (
                    float(sv) if isinstance(sv, (int, float)) and not isinstance(sv, bool) else None
                )
            rows.append(row)
        if not n_drivers:
            return None

        def _factor_median(sub: list[dict[str, Any]], key: str) -> float | None:
            vals = [r["factors"].get(key) for r in sub]
            vals = [v for v in vals if v is not None]
            return round(self._station_quantiles(vals)["median"], 6) if vals else None

        limiting: dict[str, int] = {}
        growth_rates: list[float] = []
        for row in rows:
            if row["limiting"]:
                limiting[str(row["limiting"])] = limiting.get(str(row["limiting"]), 0) + 1
            if isinstance(row["rate"], (int, float)):
                growth_rates.append(float(row["rate"]))
        factors: list[dict[str, Any]] = []
        for key, meta in factor_values.items():
            values = [r["factors"].get(key) for r in rows]
            values = [v for v in values if v is not None]
            factors.append({
                "key": key,
                "label": meta.get("label") or key,
                "unit": meta.get("unit"),
                **(self._station_quantiles(values) if values else {"n": 0}),
                "proxy_count": meta.get("proxy", 0),
                "total": meta.get("total", 0),
            })
        # 湖区分组：各分区站点数、限制因子主因与营养盐/水温中位数
        zone_groups: dict[str, Any] = {}
        for code in sorted({r["zone_code"] for r in rows if r["zone_code"]}):
            sub = [r for r in rows if r["zone_code"] == code]
            zone_limiting = {}
            for r in sub:
                if r["limiting"]:
                    zone_limiting[str(r["limiting"])] = zone_limiting.get(str(r["limiting"]), 0) + 1
            dominant = max(zone_limiting.items(), key=lambda kv: kv[1])[0] if zone_limiting else None
            zone_groups[code] = {
                "zone_name": (zones_meta.get(code) or {}).get("name") or code,
                "n": len(sub),
                "dominant_limiting_factor": dominant,
                "phosphorus_median": _factor_median(sub, "phosphorus"),
                "nitrogen_median": _factor_median(sub, "nitrogen"),
                "temperature_median": _factor_median(sub, "temperature"),
                "chla_median": self._station_quantiles([r["chla"] for r in sub if r["chla"] is not None])["median"]
                if any(r["chla"] is not None for r in sub)
                else None,
            }
        # 高风险组对比：按该时效 chla 预测值前 25% 分位为高风险组，其余为对照组（哑铃数据）
        high_risk_groups = None
        chla_rows = [r for r in rows if r["chla"] is not None]
        if len(chla_rows) >= 8:
            chla_rows.sort(key=lambda r: r["chla"])
            cut_idx = max(1, int(len(chla_rows) * 0.25))
            high = chla_rows[len(chla_rows) - cut_idx:]
            rest = chla_rows[: len(chla_rows) - cut_idx]
            factor_keys = ["temperature", "light", "phosphorus", "nitrogen", "ammonia"]
            high_risk_groups = {
                "split_rule": "该时效 chla 预测值前 25% 为高风险组",
                "high_n": len(high),
                "rest_n": len(rest),
                "high_chla_median": self._station_quantiles([r["chla"] for r in high])["median"],
                "rest_chla_median": self._station_quantiles([r["chla"] for r in rest])["median"],
                "factors": [
                    {
                        "key": key,
                        "high_median": _factor_median(high, key),
                        "rest_median": _factor_median(rest, key),
                    }
                    for key in factor_keys
                ],
            }
        return {
            "prediction_snapshot_id": snapshot_id,
            "horizon_days": horizon_days,
            "n_stations": n_drivers,
            "factors": factors,
            "limiting_factor_distribution": dict(sorted(limiting.items(), key=lambda kv: -kv[1])),
            "net_growth_rate_d": self._station_quantiles(growth_rates) if growth_rates else None,
            "zone_groups": zone_groups or None,
            "high_risk_groups": high_risk_groups,
            "note": (
                "全湖驱动因素为 79 站机理净生长率分解的分布（环境状态口径，模型无关）；"
                "它不是模型贡献排序——当前模型未通过站点响应验收时不宣称 SHAP。"
                "湖区分组按公示最近质心归属（缺坐标站不参与分组）。"
            ),
        }

    def _persist_stations(self, pred_id: str, *, ready: bool) -> None:
        with self._lock:
            if self._published.get("id") != pred_id:
                return
            stations = dict(self._published.get("stations") or {})
            manifest = dict(self._published.get("manifest") or {})
            manifest["stations"] = {
                "ready": ready,
                "done": self._stations_done,
                "total": self._stations_total,
            }
            self._published["manifest"] = manifest
        snapshot_dir = self._snapshot_dir(pred_id)
        if not snapshot_dir.is_dir():
            return
        try:
            _write_atomic(snapshot_dir / "stations.json", _dumps({"stations": stations}))
            _write_atomic(snapshot_dir / "manifest.json", _dumps(manifest))
        except Exception as exc:  # noqa: BLE001 — 落盘失败不影响内存服务
            logger.warning("站点预测落盘失败（内存服务不受影响）: %s", exc)

    def _stamp_status_file(self) -> None:
        payload = dict(self.status())
        payload["version"] = CACHE_SCHEMA_VERSION
        payload["updated_at"] = _now_iso()
        try:
            _write_atomic(self._status_path(), _dumps(payload))
        except Exception as exc:  # noqa: BLE001
            logger.warning("预测快照 status.json 写入失败: %s", exc)

    # -------------------------------------------------------------- 后台线程

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_forever, name="prediction-snapshot", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _run_forever(self) -> None:
        # 启动后立即对齐一次（磁盘有同版本快照时零推理直接复用）。
        while not self._stop.is_set():
            with self._lock:
                force = self._force_requested
                self._force_requested = False
            try:
                self.ensure_fresh(force=force)
            except Exception as exc:  # noqa: BLE001 — 后台巡检任何异常都不得终止线程
                logger.warning("预测快照巡检异常（下轮重试）: %s", exc)
            self._wake.wait(self.poll_interval_s)
            self._wake.clear()

    def trigger(self) -> None:
        """外部（如手动接口）请求立即对齐一次。"""
        self._wake.set()
