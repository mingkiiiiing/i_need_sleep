"""audit7 实机验证：对真实 uvicorn 服务逐个请求全部保留接口。

用法：先启动服务（uvicorn backend.main:app --port 8617），再运行本脚本。
结果写入 reports/audit7/live-api-verification.json；任何断言失败退出码非零。
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8617"
OUT = Path(__file__).resolve().parent / "live-api-verification.json"

META_KEYS = {"data_mode", "dataset_version", "prediction_run_id", "as_of", "claim_boundary", "request_id"}
GRID_ROWS, GRID_COLUMNS = 11, 19
STAGES = ("t1", "t3", "t7", "t15", "t30")
ZONE_IDS = [
    "northwest_hotspot", "central_lake", "river_inlet",
    "southeast_station", "water_intake", "south_channel",
]


def expect_ok(body: dict, *, dataset_version: str, run: bool = False) -> list[str]:
    problems = []
    if body.get("code") != 200 or body.get("message") != "ok":
        problems.append(f"envelope code/message 异常: {body.get('code')}/{body.get('message')}")
    meta = body.get("meta") or {}
    if set(meta.keys()) != META_KEYS:
        problems.append(f"meta 键不等于 6 键契约: {sorted(meta.keys())}")
    if meta.get("data_mode") != "simulated":
        problems.append(f"data_mode={meta.get('data_mode')!r}")
    if meta.get("claim_boundary") != "simulation_only":
        problems.append(f"claim_boundary={meta.get('claim_boundary')!r}")
    if meta.get("dataset_version") != dataset_version:
        problems.append(f"dataset_version={meta.get('dataset_version')!r} 期望 {dataset_version}")
    if meta.get("as_of") != "2026-08-24T08:00:00+08:00":
        problems.append(f"as_of={meta.get('as_of')!r}")
    if run and meta.get("prediction_run_id") != "DEMO-RUN-V1":
        problems.append(f"prediction_run_id={meta.get('prediction_run_id')!r} 期望 DEMO-RUN-V1")
    if not run and meta.get("prediction_run_id") is not None:
        problems.append(f"非预测响应 prediction_run_id={meta.get('prediction_run_id')!r} 期望 null")
    if body.get("errors") != []:
        problems.append(f"errors={body.get('errors')!r}")
    return problems


def expect_error(body: dict, *, status: int, code: str, dataset_version: str) -> list[str]:
    problems = []
    if body.get("code") != status:
        problems.append(f"code={body.get('code')} 期望 {status}")
    if body.get("data") is not None:
        problems.append("错误响应 data 非 null")
    errors = body.get("errors") or []
    if not errors or errors[0].get("code") != code:
        problems.append(f"errors[0].code={(errors or [{}])[0].get('code')!r} 期望 {code!r}")
    meta = body.get("meta") or {}
    if set(meta.keys()) != META_KEYS:
        problems.append(f"meta 键不等于 6 键契约: {sorted(meta.keys())}")
    if meta.get("data_mode") != "simulated" or meta.get("claim_boundary") != "simulation_only":
        problems.append("错误响应 meta 缺少 data_mode/claim_boundary")
    if meta.get("dataset_version") != dataset_version:
        problems.append(f"dataset_version={meta.get('dataset_version')!r} 期望 {dataset_version}")
    if meta.get("prediction_run_id") is not None:
        problems.append(f"错误响应 prediction_run_id={meta.get('prediction_run_id')!r} 期望 null")
    if meta.get("as_of") != "2026-08-24T08:00:00+08:00":
        problems.append(f"as_of={meta.get('as_of')!r}")
    if not meta.get("request_id"):
        problems.append("错误响应未保留 request_id")
    return problems


def check_grid(grid: dict, horizon_days: int) -> list[str]:
    problems = []
    if grid.get("rows") != GRID_ROWS or grid.get("columns") != GRID_COLUMNS:
        problems.append(f"rows/columns={grid.get('rows')}/{grid.get('columns')} 期望 11/19")
    if grid.get("horizon_days") != horizon_days:
        problems.append(f"horizon_days={grid.get('horizon_days')} 请求 {horizon_days}")
    if grid.get("prediction_run_id") != "DEMO-RUN-V1":
        problems.append(f"prediction_run_id={grid.get('prediction_run_id')!r}")
    if grid.get("dataset_version") != "DEMO-PRED-V1":
        problems.append(f"dataset_version={grid.get('dataset_version')!r}")
    values = grid.get("grid") or []
    if len(values) != GRID_ROWS or any(len(r) != GRID_COLUMNS for r in values):
        problems.append("grid 不是 11×19")
        return problems
    for r in values:
        for v in r:
            if not (isinstance(v, int) and 0 <= v <= 100):
                problems.append(f"格值 {v!r} 不是 0-100 整数")
                return problems
    thresholds = grid.get("thresholds") or {}
    if thresholds != {"low": [0, 44], "mid": [45, 74], "high": [75, 100]}:
        problems.append(f"thresholds={thresholds!r}")
    return problems


# ---- 用例表：(名称, 方法, 路径, 校验函数) ----
def case(name, method, path, verify):
    return {"name": name, "method": method, "path": path, "verify": verify}


def build_cases() -> list[dict]:
    cases = [
        case("health", "GET", "/api/health", lambda b: expect_ok(b, dataset_version="DEMO-OBS-V1")),
        case("root", "GET", "/", lambda b: expect_ok(b, dataset_version="DEMO-OBS-V1")),
        case("capabilities", "GET", "/api/v1/system/capabilities", lambda b: expect_ok(b, dataset_version="DEMO-OBS-V1")),
        case("datasets-summary", "GET", "/api/v1/datasets/summary", lambda b: expect_ok(b, dataset_version="DEMO-OBS-V1")),
        case("pipeline-latest", "GET", "/api/v1/pipeline/runs/latest", lambda b: expect_ok(b, dataset_version="DEMO-OBS-V1")),
        case("overview", "GET", "/api/v1/dashboard/overview", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("spatial-entities", "GET", "/api/v1/spatial-entities", lambda b: expect_ok(b, dataset_version="DEMO-OBS-V1")),
        case("spatial-entity-detail", "GET", "/api/v1/spatial-entities/northwest_hotspot", lambda b: expect_ok(b, dataset_version="DEMO-OBS-V1")),
        case("observations", "GET", "/api/v1/spatial-entities/northwest_hotspot/observations", lambda b: expect_ok(b, dataset_version="DEMO-OBS-V1")),
        case("observations-proxy", "GET", "/api/v1/spatial-entities/northwest_hotspot/observations?variable_code=air_temperature", None),
        case("quality", "GET", "/api/v1/spatial-entities/northwest_hotspot/quality", lambda b: expect_ok(b, dataset_version="DEMO-OBS-V1")),
        case("forecast-capabilities", "GET", "/api/v1/forecast-capabilities", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("forecasts-h1", "GET", "/api/v1/forecasts?spatial_entity_id=northwest_hotspot&horizon_days=1", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("forecasts-h3", "GET", "/api/v1/forecasts?spatial_entity_id=central_lake&horizon_days=3", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("forecasts-h7", "GET", "/api/v1/forecasts?spatial_entity_id=river_inlet&horizon_days=7", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("forecasts-h15", "GET", "/api/v1/forecasts?spatial_entity_id=southeast_station&horizon_days=15", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("forecast-detail", "GET", "/api/v1/forecasts/demo-forecast-water_intake-3d", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("explanation", "GET", "/api/v1/forecasts/demo-forecast-water_intake-3d/explanations", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("map-layers", "GET", "/api/v1/map/layers", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("events", "GET", "/api/v1/events", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("cockpit-time-stages", "GET", "/api/v1/cockpit/time-stages", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("cockpit-points", "GET", "/api/v1/cockpit/points", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("cockpit-point-detail", "GET", "/api/v1/cockpit/points/northwest_hotspot", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("cockpit-risk-heatmap", "GET", "/api/v1/cockpit/risk-heatmap", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("cockpit-events", "GET", "/api/v1/cockpit/events", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("cockpit-region-summary", "GET", "/api/v1/cockpit/region-summary", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("timeline-valid", "GET", "/api/v1/cockpit/timeline?start=2026-08-20&end=2026-08-22", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("timeline-90d-boundary", "GET", "/api/v1/cockpit/timeline?start=2026-06-02&end=2026-08-31", lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True)),
        case("handle-warning-event", "POST", "/api/v1/cockpit/handle-warning", None),
        case("handle-warning-zone", "POST", "/api/v1/cockpit/handle-warning", None),
        case("handle-warning-cell", "POST", "/api/v1/cockpit/handle-warning", None),
    ]
    for h in (1, 3, 7, 15, 30):
        cases.append(
            case(f"risk-grid-h{h}", "GET", f"/api/v1/map/risk-grid?horizon_days={h}",
                 (lambda hh: (lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True) + check_grid(b["data"], hh)))(h))
        )
        cases.append(
            case(f"risk-polygons-h{h}", "GET", f"/api/v1/map/risk-polygons?horizon_days={h}",
                 (lambda hh: (lambda b: expect_ok(b, dataset_version="DEMO-PRED-V1", run=True) + _polygons(b, hh)))(h))
        )
    # ---- 错误路径（dataset_version 按接口类别：观察类=DEMO-OBS-V1，预测类=DEMO-PRED-V1） ----
    OBS, PRED = "DEMO-OBS-V1", "DEMO-PRED-V1"
    cases += [
        case("err-entity-404", "GET", "/api/v1/spatial-entities/no_such_zone", lambda b: expect_error(b, status=404, code="ENTITY_NOT_FOUND", dataset_version=OBS)),
        case("err-entity-obs-404", "GET", "/api/v1/spatial-entities/no_such_zone/observations", lambda b: expect_error(b, status=404, code="ENTITY_NOT_FOUND", dataset_version=OBS)),
        case("err-mode-observed", "GET", "/api/v1/spatial-entities?mode=observed", lambda b: expect_error(b, status=409, code="SIMULATION_ONLY", dataset_version=OBS)),
        case("err-mode-bogus", "GET", "/api/v1/spatial-entities?mode=bogus", lambda b: expect_error(b, status=422, code="REQUEST_VALIDATION_FAILED", dataset_version=OBS)),
        case("err-forecast-404", "GET", "/api/v1/forecasts/demo-forecast-no_such_zone-3d", lambda b: expect_error(b, status=404, code="ENTITY_NOT_FOUND", dataset_version=PRED)),
        case("err-explanation-404", "GET", "/api/v1/forecasts/demo-forecast-no_such_zone-3d/explanations", lambda b: expect_error(b, status=404, code="ENTITY_NOT_FOUND", dataset_version=PRED)),
        case("err-horizon-0", "GET", "/api/v1/forecasts?spatial_entity_id=northwest_hotspot&horizon_days=0", lambda b: expect_error(b, status=422, code="INVALID_HORIZON", dataset_version=PRED)),
        case("err-horizon-2", "GET", "/api/v1/map/risk-grid?horizon_days=2", lambda b: expect_error(b, status=422, code="INVALID_HORIZON", dataset_version=PRED)),
        case("err-horizon-31", "GET", "/api/v1/map/risk-grid?horizon_days=31", lambda b: expect_error(b, status=422, code="INVALID_HORIZON", dataset_version=PRED)),
        case("err-t30-forecast-409", "GET", "/api/v1/forecasts?spatial_entity_id=northwest_hotspot&horizon_days=30", lambda b: expect_error(b, status=409, code="CAPABILITY_UNAVAILABLE", dataset_version=PRED)),
        case("err-t30-record-409", "GET", "/api/v1/forecasts/demo-forecast-northwest_hotspot-30d", lambda b: expect_error(b, status=409, code="CAPABILITY_UNAVAILABLE", dataset_version=PRED)),
        case("err-t30-explain-404", "GET", "/api/v1/forecasts/demo-forecast-northwest_hotspot-30d/explanations", lambda b: expect_error(b, status=404, code="ENTITY_NOT_FOUND", dataset_version=PRED)),
        case("err-timeline-reversed", "GET", "/api/v1/cockpit/timeline?start=2026-08-22&end=2026-08-20", lambda b: expect_error(b, status=422, code="INVALID_DATE_RANGE", dataset_version=PRED)),
        case("err-timeline-91d", "GET", "/api/v1/cockpit/timeline?start=2026-06-01&end=2026-08-31", lambda b: expect_error(b, status=422, code="QUERY_RANGE_TOO_LARGE", dataset_version=PRED)),
        case("err-timeline-malformed", "GET", "/api/v1/cockpit/timeline?start=not-a-date&end=2026-08-20", lambda b: expect_error(b, status=422, code="REQUEST_VALIDATION_FAILED", dataset_version=PRED)),
        case("err-mode-historical", "GET", "/api/v1/dashboard/overview?mode=historical", lambda b: expect_error(b, status=409, code="SIMULATION_ONLY", dataset_version=PRED)),
        case("err-warning-invalid", "POST", "/api/v1/cockpit/handle-warning", lambda b: expect_error(b, status=422, code="INVALID_EVENT_ID", dataset_version=PRED)),
        case("err-warning-missing-body", "POST", "/api/v1/cockpit/handle-warning", lambda b: expect_error(b, status=422, code="REQUEST_VALIDATION_FAILED", dataset_version=PRED)),
    ]
    return cases


def _polygons(body: dict, horizon_days: int) -> list[str]:
    data = body["data"]
    problems = []
    if data.get("type") != "FeatureCollection" or data.get("features") != []:
        problems.append("risk-polygons 不是空 FeatureCollection")
    if not data.get("empty_reason"):
        problems.append("缺少 empty_reason")
    if data.get("horizon_days") != horizon_days:
        problems.append(f"horizon_days={data.get('horizon_days')}")
    return problems


def extra_payload(case_name: str) -> dict | None:
    if case_name == "handle-warning-event":
        return {"event_id": "demo-event-1"}
    if case_name == "handle-warning-zone":
        return {"event_id": "northwest_hotspot"}
    if case_name == "handle-warning-cell":
        return {"event_id": "R07-C10"}
    if case_name == "err-warning-invalid":
        return {"event_id": "demo-event-999"}
    if case_name == "err-warning-missing-body":
        return {}
    return None


def check_proxy(body: dict) -> list[str]:
    problems = expect_ok(body, dataset_version="DEMO-OBS-V1")
    rows = body["data"]
    if not rows:
        problems.append("air_temperature 观测为空")
    for row in rows:
        if row.get("variable_code") == "air_temperature" and row.get("proxy_flag") is not True:
            problems.append(f"气温代理行缺少 proxy_flag=true: {row}")
        if row.get("value_origin") != "simulated":
            problems.append(f"value_origin={row.get('value_origin')!r}")
    return problems


def check_warning(body: dict) -> list[str]:
    problems = expect_ok(body, dataset_version="DEMO-PRED-V1", run=True)
    data = body["data"]
    if data.get("status") != "simulated_dispatched":
        problems.append(f"status={data.get('status')!r}")
    if data.get("persisted") is not False:
        problems.append(f"persisted={data.get('persisted')!r}")
    if data.get("channels") != ["platform_simulation"]:
        problems.append(f"channels={data.get('channels')!r}")
    return problems


def verify_deeper(name: str, body: dict) -> list[str]:
    """非 JSON 路径的专用深校验。"""
    if name == "observations-proxy":
        return check_proxy(body)
    if name.startswith("handle-warning") and not name.startswith("handle-warning-err") and "err" not in name:
        return check_warning(body)
    return []


def deep_success_checks(name: str, body: dict) -> list[str]:
    problems = []
    data = body.get("data")
    if name == "capabilities":
        caps = data.get("capabilities") or {}
        for key, want in (
            ("historical_observation", "dataset_available_backend_pending"),
            ("short_term_forecast_1_3d", "dataset_ready_model_pending"),
            ("medium_term_forecast_7_15d", "dataset_ready_model_pending"),
            ("long_term_forecast_30_90d", "blocked_auth"),
            ("real_time_warning_dispatch", "not_enabled"),
            ("demo_warning_dispatch", "available"),
        ):
            if caps.get(key) != want:
                problems.append(f"capabilities[{key}]={caps.get(key)!r} 期望 {want!r}")
        if data.get("provider_status") != {"observation_provider": "simulated", "prediction_provider": "simulated"}:
            problems.append(f"provider_status={data.get('provider_status')!r}")
    elif name == "spatial-entities":
        ids = [item.get("id") for item in data]
        if sorted(ids) != sorted(ZONE_IDS):
            problems.append(f"分区集合不符: {ids}")
        for item in data:
            if item.get("entity_type") != "demo_zone":
                problems.append(f"{item.get('id')} entity_type={item.get('entity_type')!r}")
    elif name == "spatial-entity-detail" and data:
        if data.get("entity_type") != "demo_zone":
            problems.append("detail entity_type != demo_zone")
    elif name == "cockpit-points" and data:
        pd = data.get("pointData") or {}
        if len(pd) != 6:
            problems.append(f"pointData 数量 {len(pd)} != 6")
        for point in (pd.values() if isinstance(pd, dict) else pd):
            if point.get("riskClass") not in ("low", "mid", "high"):
                problems.append(f"point riskClass={point.get('riskClass')!r}")
        positions = data.get("pointPositions") or {}
        if len(positions) != 6:
            problems.append(f"pointPositions 数量 {len(positions)} != 6")
    elif name == "cockpit-risk-heatmap" and data:
        for key in STAGES:
            matrix = data.get(key)
            ok_shape = (
                isinstance(matrix, list)
                and len(matrix) == GRID_ROWS
                and all(isinstance(r, list) and len(r) == GRID_COLUMNS for r in matrix)
            )
            if not ok_shape:
                problems.append(f"heat 场 {key} 缺失或不是 11×19 矩阵")
        if "_scenario" not in data:
            problems.append("缺少 _scenario 兼容键")
    elif name == "cockpit-region-summary" and data:
        if data.get("totalStations") != 6:
            problems.append(f"totalStations={data.get('totalStations')!r}")
        if set((data.get("riskCounts") or {}).keys()) != {"high", "mid", "low"}:
            problems.append(f"riskCounts={data.get('riskCounts')!r}")
    elif name == "cockpit-time-stages" and data:
        keys = [item.get("key") for item in data]
        if keys != list(STAGES):
            problems.append(f"stage keys={keys}")
    elif name == "events" and data:
        if not data:
            problems.append("events 为空")
        for ev in data:
            for key in ("id", "data_mode", "dataset_version", "spatial_entity_id"):
                if key not in ev:
                    problems.append(f"事件缺字段 {key}")
            if ev.get("data_mode") != "simulated":
                problems.append(f"事件 {ev.get('id')} data_mode 异常")
    elif name == "cockpit-events" and data:
        for ev in data:
            for key in ("id", "time", "stageKey", "point", "data_mode"):
                if key not in ev:
                    problems.append(f"兼容事件缺字段 {key}")
    elif name == "timeline-valid" and data:
        rows = data.get("data") or []
        if not rows:
            problems.append("timeline 行为空")
        for row in rows:
            if row.get("risk_level") not in ("low", "mid", "high"):
                problems.append(f"timeline risk_level={row.get('risk_level')!r}")
            if "chlorophyll" in str(row.keys()).lower() or "叶绿素" in str(row):
                problems.append("timeline 携带叶绿素声称")
    elif name.startswith("risk-grid"):
        pass  # 已在 case 内校验
    return problems


CONCURRENCY_GROUP = {f"conc-grid-{h}": h for h in (1, 3, 7, 15, 30)}


def main() -> int:
    results = []
    failed = 0
    with httpx.Client(base_url=BASE, timeout=15) as client:
        # P07 并发不污染：五档位并行请求，各自校验 horizon 一致
        def fetch_conc(h: int):
            r = client.get(f"/api/v1/map/risk-grid?horizon_days={h}")
            body = r.json()
            return {
                "name": f"conc-grid-h{h}",
                "method": "GET",
                "url": f"/api/v1/map/risk-grid?horizon_days={h}",
                "expected_status": 200,
                "actual_status": r.status_code,
                "request_id": body.get("meta", {}).get("request_id"),
                "problems": (expect_ok(body, dataset_version="DEMO-PRED-V1", run=True) + check_grid(body["data"], h)) if r.status_code == 200 else [f"status={r.status_code}"],
            }

        with ThreadPoolExecutor(max_workers=5) as pool:
            conc = list(pool.map(fetch_conc, [1, 3, 7, 15, 30]))
        results.extend(conc)

        for c in build_cases():
            url = c["path"]
            payload = extra_payload(c["name"])
            if c["method"] == "POST":
                resp = client.post(url, json=payload)
            else:
                resp = client.get(url)
            entry = {
                "name": c["name"],
                "method": c["method"],
                "url": url,
                "expected_status": 200 if c["name"] not in {x["name"] for x in build_cases() if x["name"].startswith("err-")} else 4,
                "actual_status": resp.status_code,
            }
            try:
                body = resp.json()
            except Exception:
                entry["problems"] = [f"响应不是 JSON: {resp.text[:120]}"]
                results.append(entry)
                failed += 1
                continue
            entry["request_id"] = (body.get("meta") or {}).get("request_id")
            entry["meta_dataset_version"] = (body.get("meta") or {}).get("dataset_version")
            entry["meta_prediction_run_id"] = (body.get("meta") or {}).get("prediction_run_id")
            if c["name"].startswith("err-"):
                entry["expected_status"] = {"err-entity-404": 404, "err-entity-obs-404": 404, "err-mode-observed": 409,
                                            "err-mode-bogus": 422, "err-forecast-404": 404, "err-explanation-404": 404,
                                            "err-horizon-0": 422, "err-horizon-2": 422,
                                            "err-horizon-31": 422, "err-t30-forecast-409": 409, "err-t30-record-409": 409,
                                            "err-t30-explain-404": 404, "err-timeline-reversed": 422, "err-timeline-91d": 422,
                                            "err-timeline-malformed": 422, "err-mode-historical": 409,
                                            "err-warning-invalid": 422, "err-warning-missing-body": 422}[c["name"]]
                problems = c["verify"](body)
                entry["error_code"] = ((body.get("errors") or [{}])[0].get("code"))
            elif c["name"] in ("handle-warning-event", "handle-warning-zone", "handle-warning-cell"):
                entry["expected_status"] = 200
                problems = check_warning(body)
            elif c["name"] == "observations-proxy":
                entry["expected_status"] = 200
                problems = check_proxy(body)
            else:
                entry["expected_status"] = 200
                problems = c["verify"](body) if c["verify"] else []
                problems += deep_success_checks(c["name"], body)
            entry["problems"] = problems
            if problems:
                failed += 1
            results.append(entry)

    request_ids = [r["request_id"] for r in results if r.get("request_id")]
    unique_ids = len(set(request_ids)) == len(request_ids)
    summary = {
        "base_url": BASE,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(results),
        "failed_cases": failed,
        "request_ids_unique": unique_ids,
        "server": "uvicorn backend.main:app (真实 HTTP 进程，非 TestClient)",
    }
    out = {"summary": summary, "results": results}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    for r in results:
        if r.get("problems"):
            print(f"FAIL {r['name']} status={r['actual_status']} problems={r['problems']}")
    return 1 if failed or not unique_ids else 0


if __name__ == "__main__":
    sys.exit(main())
