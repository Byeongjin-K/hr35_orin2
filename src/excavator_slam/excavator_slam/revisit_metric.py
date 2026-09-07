"""Revisit consistency of a terrain map: does the second pass land on the first one?

DELIBERATELY ROS-FREE, in the same spirit as the pipeline's global_map_math.hpp and
imu_leveling.hpp: this module takes plain point arrays, so it can be unit-tested
without a bag, a node, or a SLAM stack. Message plumbing belongs in the scripts.

Why the horizontal number is not a nearest-neighbour distance
------------------------------------------------------------
On a dug site the ground is the majority of every scan, and on a locally flat
surface the nearest neighbour of a point sits at the sampling distance no matter
how badly the two passes are aligned horizontally: that number measures point
density, not error, so it cannot fail. The horizontal number here is instead the
rigid xy shift (plus yaw) that best re-registers the second pass onto the first,
found by minimising the height-map residual - DEM co-registration. Zero shift
means the two passes already sit on top of each other. The nearest-neighbour
median is still reported, as a density-aware sanity number only.

Why the candidate shifts are scored on a FIXED cell set
-------------------------------------------------------
Re-binning the moved cloud for every candidate shift looks natural and is wrong:
the set of cells the two passes share changes with the shift, so the cost is an
average over a different sample at every step and can fall for reasons that have
nothing to do with alignment. Measured on aligned synthetic passes, that version
walked to a 0.148 m displacement that does not exist - the same size as the error
this metric has to detect - and more points did not help (0.148 m at 60k points).
So both height maps are built once on a shared grid, and every candidate is scored
by bilinear sampling of the revisit map at the SAME reference cells, chosen so the
whole search box stays inside the revisit COVERAGE.

Coverage, not per-cell occupancy, is what has to be eroded. A height map built at
0.15 m from a single pass is full of pinholes (cells that happen to catch fewer
than min_points_per_cell returns); eroding that mask by the search box demands
hundreds of consecutive filled cells and leaves nothing. So the coverage region is
closed and hole-filled first, pinholes up to max_fill_cells are filled from the
nearest real cell so the sampled surface is continuous, and the erosion runs on
that region (separably, since a square structuring element factorises).

Why the height maps are low-passed before the search
----------------------------------------------------
A cell median built from a handful of returns carries sampling noise that has no
alignment information, and it makes the cost landscape jagged enough for the search
to settle in a noise minimum. Measured worst-case false displacement on aligned
synthetic passes, over five seed pairs: 0.237 m unsmoothed, 0.060 m at a 2-cell
(0.30 m) box filter, while the error on a real injected 0.316 m shift went the other
way, 0.040 m -> 0.031 m at 20k points and 0.032 m -> 0.008 m at 60k. The filter is
wide against sampling noise and narrow against trench walls and spoil piles, so the
features that carry the horizontal information survive it.

Gradient weighting of the cells was tried and rejected: emphasising sloped cells
raised the false displacement to 0.33-1.05 m, because a handful of steep cells
then dominate the average.

Vertical error is reported BEFORE any re-registration, because a constant height
offset between passes is exactly the failure mode the GNSS-anchor map shows and
must not be optimised away.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import (binary_closing, binary_erosion, binary_fill_holes,
                           distance_transform_edt, uniform_filter)
from scipy.spatial import cKDTree

MIN_POINTS_PER_CELL = 2
MIN_OVERLAP_CELLS = 20
MAX_FILL_CELLS = 2
SMOOTH_CELLS = 2
MAX_CELLS = 40_000_000


def _smooth(values, cells):
    """Box-average over the valid cells only, ignoring the empty ones.

    Both maps get the SAME kernel before matching, and that is the point. Bilinear
    sampling at a fractional offset averages four cells and therefore lowers the
    variance of a noisy map; without a fixed pre-smoothing the search discovers
    that it can cut the residual simply by stepping off an integer cell, and walks
    to a displacement that is a multiple of the refinement step rather than a
    property of the terrain (measured: 0.07-0.24 m of pure artefact). Smoothing
    both maps first removes the variance the search was harvesting; a real
    displacement of a real feature survives it.
    """
    if cells <= 0:
        return values
    valid = np.isfinite(values)
    size = 2 * int(cells) + 1
    total = uniform_filter(np.where(valid, values, 0.0), size=size, mode="constant", cval=0.0)
    weight = uniform_filter(valid.astype(float), size=size, mode="constant", cval=0.0)
    return np.where(weight > 0.0, total / np.where(weight > 0.0, weight, 1.0), np.nan)


def _subsample(points, max_points, seed):
    if max_points is None or points.shape[0] <= max_points:
        return points
    rng = np.random.default_rng(seed)
    return points[np.sort(rng.choice(points.shape[0], size=max_points, replace=False))]


def _erode(mask, margin):
    """Erode by a square of half-width margin, one axis at a time.

    A square structuring element factorises into a row and a column, and the
    separable form is what keeps this affordable on a site-sized grid.
    """
    if margin <= 0:
        return mask.copy()
    rows = binary_erosion(mask, structure=np.ones((1, 2 * margin + 1), dtype=bool),
                          border_value=False)
    return binary_erosion(rows, structure=np.ones((2 * margin + 1, 1), dtype=bool),
                          border_value=False)


class _HeightMap:
    """Median height per square cell on a shared grid, with bilinear sampling.

    Median, not mean: a bucket tooth, a dust return or one stray point on the arm
    must not lift a whole cell.
    """

    def __init__(self, points, cell_m, origin, shape, min_points,
                 max_fill_cells=MAX_FILL_CELLS, smooth_cells=SMOOTH_CELLS):
        ny, nx = shape
        ix = np.clip(np.floor((points[:, 0] - origin[0]) / cell_m).astype(np.int64), 0, nx - 1)
        iy = np.clip(np.floor((points[:, 1] - origin[1]) / cell_m).astype(np.int64), 0, ny - 1)
        flat = iy * nx + ix
        order = np.lexsort((points[:, 2], flat))
        flat_sorted = flat[order]
        z_sorted = points[order, 2]
        uniq, start, count = np.unique(flat_sorted, return_index=True, return_counts=True)
        height = z_sorted[start + count // 2]
        keep = count >= min_points
        grid = np.full(ny * nx, np.nan)
        grid[uniq[keep]] = height[keep]
        self.grid = grid.reshape(ny, nx)
        self.valid = np.isfinite(self.grid)
        self.cell_m = cell_m
        self.origin = origin
        self.centres_x = origin[0] + (np.arange(nx) + 0.5) * cell_m
        self.centres_y = origin[1] + (np.arange(ny) + 0.5) * cell_m

        if not self.valid.any():
            self.surface = self.grid.copy()
            self.covered = np.zeros_like(self.valid)
            return
        region = binary_fill_holes(binary_closing(self.valid, structure=np.ones((3, 3), dtype=bool)))
        distance, (near_y, near_x) = distance_transform_edt(~self.valid, return_indices=True)
        self.covered = region & (distance <= max_fill_cells)
        filled = np.where(self.covered, self.grid[near_y, near_x], np.nan)
        self.surface = _smooth(filled, smooth_cells)
        self.covered &= np.isfinite(self.surface)

    def sample(self, x, y):
        """Bilinear height of the filled surface at world xy."""
        gx = (x - self.origin[0]) / self.cell_m - 0.5
        gy = (y - self.origin[1]) / self.cell_m - 0.5
        i0 = np.floor(gx).astype(np.int64)
        j0 = np.floor(gy).astype(np.int64)
        fx = gx - i0
        fy = gy - j0
        ny, nx = self.surface.shape
        inside = (i0 >= 0) & (j0 >= 0) & (i0 <= nx - 2) & (j0 <= ny - 2)
        i0 = np.clip(i0, 0, nx - 2)
        j0 = np.clip(j0, 0, ny - 2)
        s = self.surface
        height = ((1.0 - fx) * (1.0 - fy) * s[j0, i0]
                  + fx * (1.0 - fy) * s[j0, i0 + 1]
                  + (1.0 - fx) * fy * s[j0 + 1, i0]
                  + fx * fy * s[j0 + 1, i0 + 1])
        return height, inside & np.isfinite(height)


def _search_shift(cost, cell_m, search_radius_m, yaw_range_deg):
    """Coarse grid over xy, three refinements, then yaw, then a final xy polish."""
    best = (0.0, 0.0, 0.0)
    best_cost = cost(0.0, 0.0, 0.0)
    steps = int(np.ceil(search_radius_m / cell_m))
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            candidate = cost(i * cell_m, j * cell_m, 0.0)
            if candidate < best_cost:
                best_cost, best = candidate, (i * cell_m, j * cell_m, 0.0)

    def polish(current, current_cost, divisor):
        step = cell_m / divisor
        base_x, base_y, yaw = current
        for i in (-2, -1, 0, 1, 2):
            for j in (-2, -1, 0, 1, 2):
                dx, dy = base_x + i * step, base_y + j * step
                candidate = cost(dx, dy, yaw)
                if candidate < current_cost:
                    current_cost, current = candidate, (dx, dy, yaw)
        return current, current_cost

    for divisor in (3.0, 9.0, 27.0):
        best, best_cost = polish(best, best_cost, divisor)

    if yaw_range_deg > 0.0:
        base_x, base_y, _ = best
        for yaw in np.linspace(-yaw_range_deg, yaw_range_deg, 17):
            candidate = cost(base_x, base_y, float(yaw))
            if candidate < best_cost:
                best_cost, best = candidate, (base_x, base_y, float(yaw))
        best, best_cost = polish(best, best_cost, 27.0)

    return best, best_cost


def revisit_consistency(
    first,
    revisit,
    cell_m=0.15,
    search_radius_m=1.0,
    yaw_range_deg=2.0,
    min_points_per_cell=MIN_POINTS_PER_CELL,
    smooth_cells=1,
    max_points=400000,
    seed=0,
):
    """Compare two passes over the same ground.

    Both arrays are Nx3 (or wider; extra columns are ignored) in ONE common frame -
    world/ENU for the GNSS-anchor baseline, the SLAM map frame for SLAM. The metric
    is intra-map: it asks whether a map is consistent with itself across a revisit,
    so the two candidates never have to share a frame with each other.

    Returns a dict:
      overlap_cells         cells seen by both passes at zero shift
      cost_cells            reference cells the shift search was scored on
      saturated             the best offset sits on the search boundary, so the
                            displacement is a lower bound and the gain is understated
      horizontal_m          xy shift that best re-registers revisit onto first
      shift_xy_m            that shift, signed, as (dx, dy) to apply to revisit
      yaw_deg               yaw of the same re-registration
      dz_median_m           median absolute height difference, BEFORE registration
      dz_bias_m             signed median height difference (systematic offset)
      dz_p90_m              90th percentile absolute height difference
      residual_rms_before_m height-map RMS at zero shift
      residual_rms_m        height-map RMS after the best shift
      nn_median_m           median 3D nearest-neighbour distance (density sanity)
      cell_m                the cell size used
      smooth_cells          box-filter half width applied to both height maps
    """
    first = np.asarray(first, dtype=float)
    revisit = np.asarray(revisit, dtype=float)
    for name, cloud in (("first", first), ("revisit", revisit)):
        if cloud.ndim != 2 or cloud.shape[1] < 3:
            raise ValueError(f"{name} must be an Nx3 array of points, got shape {cloud.shape}")
        if cloud.shape[0] < 3:
            raise ValueError(f"{name} has {cloud.shape[0]} points, too few to compare")

    first = _subsample(first[:, :3], max_points, seed)
    revisit = _subsample(revisit[:, :3], max_points, seed + 1)

    low = np.minimum(first[:, :2].min(axis=0), revisit[:, :2].min(axis=0)) - cell_m
    high = np.maximum(first[:, :2].max(axis=0), revisit[:, :2].max(axis=0)) + cell_m
    nx = int(np.ceil((high[0] - low[0]) / cell_m)) + 1
    ny = int(np.ceil((high[1] - low[1]) / cell_m)) + 1
    if nx * ny > MAX_CELLS:
        raise ValueError(
            f"a {cell_m} m grid over these passes needs {nx * ny} cells; "
            "crop the clouds to the revisited area or use a coarser cell")

    first_map = _HeightMap(first, cell_m, low, (ny, nx), min_points_per_cell,
                           smooth_cells=smooth_cells)
    revisit_map = _HeightMap(revisit, cell_m, low, (ny, nx), min_points_per_cell,
                             smooth_cells=smooth_cells)

    both = first_map.valid & revisit_map.valid
    overlap_cells = int(both.sum())
    if overlap_cells < MIN_OVERLAP_CELLS:
        raise ValueError(
            f"the two passes overlap in only {overlap_cells} cells at {cell_m} m; "
            f"at least {MIN_OVERLAP_CELLS} overlap cells are needed to compare them")
    dz0 = revisit_map.grid[both] - first_map.grid[both]

    # Reference cells for the search: first-pass cells whose whole search box stays
    # inside the revisit coverage, so every candidate shift is scored on the SAME set.
    # Rotation is taken about the centroid of the FIRST pass's coverage, not about the
    # reference set's own mean. The reference set is what erosion produces, and the
    # erosion margin depends on how far a rotation can move a reference cell - so
    # deriving the centre from the reference set would make the margin depend on
    # itself. Anchoring on coverage breaks that loop and bounds the yaw displacement
    # exactly: no reference cell can lie further from this centre than the coverage
    # radius. The earlier version used the grid's half diagonal, which over-erodes
    # badly here, because the grid spans BOTH passes while each pass covers only part
    # of it.
    covered_rows, covered_cols = np.nonzero(first_map.covered)
    centre_x = float(first_map.centres_x[covered_cols].mean())
    centre_y = float(first_map.centres_y[covered_rows].mean())
    coverage_radius_m = float(np.hypot(first_map.centres_x[covered_cols] - centre_x,
                                       first_map.centres_y[covered_rows] - centre_y).max())
    yaw_swing_m = np.radians(max(yaw_range_deg, 0.0)) * coverage_radius_m
    margin = int(np.ceil((search_radius_m + yaw_swing_m) / cell_m)) + 2
    fixed = first_map.covered & _erode(revisit_map.covered, margin)
    cost_cells = int(fixed.sum())
    if cost_cells < MIN_OVERLAP_CELLS:
        raise ValueError(
            f"only {cost_cells} reference cells survive a {search_radius_m} m search margin "
            f"({margin} cells) inside the revisit coverage; shrink search_radius_m or "
            "yaw_range_deg, or compare a wider revisited area")

    rows, cols = np.nonzero(fixed)
    ref_x = first_map.centres_x[cols]
    ref_y = first_map.centres_y[rows]
    # Both sides come off the same hole-filled, identically smoothed surface, so the
    # match is like for like; _smooth explains why the kernel has to be shared.
    ref_h = first_map.surface[rows, cols]

    def cost(dx, dy, yaw_deg):
        if yaw_deg == 0.0:
            sample_x, sample_y = ref_x + dx, ref_y + dy
        else:
            yaw = np.radians(yaw_deg)
            cos_y, sin_y = np.cos(yaw), np.sin(yaw)
            rel_x, rel_y = ref_x - centre_x, ref_y - centre_y
            sample_x = centre_x + cos_y * rel_x - sin_y * rel_y + dx
            sample_y = centre_y + sin_y * rel_x + cos_y * rel_y + dy
        height, ok = revisit_map.sample(sample_x, sample_y)
        if int(ok.sum()) < MIN_OVERLAP_CELLS:
            return float("inf")
        difference = height[ok] - ref_h[ok]
        difference = difference - np.median(difference)
        return float(np.sqrt(np.mean(difference * difference)))

    (offset_x, offset_y, offset_yaw), residual = _search_shift(
        cost, cell_m, search_radius_m, yaw_range_deg)

    # An answer pinned against the search wall is a LOWER BOUND, not a measurement,
    # and it drags the residual gain down with it because the minimum was never
    # reached. Measured on the real bag, the deployed baseline came back with both
    # components at the reach and yaw at its range end; read as a number that is a
    # 1.69 m displacement, read honestly it is "at least 1.69 m". The caller cannot
    # tell those apart from the numbers alone, so the metric says it.
    reach_m = float(np.ceil(search_radius_m / cell_m) * cell_m)
    saturated = bool(max(abs(offset_x), abs(offset_y)) >= reach_m - 1e-9
                     or (yaw_range_deg > 0.0 and abs(offset_yaw) >= yaw_range_deg - 1e-9))

    # The search moves the SAMPLING point; the correction to apply to the revisit
    # pass is the opposite of it.
    nn_distance = cKDTree(first).query(revisit, k=1)[0]
    return {
        "overlap_cells": overlap_cells,
        "cost_cells": cost_cells,
        "saturated": saturated,
        "horizontal_m": float(np.hypot(offset_x, offset_y)),
        "shift_xy_m": (float(-offset_x), float(-offset_y)),
        "yaw_deg": float(-offset_yaw),
        "dz_median_m": float(np.median(np.abs(dz0))),
        "dz_bias_m": float(np.median(dz0)),
        "dz_p90_m": float(np.percentile(np.abs(dz0), 90.0)),
        "residual_rms_before_m": float(cost(0.0, 0.0, 0.0)),
        "residual_rms_m": float(residual),
        "nn_median_m": float(np.median(nn_distance)),
        "cell_m": float(cell_m),
        "smooth_cells": int(smooth_cells),
    }
