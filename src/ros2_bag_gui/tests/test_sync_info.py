"""Tests for sync_info.json: it reports what is in the bag, not what the GUI saw."""
import json
from datetime import datetime

from ros2_bag_gui.ros2.sync_info import create_sync_info, read_bag_message_counts

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
        topic_counts={'/excavator/joints': 2600},
        bag_message_counts={'/excavator/joints': 1360},
    )

    assert info['topic_message_counts'] == {'/excavator/joints': 1360}
    assert info['gui_received_counts'] == {'/excavator/joints': 2600}
    assert info['data_sources']['rosbag']['message_counts_source'] == 'rosbag_metadata'


def test_sync_info_without_bag_metadata_does_not_invent_counts(tmp_path):
    info = _write(tmp_path, topic_counts={'/excavator/joints': 2600}, bag_message_counts=None)

    assert info['topic_message_counts'] is None
    assert info['gui_received_counts'] == {'/excavator/joints': 2600}
    assert info['data_sources']['rosbag']['message_counts_source'] == 'unavailable'


def test_sync_info_time_sources_say_what_is_recorded(tmp_path):
    info = _write(
        tmp_path, topic_counts={}, camera_mode='svo2', svo2_files=[str(tmp_path / 'camera_0.svo2')]
    )

    assert info['data_sources']['rosbag']['time_source'] == 'receive_time'
    assert info['data_sources']['svo2']['time_source'] == 'camera_image_timestamp'
    assert 'timestamp_key' not in info['data_sources']['svo2']
