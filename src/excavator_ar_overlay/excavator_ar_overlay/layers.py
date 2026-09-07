"""LiDAR and dig-plan layers: mutate a BGR frame and return HUD status.

Only arrays, camera geometry and retained data enter these functions; ROS
message availability, TF lookup and logging belong to the node adapter.
"""

from __future__ import annotations

import numpy as np

from excavator_ar_overlay import rendering
from excavator_ar_overlay.camera_model import PinholeModel
from excavator_ar_overlay.dig_plan import (
    CELL_SIZE_M,
    CENTER_COL,
    cell_corners,
    remaining_to_color,
    remaining_to_colors,
)
from excavator_ar_overlay.geometry import apply_transform


def draw_cloud(
    frame: np.ndarray, model: PinholeModel, points: np.ndarray,
    matrix: np.ndarray, source_frame: str, *, min_depth_m: float,
    near_m: float, far_m: float, point_radius_px: int,
) -> "tuple[int, str]":
    if points.shape[0] == 0:
        return 0, "empty cloud"

    in_camera = apply_transform(matrix, points)
    uv, keep = model.project(in_camera, min_depth_m)
    if uv.shape[0] == 0:
        return 0, "no points in view"

    depths = np.linalg.norm(points[keep], axis=1)
    colors = rendering.depth_colors(depths, near_m, far_m)
    rendering.draw_points(frame, uv, colors, point_radius_px)
    return int(uv.shape[0]), f"TF ok: {source_frame}"


def draw_dig_plan(
    frame: np.ndarray, model: PinholeModel, action, heights: np.ndarray,
    height_note: str, matrix: np.ndarray, terrain, *, min_depth_m: float,
    fill_alpha: float, outline_thickness: int, start_marker_radius_px: int,
    font_scale: float,
) -> "list[str]":
    """Project the retained AI dig cells and fill them by remaining depth."""
    corners = cell_corners(action.rows, action.cols, heights)
    n_cells = corners.shape[0]

    in_camera = apply_transform(matrix, corners.reshape(-1, 3))
    uv, keep = model.project(in_camera, min_depth_m)

    uv_all = np.full((n_cells * 4, 2), np.nan, dtype=np.float64)
    uv_all[keep] = uv
    cell_uv = uv_all.reshape(n_cells, 4, 2)
    cell_ok = keep.reshape(n_cells, 4).all(axis=1)
    if not cell_ok.any():
        return [f"dig plan: {action.phase}, {n_cells} cells off-screen"]

    shown = np.flatnonzero(cell_ok)
    colors, color_note = cell_colors(action, shown, terrain)
    polygons = [cell_uv[i].round().astype(np.int32) for i in shown]
    rendering.draw_filled_polygons(
        frame,
        polygons,
        colors,
        fill_alpha,
        outline_thickness,
    )
    draw_start_marker(
        frame, action, cell_uv, cell_ok, start_marker_radius_px, font_scale
    )

    lines = action.hud_lines()
    lines.append(f"cells drawn: {int(cell_ok.sum())}/{n_cells}  {height_note}")
    lines.append(f"colour: {color_note}")
    return lines


def cell_colors(action, shown: np.ndarray, terrain) -> "tuple[list, str]":
    """Per-cell colour from TaskInfo, falling back to the action-wide mean.

    current-target is a difference, so it does not care what datum the two
    heights share. That is why colour can come from TaskInfo even though the
    3D placement height deliberately does not.
    """
    if terrain is None:
        color = remaining_to_color(action.mean_remaining_delta_units)
        return [color] * shown.size, "action mean (no task_info)"

    values, valid = terrain.remaining_units(action.rows[shown], action.cols[shown])
    if not valid.any():
        color = remaining_to_color(action.mean_remaining_delta_units)
        return [color] * shown.size, "action mean (cells outside work mask)"

    rgb = remaining_to_colors(values, valid)
    colors = [tuple(int(c) for c in row) for row in rgb]
    return colors, f"per-cell ({int(valid.sum())}/{valid.size})"


def cell_heights(
    action, anchor: str, grid, fallback: float, to_grid: "np.ndarray | None" = None,
) -> "tuple[np.ndarray, str]":
    """Per-cell z, from the grid map when available, else a flat fallback.

    For a grid in a different frame, to_grid is the resolved transform matrix;
    None means that TF was unavailable.
    """
    heights = np.full(action.rows.shape[0], fallback, dtype=np.float64)
    if grid is None:
        return heights, "height: flat fallback (no grid map)"

    centers = np.stack(
        (
            action.rows.astype(np.float64) * CELL_SIZE_M,
            (action.cols.astype(np.float64) - CENTER_COL) * CELL_SIZE_M,
        ),
        axis=1,
    )
    if grid.frame_id and grid.frame_id != anchor:
        if to_grid is None:
            return heights, f"height: fallback (no TF {anchor}->{grid.frame_id})"
        padded = np.column_stack((centers, np.zeros(centers.shape[0])))
        centers = apply_transform(to_grid, padded)[:, :2]

    sampled, valid = grid.sample(centers)
    heights[valid] = sampled[valid]
    return heights, f"height: grid map ({int(valid.sum())}/{valid.size} cells)"


def draw_start_marker(
    frame: np.ndarray, action, cell_uv: np.ndarray, cell_ok: np.ndarray,
    radius: int, font_scale: float,
) -> None:
    match = np.flatnonzero(
        (action.rows == action.start_row) & (action.cols == action.start_col)
    )
    if match.size == 0 or not cell_ok[match[0]]:
        return
    center = cell_uv[match[0]].mean(axis=0)
    rendering.draw_start_marker(
        frame,
        (int(round(center[0])), int(round(center[1]))),
        radius,
        "start",
        font_scale,
    )
