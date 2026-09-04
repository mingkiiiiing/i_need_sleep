"""确定性随机源与空间相关场 (设计 §6.4/§6.9).

单一 seed → SeedSequence.spawn 出独立子流；空间场用低秩谱分解，禁止逐格独立噪声。
"""

from __future__ import annotations

import numpy as np

STREAM_KEYS = ["weather", "hydrology", "nutrients", "algae", "transport", "bloom", "obs_spatial", "obs_station"]


def make_rng(seed: int) -> dict[str, np.random.Generator]:
    children = np.random.SeedSequence(int(seed)).spawn(len(STREAM_KEYS))
    return {key: np.random.default_rng(child) for key, child in zip(STREAM_KEYS, children)}


def spatial_modes(coords_utm: np.ndarray, length_km: float, k: int = 64) -> np.ndarray:
    """指数核 exp(-d/L) 的截断谱分解，返回 U (N,k) 使 z=U@w (~N(0,1)) 为空间相关场。"""

    coords = np.asarray(coords_utm, dtype=float)
    n = len(coords)
    diff = coords[:, None, :] - coords[None, :, :]
    dist = np.hypot(diff[..., 0], diff[..., 1])
    length_m = max(float(length_km) * 1000.0, 1.0)
    kernel = np.exp(-dist / length_m)
    eigenvalues, eigenvectors = np.linalg.eigh(kernel)
    order = np.argsort(eigenvalues)[::-1][:k]
    values = np.clip(eigenvalues[order], 0.0, None)
    modes = eigenvectors[:, order] * np.sqrt(values)
    return modes


def sample_field(rng: np.random.Generator, modes: np.ndarray, phi: float, prev: np.ndarray | None) -> np.ndarray:
    """AR(1) 时间持续 × 空间相关 z 场。"""

    n, k = modes.shape
    w = rng.standard_normal(k)
    field = modes @ w
    field = field / max(float(np.std(field)), 1e-9)
    if prev is None:
        return field
    phi = float(np.clip(phi, 0.0, 0.99))
    return phi * prev + np.sqrt(1.0 - phi * phi) * field
