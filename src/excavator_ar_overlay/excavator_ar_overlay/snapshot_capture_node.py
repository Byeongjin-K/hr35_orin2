"""Capture calibration snapshots automatically whenever the boom holds still.

Why this instead of a rosbag: a bag of the LiDAR runs about 35 MB/s, so a
useful session is several GB and takes half an hour of moving a target around.
None of that volume is needed. One cloud and one image per pose is enough, which
is roughly 1.2 MB, so a whole session fits in ~10 MB and a couple of minutes.

Why boom motion alone is enough now: the camera sits on the cabin and the LiDAR
rides the boom. Sweeping the boom therefore moves the LiDAR through a range of
viewpoints while the camera and the scene stay put, which is exactly the
diversity the fit was missing. The target does not have to be carried around.

Why stillness matters: the Ouster stamps clouds with sensor uptime (order 1e4 s)
and the ZED with epoch time (order 1e9 s), so the two streams cannot be time
aligned. Holding the boom still removes the question, and this node waits for
that rather than trusting the operator to press a key at the right instant.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, CompressedImage, PointCloud2
from tf2_ros import TransformException
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener

from excavator_ar_overlay import params as ar_params
from excavator_ar_overlay.pointcloud import extract_xyz

_SENSOR_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    durability=DurabilityPolicy.VOLATILE,
)

# Frames whose pose is worth freezing alongside each snapshot.
_TRACKED_FRAMES = (
    "gm_swing_axis",
    "gm_boom_hinge",
    "gm_boom_link",
    "gm_lidar_mount",
    "gm_os_lidar",
    "lidar_boom/os_sensor",
    "lidar_boom/os_lidar",
)


class SnapshotCaptureNode(Node):
    def __init__(self) -> None:
        super().__init__("snapshot_capture_node")
        ar_params.declare_all(self)
        self._declare_capture_params()

        self._out = Path(self._p("capture.output_dir")).expanduser()
        self._out.mkdir(parents=True, exist_ok=True)

        self._image: "CompressedImage | None" = None
        self._info: "CameraInfo | None" = None
        self._cloud: "PointCloud2 | None" = None

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        self._still_since: "float | None" = None
        self._last_pitch: "float | None" = None
        self._captured_pitches: "list[float]" = []

        self.create_subscription(
            CompressedImage, self._p("topics.image_in"), self._on_image, _SENSOR_QOS
        )
        self.create_subscription(
            CameraInfo, self._p("topics.camera_info_in"), self._on_info, _SENSOR_QOS
        )
        self.create_subscription(
            PointCloud2, self._p("topics.points_in"), self._on_cloud, _SENSOR_QOS
        )
        self.create_timer(0.25, self._tick)

        self.get_logger().info(
            f"snapshot capture ready -> {self._out}\n"
            f"  sweep the boom, pause ~{self._p('capture.still_seconds'):.0f}s, repeat.\n"
            f"  poses at least {self._p('capture.min_pitch_step_deg'):.0f} deg apart "
            f"are kept; target {self._p('capture.target_poses')}."
        )

    def _declare_capture_params(self) -> None:
        from rcl_interfaces.msg import ParameterDescriptor

        extra = (
            ("capture.output_dir", "~/data/lidar_cam_calib", "Where bundles are written."),
            ("capture.still_seconds", 2.0, "Hold time before a pose is accepted."),
            (
                "capture.still_tolerance_deg",
                0.25,
                "Boom pitch movement under this counts as still.",
            ),
            (
                "capture.min_pitch_step_deg",
                4.0,
                "A new pose must differ from every captured one by at least this, "
                "which is what forces boom-angle diversity instead of ten "
                "snapshots of the same attitude.",
            ),
            ("capture.target_poses", 8, "Poses to aim for; capture continues past it."),
            (
                "capture.boom_frame",
                "gm_boom_link",
                "Frame watched for stillness and pose spacing.",
            ),
        )
        for name, default, desc in extra:
            self.declare_parameter(name, default, ParameterDescriptor(description=desc))

    def _p(self, name: str):
        return self.get_parameter(name).value

    def _on_image(self, msg: CompressedImage) -> None:
        self._image = msg

    def _on_info(self, msg: CameraInfo) -> None:
        self._info = msg

    def _on_cloud(self, msg: PointCloud2) -> None:
        self._cloud = msg

    def _boom_pitch_deg(self) -> "float | None":
        try:
            tf = self._tf_buffer.lookup_transform(
                "map", self._p("capture.boom_frame"), Time()
            )
        except TransformException:
            return None
        q = tf.transform.rotation
        sin_pitch = 2.0 * (q.w * q.y - q.z * q.x)
        return math.degrees(math.asin(max(-1.0, min(1.0, sin_pitch))))

    def _tick(self) -> None:
        pitch = self._boom_pitch_deg()
        if pitch is None:
            self.get_logger().warn(
                "no TF for the boom frame yet", throttle_duration_sec=5.0
            )
            return

        now = self.get_clock().now().nanoseconds / 1e9
        tol = float(self._p("capture.still_tolerance_deg"))
        if self._last_pitch is None or abs(pitch - self._last_pitch) > tol:
            self._still_since = now
        self._last_pitch = pitch

        if self._still_since is None:
            return
        if now - self._still_since < float(self._p("capture.still_seconds")):
            return

        step = float(self._p("capture.min_pitch_step_deg"))
        if any(abs(pitch - p) < step for p in self._captured_pitches):
            self.get_logger().info(
                f"boom still at {pitch:+.1f} deg but too close to an existing pose; "
                f"move it at least {step:.0f} deg",
                throttle_duration_sec=6.0,
            )
            return

        if self._save(pitch):
            self._captured_pitches.append(pitch)
            self._still_since = None

    def _save(self, pitch: float) -> bool:
        if self._cloud is None or self._image is None or self._info is None:
            self.get_logger().warn(
                "still, but inputs are incomplete "
                f"(cloud={self._cloud is not None} image={self._image is not None} "
                f"info={self._info is not None})",
                throttle_duration_sec=5.0,
            )
            return False

        index = len(self._captured_pitches)
        stem = self._out / f"pose{index:02d}_boom{pitch:+06.1f}"
        points = extract_xyz(self._cloud, 0)
        np.save(f"{stem}_cloud.npy", points.astype(np.float32))
        Path(f"{stem}_image.jpg").write_bytes(bytes(self._image.data))

        meta = {
            "boom_pitch_deg": pitch,
            "cloud_frame": self._cloud.header.frame_id,
            "cloud_points": int(points.shape[0]),
            "image_topic": self._p("topics.image_in"),
            "camera_info": {
                "width": int(self._info.width),
                "height": int(self._info.height),
                "frame_id": self._info.header.frame_id,
                "k": [float(v) for v in self._info.k],
                "d": [float(v) for v in self._info.d],
            },
            "transforms": self._freeze_transforms(),
        }
        Path(f"{stem}_meta.json").write_text(json.dumps(meta, indent=2))

        size_mb = (points.nbytes + len(self._image.data)) / 1e6
        self.get_logger().info(
            f"pose {index} captured at boom {pitch:+.1f} deg "
            f"({points.shape[0]} pts, {size_mb:.1f} MB) -> {stem.name}  "
            f"[{index + 1}/{self._p('capture.target_poses')}]"
        )
        return True

    def _freeze_transforms(self) -> dict:
        """Snapshot map->frame for everything the offline solve may need."""
        out = {}
        frames = list(_TRACKED_FRAMES) + [self._p("extrinsic.child_frame")]
        for frame in frames:
            try:
                tf = self._tf_buffer.lookup_transform("map", frame, Time())
            except TransformException as exc:
                out[frame] = {"error": str(exc)}
                continue
            t, r = tf.transform.translation, tf.transform.rotation
            out[frame] = {
                "translation": [t.x, t.y, t.z],
                "rotation_xyzw": [r.x, r.y, r.z, r.w],
            }
        return out


def main(args=None) -> None:
    rclpy.init(args=args)
    node = SnapshotCaptureNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
