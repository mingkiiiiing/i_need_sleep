# SIM-V1.1 remediation verification source notes

Scope: `SIM-V1 / mvp_meiliangwan_2024 / df-0.2.0 / baseline / seed 20260904`.

Primary evidence:

- `data-cleaning/storage/releases/data_factory_release/SIM-V1/**`
- `data-cleaning/storage/runs/data_factory/mvp_meiliangwan_2024/**`
- `data-cleaning/data_factory/**`
- Git commits `c05abf6` and `52c9ec5`
- `reports/data-generation-audit-2026-09-04/audit_data_generation.py`

Independent checks:

- 45 release hash entries independently recomputed; 0 mismatches.
- Current HEAD and release `code_commit` both resolve to `52c9ec5787acbdf5615673f3fdd998fa0c01c6b9`.
- No data-factory/config/test path changes relative to that release commit.
- 51 data-factory pytest tests passed; one Python date parsing deprecation warning remains.
- DG-001—014 were recomputed by `verify_remediation.py`; no generator or release artifact was changed.

Interpretation boundaries:

- DG-001 is resolved by explicit partial-domain identity, not by full-lake simulation.
- DG-008 is resolved by an approved task-grain contract, not by creating every task at grid grain.
- DG-007 remains a disclosed warning: four unique-date binary task/spatial/split groups contain only one class.
- `overall PASS` means the SIM package can be released under its profile; it does not override `training_readiness=WARNING`.
- MEE real-time observations are outside the 2024 SIM training set and have not caused current leakage.

Visualization choice:

- Tables were used instead of charts because the main analytical task is exact audit mapping across 14 named controls and two residual findings.
- No trend chart was used because this is one release snapshot, not a comparable time series.
