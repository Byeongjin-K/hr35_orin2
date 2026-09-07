"""Replay a recorded excavator bag with sim time for offline SLAM runs.

Only the topics the SLAM front end and the evaluation need are played back; the
raw Ouster packet streams and camera topics stay out so replay keeps up on the
Jetson. Pass 'topics:=' (space-separated) to override.

ALWAYS run with an isolated ROS_DOMAIN_ID (e.g. 99). The host default (7) is
shared with the live sensors and the OT docker pipeline: replaying /lidar_boom/*
or /gps_msg there would inject bag data into the running global map.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.substitutions import LaunchConfiguration

DEFAULT_TOPICS = " ".join(
    [
        "/lidar_boom/points",
        "/lidar_boom/imu",
        "/gps_msg",
        "/gps_att",
        "/excavator/sensors/swing_encoder_output",
        "/kine_data",
        "/tf_static",
    ]
)


def _play(context, *args, **kwargs):
    # '--topics' takes one argv entry per topic; a single space-joined string
    # would be treated as one (non-existent) topic name and nothing would play.
    topics = LaunchConfiguration("topics").perform(context).split()
    cmd = [
        "ros2", "bag", "play", LaunchConfiguration("bag").perform(context),
        "--clock",
        "--rate", LaunchConfiguration("rate").perform(context),
        "--start-offset", LaunchConfiguration("start_offset").perform(context),
        "--topics", *topics,
    ]
    return [ExecuteProcess(cmd=cmd, output="screen")]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("bag", description="rosbag2 directory to replay"),
            DeclareLaunchArgument("rate", default_value="1.0"),
            DeclareLaunchArgument("start_offset", default_value="0.0"),
            DeclareLaunchArgument("topics", default_value=DEFAULT_TOPICS),
            OpaqueFunction(function=_play),
        ]
    )
