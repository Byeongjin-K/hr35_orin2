"""Launch two Ouster LiDAR sensors with transform configuration"""

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
    """
    Generate launch description for running two ouster LiDARs simultaneously.
    """
    bringup_config = get_package_share_directory('hr35_bringup')

    cabin_params_file = LaunchConfiguration('cabin_params_file')
    cabin_params_file_arg = DeclareLaunchArgument(
        'cabin_params_file',
        default_value=os.path.join(bringup_config, 'config', 'lidar_cabin_params.yaml'),
        description='path to the cabin LiDAR parameters file',
    )

    boom_params_file = LaunchConfiguration('boom_params_file')
    boom_params_file_arg = DeclareLaunchArgument(
        'boom_params_file',
        default_value=os.path.join(bringup_config, 'config', 'lidar_boom_params.yaml'),
        description='path to the boom LiDAR parameters file',
    )

    rviz_enable = LaunchConfiguration('viz')
    rviz_enable_arg = DeclareLaunchArgument(
        'viz',
        default_value='True',
    )

    cabin_driver = LifecycleNode(
        package='ouster_ros',
        executable='os_driver',
        name='os_driver',
        namespace='lidar_cabin',
        parameters=[cabin_params_file],
        output='screen',
    )

    boom_driver = LifecycleNode(
        package='ouster_ros',
        executable='os_driver',
        name='os_driver',
        namespace='lidar_boom',
        parameters=[boom_params_file],
        output='screen',
    )

    cabin_configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(cabin_driver),
            transition_id=lifecycle_msgs.msg.Transition.TRANSITION_CONFIGURE,
        ),
    )

    cabin_activate_event = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=cabin_driver,
            goal_state='inactive',
            entities=[
                LogInfo(msg='Cabin LiDAR driver activating...'),
                EmitEvent(
                    event=ChangeState(
                        lifecycle_node_matcher=matches_action(cabin_driver),
                        transition_id=lifecycle_msgs.msg.Transition.TRANSITION_ACTIVATE,
                    ),
                ),
            ],
            handle_once=True,
        ),
    )

    cabin_finalized_event = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=cabin_driver,
            goal_state='finalized',
            entities=[
                LogInfo(
                    msg='Failed to communicate with the cabin LiDAR sensor.',
                ),
            ],
        ),
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
                LogInfo(
                    msg='Failed to communicate with the boom LiDAR sensor.',
                ),
            ],
        ),
    )

    tf_publisher = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='tf_publisher',
        arguments=[
            '--x', '0', '--y', '0', '--z', '0',
            '--roll', '0', '--pitch', '0.25', '--yaw', '0',
            '--frame-id', 'map', '--child-frame-id', 'lidar_cabin/os_sensor',
        ],
        output='screen',
    )

    tf_publisher_boom = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='tf_publisher_boom',
        arguments=[
            '--x', '1.9', '--y', '-0.5', '--z', '-0.9',
            '--roll', '-1.5708', '--pitch', '0', '--yaw', '0',
            '--frame-id', 'map', '--child-frame-id', 'lidar_boom/os_sensor',
        ],
        output='screen',
    )

    rviz_config_path = os.path.join(bringup_config, 'config', 'dual_lidar_viz.rviz')
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', rviz_config_path],
        condition=IfCondition(rviz_enable),
        output='screen',
    )

    return launch.LaunchDescription([
        cabin_params_file_arg,
        boom_params_file_arg,
        rviz_enable_arg,
        cabin_driver,
        boom_driver,
        cabin_configure_event,
        cabin_activate_event,
        cabin_finalized_event,
        boom_configure_event,
        boom_activate_event,
        boom_finalized_event,
        tf_publisher,
        tf_publisher_boom,
        rviz_node,
    ])
