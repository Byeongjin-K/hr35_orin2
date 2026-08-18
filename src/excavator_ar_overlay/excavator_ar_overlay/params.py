"""Parameter schema for the AR overlay nodes.

Two project rules are enforced here rather than left to each call site:

* every topic name and every calibration value is a declared ROS parameter,
  so nothing is hardcoded and the YAML stays the single source of truth;
* each ``declare_parameter`` gets a *freshly constructed* ParameterDescriptor.
  rclpy stores the descriptor by reference and stamps the name/type of the
  declaration onto it, so sharing one instance across declarations makes the
  last declaration's type win for the whole group and later ``ros2 param set``
  calls fail with "Wrong parameter type".
"""

from __future__ import annotations

import math

from rcl_interfaces.msg import ParameterDescriptor

# (name, default, description). Order is the declaration order.
SCHEMA: "tuple[tuple[str, object, str], ...]" = (
    (
        "topics.image_in",
        "/zedx_cabin/zedx_cabin_node/rgb/image_rect_color/compressed",
        "Input camera image (sensor_msgs/CompressedImage, JPEG). The cabin "
        "camera looks down at the work area; the boom camera's angle misses "
        "most of where the bucket actually reaches.",
    ),
    (
        "topics.camera_info_in",
        "/zedx_cabin/zedx_cabin_node/rgb/camera_info",
        "Intrinsics for the input image.",
    ),
    (
        "topics.points_in",
        "/lidar_boom/points",
        "LiDAR cloud reprojected onto the image (sensor_msgs/PointCloud2).",
    ),
    (
        "topics.overlay_out",
        "/excavator/perception/dig_overlay/compressed",
        "Rendered overlay (sensor_msgs/CompressedImage, JPEG).",
    ),
    (
        "topics.ai_action_in",
        "/ai_status/action",
        "AI dig plan (excavator_msgs/AiActionStatus). Event-driven: only "
        "published on phase transitions, so the last value is retained.",
    ),
    (
        "topics.grid_map_in",
        "/rn/grid_map",
        "Terrain heights (grid_map_msgs/GridMap) used to place dig cells in 3D.",
    ),
    (
        "topics.task_info_in",
        "/task_info",
        "Per-cell current/target terrain (excavator_msgs/TaskInfo). Used only "
        "for the dig-cell COLOUR: current-target is a difference, so it is "
        "independent of whatever datum the heights are measured from. Absolute "
        "height for 3D placement still comes from the grid map, whose frame is "
        "known.",
    ),
    ("layers.lidar_points", True, "Draw the reprojected LiDAR cloud."),
    ("layers.dig_plan", True, "Draw the AI-selected dig cells."),
    (
        "swing_axis_row_in_gui_grid",
        -2,
        "GUI row index that AI row 0 maps onto: AI[i, j] = GUI[swing+i, j]. "
        "Declared at the top level with this exact name so the shared SSOT file "
        "excavator_task_config_gui/config/ai_grid_calibration.yaml can be passed "
        "to this node unchanged. Never hardcode it.",
    ),
    (
        "grid.anchor_frame",
        "gm_swing_axis",
        "TF frame that AI row 0 / column 33 is measured from. Its +x is forward "
        "and +y is lateral-left, established from the live tree: the boom-mounted "
        "gm_boom_link and gm_lidar_mount differ from this frame almost purely in +x.",
    ),
    (
        "grid.elevation_layer",
        "elevation",
        "GridMap layer sampled for per-cell height.",
    ),
    (
        "grid.fallback_height_m",
        0.0,
        "Height used for cells with no grid map coverage. The grid map publishes "
        "rarely (and may be absent entirely), so the overlay degrades to a flat "
        "plane at this height rather than disappearing.",
    ),
    ("dig.fill_alpha", 0.35, "Opacity of the dig-cell fill, 0..1."),
    ("dig.outline_thickness", 1, "Dig-cell outline thickness in pixels."),
    (
        "dig.start_marker_radius_px",
        7,
        "Radius of the marker drawn on the start_row/start_col cell.",
    ),
    ("publish.rate_hz", 2.0, "Overlay render/publish rate."),
    ("publish.width", 640, "Overlay output width in pixels."),
    ("publish.height", 400, "Overlay output height in pixels."),
    ("publish.jpeg_quality", 80, "JPEG quality 1-100 for the published overlay."),
    ("lidar.near_m", 1.0, "Distance mapped to the near end of the colour ramp."),
    ("lidar.far_m", 15.0, "Distance mapped to the far end of the colour ramp."),
    (
        "lidar.min_depth_m",
        0.3,
        "Points closer than this along the camera +z axis are culled.",
    ),
    (
        "lidar.max_points",
        40000,
        "Upper bound on projected points per frame; the cloud is subsampled above it.",
    ),
    (
        "lidar.point_radius_px",
        0,
        "0 draws single pixels (fast). >0 draws filled circles of that radius.",
    ),
    (
        "lidar.override_frame",
        "",
        "Reinterpret the incoming cloud as being in this frame instead of its "
        "own header frame. Empty keeps the header. This exists because the same "
        "physical Ouster appears twice in the tree: lidar_boom/os_lidar hangs "
        "off a hardcoded placeholder (map -> lidar_boom/os_sensor [0,0,2]) "
        "while gm_os_lidar comes from the boom kinematics, and the two differ "
        "by 2.141 m and 17.2 deg. Setting this to 'gm_os_lidar' and comparing "
        "the two overlays is the cheapest way to decide which chain is real.",
    ),
    ("hud.font_scale", 0.5, "OpenCV font scale for HUD and legend text."),
    ("tf.lookup_timeout_s", 1.0, "Blocking timeout for each TF lookup."),
    (
        "extrinsic.publish_static_tf",
        True,
        "Publish extrinsic.xyz/rpy as a static TF. This is how the camera gets "
        "attached to the map chain during calibration; once the value is final, "
        "move it to a static_transform_publisher or the URDF.",
    ),
    (
        "extrinsic.parent_frame",
        "gm_swing_axis",
        "Parent frame of the published extrinsic. This MUST be a cabin-rigid "
        "frame, not a boom-rigid one: the camera is mounted on the cabin while "
        "the LiDAR rides the boom, so a camera-to-LiDAR transform is not "
        "constant. Measured live, gm_swing_axis and gm_boom_hinge hold the same "
        "attitude (-4.68 vs -4.74 deg pitch) while gm_boom_link and "
        "gm_lidar_mount swing with the boom (-44.25 / -44.20 deg at the same "
        "instant). gm_swing_axis is chosen over gm_boom_hinge because the dig "
        "cells are already computed in it, so cell-to-pixel collapses to one "
        "constant transform and boom kinematics errors cannot leak into the "
        "overlay at all.",
    ),
    (
        "extrinsic.child_frame",
        "zedx_cabin_left_camera_optical_frame",
        "Child frame of the published extrinsic (the camera optical frame).",
    ),
    (
        "extrinsic.xyz",
        [0.0, 0.0, 0.0],
        "Camera optical frame origin in the parent frame [m]. UNCALIBRATED. The "
        "earlier coarse fit was for the boom camera against the LiDAR and does "
        "not transfer, so this is back to zero.",
    ),
    (
        "extrinsic.rpy",
        [-math.pi / 2.0, 0.0, -math.pi / 2.0],
        "Fixed-axis roll/pitch/yaw [rad] of the camera optical frame in the "
        "parent frame. UNCALIBRATED. The default maps an x-forward/y-left/z-up "
        "parent onto the optical x-right/y-down/z-forward convention, i.e. "
        "rotation only. A cabin camera looking down at the work area will need "
        "a substantial pitch on top of that.",
    ),
)


def declare_all(node) -> None:
    """Declare every parameter in SCHEMA with its own descriptor instance."""
    for name, default, description in SCHEMA:
        node.declare_parameter(
            name, default, ParameterDescriptor(description=description)
        )
