"""Tests for the topics a sensor's on/off switch ticks."""
from ros2_bag_gui.ros2.sensor_topics import sensor_of, switch_topics

NODE = '/zedx_cabin/zedx_cabin_node'
TOPICS = [
    ('/lidar_boom/points', 'sensor_msgs/msg/PointCloud2'),
    ('/lidar_boom/lidar_packets', 'ouster_sensor_msgs/msg/PacketMsg'),
    ('/lidar_boom/imu_packets', 'ouster_sensor_msgs/msg/PacketMsg'),
    ('/lidar_boom/range_image', 'sensor_msgs/msg/Image'),
    ('/ouster/points', 'sensor_msgs/msg/PointCloud2'),
    ('/lidar_cabin/points', 'sensor_msgs/msg/PointCloud2'),
    (f'{NODE}/left/image_rect_color/compressed', 'sensor_msgs/msg/CompressedImage'),
    (f'{NODE}/right/image_rect_color/compressed', 'sensor_msgs/msg/CompressedImage'),
    (f'{NODE}/left/image_rect_color', 'sensor_msgs/msg/Image'),
    (f'{NODE}/rgb/image_rect_color/compressed', 'sensor_msgs/msg/CompressedImage'),
    (f'{NODE}/point_cloud/cloud_registered', 'sensor_msgs/msg/PointCloud2'),
    (f'{NODE}/left/camera_info', 'sensor_msgs/msg/CameraInfo'),
    (f'{NODE}/left_gray/camera_info', 'sensor_msgs/msg/CameraInfo'),
    (f'{NODE}/path_map', 'nav_msgs/msg/Path'),
    (f'{NODE}/imu/data', 'sensor_msgs/msg/Imu'),
    ('/zedx_cabin/robot_description', 'std_msgs/msg/String'),
    ('/excavator/status', 'std_msgs/msg/String'),
]
CABIN_LIGHT = {f'{NODE}/left/camera_info', f'{NODE}/imu/data', '/zedx_cabin/robot_description'}
CABIN_IMAGES = {f'{NODE}/left/image_rect_color/compressed', f'{NODE}/right/image_rect_color/compressed'}


def test_a_lidar_ticks_all_of_its_topics_but_the_raw_packets():
    assert switch_topics('lidar_boom', TOPICS, 'svo2') == {
        '/lidar_boom/points', '/lidar_boom/range_image', '/ouster/points'}


def test_a_camera_ticks_its_compressed_left_and_right_images_only_when_images_go_into_the_bag():
    assert switch_topics('camera_cabin', TOPICS, 'bag') == CABIN_LIGHT | CABIN_IMAGES
    assert switch_topics('camera_cabin', TOPICS, 'both') == CABIN_LIGHT | CABIN_IMAGES
    assert switch_topics('camera_cabin', TOPICS, 'svo2') == CABIN_LIGHT


def test_topics_are_told_apart_by_namespace():
    assert sensor_of('/lidar_cabin/points') == 'lidar_cabin'
    assert sensor_of('/ouster/imu') == 'lidar_boom'
    assert sensor_of('/zedx_boom/zedx_boom_node/imu/data') == 'camera_boom'
    assert sensor_of('/lidar_boomer/points') is None  # a namespace is a whole path component
    assert sensor_of('/excavator/status') is None
