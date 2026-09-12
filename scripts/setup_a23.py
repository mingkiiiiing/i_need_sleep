"""A23 太湖蓝藻监测预警系统 · 队友一键部署脚本（正式版 v1.1）

用法（项目根目录，系统 Python >= 3.10 即可，项目依赖装进独立 venv）：
    python scripts/setup_a23.py            # 完整安装 + 校验
    python scripts/setup_a23.py --check    # 只校验，不安装
    python scripts/setup_a23.py --start    # 安装校验后直接启动前后端

装完后日常启动用：powershell -ExecutionPolicy Bypass -File start-a23-dev.ps1
说明文档见 QUICKSTART.md。仅用标准库，跨 Git Bash / PowerShell / CMD 可跑。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / "backend" / ".venv"
REQ = ROOT / "backend" / "requirements.txt"
DATA_FILES = [  # 队友克隆后必须存在的数据/模型文件
    ROOT / "企业提交材料/A23_小型运行数据包_V1.0/realtime_catalog/observations.parquet",
    ROOT / "企业提交材料/A23_小型运行数据包_V1.0/realtime_catalog/stations.json",
    ROOT / "企业提交材料/A23_小型运行数据包_V1.0/realtime_catalog/snapshots.json",
    ROOT / "企业提交材料/A23_小型运行数据包_V1.0/simulated/simulated_observations_v1.csv",
    ROOT / "backend/sample-data/simulated_observations_v1.csv",
    ROOT / "backend/model_runtime_v0_3/manifest.json",
    ROOT / "backend/model_runtime_v0_3/evaluation/gate_table.json",
]
PASS, FAIL = "PASS", "FAIL"


def run(cmd: list[str], **kw) -> int:
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.call([str(c) for c in cmd], cwd=ROOT, **kw)


def find_npm() -> str:
    for cand in ("npm.cmd", "npm"):
        try:
            if subprocess.call([cand, "--version"], cwd=ROOT,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                return cand
        except OSError:
            continue
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验不安装")
    ap.add_argument("--start", action="store_true", help="完成后启动前后端")
    args = ap.parse_args()
    ok = True

    print(f"[1/5] Python 解释器")
    py = sys.executable
    print(f"  {PASS} {py} ({'.'.join(map(str, sys.version_info[:3]))})")

    print("[2/5] 数据与模型文件（git 克隆即含）")
    for f in DATA_FILES:
        if f.is_file():
            print(f"  {PASS} {f.relative_to(ROOT)}")
        else:
            print(f"  {FAIL} 缺失 {f.relative_to(ROOT)}")
            ok = False
    models = sorted((ROOT / "backend/model_runtime_v0_3/models").glob("*.joblib"))
    print(f"  {'PASS' if len(models) >= 30 else FAIL} 模型文件 {len(models)}/34 个 joblib")

    if not args.check:
        print("[3/5] 后端依赖（backend/.venv 独立环境）")
        if not (VENV / "Scripts" / "python.exe").is_file() and not (VENV / "bin" / "python").exists():
            if run([py, "-m", "venv", str(VENV)]) != 0:
                print(f"  {FAIL} venv 创建失败"); return 1
        vpy = VENV / "Scripts" / "python.exe"
        if not vpy.exists():
            vpy = VENV / "bin" / "python"
        if run([vpy, "-m", "pip", "install", "-r", str(REQ), "-q"]) != 0:
            print(f"  {FAIL} pip install 失败"); return 1
        print(f"  {PASS} requirements.txt 安装完成")
    else:
        vpy = VENV / "Scripts" / "python.exe"
        if vpy.exists():
            print(f"[3/5] 后端依赖：{PASS} backend/.venv 已存在（--check 跳过安装）")
        else:
            print(f"[3/5] 后端依赖：{FAIL} backend/.venv 不存在（去掉 --check 可自动安装）")
            ok = False

    print("[4/5] 前端依赖（node_modules）")
    npm = find_npm()
    if not npm:
        print(f"  {FAIL} 未找到 npm，请先安装 Node.js >= 18"); return 1
    if (ROOT / "node_modules").is_dir():
        print(f"  {PASS} node_modules 已存在（跳过）")
    elif args.check:
        print(f"  {FAIL} node_modules 不存在（去掉 --check 可自动 npm install）"); ok = False
    else:
        if run([npm, "install", "--no-audit", "--no-fund"]) != 0:
            print(f"  {FAIL} npm install 失败"); return 1
        print(f"  {PASS} npm install 完成")

    print("[5/5] 结论")
    if ok:
        print("  全部就绪。启动方式（二选一）：")
        print("    一键启动：powershell -ExecutionPolicy Bypass -File start-a23-dev.ps1")
        print("    手动：后端 python -m uvicorn backend.main:app --port 8000")
        print("          前端 npm run dev（5173）")
        print("    验收地址：http://127.0.0.1:5173  API健康：http://127.0.0.1:8000/api/health")
        if args.start:
            ps = ROOT / "start-a23-dev.ps1"
            return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)])
        return 0
    print("  存在缺失项，请按上方 FAIL 提示处理（数据文件缺失=克隆不完整，重新 git clone）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
