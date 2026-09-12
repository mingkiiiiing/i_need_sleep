# -*- coding: utf-8 -*-
"""导出训练当时的 modeling_real 代码快照到 backend/calibration_work/_replay_pkg/。

用途：T5-chla 部署模型由 2026-09-11 13:31-13:32 的训练管线产生；工作区 HEAD 的
target_builder 在 2026-09-12（commit d92c421）新增了 chla 双单位归一
(_normalize_chla_units)，会改变监督标签与特征。要用"原训练折"忠实重放，必须取训练
当天的代码版本，否则重放出的 actual / 预测与模型记录不一致（实测 132/132 行不一致）。

本脚本从 git 只读导出 commit 73be6e7（2026-09-11 23:37，模型建立于其前 10 小时，
且该 commit 至模型文件生成之间 modeling_real 未再有变更——由 feature_sha256 复核）下的
modeling_real 包。不改动工作区、不改 git。

用法：backend/.venv/Scripts/python.exe backend/calibration_work/export_replay_package.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC_PREFIX = "backend/model_runtime_v0_3/code/modeling_real/"
COMMIT = "73be6e7"
OUT = HERE / "_replay_pkg" / "modeling_real"


def _run(args: list[str]) -> str:
    return subprocess.run(args, cwd=REPO, check=True, capture_output=True, text=True).stdout


def main() -> int:
    entries = [l for l in _run(["git", "ls-tree", "--name-only", COMMIT, SRC_PREFIX]).splitlines() if l.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for path in entries:
        if not path.endswith(".py"):
            continue
        blob = _run(["git", "show", f"{COMMIT}:{path}"])
        (OUT / Path(path).name).write_text(blob, encoding="utf-8")
        n += 1
    print(f"exported {n} files from {COMMIT} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
