"""
굴착 작업 성능 평가 Metric 엔진

연구 기반 metric 세트:
1. 기하학적 정확도: RMSE, MAE, Hausdorff, Chamfer Distance
2. 체적 분석: Cut/Fill volume, 체적 정확도
3. 단면 분석: 깊이/폭 정확도, 단면 IoU
4. 표면 품질: 거칠기, 완성도, 정밀도
"""
import numpy as np
from scipy.spatial import KDTree
from dataclasses import dataclass, field


@dataclass
class GeometricMetrics:
    rmse: float = 0.0
    mae: float = 0.0
    max_error: float = 0.0
    std_error: float = 0.0
    mean_error: float = 0.0
    hausdorff_distance: float = 0.0
    chamfer_distance: float = 0.0
    median_error: float = 0.0
    percentile_95: float = 0.0


@dataclass
class VolumeMetrics:
    cut_volume: float = 0.0
    fill_volume: float = 0.0
    net_volume: float = 0.0
    total_volume: float = 0.0
    target_cut_volume: float = 0.0
    volume_accuracy: float = 0.0
    over_excavation_volume: float = 0.0
    under_excavation_volume: float = 0.0
    over_excavation_ratio: float = 0.0
    under_excavation_ratio: float = 0.0


@dataclass
class ExcavationMetrics:
    depth_mean: float = 0.0
    depth_std: float = 0.0
    depth_min: float = 0.0
    depth_max: float = 0.0
    depth_target: float = 0.0
    depth_error_mean: float = 0.0
    depth_error_rmse: float = 0.0
    width_mean: float = 0.0
    width_target: float = 0.0
    width_error: float = 0.0
    bottom_flatness: float = 0.0
    wall_angle_mean: float = 0.0
    wall_angle_target: float = 0.0
    wall_angle_error: float = 0.0
    completeness: float = 0.0
    precision: float = 0.0


@dataclass
class CrossSectionMetrics:
    iou: float = 0.0
    area_target: float = 0.0
    area_actual: float = 0.0
    area_overlap: float = 0.0
    depth_at_section: float = 0.0
    width_at_section: float = 0.0
    profile_rmse: float = 0.0


@dataclass
class SurfaceQualityMetrics:
    roughness_ra: float = 0.0
    roughness_rq: float = 0.0
    slope_consistency: float = 0.0
    surface_completeness: float = 0.0


@dataclass
class FullMetricsReport:
    geometric: GeometricMetrics = field(default_factory=GeometricMetrics)
    volume: VolumeMetrics = field(default_factory=VolumeMetrics)
    excavation: ExcavationMetrics = field(default_factory=ExcavationMetrics)
    surface: SurfaceQualityMetrics = field(default_factory=SurfaceQualityMetrics)
    cross_sections: list = field(default_factory=list)


def compute_height_difference_metrics(target_grid: np.ndarray,
                                       actual_grid: np.ndarray) -> GeometricMetrics:
    """높이 차이 기반 기하학적 metric 계산 (두 grid가 정렬된 상태)"""
    valid = ~np.isnan(target_grid) & ~np.isnan(actual_grid)
    if valid.sum() == 0:
        return GeometricMetrics()

    diff = actual_grid[valid] - target_grid[valid]

    return GeometricMetrics(
        rmse=float(np.sqrt(np.mean(diff ** 2))),
        mae=float(np.mean(np.abs(diff))),
        max_error=float(np.max(np.abs(diff))),
        std_error=float(np.std(diff)),
        mean_error=float(np.mean(diff)),
        median_error=float(np.median(np.abs(diff))),
        percentile_95=float(np.percentile(np.abs(diff), 95)),
    )


def compute_pointcloud_metrics(target_points: np.ndarray,
                                actual_points: np.ndarray) -> GeometricMetrics:
    """포인트 클라우드 간 기하학적 metric 계산 (Hausdorff, Chamfer 등)"""
    tree_target = KDTree(target_points)
    tree_actual = KDTree(actual_points)

    dist_actual_to_target, _ = tree_target.query(actual_points)
    dist_target_to_actual, _ = tree_actual.query(target_points)

    hausdorff = float(max(dist_actual_to_target.max(), dist_target_to_actual.max()))

    chamfer = float(
        np.mean(dist_actual_to_target ** 2) + np.mean(dist_target_to_actual ** 2)
    ) / 2.0

    all_dists = np.concatenate([dist_actual_to_target, dist_target_to_actual])

    return GeometricMetrics(
        rmse=float(np.sqrt(np.mean(all_dists ** 2))),
        mae=float(np.mean(all_dists)),
        max_error=float(all_dists.max()),
        std_error=float(np.std(all_dists)),
        mean_error=float(np.mean(all_dists)),
        hausdorff_distance=hausdorff,
        chamfer_distance=chamfer,
        median_error=float(np.median(all_dists)),
        percentile_95=float(np.percentile(all_dists, 95)),
    )


def compute_volume_metrics(before_grid: dict, after_grid: dict,
                           target_grid: dict = None) -> VolumeMetrics:
    """
    체적 변화량 계산.
    양수 diff = 지면 상승 (fill), 음수 diff = 지면 하강 (cut)
    """
    from .grid_converter import align_grids

    a_before, a_after = align_grids(before_grid, after_grid)
    grid_b = a_before['grid']
    grid_a = a_after['grid']
    res = a_before['resolution']

    valid = ~np.isnan(grid_b) & ~np.isnan(grid_a)
    diff = grid_a[valid] - grid_b[valid]
    cell_area = res * res

    cut_cells = diff[diff < 0]
    fill_cells = diff[diff > 0]

    cut_volume = float(np.abs(cut_cells).sum() * cell_area) if len(cut_cells) > 0 else 0.0
    fill_volume = float(fill_cells.sum() * cell_area) if len(fill_cells) > 0 else 0.0

    metrics = VolumeMetrics(
        cut_volume=cut_volume,
        fill_volume=fill_volume,
        net_volume=fill_volume - cut_volume,
        total_volume=cut_volume + fill_volume,
    )

    if target_grid is not None:
        a_before_t, a_target = align_grids(before_grid, target_grid)
        grid_bt = a_before_t['grid']
        grid_t = a_target['grid']
        valid_t = ~np.isnan(grid_bt) & ~np.isnan(grid_t)
        target_diff = grid_t[valid_t] - grid_bt[valid_t]

        target_cut_cells = target_diff[target_diff < 0]
        metrics.target_cut_volume = float(np.abs(target_cut_cells).sum() * cell_area) if len(target_cut_cells) > 0 else 0.0

        if metrics.target_cut_volume > 0:
            metrics.volume_accuracy = (metrics.cut_volume / metrics.target_cut_volume) * 100

        a_actual, a_tgt = align_grids(after_grid, target_grid)
        g_act = a_actual['grid']
        g_tgt = a_tgt['grid']
        valid_ot = ~np.isnan(g_act) & ~np.isnan(g_tgt)
        ot_diff = g_act[valid_ot] - g_tgt[valid_ot]

        over_cells = ot_diff[ot_diff < 0]
        under_cells = ot_diff[ot_diff > 0]

        metrics.over_excavation_volume = float(np.abs(over_cells).sum() * cell_area) if len(over_cells) > 0 else 0.0
        metrics.under_excavation_volume = float(under_cells.sum() * cell_area) if len(under_cells) > 0 else 0.0

        if metrics.target_cut_volume > 0:
            metrics.over_excavation_ratio = (metrics.over_excavation_volume / metrics.target_cut_volume) * 100
            metrics.under_excavation_ratio = (metrics.under_excavation_volume / metrics.target_cut_volume) * 100

    return metrics


def compute_excavation_metrics(before_grid: dict, after_grid: dict,
                                target_grid: dict = None,
                                target_params: dict = None) -> ExcavationMetrics:
    """굴착 깊이/폭/벽면각도 등 굴착 특화 metric 계산"""
    from .grid_converter import align_grids

    a_before, a_after = align_grids(before_grid, after_grid)
    grid_b = a_before['grid']
    grid_a = a_after['grid']
    res = a_before['resolution']

    valid = ~np.isnan(grid_b) & ~np.isnan(grid_a)
    depth_map = grid_b - grid_a
    depth_map[~valid] = 0

    excavated = depth_map > 0.01
    depths = depth_map[excavated]

    metrics = ExcavationMetrics()

    if len(depths) > 0:
        metrics.depth_mean = float(np.mean(depths))
        metrics.depth_std = float(np.std(depths))
        metrics.depth_min = float(np.min(depths))
        metrics.depth_max = float(np.max(depths))

        excavated_area = float(excavated.sum() * res * res)
        total_excavatable = valid.sum() * res * res

        width_per_row = excavated.sum(axis=1) * res
        nonzero_widths = width_per_row[width_per_row > 0]
        if len(nonzero_widths) > 0:
            metrics.width_mean = float(np.mean(nonzero_widths))

        deep_threshold = metrics.depth_max * 0.8
        bottom_mask = depth_map > deep_threshold
        if bottom_mask.sum() > 1:
            bottom_depths = depth_map[bottom_mask]
            metrics.bottom_flatness = float(np.std(bottom_depths))

    if target_params is not None:
        metrics.depth_target = target_params.get('depth', 0)
        metrics.width_target = target_params.get('width', 0)
        metrics.wall_angle_target = target_params.get('wall_angle', 90)

        if metrics.depth_target > 0:
            metrics.depth_error_mean = metrics.depth_mean - metrics.depth_target
            depth_errors = depths - metrics.depth_target if len(depths) > 0 else np.array([0])
            metrics.depth_error_rmse = float(np.sqrt(np.mean(depth_errors ** 2)))

        if metrics.width_target > 0 and metrics.width_mean > 0:
            metrics.width_error = metrics.width_mean - metrics.width_target

    if target_grid is not None:
        a_tgt_b, a_tgt = align_grids(before_grid, target_grid)
        g_tgt_b = a_tgt_b['grid']
        g_tgt = a_tgt['grid']
        valid_t = ~np.isnan(g_tgt_b) & ~np.isnan(g_tgt)
        target_excavated = (g_tgt_b - g_tgt) > 0.01

        if target_excavated.sum() > 0 and excavated.sum() > 0:
            min_r = min(excavated.shape[0], target_excavated.shape[0])
            min_c = min(excavated.shape[1], target_excavated.shape[1])
            exc_crop = excavated[:min_r, :min_c]
            tgt_crop = target_excavated[:min_r, :min_c]

            intersection = (exc_crop & tgt_crop).sum()
            metrics.completeness = float(intersection / tgt_crop.sum()) * 100 if tgt_crop.sum() > 0 else 0
            metrics.precision = float(intersection / exc_crop.sum()) * 100 if exc_crop.sum() > 0 else 0

    return metrics


def compute_cross_section(before_grid: dict, after_grid: dict,
                          target_grid: dict = None,
                          section_pos: float = None,
                          axis: str = 'y') -> CrossSectionMetrics:
    """
    특정 위치에서의 단면(cross-section) 분석.
    axis='y': Y 좌표 고정, X축 따라 단면
    axis='x': X 좌표 고정, Y축 따라 단면
    """
    from .grid_converter import align_grids

    grids_to_align = [before_grid, after_grid]
    if target_grid is not None:
        grids_to_align.append(target_grid)

    a_before, a_after = align_grids(before_grid, after_grid)
    grid_b = a_before['grid']
    grid_a = a_after['grid']
    res = a_before['resolution']

    if axis == 'y':
        if section_pos is None:
            section_pos = a_before['origin'][1] + grid_b.shape[0] * res / 2
        row_idx = int((section_pos - a_before['origin'][1]) / res)
        row_idx = np.clip(row_idx, 0, grid_b.shape[0] - 1)
        profile_before = grid_b[row_idx, :]
        profile_after = grid_a[row_idx, :]
        positions = a_before['x_edges'] if 'x_edges' in a_before else np.arange(grid_b.shape[1]) * res + a_before['origin'][0]
    else:
        if section_pos is None:
            section_pos = a_before['origin'][0] + grid_b.shape[1] * res / 2
        col_idx = int((section_pos - a_before['origin'][0]) / res)
        col_idx = np.clip(col_idx, 0, grid_b.shape[1] - 1)
        profile_before = grid_b[:, col_idx]
        profile_after = grid_a[:, col_idx]
        positions = a_before['y_edges'] if 'y_edges' in a_before else np.arange(grid_b.shape[0]) * res + a_before['origin'][1]

    valid = ~np.isnan(profile_before) & ~np.isnan(profile_after)
    depth_profile = profile_before[valid] - profile_after[valid]

    metrics = CrossSectionMetrics()

    excavated = depth_profile > 0.01
    if excavated.sum() > 0:
        metrics.depth_at_section = float(np.max(depth_profile[excavated]))
        metrics.width_at_section = float(excavated.sum() * res)

        actual_area = float(depth_profile[excavated].sum() * res)
        metrics.area_actual = actual_area

    if target_grid is not None:
        a_b2, a_t = align_grids(before_grid, target_grid)
        grid_t = a_t['grid']

        if axis == 'y':
            t_row = int((section_pos - a_t['origin'][1]) / a_t['resolution'])
            t_row = np.clip(t_row, 0, grid_t.shape[0] - 1)
            profile_target = grid_t[t_row, :]
            profile_base = a_b2['grid'][t_row, :]
        else:
            t_col = int((section_pos - a_t['origin'][0]) / a_t['resolution'])
            t_col = np.clip(t_col, 0, grid_t.shape[1] - 1)
            profile_target = grid_t[:, t_col]
            profile_base = a_b2['grid'][:, t_col]

        valid_t = ~np.isnan(profile_base) & ~np.isnan(profile_target)
        target_depth_profile = profile_base[valid_t] - profile_target[valid_t]

        target_excavated = target_depth_profile > 0.01
        if target_excavated.sum() > 0:
            metrics.area_target = float(target_depth_profile[target_excavated].sum() * res)

            min_len = min(len(excavated), len(target_excavated))
            exc_s = excavated[:min_len]
            tgt_s = target_excavated[:min_len]
            intersection = float((exc_s & tgt_s).sum())
            union = float((exc_s | tgt_s).sum())
            metrics.iou = intersection / union if union > 0 else 0.0

            overlap_mask = exc_s & tgt_s
            if overlap_mask.sum() > 0:
                dp_min = min(len(depth_profile), min_len)
                tdp_min = min(len(target_depth_profile), min_len)
                overlap_idx = np.where(overlap_mask[:min(dp_min, tdp_min)])[0]
                if len(overlap_idx) > 0:
                    prof_diff = depth_profile[overlap_idx] - target_depth_profile[overlap_idx]
                    metrics.profile_rmse = float(np.sqrt(np.mean(prof_diff ** 2)))

    return metrics


def compute_surface_quality(after_grid: dict, target_grid: dict = None) -> SurfaceQualityMetrics:
    """표면 품질 metric 계산"""
    grid = after_grid['grid']
    valid = ~np.isnan(grid)

    metrics = SurfaceQualityMetrics()

    if valid.sum() < 4:
        return metrics

    total_cells = grid.size
    metrics.surface_completeness = float(valid.sum() / total_cells) * 100

    valid_values = grid[valid]
    from scipy.ndimage import uniform_filter
    smoothed = uniform_filter(np.nan_to_num(grid, nan=np.nanmean(grid)), size=3)
    residuals = grid[valid] - smoothed[valid]

    metrics.roughness_ra = float(np.mean(np.abs(residuals)))
    metrics.roughness_rq = float(np.sqrt(np.mean(residuals ** 2)))

    if target_grid is not None:
        from .grid_converter import align_grids
        a_act, a_tgt = align_grids(after_grid, target_grid)
        g_a = a_act['grid']
        g_t = a_tgt['grid']
        v = ~np.isnan(g_a) & ~np.isnan(g_t)

        if v.sum() > 4:
            safe_a = np.nan_to_num(g_a, nan=np.nanmean(g_a))
            safe_t = np.nan_to_num(g_t, nan=np.nanmean(g_t))
            dy, dx = np.gradient(safe_a)
            dy_t, dx_t = np.gradient(safe_t)
            slope_a = np.arctan(np.sqrt(dx**2 + dy**2))
            slope_t = np.arctan(np.sqrt(dx_t**2 + dy_t**2))
            slope_diff = slope_a[v] - slope_t[v]
            mean_abs_diff = np.mean(np.abs(slope_diff))
            denominator = np.pi / 4
            metrics.slope_consistency = float(np.clip(1.0 - mean_abs_diff / denominator, 0, 1))

    return metrics


def compute_full_report(before_grid: dict, after_grid: dict,
                        target_grid: dict = None,
                        target_params: dict = None,
                        n_cross_sections: int = 5,
                        section_axis: str = 'y') -> FullMetricsReport:
    from .grid_converter import align_grids

    report = FullMetricsReport()

    a_before, a_after = align_grids(before_grid, after_grid)

    if target_grid is not None:
        a_after_t, a_target = align_grids(after_grid, target_grid)
        report.geometric = compute_height_difference_metrics(a_target['grid'], a_after_t['grid'])
    else:
        report.geometric = compute_height_difference_metrics(a_before['grid'], a_after['grid'])

    report.volume = compute_volume_metrics(before_grid, after_grid, target_grid)
    report.excavation = compute_excavation_metrics(before_grid, after_grid, target_grid, target_params)
    report.surface = compute_surface_quality(after_grid, target_grid)

    if section_axis == 'y':
        axis_min = a_before['origin'][1]
        axis_max = axis_min + a_before['grid'].shape[0] * a_before['resolution']
    else:
        axis_min = a_before['origin'][0]
        axis_max = axis_min + a_before['grid'].shape[1] * a_before['resolution']

    section_positions = np.linspace(axis_min + (axis_max - axis_min) * 0.1,
                                    axis_max - (axis_max - axis_min) * 0.1,
                                    n_cross_sections)

    for pos in section_positions:
        cs = compute_cross_section(before_grid, after_grid, target_grid,
                                   section_pos=pos, axis=section_axis)
        report.cross_sections.append({'position': float(pos), 'metrics': cs, 'axis': section_axis})

    return report


def format_report_text(report: FullMetricsReport) -> str:
    """metric 리포트를 텍스트 형태로 포맷팅"""
    lines = []
    lines.append("=" * 60)
    lines.append("  EXCAVATION PERFORMANCE ANALYSIS REPORT")
    lines.append("=" * 60)

    g = report.geometric
    lines.append("\n[1] Geometric Accuracy")
    lines.append(f"  RMSE:              {g.rmse:.4f} m")
    lines.append(f"  MAE:               {g.mae:.4f} m")
    lines.append(f"  Max Error:         {g.max_error:.4f} m")
    lines.append(f"  Std Error:         {g.std_error:.4f} m")
    lines.append(f"  Mean Error:        {g.mean_error:.4f} m")
    lines.append(f"  Median Error:      {g.median_error:.4f} m")
    lines.append(f"  95th Percentile:   {g.percentile_95:.4f} m")
    lines.append(f"  Hausdorff Dist:    {g.hausdorff_distance:.4f} m")
    lines.append(f"  Chamfer Dist:      {g.chamfer_distance:.6f} m^2")

    v = report.volume
    lines.append("\n[2] Volume Analysis")
    lines.append(f"  Cut Volume:        {v.cut_volume:.4f} m^3")
    lines.append(f"  Fill Volume:       {v.fill_volume:.4f} m^3")
    lines.append(f"  Net Volume:        {v.net_volume:.4f} m^3")
    lines.append(f"  Total Volume:      {v.total_volume:.4f} m^3")
    if v.target_cut_volume > 0:
        lines.append(f"  Target Cut Vol:    {v.target_cut_volume:.4f} m^3")
        lines.append(f"  Volume Accuracy:   {v.volume_accuracy:.1f} %")
        lines.append(f"  Over-excavation:   {v.over_excavation_volume:.4f} m^3 ({v.over_excavation_ratio:.1f}%)")
        lines.append(f"  Under-excavation:  {v.under_excavation_volume:.4f} m^3 ({v.under_excavation_ratio:.1f}%)")

    e = report.excavation
    lines.append("\n[3] Excavation Specifics")
    lines.append(f"  Depth Mean:        {e.depth_mean:.4f} m")
    lines.append(f"  Depth Std:         {e.depth_std:.4f} m")
    lines.append(f"  Depth Min:         {e.depth_min:.4f} m")
    lines.append(f"  Depth Max:         {e.depth_max:.4f} m")
    if e.depth_target > 0:
        lines.append(f"  Depth Target:      {e.depth_target:.4f} m")
        lines.append(f"  Depth Error Mean:  {e.depth_error_mean:.4f} m")
        lines.append(f"  Depth Error RMSE:  {e.depth_error_rmse:.4f} m")
    lines.append(f"  Width Mean:        {e.width_mean:.4f} m")
    if e.width_target > 0:
        lines.append(f"  Width Target:      {e.width_target:.4f} m")
        lines.append(f"  Width Error:       {e.width_error:.4f} m")
    lines.append(f"  Bottom Flatness:   {e.bottom_flatness:.4f} m (std)")
    lines.append(f"  Completeness:      {e.completeness:.1f} %")
    lines.append(f"  Precision:         {e.precision:.1f} %")

    s = report.surface
    lines.append("\n[4] Surface Quality")
    lines.append(f"  Roughness Ra:      {s.roughness_ra:.4f} m")
    lines.append(f"  Roughness Rq:      {s.roughness_rq:.4f} m")
    lines.append(f"  Slope Consistency: {s.slope_consistency:.4f}")
    lines.append(f"  Completeness:      {s.surface_completeness:.1f} %")

    if report.cross_sections:
        lines.append("\n[5] Cross-Section Analysis")
        for i, cs_data in enumerate(report.cross_sections):
            cs = cs_data['metrics']
            pos = cs_data['position']
            lines.append(f"  Section {i+1} (Y={pos:.2f}m):")
            lines.append(f"    Depth: {cs.depth_at_section:.4f}m  Width: {cs.width_at_section:.4f}m")
            lines.append(f"    Area (actual/target): {cs.area_actual:.4f}/{cs.area_target:.4f} m^2")
            lines.append(f"    IoU: {cs.iou:.4f}  Profile RMSE: {cs.profile_rmse:.4f}m")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)
