"""Tests for CSV exporter module."""

import csv
import locale
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from ros2_bag_gui.export.csv_exporter import (
    CSVExportConfig,
    CSVExportResult,
    CSVExporter,
)


class TestCSVExporter:

    @pytest.fixture
    def variable_bag(self, tmp_path):
        from rclpy.serialization import serialize_message
        from rosbag2_py import ConverterOptions, SequentialWriter, StorageOptions
        from sensor_msgs.msg import JointState
        from ros2_bag_gui.compat import create_topic_metadata

        bag = tmp_path / "bag"
        writer = SequentialWriter()
        writer.open(StorageOptions(uri=str(bag), storage_id="sqlite3"),
                    ConverterOptions("", ""))
        writer.create_topic(create_topic_metadata(
            topic_id=1, name="/joints", type_="sensor_msgs/msg/JointState",
            serialization_format="cdr",
        ))
        for stamp, size in enumerate([1, 3, 2, 4], start=1):
            msg = JointState(name=[f"joint_{index}" for index in range(size)])
            msg.header.frame_id = "\ud55c\uae00"
            writer.write("/joints", serialize_message(msg), stamp)
        del writer
        return bag

    def test_export_union_when_later_messages_add_fields(self, variable_bag, tmp_path):
        # Given messages whose arrays grow, shrink, and grow again.
        output = tmp_path / "union.csv"
        config = CSVExportConfig(str(variable_bag), "/joints",
                                 "sensor_msgs/msg/JointState", str(output))

        # When exporting the whole topic.
        result = CSVExporter().export_topic(config)

        # Then columns keep first-seen order and absent fields are empty.
        assert result.success, result.error
        assert result.message_count == 4
        assert result.column_count == 9
        with output.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            assert reader.fieldnames == [
                "timestamp_sec", "timestamp_nanosec", "header_stamp_sec",
                "header_stamp_nanosec", "header_frame_id",
                "name_0", "name_1", "name_2", "name_3",
            ]
            rows = list(reader)
        assert [[row[f"name_{i}"] for i in range(4)] for row in rows] == [
            ["joint_0", "", "", ""],
            ["joint_0", "joint_1", "joint_2", ""],
            ["joint_0", "joint_1", "", ""],
            ["joint_0", "joint_1", "joint_2", "joint_3"],
        ]

    def test_export_utf8_when_ctype_is_c(self, variable_bag, tmp_path):
        # Given Unicode fields and the locale left by the ZED SDK.
        output = tmp_path / "utf8.csv"
        config = CSVExportConfig(str(variable_bag), "/joints",
                                 "sensor_msgs/msg/JointState", str(output))
        previous = locale.setlocale(locale.LC_CTYPE)
        try:
            locale.setlocale(locale.LC_CTYPE, "C")
            # When streaming and rewriting the export under that locale.
            result = CSVExporter().export_topic(config)
        finally:
            locale.setlocale(locale.LC_CTYPE, previous)

        # Then UTF-8 field values survive both passes.
        assert result.success, result.error
        with output.open(encoding="utf-8", newline="") as stream:
            assert [row["header_frame_id"] for row in csv.DictReader(stream)] == [
                "\ud55c\uae00",
            ] * 4

    def test_export_preserves_bytes_when_columns_stay_constant(self, variable_bag, tmp_path):
        # Given a range exporting only the first message's fixed schema.
        output = tmp_path / "fixed.csv"
        config = CSVExportConfig(str(variable_bag), "/joints",
                                 "sensor_msgs/msg/JointState", str(output),
                                 start_time_ns=1, end_time_ns=1)

        # When exporting without any new columns in the selected range.
        result = CSVExporter().export_topic(config)

        # Then the original header order, values, and CSV line endings survive.
        assert result.success, result.error
        assert result.message_count == 1
        assert result.column_count == 6
        assert output.read_bytes() == (
            "timestamp_sec,timestamp_nanosec,header_stamp_sec,"
            "header_stamp_nanosec,header_frame_id,name_0\r\n"
            "0,1,0,0,\ud55c\uae00,joint_0\r\n"
        ).encode("utf-8")
    
    @pytest.fixture
    def sample_bag_path(self):
        test_dir = Path(__file__).parent
        bag_path = test_dir / "fixtures" / "sample_60s"
        if not bag_path.exists():
            pytest.skip("Bag fixture tests/fixtures/sample_60s not available")
        return str(bag_path)
    
    @pytest.fixture
    def temp_output_path(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            path = f.name
        yield path
        if os.path.exists(path):
            os.remove(path)
        if os.path.exists(path + '.tmp'):
            os.remove(path + '.tmp')
    
    def test_flatten_message_with_scalars(self):
        msg = SimpleNamespace(
            x=1.5,
            y=2.5,
            z=3.5
        )
        
        result = CSVExporter.flatten_message(msg, 1234567890123456789)
        
        assert result['timestamp_sec'] == 1234567890
        assert result['timestamp_nanosec'] == 123456789
        assert result['x'] == 1.5
        assert result['y'] == 2.5
        assert result['z'] == 3.5
    
    def test_flatten_message_with_nested_fields(self):
        msg = SimpleNamespace(
            header=SimpleNamespace(
                stamp=SimpleNamespace(
                    sec=100,
                    nanosec=200
                ),
                frame_id="map"
            ),
            data=42.0
        )
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert result['header_stamp_sec'] == 100
        assert result['header_stamp_nanosec'] == 200
        assert result['header_frame_id'] == "map"
        assert result['data'] == 42.0
    
    def test_flatten_message_with_small_array(self):
        msg = SimpleNamespace(
            values=[1.0, 2.0, 3.0]
        )
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert result['values_0'] == 1.0
        assert result['values_1'] == 2.0
        assert result['values_2'] == 3.0
    
    def test_flatten_message_skips_large_array(self):
        large_array = list(range(150))
        msg = SimpleNamespace(
            data=large_array,
            other=42
        )
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert 'data_0' not in result
        assert 'data_149' not in result
        assert result['other'] == 42
    
    def test_flatten_message_skips_bytes(self):
        msg = SimpleNamespace(
            image_data=b'\x00\x01\x02\x03',
            value=123
        )
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert 'image_data' not in result
        assert result['value'] == 123
    
    def test_flatten_message_handles_none(self):
        msg = SimpleNamespace(
            optional_field=None,
            value=456
        )
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert result['optional_field'] == ''
        assert result['value'] == 456
    
    def test_flatten_message_with_dict_object(self):
        msg = SimpleNamespace(x=1, y=2)
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert result['x'] == 1
        assert result['y'] == 2
    
    def test_flatten_message_skips_private_fields(self):
        msg = SimpleNamespace(
            public_field=100,
            _private_field=200
        )
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert result['public_field'] == 100
        assert '_private_field' not in result
    
    def test_get_csv_columns(self):
        msg = SimpleNamespace(
            header=SimpleNamespace(
                stamp=SimpleNamespace(sec=0, nanosec=0),
                frame_id="test"
            ),
            data=[1.0, 2.0, 3.0]
        )
        
        columns = CSVExporter.get_csv_columns(msg)
        
        assert 'timestamp_sec' in columns
        assert 'timestamp_nanosec' in columns
        assert 'header_stamp_sec' in columns
        assert 'header_stamp_nanosec' in columns
        assert 'header_frame_id' in columns
        assert 'data_0' in columns
        assert 'data_1' in columns
        assert 'data_2' in columns
    
    def test_export_topic_missing_bag_path(self, temp_output_path):
        config = CSVExportConfig(
            bag_path="/nonexistent/path",
            topic_name="/test",
            topic_type="std_msgs/msg/String",
            output_path=temp_output_path
        )
        
        exporter = CSVExporter()
        result = exporter.export_topic(config)
        
        assert result.success is False
        assert "does not exist" in result.error
        assert result.message_count == 0
    
    def test_export_topic_invalid_message_type(self, sample_bag_path, temp_output_path):
        config = CSVExportConfig(
            bag_path=sample_bag_path,
            topic_name="/excavator/sensors/gnss_position",
            topic_type="nonexistent/msg/Type",
            output_path=temp_output_path
        )
        
        exporter = CSVExporter()
        result = exporter.export_topic(config)
        
        assert result.success is False
        assert "Message type not found" in result.error
        assert result.message_count == 0
    
    def test_export_topic_with_standard_message_type(self, sample_bag_path, temp_output_path):
        config = CSVExportConfig(
            bag_path=sample_bag_path,
            topic_name="/excavator/sensors/gnss_position",
            topic_type="sensor_msgs/msg/NavSatFix",
            output_path=temp_output_path
        )
        
        exporter = CSVExporter()
        result = exporter.export_topic(config)
        
        assert result.success is True
        assert result.message_count == 536
        assert result.column_count > 0
        assert os.path.exists(temp_output_path)
        
        with open(temp_output_path, 'r') as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
            
            assert 'timestamp_sec' in columns
            assert 'timestamp_nanosec' in columns
            assert 'latitude' in columns
            assert 'longitude' in columns
            assert 'altitude' in columns
            
            rows = list(reader)
            assert len(rows) == 536
            
            first_row = rows[0]
            assert first_row['timestamp_sec'].isdigit()
            assert first_row['timestamp_nanosec'].isdigit()
    
    def test_export_topic_with_time_range(self, sample_bag_path, temp_output_path):
        config = CSVExportConfig(
            bag_path=sample_bag_path,
            topic_name="/excavator/sensors/gnss_position",
            topic_type="sensor_msgs/msg/NavSatFix",
            output_path=temp_output_path,
            start_time_ns=1765331708854518630,
            end_time_ns=1765331708854518630 + 10_000_000_000
        )
        
        exporter = CSVExporter()
        result = exporter.export_topic(config)
        
        assert result.success is True
        assert result.message_count < 536
        assert result.message_count > 0
    
    def test_export_topic_with_progress_callback(self, sample_bag_path, temp_output_path):
        progress_calls = []
        
        def progress_callback(current, total):
            progress_calls.append((current, total))
        
        config = CSVExportConfig(
            bag_path=sample_bag_path,
            topic_name="/excavator/sensors/gnss_position",
            topic_type="sensor_msgs/msg/NavSatFix",
            output_path=temp_output_path
        )
        
        exporter = CSVExporter()
        result = exporter.export_topic(config, progress_callback=progress_callback)
        
        assert result.success is True
        assert len(progress_calls) == 536
        assert progress_calls[-1][0] == 536
    
    def test_export_topic_nonexistent_topic(self, sample_bag_path, temp_output_path):
        config = CSVExportConfig(
            bag_path=sample_bag_path,
            topic_name="/nonexistent/topic",
            topic_type="sensor_msgs/msg/NavSatFix",
            output_path=temp_output_path
        )
        
        exporter = CSVExporter()
        result = exporter.export_topic(config)
        
        assert result.success is True
        assert result.message_count == 0
        assert result.column_count == 2
        
        with open(temp_output_path, 'r') as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
            assert columns == ['timestamp_sec', 'timestamp_nanosec']
            rows = list(reader)
            assert len(rows) == 0
    
    def test_export_topic_creates_temp_file_and_renames(self, sample_bag_path, temp_output_path):
        config = CSVExportConfig(
            bag_path=sample_bag_path,
            topic_name="/excavator/sensors/gnss_position",
            topic_type="sensor_msgs/msg/NavSatFix",
            output_path=temp_output_path
        )
        
        exporter = CSVExporter()
        result = exporter.export_topic(config)
        
        assert result.success is True
        assert os.path.exists(temp_output_path)
        assert not os.path.exists(temp_output_path + '.tmp')
    
    def test_export_topic_overwrites_existing_file(self, sample_bag_path, temp_output_path):
        with open(temp_output_path, 'w') as f:
            f.write("old content")
        
        config = CSVExportConfig(
            bag_path=sample_bag_path,
            topic_name="/excavator/sensors/gnss_position",
            topic_type="sensor_msgs/msg/NavSatFix",
            output_path=temp_output_path
        )
        
        exporter = CSVExporter()
        result = exporter.export_topic(config)
        
        assert result.success is True
        
        with open(temp_output_path, 'r') as f:
            content = f.read()
            assert "old content" not in content
            assert "timestamp_sec" in content
    
    def test_csv_export_config_dataclass(self):
        config = CSVExportConfig(
            bag_path="/path/to/bag",
            topic_name="/test/topic",
            topic_type="std_msgs/msg/String",
            output_path="/path/to/output.csv",
            start_time_ns=1000,
            end_time_ns=2000
        )
        
        assert config.bag_path == "/path/to/bag"
        assert config.topic_name == "/test/topic"
        assert config.topic_type == "std_msgs/msg/String"
        assert config.output_path == "/path/to/output.csv"
        assert config.start_time_ns == 1000
        assert config.end_time_ns == 2000
    
    def test_csv_export_config_optional_fields(self):
        config = CSVExportConfig(
            bag_path="/path/to/bag",
            topic_name="/test/topic",
            topic_type="std_msgs/msg/String",
            output_path="/path/to/output.csv"
        )
        
        assert config.start_time_ns is None
        assert config.end_time_ns is None
    
    def test_csv_export_result_dataclass(self):
        result = CSVExportResult(
            success=True,
            output_path="/path/to/output.csv",
            message_count=100,
            column_count=10,
            error=None
        )
        
        assert result.success is True
        assert result.output_path == "/path/to/output.csv"
        assert result.message_count == 100
        assert result.column_count == 10
        assert result.error is None
    
    def test_csv_export_result_with_error(self):
        result = CSVExportResult(
            success=False,
            output_path="/path/to/output.csv",
            message_count=0,
            column_count=0,
            error="Test error message"
        )
        
        assert result.success is False
        assert result.error == "Test error message"
    
    def test_flatten_message_with_boolean(self):
        msg = SimpleNamespace(
            enabled=True,
            disabled=False
        )
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert result['enabled'] is True
        assert result['disabled'] is False
    
    def test_flatten_message_with_nested_array(self):
        msg = SimpleNamespace(
            matrix=[
                SimpleNamespace(x=1, y=2),
                SimpleNamespace(x=3, y=4)
            ]
        )
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert result['matrix_0_x'] == 1
        assert result['matrix_0_y'] == 2
        assert result['matrix_1_x'] == 3
        assert result['matrix_1_y'] == 4
    
    def test_flatten_message_with_tuple(self):
        msg = SimpleNamespace(
            coords=(10.0, 20.0, 30.0)
        )
        
        result = CSVExporter.flatten_message(msg, 0)
        
        assert result['coords_0'] == 10.0
        assert result['coords_1'] == 20.0
        assert result['coords_2'] == 30.0
    
    def test_max_array_size_constant(self):
        assert CSVExporter.MAX_ARRAY_SIZE == 100
