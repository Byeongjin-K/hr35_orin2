from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    zed_launch_dir = os.path.join(get_package_share_directory('zed_wrapper'), 'launch')
    config_path = os.path.join(get_package_share_directory('hr35_bringup'), 'config', 'zedx_boom_params.yaml')

    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(zed_launch_dir, 'zed_camera.launch.py')),
            launch_arguments={
                'camera_model': 'zedx',
                'camera_name': 'zedx_boom',
                'serial_number': '45233238',
                'base_frame': 'zedx_boom_base_link',
                'node_name': 'zedx_boom_node',
                'ros_params_override_path': config_path,
            }.items(),
        ),
    ])
