# Member C Mechanism-AI Modeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable member C algorithm framework for mechanism-AI fusion modeling before final team data arrives.

**Architecture:** Create an isolated milestone directory with focused Python modules for mechanism scoring, AI baselines, fusion, evaluation, explainability, and prediction output. Use tests first and sample data to prove interfaces while explicitly blocking real effect claims.

**Tech Stack:** Python standard library, `unittest`, CSV/JSON outputs.

**Spec:** `里程碑7_成员C机理AI融合建模/05_文档/2026-08-20-member-c-modeling-design.md`

## Global Constraints

- Do not claim real model accuracy before aligned real labels and features are available.
- Use simulation/sample data only for interface verification.
- Keep outputs compatible with backend JSON calls.
- Keep this milestone isolated from milestones 1-6.
- Use TDD: tests must fail before implementation.

---

### Task 1: Core Mechanism Model

**Files:**
- Create: `里程碑7_成员C机理AI融合建模/03_测试/tests/test_mechanism.py`
- Create: `里程碑7_成员C机理AI融合建模/02_代码/blue_algae_m7/mechanism.py`

**Interfaces:**
- Produces: `monod_limit(value, half_saturation) -> float`
- Produces: `temperature_limit(temp_c, optimum_c=28.0, width_c=12.0) -> float`
- Produces: `mechanism_risk_index(sample: dict) -> dict`

- [ ] Write failing tests for Monod limit, temperature response, and risk index.
- [ ] Run tests and verify missing module/function failures.
- [ ] Implement minimal mechanism functions.
- [ ] Run tests and verify pass.

### Task 2: AI Baseline Interfaces

**Files:**
- Create: `里程碑7_成员C机理AI融合建模/03_测试/tests/test_ai_models.py`
- Create: `里程碑7_成员C机理AI融合建模/02_代码/blue_algae_m7/ai_models.py`

**Interfaces:**
- Produces: `MeanRegressor.fit(rows, target_key) -> MeanRegressor`
- Produces: `WeightedRuleRegressor.fit(rows, target_key) -> WeightedRuleRegressor`
- Produces: `predict_one(row) -> float`

- [ ] Write failing tests for two trainable model interfaces.
- [ ] Run tests and verify missing module/function failures.
- [ ] Implement minimal deterministic model classes.
- [ ] Run tests and verify pass.

### Task 3: Fusion, Evaluation, Explainability

**Files:**
- Create: `里程碑7_成员C机理AI融合建模/03_测试/tests/test_fusion_evaluation.py`
- Create: `里程碑7_成员C机理AI融合建模/02_代码/blue_algae_m7/fusion.py`
- Create: `里程碑7_成员C机理AI融合建模/02_代码/blue_algae_m7/evaluation.py`
- Create: `里程碑7_成员C机理AI融合建模/02_代码/blue_algae_m7/explainability.py`

**Interfaces:**
- Produces: `cascade_fusion(mechanism_score, ai_score, mechanism_weight=0.4) -> float`
- Produces: `residual_fusion(mechanism_score, residual_score) -> float`
- Produces: `regression_metrics(y_true, y_pred) -> dict`
- Produces: `feature_importance_by_correlation(rows, feature_keys, target_key) -> list[dict]`
- Produces: `uncertainty_interval(predictions, confidence=0.8) -> dict`

- [ ] Write failing tests for fusion bounds, metrics, importance, and interval output.
- [ ] Run tests and verify missing module/function failures.
- [ ] Implement minimal deterministic functions.
- [ ] Run tests and verify pass.

### Task 4: Unified Predictor and Artifacts

**Files:**
- Create: `里程碑7_成员C机理AI融合建模/03_测试/tests/test_predictor.py`
- Create: `里程碑7_成员C机理AI融合建模/02_代码/blue_algae_m7/predictor.py`
- Create: `里程碑7_成员C机理AI融合建模/02_代码/run_member_c_demo.py`
- Create: `里程碑7_成员C机理AI融合建模/README.md`

**Interfaces:**
- Produces: `predict(station_id: str, forecast_scale: str, target_metrics: list[str]) -> dict`
- Produces: `build_demo_rows() -> list[dict]`

- [ ] Write failing tests for backend-compatible prediction JSON.
- [ ] Run tests and verify missing module/function failures.
- [ ] Implement predictor and demo artifact writer.
- [ ] Run tests and demo script.

### Task 5: Final Verification

**Files:**
- Read: all tests and outputs.

- [ ] Run full unittest discovery.
- [ ] Run demo script.
- [ ] Check generated JSON states that outputs are sample-only.
- [ ] Summarize completed member C tasks and remaining data-dependent tasks.
