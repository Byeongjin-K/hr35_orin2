import pytest
import csv
from pathlib import Path

from rosbag_csv_converter.core.bag_reader import BagReader
from rosbag_csv_converter.core.csv_writer import CsvWriter
from rosbag_csv_converter.core.topic_filter import parse_metadata, filter_topics
from rosbag_csv_converter.core.message_flattener import ArrayFormat


class TestEndToEndConversion:
    def test_full_conversion_pipeline(self, sample_rosbag_path, temp_output_dir):
        topics_info = parse_metadata(sample_rosbag_path / "metadata.yaml")
        filtered = filter_topics(topics_info)
        topic_names = [t.name for t in filtered if t.message_count > 0][:5]

        reader = BagReader(sample_rosbag_path)
        messages = list(reader.read_messages(topics=topic_names, limit=100))

        assert len(messages) > 0

        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file, resample_rate_hz=10)
        stats = writer.write(messages)

        assert stats.total_messages == len(messages)
        assert stats.files_created == 1
        assert output_file.exists()

    def test_csv_has_correct_structure(self, sample_rosbag_path, temp_output_dir):
        reader = BagReader(sample_rosbag_path)
        messages = list(reader.read_messages(
            topics=["/excavator/kinematics/bucket_orientation"],
            limit=50
        ))

        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file, resample_rate_hz=10)
        writer.write(messages)

        with open(output_file, 'r') as f:
            reader_csv = csv.DictReader(f)
            rows = list(reader_csv)

        assert len(rows) > 0
        fieldnames = reader_csv.fieldnames or []
        assert "timestamp" in fieldnames

        for row in rows:
            ts = int(row["timestamp"])
            assert ts > 0

    def test_multiple_topics_resampled(self, sample_rosbag_path, temp_output_dir):
        reader = BagReader(sample_rosbag_path)
        topics = [
            "/excavator/kinematics/bucket_orientation",
            "/excavator/sensors/swing_angle"
        ]
        messages = list(reader.read_messages(topics=topics, limit=100))

        output_file = temp_output_dir / "resampled.csv"
        writer = CsvWriter(output_file, resample_rate_hz=10)
        stats = writer.write(messages)

        assert stats.files_created == 1
        assert stats.topics_included == 2
        assert output_file.exists()

        with open(output_file, 'r') as f:
            reader_csv = csv.DictReader(f)
            fieldnames = reader_csv.fieldnames or []
        
        assert any("bucket_orientation" in f for f in fieldnames)
        assert any("swing_angle" in f for f in fieldnames)

    def test_array_format_expand(self, sample_rosbag_path, temp_output_dir):
        reader = BagReader(sample_rosbag_path, array_format=ArrayFormat.EXPAND)
        messages = list(reader.read_messages(
            topics=["/excavator/sensors/arm_inclino"],
            limit=10
        ))

        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file)
        stats = writer.write(messages)

        assert stats.total_messages == len(messages)

    def test_filtered_topics_exclude_images(self, sample_rosbag_path):
        topics = parse_metadata(sample_rosbag_path / "metadata.yaml")
        filtered = filter_topics(topics)

        filtered_types = [t.type for t in filtered]
        assert "sensor_msgs/msg/Image" not in filtered_types
        assert "sensor_msgs/msg/PointCloud2" not in filtered_types


class TestConversionStats:
    def test_stats_accuracy(self, sample_rosbag_path, temp_output_dir):
        reader = BagReader(sample_rosbag_path)
        topics = ["/excavator/kinematics/bucket_orientation"]
        messages = list(reader.read_messages(topics=topics, limit=50))

        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file, resample_rate_hz=10)
        stats = writer.write(messages)

        assert stats.total_messages == len(messages)


class TestEdgeCases:
    def test_nonexistent_topic(self, sample_rosbag_path, temp_output_dir):
        reader = BagReader(sample_rosbag_path)
        messages = list(reader.read_messages(
            topics=["/nonexistent/topic"],
            limit=10
        ))

        assert len(messages) == 0
