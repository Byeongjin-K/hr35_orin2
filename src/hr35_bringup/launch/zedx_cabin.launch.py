from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetLaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import PackageNotFoundError, get_package_share_directory
import os


def _web_video_server():
    # Browser view from any PC, no ROS needed there:
    #   http://<orin2>:8080/stream?topic=/zedx_cabin/zedx_cabin_node/left/image_rect_color&type=ros_compressed
    # ros_compressed forwards the ZED JPEGs as they are (no re-encode here, no load on ORIN1).
    # Optional: skipped until `sudo apt install ros-humble-web-video-server`.
    # A standalone server already holding port 8080 makes this one exit; stop that one first.
    try:
        get_package_share_directory('web_video_server')
    except PackageNotFoundError:
        return []
    return [Node(
        package='web_video_server',
        executable='web_video_server',
        name='zedx_cabin_web_video',
        output='screen',
        parameters=[{'port': 8080, 'default_stream_type': 'ros_compressed'}],
    )]


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
        # ORIN1 GUI camera panel only: 3 Hz, 640x400 preview on /zedx_cabin/gui_preview/compressed.
        Node(
            package='hr35_bringup',
            executable='gui_camera_preview.py',
            name='zedx_cabin_gui_preview',
            output='screen',
        ),
        *_web_video_server(),
    ])
