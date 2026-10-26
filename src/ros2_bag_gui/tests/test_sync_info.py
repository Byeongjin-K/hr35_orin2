"""Tests for sync_info.json: it reports what is in the bag, not what the GUI saw."""
import json
import re
from datetime import datetime

from ros2_bag_gui.ros2 import sync_info as sync_info_module
from ros2_bag_gui.ros2.sync_info import (
    SYNC_INFO_FORMAT_VERSION,
    create_sync_info,
    logger_commit,
    read_bag_message_counts,
)

METADATA = """\
rosbag2_bagfile_information:
  version: 5
  storage_identifier: sqlite3
  message_count: 1363
  topics_with_message_count:
    - topic_metadata:
        name: /excavator/joints
        type: excavator_msgs/msg/ExcavatorJoints
        serialization_format: cdr
      message_count: 1360
    - topic_metadata:
        name: /excavator/latched
        type: std_msgs/msg/String
        serialization_format: cdr
      message_count: 3
"""


def _write(tmp_path, **kwargs):
    path = create_sync_info(
        str(tmp_path), datetime(2026, 1, 22, 14, 30, 0), datetime(2026, 1, 22, 14, 31, 0), **kwargs
    )
    with open(path) as f:
        return json.load(f)


def test_read_bag_message_counts_from_metadata(tmp_path):
    (tmp_path / "metadata.yaml").write_text(METADATA)

    assert read_bag_message_counts(str(tmp_path)) == {
        '/excavator/joints': 1360, '/excavator/latched': 3,
    }


def test_read_bag_message_counts_without_metadata_is_unknown(tmp_path):
    assert read_bag_message_counts(str(tmp_path)) is None


def test_sync_info_counts_come_from_the_bag(tmp_path):
    info = _write(
        tmp_path,
        bag_topics=['/excavator/joints'],
        bag_message_counts={'/excavator/joints': 1360},
    )

    assert info['topic_message_counts'] == {'/excavator/joints': 1360}
    assert info['data_sources']['rosbag']['message_counts_source'] == 'rosbag_metadata'


def test_sync_info_without_bag_metadata_does_not_invent_counts(tmp_path):
    info = _write(tmp_path, bag_topics=['/excavator/joints'], bag_message_counts=None)

    assert info['topic_message_counts'] is None
    assert info['data_sources']['rosbag']['topic_count'] == 1
    assert info['data_sources']['rosbag']['message_counts_source'] == 'unavailable'


def test_sync_info_time_sources_say_what_is_recorded(tmp_path):
    info = _write(
        tmp_path, bag_topics=['/tf'], camera_mode='svo2', svo2_files=[str(tmp_path / 'camera_0.svo2')]
    )

    assert info['data_sources']['rosbag']['time_source'] == 'receive_time'
    assert info['data_sources']['svo2']['time_source'] == 'camera_image_timestamp'
    assert 'timestamp_key' not in info['data_sources']['svo2']


def test_sync_info_of_svo2_only_has_no_bag(tmp_path):
    info = _write(
        tmp_path, bag_topics=[], camera_mode='svo2', svo2_files=[str(tmp_path / 'zedx_cabin.svo2')]
    )

    assert 'rosbag' not in info['data_sources']
    assert info['data_sources']['svo2']['path'] == ['zedx_cabin.svo2']


def test_sync_info_states_its_format_and_the_code_that_wrote_it(tmp_path):
    info = _write(tmp_path, bag_topics=['/tf'])

    assert info['format_version'] == SYNC_INFO_FORMAT_VERSION
    assert re.fullmatch(r'unknown|[0-9a-f]{7,40}(-dirty)?', info['logger_commit'])


def test_sync_info_of_svo2_only_also_states_its_format(tmp_path):
    info = _write(
        tmp_path, bag_topics=[], camera_mode='svo2', svo2_files=[str(tmp_path / 'zedx_cabin.svo2')]
    )

    assert info['format_version'] == SYNC_INFO_FORMAT_VERSION
    assert info['logger_commit'] == logger_commit()


def test_logger_commit_outside_a_checkout_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(sync_info_module, '__file__', str(tmp_path / 'sync_info.py'))

    assert sync_info_module.logger_commit() == 'unknown'
