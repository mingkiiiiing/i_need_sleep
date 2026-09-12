#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A23 太湖蓝藻项目部署验证脚本（T6a）。

用途：在干净环境/开发机上快速校验 A23 项目是否具备"按文档一键启动"的前提条件。
只读探测，不写任何文件、不杀任何进程、不改动运行时服务。

校验内容：
  [1] Python 环境：优先 backend/.venv（与 start-a23-dev.ps1 一致），回退当前解释器；
      版本核对 + 按 backend/requirements.txt 逐条核对依赖可导入性与版本。
  [2] Node/npm 可用性 + 前端关键依赖（vite/vue）。
  [3] 关键路径：后端入口、模型运行时 manifest/gate_table、模型文件、小型运行数据包等。
  [4] 端口占用探测：8000/8001/5173/4173，并尝试 /api/health 识别服务身份（A23 / 非 A23）。
  [5] 一键启动幂等提示：按端口状态给出 start-a23-dev.ps1 的使用建议。

使用（Git Bash 或 PowerShell 均可）：
  python scripts/deploy_check_a23.py            # 人读格式
  python scripts/deploy_check_a23.py --json     # 机器可读 JSON

退出码：0 = 无 FAIL；1 = 存在 FAIL（环境不可一键启动）。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IS_WINDOWS = os.name == "nt"

EXPECTED_PRODUCT_ID = "taihu-a23-algae-warning"
CHECK_PORTS = [8000, 8001, 5173, 4173]

# 依赖缺失即 FAIL 的关键依赖（运行后端必需）
KEY_DEPS = {
    "fastapi", "uvicorn", "pandas", "scikit-learn", "numpy", "scipy",
    "joblib", "pydantic", "starlette", "httpx", "openpyxl",
    "pyarrow", "xgboost",
}

# 发行名 -> import 名特例（其余按 dist 名小写、'-' 换 '_' 尝试）
IMPORT_NAME_OVERRIDES = {
    "scikit-learn": "sklearn",
    "python-dotenv": "dotenv",
    "PyYAML": "yaml",
    "python-dateutil": "dateutil",
    "typing-inspection": "typing_inspection",
    "annotated-doc": "annotated_doc",
    "typing_extensions": "typing_extensions",
}

results: list[dict] = []  # {level, section, item, detail}


def add(level: str, section: str, item: str, detail: str = "") -> None:
    results.append({"level": level, "section": section, "item": item, "detail": detail})


# ---------------------------------------------------------------- Python 环境

def find_target_python() -> tuple[str, str]:
    """返回 (python 可执行路径, 来源说明)。优先项目 venv。"""
    venv_py = PROJECT_ROOT / "backend" / ".venv" / (
        "Scripts/python.exe" if IS_WINDOWS else "bin/python"
    )
    if venv_py.exists():
        return str(venv_py), "backend/.venv（start-a23-dev.ps1 实际使用）"
    return sys.executable, "系统/当前解释器（未找到 backend/.venv，需先建 venv）"


def parse_requirements() -> list[tuple[str, str]]:
    """解析 backend/requirements.txt -> [(发行名, 版本 pin)]。"""
    req_path = PROJECT_ROOT / "backend" / "requirements.txt"
    if not req_path.exists():
        add("FAIL", "[1] Python 环境", "backend/requirements.txt 存在", "文件缺失")
        return []
    add("PASS", "[1] Python 环境", "backend/requirements.txt 存在", str(req_path))
    pins = []
    for raw in req_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._!+]+)$", line)
        if m:
            pins.append((m.group(1), m.group(2)))
        else:
            pins.append((line, "?"))
    return pins


def probe_python(python_exe: str, pins: list[tuple[str, str]]) -> None:
    ver = subprocess.run([python_exe, "--version"], capture_output=True, text=True, timeout=30)
    ver_text = (ver.stdout or ver.stderr).strip()
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", ver_text)
    if not m:
        add("FAIL", "[1] Python 环境", "Python 版本可获取", f"无法解析：{ver_text!r}")
        return
    major, minor = int(m.group(1)), int(m.group(2))
    if (major, minor) >= (3, 11):
        add("PASS", "[1] Python 环境", f"Python 版本 = {ver_text}",
            "满足 >=3.11（pandas 3.x / scikit-learn 1.9 要求）")
    else:
        add("FAIL", "[1] Python 环境", f"Python 版本 = {ver_text}",
            "低于 3.11，requirements 中 pandas 3.x 无法安装/运行")

    # 一次性子进程导入全部依赖，输出 JSON
    probe = (
        "import json,sys;sys.stdout.reconfigure(encoding='utf-8',errors='replace');"
        "mods=json.load(sys.stdin);out={}\n"
        "for name in mods:\n"
        "    try:\n"
        "        mod=__import__(name);out[name]=getattr(mod,'__version__','?')\n"
        "    except Exception as e:\n"
        "        out[name]='IMPORT_ERROR:'+type(e).__name__+':'+str(e)[:120]\n"
        "print(json.dumps(out,ensure_ascii=False))"
    )
    import_names, dist_by_import = [], {}
    for dist, _pin in pins:
        imp = IMPORT_NAME_OVERRIDES.get(dist) or IMPORT_NAME_OVERRIDES.get(dist.lower()) \
            or dist.lower().replace("-", "_")
        import_names.append(imp)
        dist_by_import[imp] = dist
    try:
        run = subprocess.run(
            [python_exe, "-c", probe],
            input=json.dumps(import_names), capture_output=True, text=True,
            timeout=300, encoding="utf-8", errors="replace",
        )
        got = json.loads(run.stdout.strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        add("FAIL", "[1] Python 环境", "依赖批量导入探测执行", f"探测子进程失败：{e}")
        return

    n_pass = n_warn = n_fail = 0
    for imp in import_names:
        dist = dist_by_import[imp]
        pin = dict(pins).get(dist, "?")
        status = got.get(imp, "NOT_PROBED")
        is_key = dist in KEY_DEPS
        if status.startswith("IMPORT_ERROR:"):
            add("FAIL" if is_key else "WARN", "[1] Python 环境",
                f"依赖可导入：{dist} (import {imp})", status)
            n_fail += 1 if is_key else 0
            n_warn += 0 if is_key else 1
        elif status == "?":
            add("PASS", "[1] Python 环境", f"依赖可导入：{dist}", "导入成功（模块未暴露 __version__）")
            n_pass += 1
        else:
            if pin != "?" and str(pin) != str(status):
                add("WARN", "[1] Python 环境", f"依赖版本：{dist}",
                    f"已装 {status}，requirements.txt 钉版 {pin}（环境与钉版有漂移）")
                n_warn += 1
            else:
                add("PASS", "[1] Python 环境", f"依赖可导入：{dist}", f"版本 {status}（钉版 {pin}）")
                n_pass += 1
    add("INFO", "[1] Python 环境", "依赖核对汇总", f"PASS={n_pass} WARN={n_warn} FAIL={n_fail}")


# ---------------------------------------------------------------- Node / npm

def probe_node() -> None:
    try:
        node = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=30)
        nv = (node.stdout or "").strip()
        if node.returncode == 0 and nv:
            add("PASS", "[2] Node/npm", f"node 版本 = {nv}")
        else:
            add("FAIL", "[2] Node/npm", "node 可用", f"退出码 {node.returncode}: {node.stderr[:120]}")
    except FileNotFoundError:
        add("FAIL", "[2] Node/npm", "node 可用", "未找到 node 命令")

    npm_cmd = "npm.cmd" if IS_WINDOWS else "npm"
    try:
        npm = subprocess.run([npm_cmd, "--version"], capture_output=True, text=True, timeout=60)
        npmv = (npm.stdout or "").strip()
        if npm.returncode == 0 and npmv:
            add("PASS", "[2] Node/npm", f"npm 版本 = {npmv}（命令 {npm_cmd}）")
        else:
            add("FAIL", "[2] Node/npm", "npm 可用", f"退出码 {npm.returncode}: {npm.stderr[:120]}")
    except FileNotFoundError:
        add("FAIL", "[2] Node/npm", "npm 可用", f"未找到 {npm_cmd}（Git Bash 下 npm.cmd 需在 PATH）")

    for pkg in ("vite", "vue", "echarts", "leaflet"):
        pj = PROJECT_ROOT / "node_modules" / pkg / "package.json"
        if pj.exists():
            try:
                version = json.loads(pj.read_text(encoding="utf-8")).get("version", "?")
                add("PASS", "[2] Node/npm", f"node_modules/{pkg}", f"版本 {version}")
            except Exception:  # noqa: BLE001
                add("WARN", "[2] Node/npm", f"node_modules/{pkg}", "存在但 package.json 不可读")
        else:
            add("FAIL", "[2] Node/npm", f"node_modules/{pkg}", "缺失，请先 npm install")


# ---------------------------------------------------------------- 关键路径

def probe_paths() -> None:
    must = [
        ("backend/main.py", PROJECT_ROOT / "backend" / "main.py"),
        ("backend/requirements.txt", PROJECT_ROOT / "backend" / "requirements.txt"),
        ("backend/model_runtime_v0_3/manifest.json",
         PROJECT_ROOT / "backend" / "model_runtime_v0_3" / "manifest.json"),
        ("backend/model_runtime_v0_3/evaluation/gate_table.json",
         PROJECT_ROOT / "backend" / "model_runtime_v0_3" / "evaluation" / "gate_table.json"),
        ("package.json", PROJECT_ROOT / "package.json"),
        ("vite.config.js", PROJECT_ROOT / "vite.config.js"),
        ("start-a23-dev.ps1（一键启动）", PROJECT_ROOT / "start-a23-dev.ps1"),
        ("scripts/check-a23-backend.ps1（后端身份核查）",
         PROJECT_ROOT / "scripts" / "check-a23-backend.ps1"),
        ("小型数据包 manifest", PROJECT_ROOT / "企业提交材料" / "A23_小型运行数据包_V1.0" / "manifest.json"),
    ]
    for label, p in must:
        if p.exists():
            add("PASS", "[3] 关键路径", label, str(p.relative_to(PROJECT_ROOT)))
        else:
            add("FAIL", "[3] 关键路径", label, f"缺失：{p}")

    # 模型文件
    models_dir = PROJECT_ROOT / "backend" / "model_runtime_v0_3" / "models"
    if models_dir.is_dir():
        n = len(list(models_dir.glob("*.joblib")))
        if n > 0:
            add("PASS", "[3] 关键路径", "model_runtime_v0_3/models 模型文件", f"{n} 个 .joblib")
        else:
            add("FAIL", "[3] 关键路径", "model_runtime_v0_3/models 模型文件", "目录存在但无 .joblib")
    else:
        add("FAIL", "[3] 关键路径", "model_runtime_v0_3/models", "目录缺失")

    # 小型数据包 realtime_catalog 四件套 + simulated
    rt = PROJECT_ROOT / "企业提交材料" / "A23_小型运行数据包_V1.0" / "realtime_catalog"
    for f in ("stations.json", "snapshots.json", "observations.parquet", "status.json"):
        (add("PASS", "[3] 关键路径", f"小型数据包 realtime_catalog/{f}", "") if (rt / f).exists()
         else add("FAIL", "[3] 关键路径", f"小型数据包 realtime_catalog/{f}", "缺失"))
    sim = PROJECT_ROOT / "企业提交材料" / "A23_小型运行数据包_V1.0" / "simulated"
    n_sim = len(list(sim.glob("*"))) if sim.is_dir() else 0
    add(*(("PASS", "[3] 关键路径", "小型数据包 simulated/ 样例", f"{n_sim} 个文件") if n_sim
          else ("WARN", "[3] 关键路径", "小型数据包 simulated/ 样例", "目录缺失或为空")))

    # 运行时实时目录（README 要求复制过去）
    live = PROJECT_ROOT / "data-cleaning" / "storage" / "silver" / "mee_realtime"
    if all((live / f).exists() for f in ("stations.json", "snapshots.json", "observations.parquet", "status.json")):
        add("PASS", "[3] 关键路径", "data-cleaning/.../mee_realtime 运行时实时目录", "四件套齐全")
    else:
        add("WARN", "[3] 关键路径", "data-cleaning/.../mee_realtime 运行时实时目录",
            "四件套不全（实时接口需设 TAIHU_REALTIME_CATALOG_DIR 指向小型数据包，或复制四件套）")

    # venv python
    venv_py = PROJECT_ROOT / "backend" / ".venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
    if venv_py.exists():
        add("PASS", "[3] 关键路径", "backend/.venv Python 解释器", str(venv_py.relative_to(PROJECT_ROOT)))
    else:
        add("FAIL", "[3] 关键路径", "backend/.venv Python 解释器",
            "缺失：python -m venv backend/.venv && pip install -r backend/requirements.txt")

    # ps1 是否 UTF-8 BOM（看板第十节：ps1 必须 UTF-8 BOM）
    for ps in ("start-a23-dev.ps1", "scripts/check-a23-backend.ps1"):
        p = PROJECT_ROOT / ps
        if p.exists():
            head = p.read_bytes()[:3]
            if head == b"\xef\xbb\xbf":
                add("PASS", "[3] 关键路径", f"{ps} 编码", "UTF-8 BOM")
            else:
                add("WARN", "[3] 关键路径", f"{ps} 编码", "无 UTF-8 BOM（Windows PowerShell 5.1 解析中文可能乱码）")

    # 小型数据包 zip 与目录的新旧
    pkg_dir = PROJECT_ROOT / "企业提交材料" / "A23_小型运行数据包_V1.0"
    pkg_zip = PROJECT_ROOT / "企业提交材料" / "A23_小型运行数据包_V1.0.zip"
    if pkg_zip.exists() and pkg_dir.is_dir():
        dz = pkg_zip.stat().st_mtime - max(x.stat().st_mtime for x in pkg_dir.rglob("*") if x.is_file())
        if dz < -3600:
            add("WARN", "[3] 关键路径", "A23_小型运行数据包_V1.0.zip",
                f"zip 比目录内容旧约 {abs(dz)/3600:.1f} 小时，终审打包前需重新压缩以保持同步")
        else:
            add("PASS", "[3] 关键路径", "A23_小型运行数据包_V1.0.zip", "zip 不落后于目录")


# ---------------------------------------------------------------- 端口探测

def netstat_pids() -> dict[int, str]:
    """返回 {端口: 'PID/进程名'}；尽力而为，失败返回空。"""
    pids: dict[int, str] = {}
    if not IS_WINDOWS:
        return pids
    try:
        raw = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                             timeout=30).stdout or b""
        # netstat 输出可能是 GBK（中文 Windows），一律容错解码
        out = raw.decode("utf-8", "replace") if b"LISTENING" in raw else \
            raw.decode("gbk", "replace")
    except Exception:  # noqa: BLE001
        return pids
    for line in out.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        m = re.match(r"^(?:\d+\.[\d.]+|\[[0-9a-f:]+\]|\*):(\d+)$", local)
        if not m:
            continue
        port = int(m.group(1))
        pid = parts[-1]
        name = "?"
        if pid.isdigit():
            try:
                raw = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                     capture_output=True, timeout=20).stdout or b""
                task = raw.decode("utf-8", "replace")
                if task.strip():
                    name = task.strip().split('","')[0].strip('"')
            except Exception:  # noqa: BLE001
                pass
        pids.setdefault(port, f"PID={pid} process={name}")
    return pids


def http_health(port: int) -> str:
    """GET /api/health，返回人读身份描述。"""
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        data = body.get("data") or {}
        pid = data.get("product_id")
        if pid == EXPECTED_PRODUCT_ID:
            return f"A23 后端身份确认（product_id={pid}, api_version={data.get('api_version')}）"
        if pid:
            return f"HTTP 服务但非 A23（product_id={pid}）"
        return f"HTTP 200 但无 product_id 字段（非 A23 约定）：{str(body)[:80]}"
    except Exception as e:  # noqa: BLE001
        return f"/api/health 探测失败（非 HTTP 或非 A23 路由）：{type(e).__name__}"


def probe_ports() -> dict[int, str]:
    pids = netstat_pids()
    state: dict[int, str] = {}
    for port in CHECK_PORTS:
        occupied = False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.8):
                occupied = True
        except OSError:
            occupied = False
        if occupied:
            owner = pids.get(port, "未知（netstat 未取到）")
            ident = http_health(port)
            is_a23 = "A23 后端身份确认" in ident
            if port in (5173, 4173) and is_a23:
                ident = f"前端端口（vite）经 /api 代理链路确认后端身份：{ident}"
            if is_a23:
                level = "PASS"
            else:
                level = "WARN"
            add(level, "[4] 端口探测", f"端口 {port} LISTENING", f"{owner}；{ident}")
            state[port] = "a23" if is_a23 else "occupied"
        else:
            add("PASS", "[4] 端口探测", f"端口 {port} 空闲", "可被一键启动使用")
            state[port] = "free"
    return state


# ---------------------------------------------------------------- 幂等提示

def print_idempotency_hints(state: dict[int, str]) -> None:
    lines = ["- 一键启动：powershell -ExecutionPolicy Bypass -File start-a23-dev.ps1"
             "（默认后端 8000 / 前端 5173；可用 -BackendPort 8001 覆盖）"]

    b8000, b8001 = state.get(8000), state.get(8001)
    if b8000 == "free":
        lines.append("- 8000 空闲：可直接默认参数启动。")
    elif b8000 == "a23":
        lines.append("- 8000 已是 A23 后端：start-a23-dev.ps1 会自动复用（幂等），无需重复启动。")
    else:
        lines.append("- 8000 被非 A23 服务占用：不要杀进程；请加参数 -BackendPort 8001，"
                     "脚本会自动为前端设置 BACKEND_ORIGIN（vite 代理随之指向 8001）。")
    if b8001 == "a23":
        lines.append("- 8001 已是 A23 后端：压测/联调走 http://127.0.0.1:8001/api/v1，"
                     "启动前可用 scripts/check-a23-backend.ps1 -Port 8001 复核身份。")
    elif b8001 == "occupied":
        lines.append("- 8001 也被占用：需先与占用方协调，或另选端口（注意同步 BACKEND_ORIGIN）。")

    for port, hint in ((5173, "开发前端"), (4173, "预览（npm run preview）")):
        if state.get(port) == "free":
            lines.append(f"- {port} 空闲：{hint}可正常使用。")
        elif state.get(port) == "a23":
            lines.append(f"- {port} 已有前端在跑且代理可达 A23 后端：直接复用该端口即可；"
                         f"若重跑 start-a23-dev.ps1，新 vite 实例会因端口占用顺延到 5174 等，注意别开两个页面实例。")
        else:
            lines.append(f"- {port} 被非 A23 服务占用：{hint}启动会顺延端口（vite 未开 strictPort），"
                         f"页面实际地址以终端输出为准；需要固定端口请先协调占用方或加 --strictPort。")

    lines.append("- 幂等性提示：后端有身份检查可安全重跑；前端无幂等检查，重复执行 start-a23-dev.ps1 "
                 "会叠加 vite 进程，重启验证前建议先结束旧 node/vite 进程。")
    lines.append("- 数据包演示提示：如需使用小型运行数据包，先执行 "
                 "$env:TAIHU_REALTIME_CATALOG_DIR='<项目根>\\企业提交材料\\A23_小型运行数据包_V1.0\\realtime_catalog' "
                 "再启动后端（见小型数据包 README）。")
    for ln in lines:
        add("INFO", "[5] 一键启动幂等提示", ln, "")


# ---------------------------------------------------------------- 主流程

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    started = datetime.now()
    print("A23 部署验证 deploy-check（T6a）")
    print(f"项目根: {PROJECT_ROOT}")
    print(f"时间: {started.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)

    python_exe, source = find_target_python()
    add("INFO", "[1] Python 环境", "目标解释器", f"{python_exe}（{source}）")
    pins = parse_requirements()
    probe_python(python_exe, pins)
    probe_node()
    probe_paths()
    state = probe_ports()
    print_idempotency_hints(state)

    # 输出
    as_json = "--json" in sys.argv
    if as_json:
        print(json.dumps({"project_root": str(PROJECT_ROOT),
                          "generated_at": started.isoformat(),
                          "results": results}, ensure_ascii=False, indent=2))
    else:
        cur = None
        for r in results:
            if r["section"] != cur:
                cur = r["section"]
                print(f"\n{cur}")
                print("-" * 72)
            tag = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]", "INFO": "[INFO]"}[r["level"]]
            line = f"{tag} {r['item']}"
            if r["detail"]:
                line += f" — {r['detail']}"
            print(line)

    n_pass = sum(1 for r in results if r["level"] == "PASS")
    n_fail = sum(1 for r in results if r["level"] == "FAIL")
    n_warn = sum(1 for r in results if r["level"] == "WARN")
    n_info = sum(1 for r in results if r["level"] == "INFO")
    print("\n" + "=" * 72)
    print(f"汇总: PASS={n_pass}  WARN={n_warn}  FAIL={n_fail}  INFO={n_info}")
    if n_fail:
        print("结论: 存在 FAIL，环境尚不满足一键启动前提，请先处理 FAIL 项。")
        return 1
    print("结论: 无 FAIL。可按 start-a23-dev.ps1 进行一键启动与重启验证"
          + ("（存在 WARN，建议阅过明细）" if n_warn else "") + "。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
