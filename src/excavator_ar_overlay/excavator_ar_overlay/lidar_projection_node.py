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

import rclpy
from geometry_msgs.msg import TransformStamped
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, CompressedImage, PointCloud2
from tf2_ros import StaticTransformBroadcaster
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener

from excavator_ar_overlay import params
from excavator_ar_overlay.geometry import rpy_to_quaternion
from excavator_ar_overlay.ai_action import ActionRetainer, DigAction
from excavator_ar_overlay.grid_elevation import ElevationGrid
from excavator_ar_overlay.task_info import TerrainState
from excavator_ar_overlay.projection_interfaces import (
    AiActionStatus, GridMap, TaskInfo,
    _ACTION_QOS, _GRID_QOS, _LOG_THROTTLE_MS, _OVERLAY_QOS, _SENSOR_QOS,
)
from excavator_ar_overlay.projection_render import ProjectionRenderMixin


class LidarProjectionNode(ProjectionRenderMixin, Node):
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
