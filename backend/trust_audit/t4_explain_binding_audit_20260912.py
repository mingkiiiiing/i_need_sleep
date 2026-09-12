# -*- coding: utf-8 -*-
"""T4 解释绑定审计（2026-09-12，独立复核算，只读运行产物）。

目的（对应台账 L-vfy-05）：
  1. serving 加载的 34 个模型文件与 manifest/runs 三方对照（sha256/选族/run_id）；
  2. 解释（explainability）与预测是否同 bundle 同 frame——代码调用点证据 + 产物字段证据；
  3. is_shap=false 语义在 API/前端是否一致诚实（文本层核对，不改任何文件）。

产出：同目录 t4_explain_binding_20260912.json。
本脚本不修改任何运行时文件；模型产物与训练代码只读。
"""
from __future__ import annotations

import hashlib
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "model_runtime_v0_3"
CODE = PKG / "code"
OUT = Path(__file__).resolve().parent / "t4_explain_binding_20260912.json"

# joblib 1.5 + NumPy 2.x 已知反序列化告警（serving 侧同款屏蔽，见 backend/app/algorithm_models.py）
warnings.filterwarnings("ignore", message="Setting the shape on a NumPy array has been deprecated.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)

sys.path.insert(0, str(CODE))
from modeling_real.data_real import load_bundle  # noqa: E402


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_dir_of(entry: dict) -> Path:
    """runs 目录名（训练侧命名含时效与月偏移；manifest.run_id 不含时效）。"""
    suffix = "-cv" if entry.get("protocol") == "train_internal_time_block_cv_v1" else ""
    name = f"{entry['task_id']}-{entry['variant']}-{entry['horizon_days']}d-{entry['month_offset']}m{suffix}"
    return PKG / "runs" / name


def main() -> int:
    manifest = json.loads((PKG / "manifest.json").read_text(encoding="utf-8"))
    rows = []
    for entry in manifest.get("models", []):
        rel = entry.get("file", "")
        path = PKG / rel
        row = {
            "artifact_id": entry.get("artifact_id"),
            "task_id": entry.get("task_id"),
            "variant": entry.get("variant"),
            "protocol": entry.get("protocol"),
            "month_offset": entry.get("month_offset"),
            "horizon_days": entry.get("horizon_days"),
            "model_file": rel,
            "file_exists": path.is_file(),
        }
        if path.is_file():
            digest = sha256_file(path)
            row["file_sha256"] = digest
            row["sha256_match_manifest"] = digest == entry.get("sha256")
        run_id = entry.get("run_id", "")
        run_dir = run_dir_of(entry)
        row["run_id"] = run_id
        row["run_dir"] = str(run_dir.relative_to(PKG))
        row["run_dir_exists"] = run_dir.is_dir()
        sel_path = run_dir / "selection_manifest.json"
        if sel_path.is_file():
            try:
                sel = json.loads(sel_path.read_text(encoding="utf-8"))
                chosen = sel.get("selected") or {}
                row["run_selected_family"] = chosen.get("family") or sel.get("selected_family")
                row["run_selected_match_manifest"] = row["run_selected_family"] == entry.get("selected_family")
            except Exception as exc:  # noqa: BLE001
                row["run_selection_read_error"] = str(exc)
        # bundle 层（serving 实际加载的对象）
        if path.is_file():
            try:
                bundle = load_bundle(path)
                row["bundle_run_id"] = getattr(bundle, "run_id", None)
                row["bundle_run_id_match_manifest"] = row["bundle_run_id"] == run_id
                row["bundle_selected_family"] = getattr(bundle, "selected_family", None)
                row["bundle_family_match_manifest"] = row["bundle_selected_family"] == entry.get("selected_family")
                row["bundle_has_preprocessor"] = getattr(bundle, "preprocessor", None) is not None
                row["bundle_n_feature_columns"] = len(getattr(bundle, "feature_columns", ()) or ())
                iv = getattr(bundle, "intervals", None)
                row["bundle_has_intervals"] = iv is not None
                if iv is not None:
                    row["bundle_interval_method"] = getattr(iv, "method", None)
                um = getattr(bundle, "uncertainty_meta", None) or {}
                row["bundle_uncertainty_method"] = um.get("method")
                row["bundle_test_metrics_n"] = (getattr(bundle, "test_metrics", None) or {}).get("n")
            except Exception as exc:  # noqa: BLE001
                row["bundle_load_error"] = repr(exc)
        # 解释绑定（serving 代码路径，静态证据）
        #   backend/app/algorithm_models.py: predict_suite/predict_suite_batch 内
        #   同一 bundle 实例既产生点预测(_build_uncertainty)也产生解释(_explain)，
        #   且解释缓存键=(output_key, entity_id, month_offset, horizon_days)，
        #   快照世代翻转即清缓存（_cache_epoch/_explain_cache.clear）。
        row["explain_method_declared"] = "local_one_at_a_time_sensitivity"
        row["explain_is_shap_declared"] = False
        rows.append(row)

    # ---- 语义一致性文本核对（is_shap 恒 False；无 SHAP 冒充表述） ----
    am_text = (ROOT / "app" / "algorithm_models.py").read_text(encoding="utf-8")
    semantic = {
        "is_shap_occurrences": [i + 1 for i, line in enumerate(am_text.splitlines()) if '"is_shap"' in line],
        "is_shap_all_false": all(
            '"is_shap": False' in line
            for line in am_text.splitlines()
            if '"is_shap"' in line
        ),
        "shap_word_occurrences": [
            i + 1
            for i, line in enumerate(am_text.splitlines())
            if "SHAP" in line or "shap" in line
        ],
        "note": "is_shap 两处赋值均为 False；SHAP 仅出现在否定语义注释/说明中（不是 SHAP、无背景数据）。",
    }
    # 前端文本层核对（只读）
    src = ROOT.parent / "src"
    fe_hits = {}
    if src.is_dir():
        for pat in ("*.vue", "*.js", "*.ts"):
            for p in src.rglob(pat):
                try:
                    t = p.read_text(encoding="utf-8")
                except Exception:  # noqa: BLE001
                    continue
                for i, line in enumerate(t.splitlines()):
                    if "shap" in line.lower():
                        fe_hits.setdefault(str(p.relative_to(ROOT.parent)), []).append(i + 1)
    semantic["frontend_shap_mentions"] = fe_hits

    payload = {
        "audit": "T4 解释绑定审计（模型—解释对应表）",
        "date": "2026-09-12",
        "manifest_file": str(PKG / "manifest.json"),
        "manifest_sha256": sha256_file(PKG / "manifest.json"),
        "model_count": len(rows),
        "models": rows,
        "semantic_check": semantic,
        "explain_binding_code_evidence": [
            "backend/app/algorithm_models.py: _explain_and_quantify (v0.2 层) docstring 明示 not labelled SHAP",
            "backend/app/algorithm_models.py: _explain (v0.3 层) 返回 is_shap=False + method=local_one_at_a_time_sensitivity",
            "backend/app/algorithm_models.py predict_suite/predict_suite_batch: 同一 bundle 实例与同一 frame 同时用于点预测、区间(_build_uncertainty)与解释(_explain/_explain_cache)",
            "backend/app/prediction_snapshot.py assemble/_cached_explainability: 解释只读缓存键=(result_key, entity_id, month_offset, horizon_days)，命中才附回，未命中不展示",
            "backend/app/services.py algorithm_predictions_v3: 无 cache-miss→live-inference 路径（409 PREDICTION_SNAPSHOT_NOT_READY）",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {OUT}")
    print("models:", len(rows))
    print("is_shap_all_false:", semantic["is_shap_all_false"])
    mism = [r["artifact_id"] for r in rows if r.get("sha256_match_manifest") is False]
    print("sha mismatch:", mism or "none")
    fam_mism = [r["artifact_id"] for r in rows if r.get("bundle_family_match_manifest") is False]
    print("family mismatch:", fam_mism or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
