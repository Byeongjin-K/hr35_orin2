import numpy as np
from dataclasses import asdict


def dataclass_to_dict(obj) -> dict:
    return asdict(obj)


def safe_divide(numerator, denominator, default=0.0):
    if denominator == 0:
        return default
    return numerator / denominator


def downsample_points(points: np.ndarray, max_points: int = 100000) -> np.ndarray:
    if len(points) <= max_points:
        return points
    indices = np.random.choice(len(points), max_points, replace=False)
    return points[indices]


def colormap_height(heights: np.ndarray, vmin=None, vmax=None) -> np.ndarray:
    """높이값을 RGB 색상으로 변환 (jet 컬러맵)"""
    if vmin is None:
        vmin = np.nanmin(heights)
    if vmax is None:
        vmax = np.nanmax(heights)

    if vmax == vmin:
        vmax = vmin + 1e-6

    normalized = (heights - vmin) / (vmax - vmin)
    normalized = np.clip(normalized, 0, 1)

    colors = np.zeros((*heights.shape, 4))
    colors[..., 3] = 1.0

    for i in range(len(normalized) if normalized.ndim == 1 else normalized.size):
        idx = np.unravel_index(i, normalized.shape) if normalized.ndim > 1 else i
        t = normalized[idx]
        if t < 0.25:
            s = t / 0.25
            colors[idx] = [0, s, 1, 1]
        elif t < 0.5:
            s = (t - 0.25) / 0.25
            colors[idx] = [0, 1, 1 - s, 1]
        elif t < 0.75:
            s = (t - 0.5) / 0.25
            colors[idx] = [s, 1, 0, 1]
        else:
            s = (t - 0.75) / 0.25
            colors[idx] = [1, 1 - s, 0, 1]

    return colors


def apply_jet_colormap_fast(values: np.ndarray, vmin=None, vmax=None) -> np.ndarray:
    """빠른 jet 컬러맵 적용 (vectorized)"""
    if vmin is None:
        vmin = np.nanmin(values)
    if vmax is None:
        vmax = np.nanmax(values)

    if vmax == vmin:
        vmax = vmin + 1e-6

    t = np.clip((values - vmin) / (vmax - vmin), 0, 1)

    r = np.clip(1.5 - np.abs(t - 0.75) * 4, 0, 1)
    g = np.clip(1.5 - np.abs(t - 0.5) * 4, 0, 1)
    b = np.clip(1.5 - np.abs(t - 0.25) * 4, 0, 1)

    return np.column_stack([r, g, b, np.ones_like(r)])
