from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetLaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    zed_launch_dir = os.path.join(get_package_share_directory('zed_wrapper'), 'launch')
    config_path = os.path.join(get_package_share_directory('hr35_bringup'), 'config', 'zedx_cabin_params.yaml')

    return LaunchDescription([
        # sl::Camera::close() needs more than launch's 5 s default. When the node is
        # SIGTERM/SIGKILLed mid-stream the ZED SDK never releases the capture session,
        # the ZED-X daemon sees the camera FROZEN and restarts nvargus while the sensor
        # still streams, and tegracam's failing stop path leaks a module_put() that
        # drives /sys/module/sl_zedx/refcnt negative -- which locks out every recovery
        # short of a reboot. See docs/zedx_camera_recovery.md.
        SetLaunchConfiguration('sigterm_timeout', '30'),
        SetLaunchConfiguration('sigkill_timeout', '10'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(zed_launch_dir, 'zed_camera.launch.py')),
            launch_arguments={
                'camera_model': 'zedx',
                'camera_name': 'zedx_cabin',
                'serial_number': '49749405',
                'base_frame': 'zedx_cabin_base_link',
                'node_name': 'zedx_cabin_node',
                'ros_params_override_path': config_path,
            }.items(),
        ),
    ])
