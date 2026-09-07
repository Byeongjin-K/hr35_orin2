"""Optional ROS message types and publisher-matched QoS for the overlay."""

from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

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
