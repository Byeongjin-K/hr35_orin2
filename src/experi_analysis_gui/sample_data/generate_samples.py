import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def generate_full_sample(trench_depth=1.0, trench_width=0.8, noise_level=0.03):
    from core.target_generator import generate_flat_terrain, generate_trench_target

    x_range = (-3.0, 3.0)
    y_range = (-3.0, 3.0)
    resolution = 0.05

    before = generate_flat_terrain(x_range, y_range, resolution, base_height=0.0, noise_std=0.005)

    target = generate_trench_target(
        x_range, y_range, resolution,
        base_height=0.0,
        trench_depth=trench_depth,
        trench_width=trench_width,
        wall_angle=80.0,
        bottom_slope=0.01
    )

    after_grid = target['grid'].copy()

    after_grid += np.random.normal(0, noise_level, after_grid.shape)

    ny, nx = after_grid.shape
    for j in range(ny):
        for i in range(nx):
            depth = before['grid'][j, i] - target['grid'][j, i]
            if depth > 0.1:
                depth_error = np.random.uniform(-0.05, 0.08)
                after_grid[j, i] += depth_error

    width_shift = int(0.02 / resolution)
    if width_shift > 0:
        shifted = np.roll(after_grid, width_shift, axis=0)
        blend = 0.3
        after_grid = (1 - blend) * after_grid + blend * shifted

    after = {
        'grid': after_grid,
        'resolution': resolution,
        'origin': target['origin'],
        'x_edges': target['x_edges'],
        'y_edges': target['y_edges'],
    }

    return before, after, target


def generate_grading_sample():
    from core.target_generator import generate_flat_terrain, generate_grading_target

    x_range = (-5.0, 5.0)
    y_range = (-5.0, 5.0)
    resolution = 0.05

    before_grid_data = np.zeros((int(10 / resolution) + 1, int(10 / resolution) + 1))
    x_edges = np.arange(x_range[0], x_range[1] + resolution, resolution)[:before_grid_data.shape[1]]
    y_edges = np.arange(y_range[0], y_range[1] + resolution, resolution)[:before_grid_data.shape[0]]

    for j, y in enumerate(y_edges):
        for i, x in enumerate(x_edges):
            before_grid_data[j, i] = 0.3 * np.sin(x * 0.5) + 0.2 * np.cos(y * 0.3) + np.random.normal(0, 0.01)

    before = {
        'grid': before_grid_data,
        'resolution': resolution,
        'origin': (x_range[0], y_range[0]),
        'x_edges': x_edges,
        'y_edges': y_edges,
    }

    target = generate_grading_target(x_range, y_range, resolution, target_height=0.0, slope_x=0.02)

    after_grid = target['grid'].copy() + np.random.normal(0, 0.02, target['grid'].shape)
    after = {
        'grid': after_grid,
        'resolution': resolution,
        'origin': target['origin'],
        'x_edges': target['x_edges'],
        'y_edges': target['y_edges'],
    }

    return before, after, target


def generate_pit_sample():
    from core.target_generator import generate_flat_terrain, generate_pit_target

    x_range = (-4.0, 4.0)
    y_range = (-4.0, 4.0)
    resolution = 0.05

    before = generate_flat_terrain(x_range, y_range, resolution, base_height=0.0, noise_std=0.005)

    target = generate_pit_target(
        x_range, y_range, resolution,
        base_height=0.0,
        pit_depth=1.5,
        pit_width_x=3.0,
        pit_width_y=2.0,
        wall_angle=70.0,
        shape='rectangular'
    )

    after_grid = target['grid'].copy() + np.random.normal(0, 0.04, target['grid'].shape)
    after = {
        'grid': after_grid,
        'resolution': resolution,
        'origin': target['origin'],
        'x_edges': target['x_edges'],
        'y_edges': target['y_edges'],
    }

    return before, after, target


if __name__ == '__main__':
    print("Generating trench sample...")
    b, a, t = generate_full_sample()
    print(f"  Before: {b['grid'].shape}, After: {a['grid'].shape}, Target: {t['grid'].shape}")

    print("Generating grading sample...")
    b, a, t = generate_grading_sample()
    print(f"  Before: {b['grid'].shape}, After: {a['grid'].shape}, Target: {t['grid'].shape}")

    print("Generating pit sample...")
    b, a, t = generate_pit_sample()
    print(f"  Before: {b['grid'].shape}, After: {a['grid'].shape}, Target: {t['grid'].shape}")

    print("All samples generated successfully!")
