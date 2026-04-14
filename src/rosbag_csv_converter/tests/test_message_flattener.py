import pytest
from rosbag_csv_converter.core.message_flattener import flatten_message, ArrayFormat


class TestFlattenSimpleTypes:
    def test_flatten_float32(self):
        msg = type('Float32', (), {'data': 3.14})()
        result = flatten_message(msg, "test_topic")
        assert result == {"test_topic.data": 3.14}

    def test_flatten_int32(self):
        msg = type('Int32', (), {'data': 42})()
        result = flatten_message(msg, "test_topic")
        assert result == {"test_topic.data": 42}

    def test_flatten_bool(self):
        msg = type('Bool', (), {'data': True})()
        result = flatten_message(msg, "test_topic")
        assert result == {"test_topic.data": True}

    def test_flatten_string(self):
        msg = type('String', (), {'data': "hello"})()
        result = flatten_message(msg, "test_topic")
        assert result == {"test_topic.data": "hello"}


class TestFlattenNestedMessages:
    def test_flatten_header_stamp(self):
        stamp = type('Time', (), {'sec': 123, 'nanosec': 456789})()
        header = type('Header', (), {'stamp': stamp, 'frame_id': 'base_link'})()
        msg = type('MsgWithHeader', (), {'header': header, 'value': 1.0})()
        
        result = flatten_message(msg, "topic")
        
        assert result["topic.header.stamp.sec"] == 123
        assert result["topic.header.stamp.nanosec"] == 456789
        assert result["topic.header.frame_id"] == "base_link"
        assert result["topic.value"] == 1.0

    def test_flatten_point(self):
        point = type('Point', (), {'x': 1.0, 'y': 2.0, 'z': 3.0})()
        msg = type('PointStamped', (), {'point': point})()
        
        result = flatten_message(msg, "pos")
        
        assert result["pos.point.x"] == 1.0
        assert result["pos.point.y"] == 2.0
        assert result["pos.point.z"] == 3.0


class TestFlattenArraysExpandMode:
    def test_flatten_float_array_expand(self):
        msg = type('Float32MultiArray', (), {'data': [1.0, 2.0, 3.0]})()
        
        result = flatten_message(msg, "arr", array_format=ArrayFormat.EXPAND)
        
        assert result["arr.data_0"] == 1.0
        assert result["arr.data_1"] == 2.0
        assert result["arr.data_2"] == 3.0

    def test_flatten_empty_array_expand(self):
        msg = type('Float32MultiArray', (), {'data': []})()
        
        result = flatten_message(msg, "arr", array_format=ArrayFormat.EXPAND)
        
        assert "arr.data" not in result


class TestFlattenArraysJsonMode:
    def test_flatten_float_array_json(self):
        msg = type('Float32MultiArray', (), {'data': [1.0, 2.0, 3.0]})()
        
        result = flatten_message(msg, "arr", array_format=ArrayFormat.JSON)
        
        assert result["arr.data"] == "[1.0, 2.0, 3.0]"

    def test_flatten_int_array_json(self):
        msg = type('Int32MultiArray', (), {'data': [1, 2, 3]})()
        
        result = flatten_message(msg, "arr", array_format=ArrayFormat.JSON)
        
        assert result["arr.data"] == "[1, 2, 3]"


class TestFlattenArraysCommaMode:
    def test_flatten_float_array_comma(self):
        msg = type('Float32MultiArray', (), {'data': [1.0, 2.0, 3.0]})()
        
        result = flatten_message(msg, "arr", array_format=ArrayFormat.COMMA)
        
        assert result["arr.data"] == "1.0;2.0;3.0"


class TestFlattenComplexMessages:
    def test_flatten_remote_controller_feedback_like(self):
        stamp = type('Time', (), {'sec': 100, 'nanosec': 500})()
        msg = type('RemoteControllerFeedback', (), {
            'arm_remote_controller': 0.5,
            'swing_remote_controller': -0.3,
            'boom_remote_controller': 0.8,
            'bucket_remote_controller': -0.2,
            'right_track_remote_controller': 0.1,
            'left_track_remote_controller': 0.1,
            'reserved_6_remote_controller': 0,
            'reserved_7_remote_controller': 0,
            'stamp': stamp
        })()
        
        result = flatten_message(msg, "rc")
        
        assert result["rc.arm_remote_controller"] == 0.5
        assert result["rc.swing_remote_controller"] == -0.3
        assert result["rc.stamp.sec"] == 100


class TestEdgeCases:
    def test_flatten_none_value(self):
        msg = type('MsgWithNone', (), {'value': None})()
        result = flatten_message(msg, "test")
        assert result["test.value"] is None

    def test_flatten_with_slots(self):
        class MsgWithSlots:
            __slots__ = ['x', 'y']
            def __init__(self):
                self.x = 1.0
                self.y = 2.0
        
        msg = MsgWithSlots()
        result = flatten_message(msg, "slot")
        assert result["slot.x"] == 1.0
        assert result["slot.y"] == 2.0
