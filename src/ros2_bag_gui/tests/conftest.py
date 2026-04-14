"""Pytest configuration and fixtures"""
import os
import pytest
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

@pytest.fixture(scope="session", autouse=True)
def clean_config():
    """Clean config file before tests to ensure default settings are used."""
    config_file = Path.home() / ".ros2_bag_gui" / "config.json"
    if config_file.exists():
        config_file.unlink()

@pytest.fixture(autouse=True)
def reset_config_after_test():
    """Reset config file after each test."""
    yield
    config_file = Path.home() / ".ros2_bag_gui" / "config.json"
    if config_file.exists():
        config_file.unlink()

@pytest.fixture
def sample_topic_list():
    """Sample topic list for testing"""
    return [
        ("/excavator/sensors/gnss_position", "sensor_msgs/msg/NavSatFix"),
        ("/lidar_boom/points", "sensor_msgs/msg/PointCloud2"),
        ("/tf", "tf2_msgs/msg/TFMessage"),
    ]
