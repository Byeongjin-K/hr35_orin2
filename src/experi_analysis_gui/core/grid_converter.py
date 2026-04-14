"""
Point Cloud ↔ 2D Grid Map 변환기

포인트 클라우드를 2D 높이맵(grid)으로 변환하거나,
grid를 포인트 클라우드로 역변환하는 기능을 제공합니다.
"""
import numpy as np
from scipy.interpolate import griddata


def pointcloud_to_grid(points: np.ndarray,
                       resolution: float = 0.05,
                       method: str = 'linear',
                       fill_value: float = np.nan,
                       bounds: tuple = None) -> dict:
    """
    포인트 클라우드를 2D 높이맵 grid로 변환.

    Args:
        points: (N, 3) numpy array
        resolution: grid 셀 크기 (m)
        method: 보간 방법 ('nearest', 'linear', 'cubic')
        fill_value: 데이터 없는 셀의 값
        bounds: (x_min, x_max, y_min, y_max), None이면 자동 계산

    Returns:
        dict: {
            'grid': 2D numpy array (높이값),
            'resolution': float,
            'origin': (x_min, y_min),
            'x_edges': 1D array,
            'y_edges': 1D array
        }
    """
    x, y, z = points[:, 0], points[:, 1], points[:, 2]

    if bounds is None:
        x_min, x_max = x.min(), x.max()
        y_min, y_max = y.min(), y.max()
    else:
        x_min, x_max, y_min, y_max = bounds

    # 약간의 margin
    margin = resolution * 0.5
    x_edges = np.arange(x_min - margin, x_max + margin + resolution, resolution)
    y_edges = np.arange(y_min - margin, y_max + margin + resolution, resolution)
    grid_x, grid_y = np.meshgrid(x_edges, y_edges)

    actual_method = method
    if len(points) < 4 and method in ('linear', 'cubic'):
        actual_method = 'nearest'

    grid_z = griddata(
        points=(x, y), values=z,
        xi=(grid_x, grid_y),
        method=actual_method,
        fill_value=fill_value
    )

    return {
        'grid': grid_z,
        'resolution': resolution,
        'origin': (x_min - margin, y_min - margin),
        'x_edges': x_edges,
        'y_edges': y_edges,
    }


def pointcloud_to_grid_binned(points: np.ndarray,
                               resolution: float = 0.05,
                               aggregation: str = 'mean',
                               bounds: tuple = None) -> dict:
    """
    포인트 클라우드를 bin 기반으로 2D grid로 변환 (보간 없이).
    각 셀 내의 포인트들을 집계합니다.

    Args:
        points: (N, 3) numpy array
        resolution: grid 셀 크기 (m)
        aggregation: 집계 방법 ('mean', 'max', 'min', 'median')
        bounds: (x_min, x_max, y_min, y_max)

    Returns:
        dict: grid 정보
    """
    x, y, z = points[:, 0], points[:, 1], points[:, 2]

    if bounds is None:
        x_min, x_max = x.min(), x.max()
        y_min, y_max = y.min(), y.max()
    else:
        x_min, x_max, y_min, y_max = bounds

    nx = int(np.ceil((x_max - x_min) / resolution)) + 1
    ny = int(np.ceil((y_max - y_min) / resolution)) + 1

    ix = np.clip(((x - x_min) / resolution).astype(int), 0, nx - 1)
    iy = np.clip(((y - y_min) / resolution).astype(int), 0, ny - 1)

    grid = np.full((ny, nx), np.nan)
    count = np.zeros((ny, nx), dtype=int)

    agg_funcs = {
        'mean': np.nanmean,
        'max': np.nanmax,
        'min': np.nanmin,
        'median': np.nanmedian,
    }
    agg_func = agg_funcs.get(aggregation, np.nanmean)

    # bin별 집계
    for i in range(len(points)):
        ci, ri = ix[i], iy[i]
        if count[ri, ci] == 0:
            grid[ri, ci] = z[i]
        else:
            if aggregation == 'mean':
                grid[ri, ci] = (grid[ri, ci] * count[ri, ci] + z[i]) / (count[ri, ci] + 1)
            elif aggregation == 'max':
                grid[ri, ci] = max(grid[ri, ci], z[i])
            elif aggregation == 'min':
                grid[ri, ci] = min(grid[ri, ci], z[i])
            else:
                grid[ri, ci] = z[i]  # median은 별도 처리 필요
        count[ri, ci] += 1

    x_edges = np.arange(nx) * resolution + x_min
    y_edges = np.arange(ny) * resolution + y_min

    return {
        'grid': grid,
        'resolution': resolution,
        'origin': (x_min, y_min),
        'x_edges': x_edges,
        'y_edges': y_edges,
        'count': count,
    }


def grid_to_pointcloud(grid_data: dict) -> np.ndarray:
    """
    2D grid map을 포인트 클라우드로 변환.

    Args:
        grid_data: {
            'grid': 2D numpy array,
            'resolution': float,
            'origin': (x, y)
        }

    Returns:
        (N, 3) numpy array
    """
    grid = grid_data['grid']
    res = grid_data['resolution']
    origin = grid_data['origin']

    ny, nx = grid.shape
    valid = ~np.isnan(grid)

    row_idx, col_idx = np.where(valid)
    x = col_idx * res + origin[0]
    y = row_idx * res + origin[1]
    z = grid[valid]

    return np.column_stack([x, y, z])


def align_grids(grid_a: dict, grid_b: dict, resolution: float = None) -> tuple:
    """
    두 grid를 동일한 영역과 해상도로 정렬합니다.

    Args:
        grid_a, grid_b: grid 데이터 dict
        resolution: 목표 해상도 (None이면 더 높은 해상도 사용)

    Returns:
        (aligned_a, aligned_b) 동일 크기의 grid dict
    """
    if resolution is None:
        resolution = min(grid_a['resolution'], grid_b['resolution'])

    # 두 grid를 포인트로 변환
    pts_a = grid_to_pointcloud(grid_a)
    pts_b = grid_to_pointcloud(grid_b)

    # 공통 영역 계산
    x_min = max(pts_a[:, 0].min(), pts_b[:, 0].min())
    x_max = min(pts_a[:, 0].max(), pts_b[:, 0].max())
    y_min = max(pts_a[:, 1].min(), pts_b[:, 1].min())
    y_max = min(pts_a[:, 1].max(), pts_b[:, 1].max())
    bounds = (x_min, x_max, y_min, y_max)

    aligned_a = pointcloud_to_grid(pts_a, resolution=resolution, bounds=bounds)
    aligned_b = pointcloud_to_grid(pts_b, resolution=resolution, bounds=bounds)

    return aligned_a, aligned_b


def compute_difference_map(grid_before: dict, grid_after: dict) -> dict:
    """
    전/후 grid의 차이 맵 계산 (after - before).
    양수 = 지면이 높아짐 (메움), 음수 = 지면이 낮아짐 (굴착)

    Args:
        grid_before, grid_after: 정렬된 grid 데이터

    Returns:
        dict: 차이 grid
    """
    ga, gb = align_grids(grid_before, grid_after)
    diff = gb['grid'] - ga['grid']

    return {
        'grid': diff,
        'resolution': ga['resolution'],
        'origin': ga['origin'],
        'x_edges': ga['x_edges'],
        'y_edges': ga['y_edges'],
    }
