"""ICP 기반 포인트 클라우드 정합 (안정 영역 사용)"""
import numpy as np
from scipy.spatial import KDTree
from scipy.spatial.transform import Rotation


def icp_align(source: np.ndarray, target: np.ndarray,
              max_iterations: int = 50,
              tolerance: float = 1e-6,
              max_correspondence_dist: float = 1.0,
              lock_yaw: bool = False) -> dict:
    """
    ICP로 source를 target에 정합.
    lock_yaw=True: Z축 회전(yaw)만 허용, roll/pitch 고정
    반환: {'rotation': 3x3, 'translation': 3, 'transformed': (N,3),
           'rmse': float, 'iterations': int}
    """
    src = source.copy()
    total_R = np.eye(3)
    total_t = np.zeros(3)

    prev_rmse = float('inf')
    for i in range(max_iterations):
        tree = KDTree(target)
        dists, indices = tree.query(src)

        mask = dists < max_correspondence_dist
        if mask.sum() < 10:
            break

        src_matched = src[mask]
        tgt_matched = target[indices[mask]]

        R, t = _best_fit_transform(src_matched, tgt_matched)

        if lock_yaw:
            R = _extract_yaw_only(R)

        src = (R @ src.T).T + t
        total_R = R @ total_R
        total_t = R @ total_t + t

        rmse = float(np.sqrt(np.mean(dists[mask] ** 2)))
        if abs(prev_rmse - rmse) < tolerance:
            break
        prev_rmse = rmse

    transformed = (total_R @ source.T).T + total_t
    final_tree = KDTree(target)
    final_dists, _ = final_tree.query(transformed)
    final_rmse = float(np.sqrt(np.mean(final_dists ** 2)))

    return {
        'rotation': total_R,
        'translation': total_t,
        'transformed': transformed,
        'rmse': final_rmse,
        'iterations': i + 1,
    }


def _extract_yaw_only(R: np.ndarray) -> np.ndarray:
    """3x3 회전행렬에서 Z축 회전(yaw) 성분만 추출, roll/pitch 제거"""
    r = Rotation.from_matrix(R)
    euler = r.as_euler('ZYX', degrees=False)
    yaw_only = Rotation.from_euler('Z', euler[0])
    return yaw_only.as_matrix()


def icp_align_stable_region(source_full: np.ndarray, target_full: np.ndarray,
                             stable_mask_source: np.ndarray = None,
                             stable_mask_target: np.ndarray = None,
                             z_range: tuple = None,
                             max_iterations: int = 50,
                             tolerance: float = 1e-6,
                             lock_yaw: bool = False) -> dict:
    """
    안정 영역(굴착되지 않은 부분)만으로 ICP 수행 후 전체 점군에 적용.

    stable_mask: bool 배열 (True=안정 영역)
    z_range: (z_min, z_max) - 이 높이 범위 내의 점만 안정 영역으로 간주
    """
    if stable_mask_source is None:
        if z_range is not None:
            stable_mask_source = (source_full[:, 2] >= z_range[0]) & (source_full[:, 2] <= z_range[1])
        else:
            z_median = np.median(source_full[:, 2])
            z_std = np.std(source_full[:, 2])
            stable_mask_source = np.abs(source_full[:, 2] - z_median) < z_std * 0.5

    if stable_mask_target is None:
        if z_range is not None:
            stable_mask_target = (target_full[:, 2] >= z_range[0]) & (target_full[:, 2] <= z_range[1])
        else:
            z_median = np.median(target_full[:, 2])
            z_std = np.std(target_full[:, 2])
            stable_mask_target = np.abs(target_full[:, 2] - z_median) < z_std * 0.5

    src_stable = source_full[stable_mask_source]
    tgt_stable = target_full[stable_mask_target]

    if len(src_stable) < 20 or len(tgt_stable) < 20:
        return {
            'rotation': np.eye(3),
            'translation': np.zeros(3),
            'transformed': source_full.copy(),
            'rmse': float('inf'),
            'iterations': 0,
            'stable_count_source': len(src_stable),
            'stable_count_target': len(tgt_stable),
        }

    max_pts = 50000
    if len(src_stable) > max_pts:
        idx = np.random.choice(len(src_stable), max_pts, replace=False)
        src_stable = src_stable[idx]
    if len(tgt_stable) > max_pts:
        idx = np.random.choice(len(tgt_stable), max_pts, replace=False)
        tgt_stable = tgt_stable[idx]

    result = icp_align(src_stable, tgt_stable, max_iterations, tolerance, lock_yaw=lock_yaw)

    transformed_full = (result['rotation'] @ source_full.T).T + result['translation']

    result['transformed'] = transformed_full
    result['stable_count_source'] = int(stable_mask_source.sum())
    result['stable_count_target'] = int(stable_mask_target.sum())

    return result


def _best_fit_transform(src: np.ndarray, tgt: np.ndarray):
    """SVD 기반 최적 rigid transform: src -> tgt"""
    centroid_src = src.mean(axis=0)
    centroid_tgt = tgt.mean(axis=0)

    src_centered = src - centroid_src
    tgt_centered = tgt - centroid_tgt

    H = src_centered.T @ tgt_centered
    U, S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T

    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T

    t = centroid_tgt - R @ centroid_src
    return R, t
