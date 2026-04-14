import pytest
from pathlib import Path
from rosbag_csv_converter.core.bag_reader import BagReader, MessageData


class TestBagReaderInit:
    def test_init_with_valid_folder(self, sample_rosbag_path):
        reader = BagReader(sample_rosbag_path)
        assert reader.bag_path == sample_rosbag_path

    def test_init_with_nonexistent_folder_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            BagReader(tmp_path / "nonexistent")


class TestBagReaderTopics:
    def test_get_available_topics(self, sample_rosbag_path):
        reader = BagReader(sample_rosbag_path)
        topics = reader.get_available_topics()
        
        assert len(topics) > 0
        topic_names = [t.name for t in topics]
        assert "/excavator/kinematics/bucket_orientation" in topic_names

    def test_get_available_topics_returns_topic_info(self, sample_rosbag_path):
        reader = BagReader(sample_rosbag_path)
        topics = reader.get_available_topics()
        
        for topic in topics:
            assert hasattr(topic, 'name')
            assert hasattr(topic, 'type')
            assert hasattr(topic, 'message_count')


class TestBagReaderReadMessages:
    def test_read_single_topic(self, sample_rosbag_path):
        reader = BagReader(sample_rosbag_path)
        messages = list(reader.read_messages(
            topics=["/excavator/kinematics/bucket_orientation"],
            limit=10
        ))
        
        assert len(messages) > 0
        assert len(messages) <= 10

    def test_message_data_has_timestamp(self, sample_rosbag_path):
        reader = BagReader(sample_rosbag_path)
        messages = list(reader.read_messages(
            topics=["/excavator/kinematics/bucket_orientation"],
            limit=5
        ))
        
        for msg_data in messages:
            assert isinstance(msg_data, MessageData)
            assert isinstance(msg_data.timestamp_ns, int)
            assert msg_data.timestamp_ns > 0

    def test_message_data_has_topic(self, sample_rosbag_path):
        reader = BagReader(sample_rosbag_path)
        messages = list(reader.read_messages(
            topics=["/excavator/kinematics/bucket_orientation"],
            limit=5
        ))
        
        for msg_data in messages:
            assert msg_data.topic == "/excavator/kinematics/bucket_orientation"

    def test_message_data_has_flattened_data(self, sample_rosbag_path):
        reader = BagReader(sample_rosbag_path)
        messages = list(reader.read_messages(
            topics=["/excavator/kinematics/bucket_orientation"],
            limit=5
        ))
        
        for msg_data in messages:
            assert isinstance(msg_data.data, dict)
            assert len(msg_data.data) > 0

    def test_read_multiple_topics(self, sample_rosbag_path):
        reader = BagReader(sample_rosbag_path)
        topics = [
            "/excavator/kinematics/bucket_orientation",
            "/excavator/sensors/swing_angle"
        ]
        messages = list(reader.read_messages(topics=topics, limit=20))
        
        topic_names_in_messages = set(m.topic for m in messages)
        assert len(topic_names_in_messages) >= 1

    def test_read_with_progress_callback(self, sample_rosbag_path):
        reader = BagReader(sample_rosbag_path)
        progress_values = []
        
        def on_progress(current, total):
            progress_values.append((current, total))
        
        list(reader.read_messages(
            topics=["/excavator/kinematics/bucket_orientation"],
            limit=10,
            progress_callback=on_progress
        ))
        
        assert len(progress_values) > 0


class TestMessageData:
    def test_message_data_creation(self):
        data = MessageData(
            timestamp_ns=1234567890,
            topic="/test/topic",
            data={"field": 1.0}
        )
        
        assert data.timestamp_ns == 1234567890
        assert data.topic == "/test/topic"
        assert data.data == {"field": 1.0}
