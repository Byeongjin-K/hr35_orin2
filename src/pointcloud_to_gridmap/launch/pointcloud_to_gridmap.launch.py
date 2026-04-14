#!/usr/bin/env python3
# launch/grid_map_launch.py

from launch import LaunchDescription
from launch_ros.actions import Node
import os


def generate_launch_description():
    # 패키지 공유 디렉토리 경로 찾기
    config_file_pointcloud_to_gridmap = os.path.join(
        os.getcwd(), "robot_ws/config", "grid_map_params.yaml"
    )

    grid_map_extractor_params_file = os.path.join(
        os.getcwd(), "robot_ws/config", "grid_map_extractor_params.yaml"
    )

    # RViz 설정 파일 경로 설정 (패키지 내 config 디렉토리에 위치한다고 가정)
    rviz_config_file = "/home/kimm/robot_ws/20241101.rviz"

    # 포인트클라우드에서 그리드맵으로 변환하는 노드 설정
    pointcloud_to_gridmap_node = Node(
        package="pointcloud_to_gridmap",
        executable="pointcloud_to_gridmap",
        name="pointcloud_to_gridmap",
        output="screen",
        parameters=[config_file_pointcloud_to_gridmap],  # YAML 파라미터 파일 전달
    )

    grid_map_extractor_node = Node(
        package="pointcloud_to_gridmap",
        executable="grid_map_extractor",
        name="grid_map_extractor",
        output="screen",
        parameters=[grid_map_extractor_params_file],  # YAML 파라미터 파일 전달
    )

    # RViz 노드 설정
    rviz_node = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        arguments=["-d", rviz_config_file],
        output="screen",
    )

    return LaunchDescription(
        [pointcloud_to_gridmap_node, grid_map_extractor_node, rviz_node]
    )
