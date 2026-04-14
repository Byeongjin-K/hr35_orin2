"""Tests for topic discovery."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from ros2_bag_gui.ros2.ros2_thread import ROS2Thread
from ros2_bag_gui.ros2.topic_discovery import TopicDiscoveryManager


class TestROS2Thread:
    def test_categorize_topic_excavator(self):
        thread = ROS2Thread()
        assert thread._categorize_topic('/excavator/status') == 'excavator'
    
    def test_categorize_topic_lidar(self):
        thread = ROS2Thread()
        assert thread._categorize_topic('/lidar_boom/points') == 'lidar'
    
    def test_categorize_topic_zed(self):
        thread = ROS2Thread()
        assert thread._categorize_topic('/zedx_boom/image') == 'zed'
    
    def test_categorize_topic_gps(self):
        thread = ROS2Thread()
        assert thread._categorize_topic('/gps/fix') == 'gps'
        assert thread._categorize_topic('/gnss/data') == 'gps'
    
    def test_categorize_topic_system(self):
        thread = ROS2Thread()
        assert thread._categorize_topic('/tf') == 'system'
        assert thread._categorize_topic('/tf_static') == 'system'
        assert thread._categorize_topic('/rosout') == 'system'
    
    def test_categorize_topic_other(self):
        thread = ROS2Thread()
        assert thread._categorize_topic('/some/random/topic') == 'other'
    
    def test_request_discover_topics(self):
        thread = ROS2Thread()
        thread.request_discover_topics()
        assert thread._pending_command == 'discover_topics'
    
    def test_is_connected_false_initially(self):
        thread = ROS2Thread()
        assert thread.is_connected is False


class TestTopicDiscoveryManager:
    def test_discovery_timeout(self, qtbot):
        mock_thread = Mock(spec=ROS2Thread)
        mock_thread.topic_list_updated = Mock()
        mock_thread.error_occurred = Mock()
        
        manager = TopicDiscoveryManager(mock_thread)
        
        assert manager._timeout_timer.isSingleShot()
    
    def test_discover_topics_starts_timer(self, qtbot):
        mock_thread = Mock(spec=ROS2Thread)
        mock_thread.topic_list_updated = Mock()
        mock_thread.error_occurred = Mock()
        
        manager = TopicDiscoveryManager(mock_thread)
        manager.discover_topics(timeout_ms=5000)
        
        assert manager._timeout_timer.isActive()
        mock_thread.request_discover_topics.assert_called_once()
    
    def test_on_topics_received_stops_timer(self, qtbot):
        mock_thread = Mock(spec=ROS2Thread)
        mock_thread.topic_list_updated = Mock()
        mock_thread.error_occurred = Mock()
        
        manager = TopicDiscoveryManager(mock_thread)
        manager._timeout_timer.start(5000)
        
        test_topics = [{'name': '/test', 'type': 'std_msgs/String', 'hz': 0.0, 'category': 'other'}]
        manager._on_topics_received(test_topics)
        
        assert not manager._timeout_timer.isActive()
