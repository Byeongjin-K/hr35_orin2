"""Bring up ONLY the cabin LiDAR, leaving a running boom driver alone.

This exists because dual_lidar.launch.py starts both drivers. On this machine the boom
stream is not spare capacity: the deployed stack consumes /lidar_boom/points
(rn_voxelizer -> rn_global_map -> surface reconstruction -> gridmap), so launching the
dual file to add the cabin takes the live map down for as long as the boom driver needs
to reconfigure its sensor and come back. There was a boom_only_driver.launch.py and no
counterpart, which left "add the cabin without disturbing anything" with no safe path.

Nothing here names the boom. The driver runs under its own namespace and the sensor it
configures is addressed by lidar_cabin_params.yaml, so the two sensors never meet.

The static transform is the one dual_lidar.launch.py publishes for this sensor, kept
identical so a cabin brought up either way lands in the same place. It is published
under a distinct node name rather than the dual file's "tf_publisher", because two
static publishers with the same node name in one graph is a name collision, and the
whole point of this file is that it can run beside things that are already up. Set
publish_tf:=False if something else already provides map -> lidar_cabin/os_sensor.

Example, once hr35_bringup is built in this workspace:

  ros2 launch hr35_bringup cabin_only_driver.launch.py

The params file defaults to this package's share copy. If you are running against a
workspace whose installed hr35_bringup is older than this branch - the deployed one is
built from main - pass the path explicitly, or the driver will use main's parameters
instead of these:

  ros2 launch hr35_bringup cabin_only_driver.launch.py \
      params_file:=$PWD/src/hr35_bringup/config/lidar_cabin_params.yaml
"""

import os

import launch
import lifecycle_msgs.msg
from ament_index_python.packages import get_package_share_directory
from launch.actions import DeclareLaunchArgument, EmitEvent, LogInfo, RegisterEventHandler
from launch.conditions import IfCondition
from launch.events import matches_action
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState


def generate_launch_description():
    bringup_config = get_package_share_directory('hr35_bringup')

    cabin_params_file = LaunchConfiguration('params_file')
    cabin_params_file_arg = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(bringup_config, 'config', 'lidar_cabin_params.yaml'),
        description='Path to the cabin LiDAR parameters file',
    )

    publish_tf = LaunchConfiguration('publish_tf')
    publish_tf_arg = DeclareLaunchArgument(
        'publish_tf',
        default_value='True',
        description='Publish map -> lidar_cabin/os_sensor; turn off if something else does',
    )

    rviz_enable = LaunchConfiguration('viz')
    rviz_enable_arg = DeclareLaunchArgument(
        'viz',
        default_value='False',
        description='Open RViz. Off by default: this file is meant to run beside a live stack',
    )

    cabin_driver = LifecycleNode(
        package='ouster_ros',
        executable='os_driver',
        name='os_driver',
        namespace='lidar_cabin',
        parameters=[cabin_params_file],
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
                LogInfo(msg='Failed to communicate with the cabin LiDAR sensor.'),
            ],
        ),
    )

    tf_publisher_cabin = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='tf_publisher_cabin',
        arguments=[
            '--x', '0', '--y', '0', '--z', '0',
            '--roll', '0', '--pitch', '0.25', '--yaw', '0',
            '--frame-id', 'map', '--child-frame-id', 'lidar_cabin/os_sensor',
        ],
        condition=IfCondition(publish_tf),
        output='screen',
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        arguments=['-d', os.path.join(bringup_config, 'config', 'dual_lidar_viz.rviz')],
        condition=IfCondition(rviz_enable),
        output='screen',
    )

    return launch.LaunchDescription([
        cabin_params_file_arg,
        publish_tf_arg,
        rviz_enable_arg,
        cabin_driver,
        cabin_configure_event,
        cabin_activate_event,
        cabin_finalized_event,
        tf_publisher_cabin,
        rviz_node,
    ])
