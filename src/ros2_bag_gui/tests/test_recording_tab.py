"""Tests for recording tab widget."""
import pytest
from pathlib import Path
from PySide6.QtCore import Qt
from ros2_bag_gui.widgets.recording_tab import RecordingTab
from ros2_bag_gui.widgets.recording_status import RecordingState
from ros2_bag_gui.config.profiles import RecordingProfile


MOCK_TOPICS = [
    {'name': '/excavator/sensors/gnss_position', 'type': 'sensor_msgs/msg/NavSatFix', 'hz': 10.0, 'category': 'excavator'},
    {'name': '/excavator/status', 'type': 'std_msgs/msg/String', 'hz': 1.0, 'category': 'excavator'},
    {'name': '/lidar_boom/points', 'type': 'sensor_msgs/msg/PointCloud2', 'hz': 7.7, 'category': 'lidar'},
    {'name': '/lidar_boom/imu', 'type': 'sensor_msgs/msg/Imu', 'hz': 97.3, 'category': 'lidar'},
    {'name': '/zedx_boom/left/image', 'type': 'sensor_msgs/msg/Image', 'hz': 30.0, 'category': 'zed'},
    {'name': '/zedx_cabin/left/image', 'type': 'sensor_msgs/msg/Image', 'hz': 30.0, 'category': 'zed'},
    {'name': '/tf', 'type': 'tf2_msgs/msg/TFMessage', 'hz': 273.6, 'category': 'system'},
    {'name': '/gps_interface/position', 'type': 'sensor_msgs/msg/NavSatFix', 'hz': 5.0, 'category': 'gps'},
]


@pytest.fixture
def recording_tab(qtbot, tmp_path):
    widget = RecordingTab()
    profiles_dir = str(tmp_path / "profiles")
    widget.profile_manager = widget.profile_manager.__class__(profiles_dir)
    qtbot.addWidget(widget)
    widget.set_topics(MOCK_TOPICS)
    # Stop timer to prevent hangs in headless mode
    widget.status_panel._timer.stop()
    return widget


def test_widget_creation(recording_tab):
    """Test that all sub-widgets are created."""
    assert recording_tab.topic_list is not None
    assert recording_tab.settings_panel is not None
    assert recording_tab.status_panel is not None
    assert recording_tab.profile_manager is not None
    assert recording_tab.start_btn is not None
    assert recording_tab.stop_btn is not None
    assert recording_tab.profile_combo is not None


def test_initial_button_state(recording_tab):
    """Test initial button states."""
    assert recording_tab.start_btn.isEnabled()
    assert not recording_tab.stop_btn.isEnabled()


def test_set_topics(recording_tab):
    """Test that set_topics populates TopicListWidget."""
    topics = [
        {'name': '/test/topic1', 'type': 'std_msgs/msg/String', 'hz': 10.0, 'category': 'test'},
        {'name': '/test/topic2', 'type': 'std_msgs/msg/Int32', 'hz': 5.0, 'category': 'test'}
    ]
    recording_tab.set_topics(topics)
    assert recording_tab.topic_list._topics == topics


def test_start_button_emits_signal(recording_tab, qtbot):
    """Test that start button emits recording_start_requested with config."""
    recording_tab.topic_list.list_btn.setChecked(True)
    first_item = recording_tab.topic_list.tree.topLevelItem(0)
    first_item.setCheckState(0, Qt.CheckState.Checked)
    
    recording_tab.settings_panel.session_name_edit.setText("test_session")
    
    received_signals = []
    recording_tab.recording_start_requested.connect(lambda config: received_signals.append(config))
    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()
    
    assert len(received_signals) == 1
    config = received_signals[0]
    assert 'topics' in config
    assert len(config['topics']) > 0
    assert config['session_name'] == "test_session"
    assert 'split_mode' in config
    assert 'split_size_gb' in config


def test_start_button_updates_ui_state(recording_tab, qtbot):
    """Test that start button updates UI state."""
    recording_tab.topic_list.list_btn.setChecked(True)
    first_item = recording_tab.topic_list.tree.topLevelItem(0)
    first_item.setCheckState(0, Qt.CheckState.Checked)
    
    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()
    
    assert not recording_tab.start_btn.isEnabled()
    assert recording_tab.stop_btn.isEnabled()
    assert recording_tab.status_panel._state == RecordingState.RECORDING


def test_start_button_requires_topics(recording_tab, qtbot, monkeypatch):
    """Test that start button shows warning if no topics selected."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args, **kwargs: None)
    
    received_signals = []
    recording_tab.recording_start_requested.connect(lambda config: received_signals.append(config))
    recording_tab._on_start_clicked()
    
    assert len(received_signals) == 0


def test_start_button_requires_output_path(recording_tab, qtbot, monkeypatch):
    """Test that start button shows warning if no output path."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args, **kwargs: None)
    
    recording_tab.topic_list.list_btn.setChecked(True)
    first_item = recording_tab.topic_list.tree.topLevelItem(0)
    first_item.setCheckState(0, Qt.CheckState.Checked)
    
    recording_tab.settings_panel._settings_manager.update(output_path="")
    
    received_signals = []
    recording_tab.recording_start_requested.connect(lambda config: received_signals.append(config))
    recording_tab._on_start_clicked()
    
    assert len(received_signals) == 0


def test_stop_button_emits_signal(recording_tab, qtbot):
    """Test that stop button emits recording_stop_requested."""
    recording_tab.topic_list.list_btn.setChecked(True)
    first_item = recording_tab.topic_list.tree.topLevelItem(0)
    first_item.setCheckState(0, Qt.CheckState.Checked)
    
    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()
    
    received_signals = []
    recording_tab.recording_stop_requested.connect(lambda: received_signals.append(True))
    recording_tab._on_stop_clicked()
    
    assert len(received_signals) == 1


def test_stop_button_updates_ui_state(recording_tab, qtbot):
    """Test that stop button updates UI state."""
    recording_tab.topic_list.list_btn.setChecked(True)
    first_item = recording_tab.topic_list.tree.topLevelItem(0)
    first_item.setCheckState(0, Qt.CheckState.Checked)
    
    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()
    recording_tab._on_stop_clicked()
    
    assert recording_tab.start_btn.isEnabled()
    assert not recording_tab.stop_btn.isEnabled()
    assert recording_tab.status_panel._state == RecordingState.STOPPED


def test_save_profile(recording_tab, qtbot, monkeypatch):
    """Test profile save functionality."""
    recording_tab.topic_list.list_btn.setChecked(True)
    first_item = recording_tab.topic_list.tree.topLevelItem(0)
    first_item.setCheckState(0, Qt.CheckState.Checked)
    
    recording_tab.settings_panel.session_name_edit.setText("test_session")
    
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ("test_profile", True))
    monkeypatch.setattr(QMessageBox, 'information', lambda *args, **kwargs: None)
    
    recording_tab._on_save_profile()
    
    profiles = recording_tab.profile_manager.list_profiles()
    assert "test_profile" in profiles


def test_load_profile(recording_tab, qtbot, monkeypatch):
    """Test profile load functionality."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', lambda *args, **kwargs: None)
    
    profile = RecordingProfile(
        name="test_load_profile",
        selected_topics=[MOCK_TOPICS[0]['name'], MOCK_TOPICS[1]['name']],
        save_path="/tmp/test_load",
        session_name_template="loaded_session",
        max_bag_size_gb=5.0,
        include_images_without_sdk=False
    )
    recording_tab.profile_manager.save_profile(profile)
    recording_tab._load_profile_list()
    
    index = recording_tab.profile_combo.findText("test_load_profile")
    recording_tab.profile_combo.setCurrentIndex(index)
    
    recording_tab._on_load_profile()
    
    assert recording_tab.settings_panel.path_edit.text() == "/tmp/test_load"
    assert recording_tab.settings_panel.session_name_edit.text() == "loaded_session"
    assert recording_tab.settings_panel.split_size_spin.value() == 5.0
    assert not recording_tab.settings_panel.include_images_cb.isChecked()
    
    selected_topics = recording_tab.topic_list.get_selected_topics()
    assert MOCK_TOPICS[0]['name'] in selected_topics
    assert MOCK_TOPICS[1]['name'] in selected_topics


def test_delete_profile(recording_tab, qtbot, monkeypatch):
    """Test profile delete functionality."""
    profile = RecordingProfile(
        name="test_delete_profile",
        selected_topics=[],
        save_path="/tmp/test"
    )
    recording_tab.profile_manager.save_profile(profile)
    recording_tab._load_profile_list()
    
    index = recording_tab.profile_combo.findText("test_delete_profile")
    recording_tab.profile_combo.setCurrentIndex(index)
    
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'information', lambda *args, **kwargs: None)
    
    recording_tab._on_delete_profile()
    
    profiles = recording_tab.profile_manager.list_profiles()
    assert "test_delete_profile" not in profiles


def test_profile_save_load_cycle(recording_tab, qtbot, monkeypatch):
    """Test complete save/load cycle."""
    recording_tab.topic_list.list_btn.setChecked(True)
    first_item = recording_tab.topic_list.tree.topLevelItem(0)
    second_item = recording_tab.topic_list.tree.topLevelItem(1)
    first_item.setCheckState(0, Qt.CheckState.Checked)
    second_item.setCheckState(0, Qt.CheckState.Checked)
    
    recording_tab.settings_panel.path_edit.setText("/tmp/cycle_test")
    recording_tab.settings_panel.session_name_edit.setText("cycle_session")
    recording_tab.settings_panel.split_size_spin.setValue(4.5)
    
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    monkeypatch.setattr(QInputDialog, 'getText', lambda *args, **kwargs: ("cycle_profile", True))
    monkeypatch.setattr(QMessageBox, 'information', lambda *args, **kwargs: None)
    
    recording_tab._on_save_profile()
    
    recording_tab.topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Unchecked)
    recording_tab.topic_list.tree.topLevelItem(1).setCheckState(0, Qt.CheckState.Unchecked)
    recording_tab.settings_panel.path_edit.setText("")
    recording_tab.settings_panel.session_name_edit.setText("")
    
    index = recording_tab.profile_combo.findText("cycle_profile")
    recording_tab.profile_combo.setCurrentIndex(index)
    recording_tab._on_load_profile()
    
    assert recording_tab.settings_panel.path_edit.text() == "/tmp/cycle_test"
    assert recording_tab.settings_panel.session_name_edit.text() == "cycle_session"
    assert recording_tab.settings_panel.split_size_spin.value() == 4.5
    
    selected = recording_tab.topic_list.get_selected_topics()
    assert len(selected) == 2


def test_reset(recording_tab, qtbot):
    """Test reset functionality."""
    recording_tab.topic_list.list_btn.setChecked(True)
    first_item = recording_tab.topic_list.tree.topLevelItem(0)
    first_item.setCheckState(0, Qt.CheckState.Checked)
    
    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()
    
    recording_tab.reset()
    
    assert recording_tab.start_btn.isEnabled()
    assert not recording_tab.stop_btn.isEnabled()
    assert recording_tab.status_panel._state == RecordingState.READY
