"""Reading a binary format nobody wrote a spec for, so the layout is pinned by test."""

from __future__ import annotations

import numpy as np
import pytest

from excavator_slam.glim_dump import (
    dump_points_in_map,
    parse_pose,
    read_dump,
    read_submap,
)

HEADER = """id: {identifier}
T_world_origin: 
{pose}
T_lidar_imu: 
1 0 0 0
0 1 0 0
0 0 1 0
0 0 0 1
num_frames: 3
"""


def _pose_text(matrix):
    return "\n".join(" ".join(f"{value:.6f}" for value in row) for row in matrix)


def _write_submap(root, name, points, pose):
    directory = root / name
    directory.mkdir()
    (directory / "data.txt").write_text(
        HEADER.format(identifier=name, pose=_pose_text(pose)))
    np.asarray(points, dtype=np.float32).tofile(directory / "points_compact.bin")
    return directory


def _yaw_pose(degrees, translation):
    angle = np.radians(degrees)
    pose = np.eye(4)
    pose[:3, :3] = [[np.cos(angle), -np.sin(angle), 0.0],
                    [np.sin(angle), np.cos(angle), 0.0],
                    [0.0, 0.0, 1.0]]
    pose[:3, 3] = translation
    return pose


def test_a_submap_reads_back_as_xyz_triples(tmp_path):
    points = np.array([[1.0, 2.0, 3.0], [-4.0, 5.0, -6.0]])
    directory = _write_submap(tmp_path, "000000", points, np.eye(4))
    submap = read_submap(directory)

    assert submap.identifier == "000000"
    assert submap.points == pytest.approx(points, abs=1e-6)


def test_the_submap_pose_carries_its_points_into_the_map_frame(tmp_path):
    directory = _write_submap(tmp_path, "000000", [[1.0, 0.0, 0.0]],
                              _yaw_pose(90.0, [10.0, -2.0, 0.5]))
    placed = read_submap(directory).points_in_map()
    assert placed[0] == pytest.approx(np.array([10.0, -1.0, 0.5]), abs=1e-6)


def test_submaps_come_back_in_id_order_and_concatenated(tmp_path):
    _write_submap(tmp_path, "000001", [[0.0, 1.0, 0.0]], _yaw_pose(0.0, [0.0, 0.0, 0.0]))
    _write_submap(tmp_path, "000000", [[1.0, 0.0, 0.0]], _yaw_pose(0.0, [0.0, 0.0, 0.0]))

    assert [submap.identifier for submap in read_dump(tmp_path)] == ["000000", "000001"]
    assert dump_points_in_map(tmp_path) == pytest.approx(
        np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]), abs=1e-6)


def test_a_binary_that_is_not_whole_xyz_points_is_refused(tmp_path):
    """The failure this guard exists for: a different layout read as xyz is not an error
    anywhere downstream, it is just a map made of shredded coordinates."""
    directory = tmp_path / "000000"
    directory.mkdir()
    (directory / "data.txt").write_text(
        HEADER.format(identifier="000000", pose=_pose_text(np.eye(4))))
    np.arange(7, dtype=np.float32).tofile(directory / "points_compact.bin")

    with pytest.raises(ValueError):
        read_submap(directory)


def test_a_directory_missing_its_header_is_refused(tmp_path):
    directory = tmp_path / "000000"
    directory.mkdir()
    np.zeros(3, dtype=np.float32).tofile(directory / "points_compact.bin")
    with pytest.raises(ValueError):
        read_submap(directory)


def test_an_empty_dump_is_an_error_rather_than_an_empty_map(tmp_path):
    with pytest.raises(ValueError):
        read_dump(tmp_path)


def test_a_header_without_the_pose_block_is_refused():
    with pytest.raises(ValueError):
        parse_pose("id: 0\nnum_frames: 3\n")
