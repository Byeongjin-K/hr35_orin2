"""Stage 1 of the AR overlay: reproject the boom LiDAR onto the ZED X image.

This exists to *verify the LiDAR-to-camera extrinsic*. Until that extrinsic is
right, any dig-plan overlay drawn later is meaningless, and an error could not
be attributed to calibration versus grid-coordinate conversion. Points that
land on the real contours of the scene mean the calibration is good.

Design notes that are load-bearing:

* Subscription callbacks only stash the latest message. All decoding,
  projection and drawing happen on the publish timer, so a slow render can
  never block the executor.
* TF is looked up at time 0 (latest available) on purpose. The Ouster stamps
  its clouds with sensor uptime (order 1e4 s) while the camera stamps with
  epoch time (order 1e9 s), so a stamped lookup cannot succeed. The transform
  being resolved is static, so "latest" is also the correct answer.
"""

from __future__ import annotations

import cv2
import numpy as np
import rclpy
from geometry_msgs.msg import TransformStamped
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, CompressedImage, PointCloud2
from tf2_ros import StaticTransformBroadcaster, TransformException
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener

from excavator_ar_overlay import params, rendering
from excavator_ar_overlay.camera_model import PinholeModel
from excavator_ar_overlay.geometry import (
    apply_transform,
    rpy_to_quaternion,
    transform_to_matrix,
)
from excavator_ar_overlay.pointcloud import extract_xyz
from excavator_ar_overlay.ai_action import ActionRetainer, DigAction
from excavator_ar_overlay.dig_plan import (
    CELL_SIZE_M,
    CENTER_COL,
    cell_corners,
    remaining_to_color,
    remaining_to_colors,
)
from excavator_ar_overlay.grid_elevation import ElevationGrid
from excavator_ar_overlay.task_info import TerrainState

try:  # grid_map_msgs ships with the workspace; treat it as optional anyway.
    from grid_map_msgs.msg import GridMap
except ImportError:  # pragma: no cover - exercised only on a partial install
    GridMap = None

# AiActionStatus lives in the HR35 excavator_msgs, which is a superset of the
# robot_ws package of the same name. If that overlay is not sourced we still
# publish the LiDAR layer instead of refusing to start, and say so on the HUD.
try:
    from excavator_msgs.msg import AiActionStatus
except ImportError:  # pragma: no cover - depends on which overlay is sourced
    AiActionStatus = None

try:
    from excavator_msgs.msg import TaskInfo
except ImportError:  # pragma: no cover - depends on which overlay is sourced
    TaskInfo = None

_SENSOR_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.BEST_EFFORT,
    history=HistoryPolicy.KEEP_LAST,
    durability=DurabilityPolicy.VOLATILE,
)
_OVERLAY_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    durability=DurabilityPolicy.VOLATILE,
)
# Matches the publishers: /ai_status/action is RELIABLE/VOLATILE/depth=10 and
# /rn/grid_map is RELIABLE/KEEP_LAST(1)/VOLATILE.
_ACTION_QOS = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    durability=DurabilityPolicy.VOLATILE,
)
_GRID_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    durability=DurabilityPolicy.VOLATILE,
)
_LOG_THROTTLE_MS = 10_000


class LidarProjectionNode(Node):
    def __init__(self) -> None:
        super().__init__("lidar_projection_node")
        params.declare_all(self)

        self._image: "CompressedImage | None" = None
        self._info: "CameraInfo | None" = None
        self._cloud: "PointCloud2 | None" = None
        self._info_warning: "str | None" = None
        self._actions = ActionRetainer()
        self._grid: "ElevationGrid | None" = None
        self._terrain: "TerrainState | None" = None
        self._action_support = "ok" if AiActionStatus is not None else "missing msg"

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._static_tf = StaticTransformBroadcaster(self)

        self.create_subscription(
            CompressedImage, self._p("topics.image_in"), self._on_image, _SENSOR_QOS
        )
        self.create_subscription(
            CameraInfo, self._p("topics.camera_info_in"), self._on_info, _SENSOR_QOS
        )
        self.create_subscription(
            PointCloud2, self._p("topics.points_in"), self._on_cloud, _SENSOR_QOS
        )
        if AiActionStatus is not None:
            self.create_subscription(
                AiActionStatus,
                self._p("topics.ai_action_in"),
                self._on_action,
                _ACTION_QOS,
            )
        else:
            self.get_logger().warn(
                "excavator_msgs/AiActionStatus is not importable, so the dig-plan "
                "layer is disabled. Source the HR35 workspace after this one: "
                "'source /home/kimm/hr35/install/setup.bash'."
            )
        if GridMap is not None:
            self.create_subscription(
                GridMap, self._p("topics.grid_map_in"), self._on_grid, _GRID_QOS
            )
        if TaskInfo is not None:
            self.create_subscription(
                TaskInfo, self._p("topics.task_info_in"), self._on_task_info, _GRID_QOS
            )
        self._pub = self.create_publisher(
            CompressedImage, self._p("topics.overlay_out"), _OVERLAY_QOS
        )

        if self._p("extrinsic.publish_static_tf"):
            self._broadcast_extrinsic()

        self.add_on_set_parameters_callback(self._on_params)
        rate = max(0.1, float(self._p("publish.rate_hz")))
        self.create_timer(1.0 / rate, self._render)
        self.get_logger().info(
            f"lidar_projection_node up: publishing {self._p('topics.overlay_out')} "
            f"at {rate:.1f} Hz"
        )

    def _p(self, name: str):
        return self.get_parameter(name).value

    # ---------------------------------------------------------------- inputs

    def _on_image(self, msg: CompressedImage) -> None:
        self._image = msg

    def _on_info(self, msg: CameraInfo) -> None:
        self._info = msg

    def _on_cloud(self, msg: PointCloud2) -> None:
        self._cloud = msg

    def _on_action(self, msg) -> None:
        """Event-driven: only arrives on phase transitions, so retain it."""
        self._actions.update(DigAction.from_message(msg))

    def _on_task_info(self, msg) -> None:
        terrain = TerrainState.from_message(msg)
        if terrain is None:
            self.get_logger().warn(
                "task_info payload does not match its declared grid dimensions",
                throttle_duration_sec=_LOG_THROTTLE_MS / 1000.0,
            )
            return
        self._terrain = terrain

    def _on_grid(self, msg) -> None:
        grid = ElevationGrid.from_message(msg, self._p("grid.elevation_layer"))
        if grid is None:
            self.get_logger().warn(
                f"grid map has no usable '{self._p('grid.elevation_layer')}' layer",
                throttle_duration_sec=_LOG_THROTTLE_MS / 1000.0,
            )
            return
        self._grid = grid

    def _on_params(self, parameters) -> SetParametersResult:
        """Validate against param.value.

        Humble validates before accepting, so get_parameter() inside this
        callback still returns the OLD value and must not be used here.
        """
        refresh_tf = False
        for param in parameters:
            value = param.value
            if param.name in ("publish.width", "publish.height") and int(value) <= 0:
                return SetParametersResult(
                    successful=False, reason=f"{param.name} must be positive"
                )
            if param.name == "publish.jpeg_quality" and not 1 <= int(value) <= 100:
                return SetParametersResult(
                    successful=False, reason="publish.jpeg_quality must be 1..100"
                )
            if param.name in ("extrinsic.xyz", "extrinsic.rpy") and len(value) != 3:
                return SetParametersResult(
                    successful=False, reason=f"{param.name} must have 3 elements"
                )
            if param.name.startswith("extrinsic."):
                refresh_tf = True

        if refresh_tf:
            overrides = {p.name: p.value for p in parameters}
            self._broadcast_extrinsic(overrides)
        return SetParametersResult(successful=True)

    # ------------------------------------------------------------- extrinsic

    def _broadcast_extrinsic(self, overrides: "dict | None" = None) -> None:
        overrides = overrides or {}

        def value(name):
            return overrides.get(name, self._p(name))

        if not value("extrinsic.publish_static_tf"):
            return

        xyz = [float(v) for v in value("extrinsic.xyz")]
        rpy = [float(v) for v in value("extrinsic.rpy")]
        qx, qy, qz, qw = rpy_to_quaternion(*rpy)

        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = value("extrinsic.parent_frame")
        transform.child_frame_id = value("extrinsic.child_frame")
        transform.transform.translation.x = xyz[0]
        transform.transform.translation.y = xyz[1]
        transform.transform.translation.z = xyz[2]
        transform.transform.rotation.x = qx
        transform.transform.rotation.y = qy
        transform.transform.rotation.z = qz
        transform.transform.rotation.w = qw
        self._static_tf.sendTransform(transform)
        self.get_logger().info(
            f"extrinsic {transform.header.frame_id} -> {transform.child_frame_id}: "
            f"xyz={xyz} rpy={rpy}"
        )

    # ---------------------------------------------------------------- render

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
        in_camera = apply_transform(matrix, points)
        uv, keep = model.project(in_camera, float(self._p("lidar.min_depth_m")))
        if uv.shape[0] == 0:
            return 0, "no points in view"

        depths = np.linalg.norm(points[keep], axis=1)
        colors = rendering.depth_colors(
            depths, float(self._p("lidar.near_m")), float(self._p("lidar.far_m"))
        )
        rendering.draw_points(frame, uv, colors, int(self._p("lidar.point_radius_px")))
        return int(uv.shape[0]), f"TF ok: {source_frame}"

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
        corners = cell_corners(action.rows, action.cols, heights)
        n_cells = corners.shape[0]

        matrix = transform_to_matrix(
            transform.transform.translation, transform.transform.rotation
        )
        in_camera = apply_transform(matrix, corners.reshape(-1, 3))
        uv, keep = model.project(in_camera, float(self._p("lidar.min_depth_m")))

        uv_all = np.full((n_cells * 4, 2), np.nan, dtype=np.float64)
        uv_all[keep] = uv
        cell_uv = uv_all.reshape(n_cells, 4, 2)
        cell_ok = keep.reshape(n_cells, 4).all(axis=1)
        if not cell_ok.any():
            return [f"dig plan: {action.phase}, {n_cells} cells off-screen"]

        shown = np.flatnonzero(cell_ok)
        colors, color_note = self._cell_colors(action, shown)
        polygons = [cell_uv[i].round().astype(np.int32) for i in shown]
        rendering.draw_filled_polygons(
            frame,
            polygons,
            colors,
            float(self._p("dig.fill_alpha")),
            int(self._p("dig.outline_thickness")),
        )
        self._draw_start_marker(frame, action, cell_uv, cell_ok)

        lines = action.hud_lines()
        lines.append(f"cells drawn: {int(cell_ok.sum())}/{n_cells}  {height_note}")
        lines.append(f"colour: {color_note}")
        return lines

    def _cell_colors(self, action, shown: np.ndarray) -> "tuple[list, str]":
        """Per-cell colour from TaskInfo, falling back to the action-wide mean.

        current-target is a difference, so it does not care what datum the two
        heights share. That is why colour can come from TaskInfo even though the
        3D placement height deliberately does not.
        """
        if self._terrain is None:
            color = remaining_to_color(action.mean_remaining_delta_units)
            return [color] * shown.size, "action mean (no task_info)"

        values, valid = self._terrain.remaining_units(
            action.rows[shown], action.cols[shown]
        )
        if not valid.any():
            color = remaining_to_color(action.mean_remaining_delta_units)
            return [color] * shown.size, "action mean (cells outside work mask)"

        rgb = remaining_to_colors(values, valid)
        colors = [tuple(int(c) for c in row) for row in rgb]
        return colors, f"per-cell ({int(valid.sum())}/{valid.size})"

    def _cell_heights(self, action, anchor: str) -> "tuple[np.ndarray, str]":
        """Per-cell z, from the grid map when available, else a flat fallback."""
        fallback = float(self._p("grid.fallback_height_m"))
        heights = np.full(action.rows.shape[0], fallback, dtype=np.float64)
        grid = self._grid
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
                return heights, f"height: fallback (no TF {anchor}->{grid.frame_id})"
            matrix = transform_to_matrix(
                to_grid.transform.translation, to_grid.transform.rotation
            )
            padded = np.column_stack((centers, np.zeros(centers.shape[0])))
            centers = apply_transform(matrix, padded)[:, :2]

        sampled, valid = grid.sample(centers)
        heights[valid] = sampled[valid]
        return heights, f"height: grid map ({int(valid.sum())}/{valid.size} cells)"

    def _draw_start_marker(
        self, frame: np.ndarray, action, cell_uv: np.ndarray, cell_ok: np.ndarray
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
            int(self._p("dig.start_marker_radius_px")),
            "start",
            float(self._p("hud.font_scale")),
        )

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




def main(args=None) -> None:
    rclpy.init(args=args)
    node = LidarProjectionNode()
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
