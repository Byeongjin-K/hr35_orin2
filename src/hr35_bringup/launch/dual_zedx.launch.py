from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    zed_launch_dir = os.path.join(get_package_share_directory('zed_wrapper'), 'launch')
    bringup_config = get_package_share_directory('hr35_bringup')
    boom_yaml = os.path.join(bringup_config, 'config', 'zedx_boom_params.yaml')
    cabin_yaml = os.path.join(bringup_config, 'config', 'zedx_cabin_params.yaml')

    return LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(zed_launch_dir, 'zed_camera.launch.py')),
            launch_arguments={
                'camera_model': 'zedx',
                'camera_name': 'zedx_boom',
                'serial_number': '45233238',
                'base_frame': 'zedx_boom_base_link',
                'node_name': 'zedx_boom_node',
                'ros_params_override_path': boom_yaml,
            }.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(zed_launch_dir, 'zed_camera.launch.py')),
            launch_arguments={
                'camera_model': 'zedx',
                'camera_name': 'zedx_cabin',
                'serial_number': '49749405',
                'base_frame': 'zedx_cabin_base_link',
                'node_name': 'zedx_cabin_node',
                'ros_params_override_path': cabin_yaml,
            }.items(),
        ),
    ])
