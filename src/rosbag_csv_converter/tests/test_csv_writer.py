import pytest
import csv
from pathlib import Path
from rosbag_csv_converter.core.csv_writer import CsvWriter, ConversionStats
from rosbag_csv_converter.core.bag_reader import MessageData


class TestCsvWriterInit:
    def test_init_creates_parent_dir(self, temp_output_dir):
        output_file = temp_output_dir / "subdir" / "output.csv"
        writer = CsvWriter(output_file)
        assert writer.output_path == output_file
        assert output_file.parent.exists()


class TestCsvWriterOutput:
    def test_creates_single_csv_file(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file, resample_rate_hz=10)
        
        messages = [
            MessageData(1000000000, "/topic1", {"/topic1.value": 1.0}),
            MessageData(1100000000, "/topic2", {"/topic2.value": 2.0}),
        ]
        
        stats = writer.write(messages)
        
        assert stats.files_created == 1
        assert output_file.exists()

    def test_csv_has_timestamp_column(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file)
        
        messages = [
            MessageData(1234567890000000000, "/topic", {"/topic.value": 1.0}),
        ]
        
        writer.write(messages)
        
        with open(output_file, 'r') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            assert "timestamp" in fieldnames

    def test_csv_has_topic_columns(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file)
        
        messages = [
            MessageData(1234567890000000000, "/sensor", {"/sensor.x": 1.5, "/sensor.y": 2.5}),
        ]
        
        writer.write(messages)
        
        with open(output_file, 'r') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            assert "sensor/x" in fieldnames
            assert "sensor/y" in fieldnames

    def test_empty_messages_creates_empty_file(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file)
        
        stats = writer.write([])
        
        assert stats.files_created == 1
        assert stats.total_messages == 0
        assert output_file.exists()


class TestResampling:
    def test_resample_10hz(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file, resample_rate_hz=10)
        
        messages = [
            MessageData(1000000000, "/sensor", {"/sensor.value": 1.0}),
            MessageData(1050000000, "/sensor", {"/sensor.value": 1.5}),
            MessageData(1100000000, "/sensor", {"/sensor.value": 2.0}),
            MessageData(1200000000, "/sensor", {"/sensor.value": 3.0}),
        ]
        
        stats = writer.write(messages)
        
        assert stats.total_rows == 3
        assert stats.resample_rate_hz == 10

    def test_forward_fill(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file, resample_rate_hz=10)
        
        messages = [
            MessageData(1000000000, "/sensor1", {"/sensor1.a": 1.0}),
            MessageData(1200000000, "/sensor2", {"/sensor2.b": 2.0}),
        ]
        
        stats = writer.write(messages)
        
        with open(output_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 3
        assert rows[1]["sensor1/a"] == "1.0"
        assert rows[2]["sensor1/a"] == "1.0"
        assert rows[2]["sensor2/b"] == "2.0"

    def test_multiple_topics_same_bucket(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file, resample_rate_hz=10)
        
        messages = [
            MessageData(1000000000, "/sensor1", {"/sensor1.a": 1.0}),
            MessageData(1050000000, "/sensor2", {"/sensor2.b": 2.0}),
        ]
        
        stats = writer.write(messages)
        
        with open(output_file, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 1
        assert rows[0]["sensor1/a"] == "1.0"
        assert rows[0]["sensor2/b"] == "2.0"


class TestConversionStats:
    def test_stats_returned_after_write(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file, resample_rate_hz=10)
        
        messages = [
            MessageData(1000000000, "/topic1", {"/topic1.value": 1.0}),
            MessageData(1100000000, "/topic1", {"/topic1.value": 2.0}),
            MessageData(1200000000, "/topic2", {"/topic2.value": 3.0}),
        ]
        
        stats = writer.write(messages)
        
        assert isinstance(stats, ConversionStats)
        assert stats.total_messages == 3
        assert stats.files_created == 1
        assert stats.topics_included == 2

    def test_stats_columns_count(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file)
        
        messages = [
            MessageData(1000000000, "/topic1", {"/topic1.a": 1.0, "/topic1.b": 2.0}),
            MessageData(1100000000, "/topic2", {"/topic2.c": 3.0}),
        ]
        
        stats = writer.write(messages)
        
        assert stats.total_columns == 4


class TestFieldNameShortening:
    def test_removes_topic_prefix(self, temp_output_dir):
        output_file = temp_output_dir / "output.csv"
        writer = CsvWriter(output_file)
        
        messages = [
            MessageData(1000000000, "/sensor/data", {"/sensor/data.x": 1.0}),
        ]
        
        writer.write(messages)
        
        with open(output_file, 'r') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
        
        assert "sensor/data/x" in fieldnames
