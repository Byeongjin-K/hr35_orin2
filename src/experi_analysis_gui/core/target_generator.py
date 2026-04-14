"""
목표(이상적) 지형 생성기

굴착 작업 유형별로 이상적인 작업 후 지형을 생성합니다:
- 트렌치 (도랑파기)
- 평탄화 (Grading)
- 구덩이 (Pit)
- 사면 정리 (Slope)
"""
import numpy as np


def generate_flat_terrain(x_range: tuple, y_range: tuple,
                          resolution: float = 0.05,
                          base_height: float = 0.0,
                          noise_std: float = 0.0) -> dict:
    """평탄한 기본 지형 생성"""
    x_edges = np.arange(x_range[0], x_range[1] + resolution, resolution)
    y_edges = np.arange(y_range[0], y_range[1] + resolution, resolution)
    grid = np.full((len(y_edges), len(x_edges)), float(base_height), dtype=np.float64)

    if noise_std > 0:
        grid += np.random.normal(0, noise_std, grid.shape)

    return {
        'grid': grid,
        'resolution': resolution,
        'origin': (x_range[0], y_range[0]),
        'x_edges': x_edges,
        'y_edges': y_edges,
    }


def generate_trench_target(x_range: tuple, y_range: tuple,
                           resolution: float = 0.05,
                           base_height: float = 0.0,
                           trench_depth: float = 1.0,
                           trench_width: float = 0.6,
                           trench_center_y: float = None,
                           trench_start_x: float = None,
                           trench_end_x: float = None,
                           wall_angle: float = 90.0,
                           bottom_slope: float = 0.0) -> dict:
    """
    트렌치(도랑) 형태의 목표 지형 생성.

    Args:
        x_range, y_range: 전체 영역 범위
        resolution: 그리드 해상도
        base_height: 기본 지면 높이
        trench_depth: 트렌치 깊이 (m)
        trench_width: 트렌치 상단 폭 (m)
        trench_center_y: 트렌치 중심 Y 좌표 (None이면 중앙)
        trench_start_x, trench_end_x: 트렌치 시작/끝 X (None이면 전체)
        wall_angle: 벽면 각도 (도, 90=수직)
        bottom_slope: 바닥 경사 (rad/m, 양수=x 증가방향 하강)
    """
    terrain = generate_flat_terrain(x_range, y_range, resolution, base_height)
    grid = terrain['grid']
    x_edges = terrain['x_edges']
    y_edges = terrain['y_edges']

    if trench_center_y is None:
        trench_center_y = (y_range[0] + y_range[1]) / 2
    if trench_start_x is None:
        trench_start_x = x_range[0]
    if trench_end_x is None:
        trench_end_x = x_range[1]

    half_width = trench_width / 2.0
    wall_angle_rad = np.radians(wall_angle)

    # 벽 각도에 따른 바닥 폭 계산
    if wall_angle < 90:
        wall_offset = trench_depth / np.tan(wall_angle_rad)
        bottom_half_width = half_width - wall_offset
        if bottom_half_width < 0:
            bottom_half_width = 0
    else:
        wall_offset = 0
        bottom_half_width = half_width

    for j, y_val in enumerate(y_edges):
        for i, x_val in enumerate(x_edges):
            if x_val < trench_start_x or x_val > trench_end_x:
                continue

            dist_from_center = abs(y_val - trench_center_y)

            if dist_from_center <= bottom_half_width:
                # 트렌치 바닥 영역
                depth = trench_depth
                depth += bottom_slope * (x_val - trench_start_x)
                grid[j, i] = base_height - depth
            elif dist_from_center <= half_width:
                # 경사 벽면 영역
                if wall_offset > 0:
                    t = (dist_from_center - bottom_half_width) / wall_offset
                    t = np.clip(t, 0, 1)
                    depth = trench_depth * (1 - t)
                    depth_at_x = depth + bottom_slope * (x_val - trench_start_x) * (1 - t)
                    grid[j, i] = base_height - depth_at_x
                else:
                    depth = trench_depth + bottom_slope * (x_val - trench_start_x)
                    grid[j, i] = base_height - depth

    terrain['grid'] = grid
    terrain['params'] = {
        'type': 'trench',
        'depth': trench_depth,
        'width': trench_width,
        'wall_angle': wall_angle,
        'center_y': trench_center_y,
    }
    return terrain


def generate_grading_target(x_range: tuple, y_range: tuple,
                            resolution: float = 0.05,
                            target_height: float = 0.0,
                            slope_x: float = 0.0,
                            slope_y: float = 0.0) -> dict:
    """
    평탄화(Grading) 목표 지형 생성.

    Args:
        target_height: 목표 높이 (기준점에서)
        slope_x: X 방향 경사 (m/m)
        slope_y: Y 방향 경사 (m/m)
    """
    terrain = generate_flat_terrain(x_range, y_range, resolution, target_height)
    grid = terrain['grid']
    x_edges = terrain['x_edges']
    y_edges = terrain['y_edges']

    x_center = (x_range[0] + x_range[1]) / 2
    y_center = (y_range[0] + y_range[1]) / 2

    for j, y_val in enumerate(y_edges):
        for i, x_val in enumerate(x_edges):
            grid[j, i] += slope_x * (x_val - x_center) + slope_y * (y_val - y_center)

    terrain['grid'] = grid
    terrain['params'] = {
        'type': 'grading',
        'target_height': target_height,
        'slope_x': slope_x,
        'slope_y': slope_y,
    }
    return terrain


def generate_pit_target(x_range: tuple, y_range: tuple,
                        resolution: float = 0.05,
                        base_height: float = 0.0,
                        pit_depth: float = 1.5,
                        pit_width_x: float = 2.0,
                        pit_width_y: float = 2.0,
                        pit_center: tuple = None,
                        wall_angle: float = 75.0,
                        shape: str = 'rectangular') -> dict:
    """
    구덩이(Pit) 형태의 목표 지형 생성.

    Args:
        pit_depth: 구덩이 깊이
        pit_width_x, pit_width_y: 구덩이 상단 폭 (X, Y 방향)
        pit_center: 중심 좌표 (None이면 영역 중앙)
        wall_angle: 벽면 각도 (도)
        shape: 'rectangular' 또는 'circular'
    """
    terrain = generate_flat_terrain(x_range, y_range, resolution, base_height)
    grid = terrain['grid']
    x_edges = terrain['x_edges']
    y_edges = terrain['y_edges']

    if pit_center is None:
        pit_center = ((x_range[0] + x_range[1]) / 2,
                      (y_range[0] + y_range[1]) / 2)

    half_wx = pit_width_x / 2
    half_wy = pit_width_y / 2
    wall_angle_rad = np.radians(wall_angle)

    if wall_angle < 90:
        wall_offset = pit_depth / np.tan(wall_angle_rad)
    else:
        wall_offset = 0

    for j, y_val in enumerate(y_edges):
        for i, x_val in enumerate(x_edges):
            dx = abs(x_val - pit_center[0])
            dy = abs(y_val - pit_center[1])

            if shape == 'circular':
                rx = dx / half_wx
                ry = dy / half_wy
                r = np.sqrt(rx**2 + ry**2)

                if r <= 1.0:
                    # 내부
                    inner_r = (half_wx - wall_offset) / half_wx if wall_offset < half_wx else 0
                    if r <= inner_r:
                        grid[j, i] = base_height - pit_depth
                    else:
                        t = (r - inner_r) / (1.0 - inner_r) if (1.0 - inner_r) > 0 else 1
                        grid[j, i] = base_height - pit_depth * (1 - t)
            else:
                # 사각형
                inner_half_wx = max(0, half_wx - wall_offset)
                inner_half_wy = max(0, half_wy - wall_offset)

                if dx <= inner_half_wx and dy <= inner_half_wy:
                    grid[j, i] = base_height - pit_depth
                elif dx <= half_wx and dy <= half_wy:
                    tx = 0 if inner_half_wx == half_wx else max(0, (dx - inner_half_wx) / wall_offset)
                    ty = 0 if inner_half_wy == half_wy else max(0, (dy - inner_half_wy) / wall_offset)
                    t = max(tx, ty)
                    t = min(t, 1.0)
                    grid[j, i] = base_height - pit_depth * (1 - t)

    terrain['grid'] = grid
    terrain['params'] = {
        'type': 'pit',
        'depth': pit_depth,
        'width_x': pit_width_x,
        'width_y': pit_width_y,
        'center': pit_center,
        'shape': shape,
        'wall_angle': wall_angle,
    }
    return terrain


def generate_slope_target(x_range: tuple, y_range: tuple,
                          resolution: float = 0.05,
                          top_height: float = 0.0,
                          bottom_height: float = -2.0,
                          slope_start_y: float = None,
                          slope_end_y: float = None,
                          target_angle: float = None) -> dict:
    """
    사면 정리(Slope) 목표 지형 생성.

    Args:
        top_height: 상단 높이
        bottom_height: 하단 높이
        slope_start_y: 경사 시작 Y
        slope_end_y: 경사 끝 Y
        target_angle: 목표 경사각 (도, None이면 start/end에서 자동 계산)
    """
    terrain = generate_flat_terrain(x_range, y_range, resolution, top_height)
    grid = terrain['grid']
    y_edges = terrain['y_edges']

    if slope_start_y is None:
        slope_start_y = y_range[0] + (y_range[1] - y_range[0]) * 0.3
    if slope_end_y is None:
        slope_end_y = y_range[0] + (y_range[1] - y_range[0]) * 0.7

    if target_angle is not None:
        height_diff = abs(top_height - bottom_height)
        horizontal_dist = height_diff / np.tan(np.radians(target_angle))
        slope_end_y = slope_start_y + horizontal_dist

    for j, y_val in enumerate(y_edges):
        if y_val < slope_start_y:
            grid[j, :] = top_height
        elif y_val > slope_end_y:
            grid[j, :] = bottom_height
        else:
            t = (y_val - slope_start_y) / (slope_end_y - slope_start_y)
            grid[j, :] = top_height + t * (bottom_height - top_height)

    terrain['grid'] = grid
    terrain['params'] = {
        'type': 'slope',
        'top_height': top_height,
        'bottom_height': bottom_height,
        'slope_start_y': slope_start_y,
        'slope_end_y': slope_end_y,
    }
    return terrain


def generate_target_pointcloud(target_grid: dict, density: float = 400) -> np.ndarray:
    """
    목표 지형 grid에서 포인트 클라우드 생성.

    Args:
        target_grid: grid 데이터
        density: 포인트 밀도 (points/m^2)

    Returns:
        (N, 3) numpy array
    """
    from .grid_converter import grid_to_pointcloud
    points = grid_to_pointcloud(target_grid)

    # 밀도에 따라 추가 포인트 생성 (보간)
    res = target_grid['resolution']
    target_per_cell = density * res * res
    if target_per_cell <= 1:
        return points

    # 각 셀 내에서 랜덤 포인트 추가
    all_points = [points]
    n_extra = int(target_per_cell) - 1
    if n_extra > 0:
        for _ in range(n_extra):
            jitter = np.random.uniform(-res/2, res/2, size=(len(points), 2))
            extra = points.copy()
            extra[:, 0] += jitter[:, 0]
            extra[:, 1] += jitter[:, 1]
            all_points.append(extra)

    return np.vstack(all_points)
