"""What a capture session actually writes to disk.

The pure modules are covered on their own, but nothing exercised the node that
joins them, and a capture session is unrepeatable: the machine is running, the
operator is waiting, and a bundle that turns out to be unreadable offline costs
another field visit. This drives the node with synthetic messages instead of
live topics, so the file layout stays pinned without hardware.
"""

from __future__ import annotations

import array
import json

import numpy as np
import pytest

rclpy = pytest.importorskip("rclpy")

import cv2
from sensor_msgs.msg import CameraInfo, CompressedImage, PointCloud2, PointField

from excavator_ar_overlay.snapshot_capture_node import SnapshotCaptureNode
from excavator_ar_overlay.target_pick import xyz_from_capture

# One beam of the second row never came back, which is the case a flat point
# list used to erase.
POINTS = [
    (1.0, 2.0, 3.0, 11.0),
    (4.0, 5.0, 6.0, 12.0),
    (0.0, 0.0, 0.0, 0.0),
    (7.0, 8.0, 9.0, 14.0),
]


@pytest.fixture
def node(tmp_path):
    rclpy.init(args=["pytest", "--ros-args", "-p", f"capture.output_dir:={tmp_path}"])
    created = SnapshotCaptureNode()
    try:
        yield created
    finally:
        created.destroy_node()
        rclpy.shutdown()


def make_cloud(points, width=2, height=2) -> PointCloud2:
    msg = PointCloud2()
    msg.header.frame_id = "lidar_boom/os_lidar"
    msg.height, msg.width = height, width
    msg.fields = [
        PointField(name=name, offset=offset, datatype=PointField.FLOAT32, count=1)
        for name, offset in (("x", 0), ("y", 4), ("z", 8), ("intensity", 12))
    ]
    msg.point_step = 16
    msg.row_step = msg.point_step * width
    buf = bytearray()
    for point in points:
        buf += np.array(point, dtype="<f4").tobytes()
    msg.data = array.array("B", buf)
    return msg


def make_image(mean: int = 128) -> CompressedImage:
    frame = np.full((8, 8, 3), mean, dtype=np.uint8)
    msg = CompressedImage()
    msg.format = "bgr8; jpeg compressed bgr8"
    msg.data = array.array("B", cv2.imencode(".jpg", frame)[1].tobytes())
    return msg


def make_info() -> CameraInfo:
    msg = CameraInfo()
    msg.width, msg.height = 1280, 800
    msg.header.frame_id = "zedx_cabin_left_camera_optical_frame"
    msg.k = np.array(
        [849.456, 0.0, 604.451, 0.0, 849.456, 366.265, 0.0, 0.0, 1.0],
        dtype=np.float64,
    )
    msg.d = [0.0] * 5
    return msg


def kinematic_frames() -> dict:
    """What TF looks like once the stack publishing the gm_ frames is up."""
    identity = {"translation": [0.0, 0.0, 0.0], "rotation_xyzw": [0.0, 0.0, 0.0, 1.0]}
    return {frame: dict(identity) for frame in ("gm_os_lidar", "gm_swing_axis")}


def feed(node, transforms=None) -> None:
    node._on_cloud(make_cloud(POINTS))
    node._on_image(make_image())
    node._on_info(make_info())
    node._freeze_transforms = lambda: (
        kinematic_frames() if transforms is None else transforms
    )


def saved(node, tmp_path):
    assert node._save(np.array([0.0]), "interval") is True
    stem = next(tmp_path.glob("*_meta.json")).with_name(
        next(tmp_path.glob("*_meta.json")).name.replace("_meta.json", "")
    )
    return stem


def test_a_capture_writes_cloud_image_and_meta(node, tmp_path):
    feed(node)
    stem = saved(node, tmp_path)
    for suffix in ("_cloud.npy", "_image.jpg", "_meta.json"):
        assert stem.with_name(stem.name + suffix).exists()


def test_the_saved_cloud_keeps_the_grid_and_the_intensity_channel(node, tmp_path):
    feed(node)
    stem = saved(node, tmp_path)
    cloud = np.load(f"{stem}_cloud.npy")
    assert cloud.shape == (2, 2, 4)
    assert np.allclose(cloud[0, 0], [1.0, 2.0, 3.0, 11.0])
    assert np.isnan(cloud[1, 0, 0])  # the non-return keeps its place in the grid
    assert cloud[1, 1, 3] == pytest.approx(14.0)


def test_the_saved_cloud_reads_back_as_correspondence_input(node, tmp_path):
    feed(node)
    stem = saved(node, tmp_path)
    points = xyz_from_capture(np.load(f"{stem}_cloud.npy"))
    assert points.shape == (3, 3)
    assert np.allclose(points[-1], [7.0, 8.0, 9.0])


def test_meta_records_the_layout_and_counts_only_real_returns(node, tmp_path):
    feed(node)
    stem = saved(node, tmp_path)
    meta = json.loads(stem.with_name(stem.name + "_meta.json").read_text())
    assert meta["cloud_points"] == 3
    assert meta["cloud_layout"]["shape"] == [2, 2, 4]
    assert meta["cloud_layout"]["channels"] == ["x", "y", "z", "intensity"]
    assert meta["camera_info"]["width"] == 1280


def test_a_stalled_camera_stops_the_second_capture(node, tmp_path):
    """The freshness gate is what keeps duplicate frames out of a session."""
    feed(node)
    assert node._save(np.array([0.0]), "interval") is True
    node._on_cloud(make_cloud(POINTS))  # cloud moves on, image does not
    assert node._save(np.array([1.0]), "interval") is False


def test_incomplete_inputs_do_not_write_a_bundle(node, tmp_path):
    node._on_cloud(make_cloud(POINTS))
    assert node._save(np.array([0.0]), "interval") is False
    assert list(tmp_path.glob("*")) == []


def test_a_bundle_the_solve_could_not_use_is_refused(node, tmp_path):
    """Measured on 2026-09-22: sensors alone let three unusable shots through."""
    feed(node, transforms={"gm_os_lidar": {"error": "frame does not exist"}})
    assert node._save(np.array([0.0]), "interval") is False
    assert list(tmp_path.glob("*")) == []
