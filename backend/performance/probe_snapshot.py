"""T2 短探针：全湖/站点快照端点延迟复现与定位（不跑完整压测）。

用途：在运行中的 A23 后端（默认 http://127.0.0.1:8000）上复现
tests/stress-report.json C1 的"首波慢"现象，采集修复前后对比数据。
只发少量请求（单请求 5 次 + 并发 2 轮），不构成完整压测。

场景设计（对应 C1 首波语义）：
  A. seq    —— 5 个顺序单请求（热缓存基线）
  B. burst  —— 等 TTL(_VIEW_PAYLOAD_CACHE_TTL_S=15s)+1s 过期后，
               打 5 并发 × 2 轮（轮间隔 300ms，与 stress-heatmap.mjs 同口径）。
               第一轮即"首波"（视图缓存重建波），第二轮为命中波。

用法：
  python backend/performance/probe_snapshot.py [--base http://127.0.0.1:8000] [--tag before]
输出：逐请求延迟 + 场景摘要（p50/p95/max），JSON 打印到 stdout。
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import urllib.request

TTL_EXPIRE_WAIT_S = 16.0  # 视图缓存 TTL 15s + 1s 余量
ROUND_GAP_S = 0.3


def fetch_once(base: str, path: str, timeout: float = 15.0) -> dict:
    t0 = time.perf_counter()
    status = 0
    try:
        req = urllib.request.Request(base + path, headers={"Connection": "close"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            resp.read()
        ok = True
    except Exception as exc:  # noqa: BLE001 — 探针自身如实记录失败
        ok = False
        return {"ok": False, "status": status, "ms": round((time.perf_counter() - t0) * 1000, 1), "error": str(exc)[:120]}
    return {"ok": ok, "status": status, "ms": round((time.perf_counter() - t0) * 1000, 1)}


def burst(base: str, paths: list[str], timeout: float = 15.0) -> list[dict]:
    """并发请求多个路径（每路径一个线程），全部完成后返回逐请求结果。"""
    results: list[dict] = []
    lock = threading.Lock()

    def worker(path: str) -> None:
        r = fetch_once(base, path, timeout=timeout)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker, args=(p,)) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def burst_same(base: str, path: str, concurrency: int) -> list[dict]:
    results: list[dict] = []
    lock = threading.Lock()

    def worker() -> None:
        r = fetch_once(base, path)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def stats(lat: list[float]) -> dict:
    if not lat:
        return {}
    xs = sorted(lat)

    def p(q: float) -> float:
        pos = q * (len(xs) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(xs) - 1)
        frac = pos - lo
        return round(xs[lo] * (1 - frac) + xs[hi] * frac, 1)

    return {
        "n": len(xs),
        "p50": p(0.5),
        "p95": p(0.95),
        "max": round(xs[-1], 1),
        "mean": round(statistics.fmean(xs), 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--tag", default="probe")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--entity", default="lake")
    ap.add_argument("--metric", default="chla")
    ap.add_argument("--c2", action="store_true", help="复现 C2：8 站点并发（每站 1 请求，TTL 过期后打）")
    args = ap.parse_args()

    if args.c2:
        # C2 缩小复现：8 站点各 1 请求并发（8 个不同缓存键 = 8 个 builder 并发）
        stations = [
            "mee-077b367a", "mee-0e770fb5", "mee-1d96cbf3", "mee-200076ad",
            "mee-2f8fdf3a", "mee-32bb00e0", "mee-3690676e", "mee-36e4cf04",
        ]
        fetch_once(args.base, "/api/v1/model/v3/prediction-snapshot?entity_id=lake&focus_metric=chla")
        time.sleep(TTL_EXPIRE_WAIT_S)
        results = burst(
            args.base,
            [f"/api/v1/model/v3/prediction-snapshot?entity_id={s}&focus_metric=chla" for s in stations],
        )
        out = {"tag": args.tag, "c2_stations": stations, "requests": results,
               **stats([r["ms"] for r in results])}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    path = f"/api/v1/model/v3/prediction-snapshot?entity_id={args.entity}&focus_metric={args.metric}"
    out: dict = {"tag": args.tag, "base": args.base, "path": path, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    # A. 顺序单请求 5 次（热缓存基线）
    seq = [fetch_once(args.base, path) for _ in range(5)]
    out["seq"] = {"requests": seq, **stats([r["ms"] for r in seq])}

    # B. 等 TTL 过期 → 并发波（第一轮 = 首波/重建波）
    time.sleep(TTL_EXPIRE_WAIT_S)
    rounds = []
    for r in range(args.rounds):
        batch = burst_same(args.base, path, args.concurrency)
        rounds.append({"round": r + 1, "requests": batch, **stats([x["ms"] for x in batch])})
        if r < args.rounds - 1:
            time.sleep(ROUND_GAP_S)
    out["burst"] = {"concurrency": args.concurrency, "rounds": rounds,
                    "first_wave": rounds[0] if rounds else None}
    out["burst_all_stats"] = stats([x["ms"] for rd in rounds for x in rd["requests"]])

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
