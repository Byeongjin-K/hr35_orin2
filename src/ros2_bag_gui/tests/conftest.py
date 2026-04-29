"""Pytest configuration and fixtures"""
import os
import pytest
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect config to temp dir so real user config is never touched."""
    config_dir = tmp_path / ".ros2_bag_gui"
    monkeypatch.setattr(
        "ros2_bag_gui.config.settings.SettingsManager.CONFIG_DIR", config_dir
    )
    monkeypatch.setattr(
        "ros2_bag_gui.config.settings.SettingsManager.CONFIG_FILE",
        config_dir / "config.json",
    )
    profiles_dir = str(config_dir / "profiles")
    monkeypatch.setattr(
        "ros2_bag_gui.config.profiles.ProfileManager.DEFAULT_PROFILES_DIR",
        profiles_dir,
    )


@pytest.fixture
def sample_topic_list():
    """Sample topic list for testing"""
    return [
        ("/excavator/sensors/gnss_position", "sensor_msgs/msg/NavSatFix"),
        ("/lidar_boom/points", "sensor_msgs/msg/PointCloud2"),
        ("/tf", "tf2_msgs/msg/TFMessage"),
    ]
