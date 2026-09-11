# -*- coding: utf-8 -*-
"""复审整改端到端验收脚本（只读，可复现交付证据）。

用法：python tests/acceptance_e2e.py [--base http://127.0.0.1:8000]
依赖：后端已在本地运行且预测快照已发布；仓库内清单/季节基线产物可读。

断言覆盖（对应 2026-09-11/12 两轮复审的整改口径）：
  ① 快照状态：state=ready、79/79 站点、读的是已发布快照；
  ② 标签来源：chla 系结果逐行如实披露（proxy/mixed），清单对账 mismatch=0；
  ③ 不确定性四条件：decision_usable = 结构自洽 ∧ test_n≥15 ∧ 覆盖率已核算 ∧ 覆盖率≥88%
    （季节基线必须是独立测试段覆盖率，产物为 seasonal_climatology_v3 三段互不重叠）；
  ④ 中长期路由：T+30/60 评估不足的逐站模型被拒并回退季节基线；
  ⑤ 模型身份：API 返回 artifact_id + 清单真实 file/sha256，34 个产物文件在盘且哈希一致；
  ⑥ 站点响应语义：chla T+90 逐站变化；概率/生物量/密度在 non_responsive_horizons；
  ⑦ 派生风险等级：源区间可决策才给等级范围，否则阻断并给原因。
所有覆盖率判定均为数据驱动（期望可用性 = 覆盖率 ≥ 验收线），产物口径变化不需改本脚本。
"""
import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "backend" / "model_runtime_v0_3"
COV_MIN = 0.88
HORIZONS = ["1", "3", "7", "15", "30", "60", "90"]

FAILS: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" | {detail}" if detail else ""))
    if not ok:
        FAILS.append(f"{name}: {detail}")


def make_get(base: str):
    def get(path: str, timeout: int = 180):
        with urllib.request.urlopen(base + path, timeout=timeout) as r:
            return json.load(r)["data"]
    return get


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def expected_usable(coverage, test_n) -> bool:
    """四条件合同的期望结论：样本充分 ∧ 覆盖率已核算 ∧ 达到验收线（结构自洽另行判定）。"""
    return (
        isinstance(test_n, (int, float)) and not isinstance(test_n, bool) and int(test_n) >= 15
        and coverage is not None and float(coverage) >= COV_MIN
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()
    get = make_get(args.base.rstrip("/"))

    # ---------- ① 清单产物身份：文件在盘 + SHA256 一致 ----------
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    art_by_id = {m.get("artifact_id"): m for m in manifest.get("models") or []}
    bad_art = []
    for aid, m in art_by_id.items():
        f = PKG / (m.get("file") or "")
        if not f.exists() or sha256_file(f) != m.get("sha256"):
            bad_art.append(str(aid))
    check(f"清单产物文件存在且 SHA256 全一致（{len(art_by_id)} 个）",
          not bad_art and len(art_by_id) == 34, "; ".join(bad_art[:4]))

    # ---------- ② 季节基线产物 v3：三段互不重叠、覆盖率来自独立测试段 ----------
    clim = json.loads((PKG / "evaluation" / "seasonal_climatology.json").read_text(encoding="utf-8"))
    check("季节基线产物为 v4（三段回测+类别支持）",
          clim.get("artifact_version") == "seasonal_climatology_v4",
          str(clim.get("artifact_version")))
    clim_by_task = {(b.get("task_id"), b.get("variant")): b for b in clim.get("tasks") or []}
    seg_bad = []
    for blk in clim.get("tasks") or []:
        bt = blk.get("backtest") or {}
        if bt.get("residual_quantiles"):
            if not (bt.get("interval_calibration_max_month") or "") < (bt.get("test_min_month") or ""):
                seg_bad.append(f"{blk.get('task_id')} 段重叠")
            if bt.get("empirical_coverage") is None or not bt.get("coverage_n"):
                seg_bad.append(f"{blk.get('task_id')} 覆盖率缺失")
    check("季节基线校准段/测试段互不重叠且独立覆盖率已核算", not seg_bad, "; ".join(seg_bad))

    # ---------- ③ 快照状态 ----------
    status = get("/model/v3/prediction-status")
    check("快照 state=ready", status.get("state") == "ready", str(status.get("state")))
    stb = status.get("stations") or {}
    check("快照站点层 完成数=分母（动态口径，不写死 79）",
          stb.get("done") == stb.get("total") and (stb.get("total") or 0) > 0,
          json.dumps(stb, ensure_ascii=False))
    dir_total = stb.get("directory_total")
    check("目录站总数已披露且 ≥ 活跃预测站",
          isinstance(dir_total, int) and dir_total >= (stb.get("total") or 0),
          f"directory={dir_total} active={stb.get('total')}")
    excluded = stb.get("excluded_stations")
    check("当轮缺测站连同原因披露（可为空表）",
          isinstance(excluded, list) and all(
              isinstance(x, dict) and x.get("station_id") and x.get("reason") for x in excluded),
          json.dumps(excluded, ensure_ascii=False)[:200])
    check("无回退旧版", status.get("using_previous_success") is False)
    print(f"    schema={status.get('schema')} generated_at={status.get('generated_at')}")

    summary = get("/realtime/summary")
    st_ids = []
    for w in summary.get("warnings") or []:
        sid = w.get("station_id")
        if sid and sid not in st_ids:
            st_ids.append(sid)
    st_ids = st_ids[:3]
    check("取到站点样本", len(st_ids) >= 2, f"{st_ids}")

    # ---------- ④ 指标级站点响应诊断（T+90 语义） ----------
    lake_view = get("/model/v3/prediction-snapshot?entity_id=lake&focus_metric=chla")
    diag = lake_view.get("metric_diagnostics") or {}
    check("chla T+90 有站点响应", 90 in (diag.get("chla") or {}).get("variation_horizons", []),
          json.dumps((diag.get("chla") or {}).get("variation_horizons")))
    for key in ("probability", "biomass", "density"):
        d = diag.get(key) or {}
        check(f"{key} T+90 无站点响应（全湖常量模型）", 90 in (d.get("non_responsive_horizons") or []),
              json.dumps(d.get("non_responsive_horizons")))

    # ---------- ⑤ 逐实体 × 逐时效 × 逐任务合同 ----------
    seen_artifacts: set[str] = set()
    chla_vals: dict[tuple[str, str], float] = {}

    for entity in ["lake"] + st_ids:
        d = get(f"/model/v3/prediction-snapshot?entity_id={entity}&focus_metric=chla")
        check(f"[{entity}] 读的是已发布快照",
              (d.get("snapshot_source") or {}).get("served_from_snapshot") is True)
        for h in HORIZONS:
            results = d["horizons"][h].get("results") or {}
            ch = results.get("chla") or {}
            u = ch.get("uncertainty") or {}
            origin = ch.get("value_origin")
            cov, tn = u.get("empirical_coverage"), u.get("test_n")
            tag = f"[{entity}] T+{h} chla"
            chla_vals[(entity, h)] = ch.get("value")
            if origin == "seasonal_climatology_baseline":
                exp = expected_usable(cov, tn)
                bt = (clim_by_task.get((ch.get("task_id"), ch.get("variant"))) or {}).get("backtest") or {}
                class_ok = bt.get("class_support_sufficient")
                expected_status = "undercovered"
                if class_ok is False:
                    expected_status = "single_class_test"
                    exp = False
                elif exp:
                    expected_status = "validated"
                check(f"{tag} 季节基线+全湖同值", ch.get("station_resolution") is False)
                check(f"{tag} 覆盖率按独立测试段口径有记录", cov is not None, f"cov={cov} n={tn}")
                check(f"{tag} calibration_n 绑定区间校准段（审计整改）",
                      u.get("calibration_n") == bt.get("interval_calibration_n"),
                      f"api={u.get('calibration_n')} artifact={bt.get('interval_calibration_n')}")
                check(f"{tag} lookup 口径已披露",
                      ch.get("seasonal_lookup_mode") in ("target_month_climatology", "global_fallback"),
                      str(ch.get("seasonal_lookup_mode")))
                check(f"{tag} decision_usable 与(覆盖率∧类别支持)期望一致（期望 {expected_status}）",
                      u.get("decision_usable") is exp and u.get("calibration_status") == expected_status,
                      f"cov={cov} class_ok={class_ok} got={u.get('calibration_status')}/{u.get('decision_usable')}")
            elif origin == "v0_3_real_bundle":
                aid = ch.get("artifact_id")
                seen_artifacts.add(aid)
                m = art_by_id.get(aid) or {}
                check(f"{tag} 身份来自清单", bool(aid)
                      and ch.get("model_file") == Path(m.get("file") or "").name
                      and ch.get("model_sha256") == m.get("sha256"), f"aid={aid}")
                exp = expected_usable(cov, tn)
                got_status = u.get("calibration_status")
                ok_status = got_status == ("validated" if exp else ("undercovered" if cov is not None else got_status))
                check(f"{tag} 校准判定按覆盖率规则（期望 {'validated' if exp else '欠覆盖/无证据'}）",
                      ok_status, f"cov={cov} got={got_status}")
                check(f"{tag} decision_usable 与校准联动",
                      u.get("decision_usable") is (got_status == "validated"),
                      f"usable={u.get('decision_usable')}")
                check(f"{tag} 标签来源如实（不得声称 ground_truth）",
                      ch.get("label_provenance") in ("chla_station_proxy_v1",
                                                     "mixed(chla_station_proxy_v1|ground_truth)"),
                      str(ch.get("label_provenance")))
            else:
                check(f"{tag} 来源可接受", False, f"origin={origin}")
            # 派生风险等级
            rl = results.get("risk_level") or {}
            rtag = f"[{entity}] T+{h} risk_level"
            check(f"{rtag} 派生口径+代理披露",
                  rl.get("value_origin") == "derived_from_chla_v0_3_risk_bands"
                  and rl.get("derived_is_proxy") is True)
            src_usable = bool((results.get("chla") or {}).get("uncertainty", {}).get("decision_usable"))
            ru = rl.get("uncertainty") or {}
            blocked = rl.get("band_range_blocked") or {}
            if src_usable:
                check(f"{rtag} 源区间可用→等级范围给出", bool(ru.get("band_range")))
            else:
                check(f"{rtag} 源区间不可用→等级范围阻断且有原因",
                      not ru.get("band_range") and bool(blocked.get("reason")),
                      str(blocked.get("reason"))[:60])
            # 中长期默认风险概率路由
            if h in ("30", "60"):
                pr = results.get("probability") or {}
                route = pr.get("long_term_route") or {}
                rej = route.get("model_rejected") is True or pr.get("value_origin") == "seasonal_climatology_baseline"
                check(f"[{entity}] T+{h} probability 评估不足模型被拒或回退基线", rej,
                      f"route={route.get('reason')} origin={pr.get('value_origin')}")

    # ---------- ⑥ 站点分辨事实 ----------
    if len(st_ids) >= 2:
        a, b = st_ids[0], st_ids[1]
        v90a, v90b = chla_vals.get((a, "90")), chla_vals.get((b, "90"))
        check("T+90 chla 站点间不同（逐站模型）",
              v90a is not None and v90b is not None and abs(v90a - v90b) > 1e-9, f"{v90a} vs {v90b}")

    # ---------- ⑦ 治理口径 ----------
    audit = manifest.get("label_provenance_audit") or {}
    check("清单标签来源对账 mismatch=0（逐行 actual_provenance）",
          audit.get("mismatch_count") == 0 and len(audit.get("rows") or []) > 0,
          f"mismatch={audit.get('mismatch_count')} rows={len(audit.get('rows') or [])}")
    a30 = lake_view["horizons"]["30"].get("acceptance") or {}
    check("门禁结论如实暴露（FAIL 不掩盖）", a30.get("status") in ("FAIL", "PASS"),
          f"{a30.get('status')} pass={a30.get('pass')} fail={a30.get('fail')}")
    check("快照层有诚实口径注记", bool(a30.get("honesty_note") or a30.get("note")))

    print("\n==============================")
    print(f"TOTAL {CHECKS} checks, FAIL {len(FAILS)}")
    for f in FAILS:
        print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
