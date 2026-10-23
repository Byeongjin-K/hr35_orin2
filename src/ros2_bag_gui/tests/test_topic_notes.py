"""Tests for telling which topics hold the same data, and what a recording costs on disk."""
import pytest

from ros2_bag_gui.ros2.topic_notes import (
    LAZ_GB_PER_HOUR, SVO2_GB_PER_HOUR, StartPlan, duplicates, start_report,
)

CAB = '/zedx_cabin/zedx_cabin_node'


def test_zed_streams_of_one_picture_duplicate_its_compressed_rectified_image():
    kept = f'{CAB}/left/image_rect_color/compressed'
    same_picture = [f'{CAB}/left/image_rect_color', f'{CAB}/rgb/image_rect_color',
                    f'{CAB}/left_gray/image_rect_gray', f'{CAB}/left_raw/image_raw_color',
                    f'{CAB}/stereo/image_rect_color']
    others = [f'{CAB}/right/image_rect_color/compressed', f'{CAB}/left/camera_info',
              f'{CAB}/left/image_rect_color/compressed/parameter_descriptions']

    assert duplicates([kept, *same_picture, *others]) == {name: kept for name in same_picture}


def test_without_its_compressed_form_the_left_rectified_image_is_kept():
    assert duplicates([f'{CAB}/rgb/image_rect_color', f'{CAB}/left/image_rect_color']) == {
        f'{CAB}/rgb/image_rect_color': f'{CAB}/left/image_rect_color'}


def test_disparity_and_cloud_duplicate_the_depth():
    depth = f'{CAB}/depth/depth_registered'
    names = [depth, f'{CAB}/disparity/disparity_image', f'{CAB}/point_cloud/cloud_registered',
             f'{CAB}/depth/camera_info', f'{CAB}/confidence/confidence_map']

    assert duplicates(names) == {names[1]: depth, names[2]: depth}


def test_raw_lidar_packets_duplicate_the_decoded_topics_that_are_there():
    names = ['/lidar_boom/lidar_packets', '/lidar_boom/points', '/lidar_boom/imu_packets']

    assert duplicates(names) == {'/lidar_boom/lidar_packets': '/lidar_boom/points'}


def test_an_uncompressed_image_duplicates_its_compressed_transport():
    assert duplicates(['/camera/image', '/camera/image/compressed']) == {
        '/camera/image': '/camera/image/compressed'}


def test_a_heavy_topic_or_the_same_data_twice_is_worth_a_question_at_start():
    light = start_report(StartPlan(('/tf', '/imu'), (), 0, 0), {'/tf': 0.1, '/imu': 0.8}, 10**12)
    heavy = start_report(StartPlan(('/tf', '/points'), (), 0, 0), {'/tf': 0.1, '/points': 113.0}, 10**12)
    twice = start_report(StartPlan(('/lidar_boom/points',), ('/lidar_boom/points',), 1, 0), {}, 10**12)

    assert not light.worth_asking
    assert heavy.worth_asking and heavy.heavy == (('/points', 113.0),)
    assert twice.worth_asking


def test_the_hours_left_count_what_is_recorded_beside_the_bag():
    report = start_report(StartPlan(('/a', '/b', '/c'), (), laz_lidars=1, svo2_cameras=2),
                          {'/a': 1.4, '/b': 2.0, '/c': 0.3}, free_bytes=100 * 10**9)

    assert report.heavy == (('/b', 2.0), ('/a', 1.4))
    side = LAZ_GB_PER_HOUR + 2 * SVO2_GB_PER_HOUR
    assert report.side_gb_per_hour == pytest.approx(side)
    assert report.hours_left == pytest.approx(100 / (3.7 + side))


def test_with_nothing_measured_and_nothing_beside_the_bag_the_time_left_is_unknown():
    assert start_report(StartPlan(('/a',), (), 0, 0), {}, 10**12).hours_left is None
