"""审查探针：V0.3 全矩阵接口扫描（7 时效 × 5 指标 × 实体 + 空间场全参数），找运行时崩溃与逻辑异常。"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app, raise_server_exceptions=False)

HORIZONS = [1, 3, 7, 15, 30, 60, 90]
FOCUS = ["risk", "chla", "area", "biomass", "density"]
problems: list[str] = []
stats = {"ok": 0, "http4xx5xx": 0}


def check(cond: bool, msg: str) -> None:
    if not cond:
        problems.append(msg)


# 找一个真实站点 id
summary = client.get("/api/v1/realtime/summary").json()["data"]
markers = [m for m in summary.get("markers", []) if m.get("id")]
station_id = markers[0]["id"] if markers else None
print(f"[probe] realtime markers={len(markers)} station={station_id}")

start = time.time()
for horizon in HORIZONS:
    for focus in FOCUS:
        for entity in ("lake", station_id):
            if entity is None:
                continue
            t0 = time.time()
            r = client.get(
                "/api/v1/model/v3/predictions",
                params={"horizon_days": horizon, "entity_id": entity, "focus_metric": focus},
            )
            dt = time.time() - t0
            if r.status_code != 200:
                stats["http4xx5xx"] += 1
                problems.append(f"predict {horizon}d/{focus}/{entity} -> HTTP {r.status_code}: {r.text[:160]}")
                continue
            stats["ok"] += 1
            data = r.json()["data"]
            results = data["results"]
            # 结构断言：9 任务齐、value_origin 合法、质量门与 origin 计数一致
            check(len(results) == 9, f"{horizon}d/{focus}/{entity}: results={len(results)} != 9")
            counts = {"real": 0, "derived": 0, "legacy": 0, "na": 0}
            for key, item in results.items():
                origin = item.get("value_origin")
                if item.get("value") is None or item.get("status") == "not_applicable":
                    counts["na"] += 1
                    check(origin is None, f"{horizon}d/{focus}/{entity}/{key}: NA 但 origin={origin}")
                elif origin == "legacy_v0_2_synthetic_fallback":
                    counts["legacy"] += 1
                elif origin == "derived_from_chla_v0_3_risk_bands":
                    counts["derived"] += 1
                elif origin == "v0_3_real_bundle":
                    counts["real"] += 1
                else:
                    problems.append(f"{horizon}d/{focus}/{entity}/{key}: 非法 origin={origin}")
            gate = data["quality_gate"]
            check(
                gate["value_origin_counts"]["real_data_v0_3"] == counts["real"]
                and gate["value_origin_counts"]["legacy_v0_2_synthetic_fallback"] == counts["legacy"]
                and gate["value_origin_counts"]["derived_from_chla"] == counts["derived"]
                and gate["value_origin_counts"]["not_applicable"] == counts["na"],
                f"{horizon}d/{focus}/{entity}: gate counts {gate['value_origin_counts']} != 实测 {counts}",
            )
            focus_key = {"risk": "probability", "chla": "chla", "area": "area", "biomass": "biomass", "density": "density"}[focus]
            focus_item = results[focus_key]
            if counts["na"] == 9:
                check(gate["status"] == "unavailable", f"{horizon}d/{focus}/{entity}: 全空但 gate={gate['status']}")
            elif focus_item.get("value_origin") == "legacy_v0_2_synthetic_fallback":
                check(gate["status"] == "degraded", f"{horizon}d/{focus}/{entity}: 焦点 legacy 但 gate={gate['status']}")
            elif counts["legacy"] > 0:
                check(gate["status"] == "partial", f"{horizon}d/{focus}/{entity}: 混合但 gate={gate['status']}")
            else:
                check(gate["status"] == "ok", f"{horizon}d/{focus}/{entity}: 全真实但 gate={gate['status']}")
            # 风险得分一致性
            prob = results["probability"]
            pv = prob.get("probability") if prob.get("probability") is not None else prob.get("value")
            if pv is not None:
                check(abs(data["risk_score"] - round(float(pv) * 100, 1)) < 1e-6, f"{horizon}d/{entity}: risk_score 不一致")
            # 风险等级与叶绿素一致
            chla_v = results["chla"].get("value")
            rl = results["risk_level"]
            if chla_v is not None and rl.get("value_origin") == "derived_from_chla_v0_3_risk_bands":
                bands = [(0, 10, "none"), (10, 20, "low"), (20, 30, "medium"), (30, 50, "high"), (50, 1e9, "severe")]
                expect = next(name for lo, hi, name in bands if lo <= float(chla_v) < hi)
                check(rl["value"] == expect, f"{horizon}d/{entity}: 等级 {rl['value']} != chla {chla_v} 应为 {expect}")
            if dt > 25:
                print(f"  [slow] {horizon}d/{focus}/{entity}: {dt:.1f}s")

print(f"[probe] predict matrix done in {time.time()-start:.0f}s ok={stats['ok']} bad={stats['http4xx5xx']}")

# 空间场全参数
start = time.time()
for horizon in HORIZONS:
    for metric in ("risk", "chla", "area", "biomass"):
        for layer in ("model", "raster"):
            r = client.get(
                "/api/v1/model/spatial-field",
                params={"horizon_days": horizon, "metric": metric, "layer": layer, "run_id": "PROBE-RUN"},
            )
            if r.status_code != 200:
                problems.append(f"spatial {horizon}d/{metric}/{layer} -> HTTP {r.status_code}: {r.text[:160]}")
                continue
            data = r.json()["data"]
            if layer == "raster" and metric == "chla":
                check(data.get("layer_semantics") == "monthly_reconstruction_base_not_horizon_forecast", f"raster {horizon}d: 缺 layer_semantics")
                check(data.get("prediction_run_id", "").startswith("PROBE-RUN"), f"raster {horizon}d: run_id 未串联")
print(f"[probe] spatial matrix done in {time.time()-start:.0f}s")

# 其余 v3 端点
for path in (
    "/api/v1/model/v3/status",
    "/api/v1/model/v3/acceptance",
    "/api/v1/model/acceptance/detail",
    "/api/v1/model/calibration/coverage",
    "/api/v1/rs/retrieval/validation",
    "/api/v1/acceptance/overview",
    "/api/v1/model/status",
    "/api/v1/model/acceptance",
    "/api/v1/model/retrieval/status",
):
    r = client.get(path)
    check(r.status_code == 200, f"{path} -> HTTP {r.status_code}: {r.text[:160]}")

# 非法输入
check(client.get("/api/v1/model/v3/predictions", params={"horizon_days": 45}).status_code == 422, "非法时效应 422")
check(client.get("/api/v1/model/v3/predictions", params={"horizon_days": 3, "entity_id": "mee-99999"}).status_code == 404, "不存在站点应 404")

print("=== PROBLEMS ===" if problems else "=== ALL CLEAN ===")
for p in problems:
    print(" -", p)
with open("probe_matrix_result.json", "w", encoding="utf-8") as f:
    json.dump({"ok": stats["ok"], "bad": stats["http4xx5xx"], "problems": problems}, f, ensure_ascii=False, indent=2)
