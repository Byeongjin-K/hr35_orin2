from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='rosbag_csv_converter',
            executable='converter',
            name='rosbag_csv_converter',
            output='screen',
        ),
    ])
