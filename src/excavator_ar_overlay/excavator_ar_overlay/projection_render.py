"""ROS image/TF adapter for the pure overlay layers.

TF is looked up at time 0 (latest available) on purpose. The Ouster stamps
its clouds with sensor uptime (order 1e4 s) while the camera stamps with
epoch time (order 1e9 s), so a stamped lookup cannot succeed. The transform
being resolved is static, so "latest" is also the correct answer.
"""

from __future__ import annotations

import cv2
import numpy as np
import rclpy
from rclpy.time import Time
from sensor_msgs.msg import CompressedImage
from tf2_ros import TransformException

from excavator_ar_overlay import layers, rendering
from excavator_ar_overlay.camera_model import PinholeModel
from excavator_ar_overlay.geometry import transform_to_matrix
from excavator_ar_overlay.pointcloud import extract_xyz
from excavator_ar_overlay.projection_interfaces import AiActionStatus, _LOG_THROTTLE_MS


class ProjectionRenderMixin:
    """Render-timer methods of LidarProjectionNode; owns no separate state."""

    def _render(self) -> None:
        out_w = int(self._p("publish.width"))
        out_h = int(self._p("publish.height"))

        frame = self._decode_frame(out_w, out_h)
        if frame is None:
            frame = np.zeros((out_h, out_w, 3), dtype=np.uint8)
            rendering.draw_banner(frame, "no camera image", 0.8)
            self._publish(frame)
            return

        status = []
        drawn = 0
        model = self._camera_model(frame.shape[1], frame.shape[0])

        if model is None:
            status.append("waiting for camera_info")
        else:
            if self._p("layers.lidar_points"):
                drawn, note = self._draw_cloud(frame, model)
                status.append(f"lidar: {note} ({drawn} pts)")
            if self._p("layers.dig_plan"):
                status.extend(self._draw_dig_plan(frame, model))

        scale = float(self._p("hud.font_scale"))
        rendering.draw_hud(frame, status or ["overlay idle"], scale)
        if self._p("layers.lidar_points"):
            rendering.draw_depth_legend(
                frame,
                float(self._p("lidar.near_m")),
                float(self._p("lidar.far_m")),
                scale,
            )
        self._publish(frame)

    def _decode_frame(self, out_w: int, out_h: int) -> "np.ndarray | None":
        if self._image is None:
            return None
        buffer = np.frombuffer(self._image.data, dtype=np.uint8)
        # imdecode already yields BGR. Swapping channels here turns the sky
        # orange, despite what the ZED 'format' string suggests.
        decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if decoded is None:
            self.get_logger().warn_once("failed to decode the camera JPEG")
            return None
        self._reconcile_info(decoded.shape[1], decoded.shape[0])
        if (decoded.shape[1], decoded.shape[0]) != (out_w, out_h):
            decoded = cv2.resize(decoded, (out_w, out_h), interpolation=cv2.INTER_AREA)
        return decoded

    def _reconcile_info(self, image_w: int, image_h: int) -> None:
        """Log once per throttle window if CameraInfo disagrees with the image."""
        if self._info is None:
            return
        _, warning = PinholeModel.from_camera_info_values(
            self._info.k, self._info.width, self._info.height
        ).reconcile_to_image(image_w, image_h)
        if warning and warning != self._info_warning:
            self._info_warning = warning
            self.get_logger().warn(warning)

    def _camera_model(self, out_w: int, out_h: int) -> "PinholeModel | None":
        if self._info is None:
            return None
        try:
            base = PinholeModel.from_camera_info_values(
                self._info.k, self._info.width, self._info.height
            )
        except ValueError as exc:
            self.get_logger().warn_once(f"unusable camera_info: {exc}")
            return None
        model, _ = base.reconcile_to_image(out_w, out_h)
        return model

    def _draw_cloud(self, frame: np.ndarray, model: PinholeModel) -> "tuple[int, str]":
        if self._cloud is None:
            return 0, "waiting for LiDAR cloud"

        cloud = self._cloud
        # The cloud's own header frame hangs off a hardcoded placeholder in
        # bringup; override_frame lets the kinematic frame be substituted so the
        # two chains can be compared without touching the driver.
        source_frame = self._p("lidar.override_frame") or cloud.header.frame_id
        try:
            transform = self._tf_buffer.lookup_transform(
                self._p("extrinsic.child_frame"),
                source_frame,
                Time(),
                timeout=rclpy.duration.Duration(
                    seconds=float(self._p("tf.lookup_timeout_s"))
                ),
            )
        except TransformException as exc:
            self.get_logger().warn(
                f"TF {source_frame} -> "
                f"{self._p('extrinsic.child_frame')} unavailable: {exc}",
                throttle_duration_sec=_LOG_THROTTLE_MS / 1000.0,
            )
            return 0, "TF unavailable"

        points = extract_xyz(cloud, int(self._p("lidar.max_points")))
        if points.shape[0] == 0:
            return 0, "empty cloud"
        matrix = transform_to_matrix(
            transform.transform.translation, transform.transform.rotation
        )
        return layers.draw_cloud(
            frame, model, points, matrix, source_frame,
            min_depth_m=float(self._p("lidar.min_depth_m")),
            near_m=float(self._p("lidar.near_m")),
            far_m=float(self._p("lidar.far_m")),
            point_radius_px=int(self._p("lidar.point_radius_px")),
        )

    def _draw_dig_plan(self, frame: np.ndarray, model: PinholeModel) -> "list[str]":
        """Project the retained AI dig cells and fill them by remaining depth."""
        if AiActionStatus is None:
            return [f"dig plan: unavailable ({self._action_support})"]

        action = self._actions.get()
        if action is None:
            return ["dig plan: none (idle/terminated or not yet received)"]
        if not action.has_cells():
            return [f"dig plan: {action.phase}, no cells"]

        anchor = self._p("grid.anchor_frame")
        try:
            transform = self._tf_buffer.lookup_transform(
                self._p("extrinsic.child_frame"),
                anchor,
                Time(),
                timeout=rclpy.duration.Duration(
                    seconds=float(self._p("tf.lookup_timeout_s"))
                ),
            )
        except TransformException as exc:
            self.get_logger().warn(
                f"TF {anchor} -> {self._p('extrinsic.child_frame')} unavailable: {exc}",
                throttle_duration_sec=_LOG_THROTTLE_MS / 1000.0,
            )
            return [f"dig plan: TF {anchor} unavailable"]

        heights, height_note = self._cell_heights(action, anchor)
        matrix = transform_to_matrix(
            transform.transform.translation, transform.transform.rotation
        )
        return layers.draw_dig_plan(
            frame, model, action, heights, height_note, matrix, self._terrain,
            min_depth_m=float(self._p("lidar.min_depth_m")),
            fill_alpha=float(self._p("dig.fill_alpha")),
            outline_thickness=int(self._p("dig.outline_thickness")),
            start_marker_radius_px=int(self._p("dig.start_marker_radius_px")),
            font_scale=float(self._p("hud.font_scale")),
        )

    def _cell_heights(self, action, anchor: str) -> "tuple[np.ndarray, str]":
        """Per-cell z, from the grid map when available, else a flat fallback."""
        fallback = float(self._p("grid.fallback_height_m"))
        grid = self._grid
        matrix = None
        if grid is not None and grid.frame_id and grid.frame_id != anchor:
            try:
                to_grid = self._tf_buffer.lookup_transform(
                    grid.frame_id,
                    anchor,
                    Time(),
                    timeout=rclpy.duration.Duration(
                        seconds=float(self._p("tf.lookup_timeout_s"))
                    ),
                )
            except TransformException:
                return layers.cell_heights(action, anchor, grid, fallback)
            matrix = transform_to_matrix(
                to_grid.transform.translation, to_grid.transform.rotation
            )
        return layers.cell_heights(action, anchor, grid, fallback, matrix)

    def _publish(self, frame: np.ndarray) -> None:
        quality = int(self._p("publish.jpeg_quality"))
        ok, encoded = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        )
        if not ok:
            self.get_logger().warn("JPEG encode failed")
            return
        msg = CompressedImage()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self._p("extrinsic.child_frame")
        msg.format = "jpeg"
        msg.data = encoded.tobytes()
        self._pub.publish(msg)
