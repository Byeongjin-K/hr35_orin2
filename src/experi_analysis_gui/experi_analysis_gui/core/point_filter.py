"""점군 필터링: self-body 제거, 지면 추출, 통계적 이상치 제거, 지면 수평 보정"""
import numpy as np


def remove_self_body(points: np.ndarray,
                     ground_height: float = None,
                     above_ground_min: float = 0.3,
                     above_ground_max: float = 8.0,
                     density_cell_size: float = 0.5,
                     density_threshold: int = 15) -> np.ndarray:
    """
    굴착기 self-body 제거 (높이 기반 + 고밀도 클러스터 제거).
    지면보다 above_ground_min~above_ground_max 높이에 있는 점 중,
    XY 셀당 포인트 밀도가 높은 것을 구조물(굴착기)로 판단.

    ground_height: 지면 높이 (None이면 Z의 하위 20% 중앙값 사용)
    above_ground_min/max: 지면 위 이 범위의 점을 후보로 선별 (m)
    density_cell_size: XY 밀도 셀 크기 (m)
    density_threshold: 이 이상 밀집된 셀은 구조물로 판단
    """
    if len(points) < 100:
        return points

    z = points[:, 2]
    if ground_height is None:
        z_sorted = np.sort(z)
        ground_height = np.median(z_sorted[:max(1, len(z_sorted) // 5)])

    above_mask = (z > ground_height + above_ground_min) & (z < ground_height + above_ground_max)
    above_pts = points[above_mask]

    if len(above_pts) < 10:
        return points

    x, y = above_pts[:, 0], above_pts[:, 1]
    cx = ((x - x.min()) / density_cell_size).astype(int)
    cy = ((y - y.min()) / density_cell_size).astype(int)
    cell_ids = cx * 100000 + cy

    unique_cells, counts = np.unique(cell_ids, return_counts=True)
    dense_cells = set(unique_cells[counts >= density_threshold])

    if not dense_cells:
        return points

    all_x, all_y = points[:, 0], points[:, 1]
    all_cx = ((all_x - above_pts[:, 0].min()) / density_cell_size).astype(int)
    all_cy = ((all_y - above_pts[:, 1].min()) / density_cell_size).astype(int)
    all_cell_ids = all_cx * 100000 + all_cy

    in_dense = np.array([cid in dense_cells for cid in all_cell_ids])
    is_body = in_dense & (z > ground_height + above_ground_min)

    return points[~is_body]


def extract_ground(points: np.ndarray,
                   cell_size: float = 1.0,
                   height_threshold: float = 0.3,
                   min_points_per_cell: int = 5) -> tuple:
    """
    간이 지면 추출 (cell-based lowest point).
    지면 높이에서 threshold 이내의 점만 지면으로 분류.

    Returns: (ground_points, non_ground_points)
    """
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    x_min, y_min = x.min(), y.min()

    cx = ((x - x_min) / cell_size).astype(int)
    cy = ((y - y_min) / cell_size).astype(int)
    cell_ids = cx * 10000 + cy

    unique_cells = np.unique(cell_ids)
    ground_z = {}
    for cell_id in unique_cells:
        mask = cell_ids == cell_id
        if mask.sum() >= min_points_per_cell:
            cell_z = z[mask]
            ground_z[cell_id] = np.percentile(cell_z, 10)

    is_ground = np.zeros(len(points), dtype=bool)
    for i in range(len(points)):
        cid = cell_ids[i]
        if cid in ground_z:
            if z[i] <= ground_z[cid] + height_threshold:
                is_ground[i] = True

    return points[is_ground], points[~is_ground]


def remove_statistical_outliers(points: np.ndarray,
                                 k_neighbors: int = 20,
                                 std_multiplier: float = 2.0) -> np.ndarray:
    """
    KNN 기반 통계적 이상치 제거.
    각 점의 k-nearest 이웃까지 평균 거리가 전체 평균 + std_multiplier*σ를 초과하면 제거.
    """
    from scipy.spatial import KDTree

    if len(points) < k_neighbors + 1:
        return points

    sample_size = min(len(points), 100000)
    if len(points) > sample_size:
        idx = np.random.choice(len(points), sample_size, replace=False)
        sampled = points[idx]
    else:
        sampled = points

    tree = KDTree(sampled)
    dists, _ = tree.query(sampled, k=k_neighbors + 1)
    mean_dists = dists[:, 1:].mean(axis=1)

    global_mean = mean_dists.mean()
    global_std = mean_dists.std()
    threshold = global_mean + std_multiplier * global_std

    if len(points) > sample_size:
        tree_full = KDTree(points)
        dists_full, _ = tree_full.query(points, k=min(k_neighbors + 1, len(points)))
        mean_dists_full = dists_full[:, 1:].mean(axis=1)
        keep = mean_dists_full < threshold
    else:
        keep = mean_dists < threshold

    return points[keep]


def remove_range_outliers(points: np.ndarray, max_range: float = 50.0,
                           center: np.ndarray = None) -> np.ndarray:
    if center is None:
        center = np.array([0.0, 0.0, 0.0])
    dists = np.linalg.norm(points - center, axis=1)
    return points[dists < max_range]


def estimate_ground_plane(points: np.ndarray,
                           n_iterations: int = 200,
                           distance_threshold: float = 0.1,
                           sample_size: int = 3) -> tuple:
    """
    RANSAC으로 지면 평면을 추정.
    Returns: (normal_vector [a,b,c], d, inlier_mask)
             평면: ax + by + cz + d = 0, normal은 상향 보장
    """
    if len(points) < sample_size * 2:
        return np.array([0, 0, 1.0]), 0.0, np.ones(len(points), dtype=bool)

    best_inliers = 0
    best_normal = np.array([0, 0, 1.0])
    best_d = 0.0
    best_mask = np.ones(len(points), dtype=bool)

    pts = points
    if len(pts) > 50000:
        idx = np.random.choice(len(pts), 50000, replace=False)
        pts = pts[idx]

    for _ in range(n_iterations):
        idx = np.random.choice(len(pts), sample_size, replace=False)
        p1, p2, p3 = pts[idx[0]], pts[idx[1]], pts[idx[2]]

        v1 = p2 - p1
        v2 = p3 - p1
        normal = np.cross(v1, v2)
        norm_len = np.linalg.norm(normal)
        if norm_len < 1e-10:
            continue
        normal = normal / norm_len

        if normal[2] < 0:
            normal = -normal

        d = -np.dot(normal, p1)
        distances = np.abs(pts @ normal + d)
        inlier_mask = distances < distance_threshold
        n_inliers = inlier_mask.sum()

        if n_inliers > best_inliers:
            best_inliers = n_inliers
            best_normal = normal
            best_d = d
            best_mask = inlier_mask

    if len(points) != len(pts):
        distances_full = np.abs(points @ best_normal + best_d)
        best_mask = distances_full < distance_threshold

    return best_normal, best_d, best_mask


def level_to_ground_plane(points: np.ndarray,
                           normal: np.ndarray = None,
                           target_normal: np.ndarray = None) -> tuple:
    """
    점군을 지면 평면이 수평이 되도록 회전.
    normal: 현재 지면 법선 (None이면 RANSAC 추정)
    target_normal: 목표 법선 (None이면 [0,0,1] = 수평)
    Returns: (rotated_points, rotation_matrix_3x3)
    """
    from scipy.spatial.transform import Rotation

    if normal is None:
        normal, _, _ = estimate_ground_plane(points)

    if target_normal is None:
        target_normal = np.array([0.0, 0.0, 1.0])

    normal = normal / np.linalg.norm(normal)
    target_normal = target_normal / np.linalg.norm(target_normal)

    cross = np.cross(normal, target_normal)
    cross_len = np.linalg.norm(cross)

    if cross_len < 1e-10:
        return points.copy(), np.eye(3)

    axis = cross / cross_len
    angle = np.arccos(np.clip(np.dot(normal, target_normal), -1, 1))

    rot = Rotation.from_rotvec(axis * angle)
    R = rot.as_matrix()

    centroid = points.mean(axis=0)
    centered = points - centroid
    rotated = (R @ centered.T).T + centroid

    return rotated, R
