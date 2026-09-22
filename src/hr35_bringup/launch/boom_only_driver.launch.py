"""Launch only one Ouster LiDAR sensor (Boom) with transform and RViz"""

import os
from ament_index_python.packages import get_package_share_directory
from launch_ros.actions import LifecycleNode, Node
from launch.actions import DeclareLaunchArgument, RegisterEventHandler, EmitEvent, LogInfo
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch.events import matches_action
from launch_ros.events.lifecycle import ChangeState
from launch_ros.event_handlers import OnStateTransition
import launch
import lifecycle_msgs.msg


def generate_launch_description():
    bringup_config = get_package_share_directory('hr35_bringup')

    boom_params_file = LaunchConfiguration('params_file')
    boom_params_file_arg = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(bringup_config, 'config', 'lidar_boom_params.yaml'),
        description='Path to the boom LiDAR parameters file',
    )

    rviz_enable = LaunchConfiguration('viz')
    rviz_enable_arg = DeclareLaunchArgument(
        'viz',
        default_value='False',
    )

    boom_driver = LifecycleNode(
        package='ouster_ros',
        executable='os_driver',
        name='os_driver',
        namespace='lidar_boom',
        parameters=[boom_params_file],
        output='screen',
    )

    boom_configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(boom_driver),
            transition_id=lifecycle_msgs.msg.Transition.TRANSITION_CONFIGURE,
        ),
    )

    boom_activate_event = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=boom_driver,
            goal_state='inactive',
            entities=[
                LogInfo(msg='Boom LiDAR driver activating...'),
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(boom_driver),
                        transition_id=lifecycle_msgs.msg.Transition.TRANSITION_ACTIVATE,
                    ),
                ),
            ],
            handle_once=True,
        ),
    )

    boom_finalized_event = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=boom_driver,
            goal_state='finalized',
            entities=[
                LogInfo(msg='Failed to communicate with the Boom LiDAR sensor.'),
            ],
        ),
    )

    # The boom LiDAR hangs off the boom, so anchoring it to map pins a moving
    # sensor to a fixed pose: the old [0, 0, 2] placeholder simply dropped the
    # boom rotation. Measured 2026-09-22 against the live /rn/grid_map, cell by
    # cell: through this chain the cloud's ground sat 1.776 m from the mapped
    # terrain (median), and the error swung +0.541 -> -1.776 m as the boom moved,
    # while the kinematic chain held 0.065 m.
    #
    # Parenting os_sensor to gm_os_lidar instead makes it ride the boom, and
    # every consumer gets the right value with no code change. The driver
    # publishes os_sensor -> os_lidar itself, so this one constant is all that is
    # needed; it is read straight off that transform:
    #   ros2 run tf2_ros tf2_echo lidar_boom/os_lidar lidar_boom/os_sensor
    #   -> translation [0, 0, -0.038], rpy [0, 0, 180 deg]
    #
    # Consequence worth knowing: map -> lidar_boom/* now exists only while the
    # stack publishing the gm_ frames is up. When it is not, the transform is
    # absent rather than silently wrong by metres.
    tf_publisher_boom = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='tf_publisher_boom',
        arguments=[
            '--x', '0', '--y', '0', '--z', '-0.038',
            '--roll', '0', '--pitch', '0', '--yaw', '3.14159265',
            '--frame-id', 'gm_os_lidar', '--child-frame-id', 'lidar_boom/os_sensor',
        ],
        output='screen',
    )

    rviz_config_path = os.path.join(bringup_config, 'config', 'lidar_boom_viz.rviz')
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', rviz_config_path],
        condition=IfCondition(rviz_enable),
        output='screen',
    )

    return launch.LaunchDescription([
        boom_params_file_arg,
        rviz_enable_arg,
        boom_driver,
        boom_configure_event,
        boom_activate_event,
        boom_finalized_event,
        tf_publisher_boom,
        rviz_node,
    ])
