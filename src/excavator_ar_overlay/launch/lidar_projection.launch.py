import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_params = os.path.join(
        get_package_share_directory("excavator_ar_overlay"),
        "config",
        "lidar_projection_params.yaml",
    )

    params_file = LaunchConfiguration("params_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "params_file",
                default_value=default_params,
                description="Path to the AR overlay parameter file.",
            ),
            Node(
                package="excavator_ar_overlay",
                executable="lidar_projection_node",
                name="lidar_projection_node",
                parameters=[params_file],
                output="screen",
            ),
        ]
    )
