from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetLaunchConfiguration
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
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
        # 640x400 preview on /zedx_cabin/gui_preview/compressed for the ORIN1 GUI camera panel and the
        # browser overlay (camera_overlay_publisher). 5 Hz keeps the overlay page under ~1.2 Mbps; the GUI
        # panel still throttles itself with ai_camera_max_fps.
        Node(
            package='hr35_bringup',
            executable='gui_camera_preview.py',
            name='zedx_cabin_gui_preview',
            output='screen',
            parameters=[{'rate_hz': 5.0}],
        ),
        # web_video_server(:8080) 는 여기서 띄우지 않는다. 3.1.0 이 끊긴 HTTP 접속의 구독을 지우지 않아
        # (접속 1회당 1개 영구 잔류) 사용자 systemd 서비스 zed-web-video.service 가 띄우고,
        # zed-web-video-idle-restart.timer 가 시청자 없을 때 재시작해 비운다(ORIN1 robot_ws scripts/zed_view/).
    ])
