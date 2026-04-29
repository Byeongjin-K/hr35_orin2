"""Tests for export tab widget."""
import pytest
import os
import yaml
from pathlib import Path
from PySide6.QtCore import Qt
from ros2_bag_gui.widgets.export_tab import ExportTab
from ros2_bag_gui.export.bag_loader import BagSessionInfo, TopicInfo
from ros2_bag_gui.export.image_exporter import ImageSource


@pytest.fixture
def mock_session_dir(tmp_path):
    """Create a mock session directory with metadata.yaml."""
    session_dir = tmp_path / "test_session"
    session_dir.mkdir()
    
    rosbag_dir = session_dir / "rosbag"
    rosbag_dir.mkdir()
    
    metadata = {
        'rosbag2_bagfile_information': {
            'duration': {
                'nanoseconds': 592000000000
            },
            'starting_time': {
                'nanoseconds_since_epoch': 1733824508000000000
            },
            'storage_identifier': 'sqlite3',
            'relative_file_paths': ['test_0.db3'],
            'topics_with_message_count': [
                {
                    'topic_metadata': {
                        'name': '/excavator/sensors/gnss_position',
                        'type': 'sensor_msgs/msg/NavSatFix',
                        'serialization_format': 'cdr'
                    },
                    'message_count': 536
                },
                {
                    'topic_metadata': {
                        'name': '/lidar_boom/points',
                        'type': 'sensor_msgs/msg/PointCloud2',
                        'serialization_format': 'cdr'
                    },
                    'message_count': 4500
                },
                {
                    'topic_metadata': {
                        'name': '/excavator/sensors/imu',
                        'type': 'sensor_msgs/msg/Imu',
                        'serialization_format': 'cdr'
                    },
                    'message_count': 1200
                }
            ]
        }
    }
    
    metadata_path = rosbag_dir / "metadata.yaml"
    with open(metadata_path, 'w') as f:
        yaml.dump(metadata, f)
    
    db3_file = rosbag_dir / "test_0.db3"
    db3_file.touch()
    
    pointcloud_dir = session_dir / "pointcloud"
    pointcloud_dir.mkdir()
    for i in range(5):
        laz_file = pointcloud_dir / f"173382450{i}000000000.laz"
        laz_file.touch()
    
    return session_dir


@pytest.fixture
def export_tab(qtbot):
    widget = ExportTab()
    qtbot.addWidget(widget)
    return widget


def test_widget_creation(export_tab):
    """Test that all sub-widgets are created."""
    assert export_tab.session_path_edit is not None
    assert export_tab.browse_btn is not None
    assert export_tab.load_btn is not None
    assert export_tab.session_status_label is not None
    assert export_tab.time_range_selector is not None
    assert export_tab.csv_checkbox is not None
    assert export_tab.topic_tree is not None
    assert export_tab.topic_count_label is not None
    assert export_tab.laz_checkbox is not None
    assert export_tab.laz_status_label is not None
    assert export_tab.image_checkbox is not None
    assert export_tab.image_status_label is not None
    assert export_tab.output_dir_edit is not None
    assert export_tab.output_browse_btn is not None
    assert export_tab.generate_timestamps_cb is not None
    assert export_tab.merge_laz_cb is not None
    assert export_tab.export_btn is not None


def test_initial_state_disabled(export_tab):
    """Test that export button is disabled when no session loaded."""
    assert not export_tab.export_btn.isEnabled()
    assert not export_tab.time_range_selector.isEnabled()
    assert export_tab.session_status_label.text() == "Status: No session loaded"


def test_load_session_populates_ui(export_tab, mock_session_dir, monkeypatch):
    """Test that loading a session populates the UI."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    assert export_tab._session is not None
    assert export_tab.time_range_selector.isEnabled()
    assert "Loaded:" in export_tab.session_status_label.text()
    assert "topics" in export_tab.session_status_label.text()


def test_time_range_populated_after_load(export_tab, mock_session_dir, monkeypatch):
    """Test that time range selector is populated after loading session."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    start_ns, end_ns = export_tab.time_range_selector.get_selected_range()
    assert start_ns == 1733824508000000000
    assert end_ns == 1733824508000000000 + 592000000000


def test_csv_topic_list_populated_with_numeric_only(export_tab, mock_session_dir, monkeypatch):
    """Test that topic list shows only numeric topics (excludes PointCloud2)."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    assert export_tab.topic_tree.topLevelItemCount() == 2
    
    topic_names = []
    for i in range(export_tab.topic_tree.topLevelItemCount()):
        item = export_tab.topic_tree.topLevelItem(i)
        topic_names.append(item.text(0))
    
    assert '/excavator/sensors/gnss_position' in topic_names
    assert '/excavator/sensors/imu' in topic_names
    assert '/lidar_boom/points' not in topic_names
    
    assert "2 topics available" in export_tab.topic_count_label.text()


def test_laz_status_shows_count(export_tab, mock_session_dir, monkeypatch):
    """Test that LAZ status shows file count when pointcloud exists."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    assert "5 LAZ files" in export_tab.laz_status_label.text()
    assert export_tab.laz_checkbox.isEnabled()


def test_image_status_unavailable(export_tab, mock_session_dir, monkeypatch):
    """Test that image status shows unavailable when no images."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    assert "Unavailable" in export_tab.image_status_label.text()
    assert not export_tab.image_checkbox.isEnabled()


def test_build_export_tasks_csv(export_tab, mock_session_dir, tmp_path, monkeypatch):
    """Test building CSV export tasks."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    export_tab.output_dir_edit.setText(str(tmp_path / "output"))
    
    export_tab.csv_checkbox.setChecked(True)
    export_tab.laz_checkbox.setChecked(False)
    export_tab.image_checkbox.setChecked(False)
    
    tasks = export_tab._build_export_tasks()
    
    assert len(tasks) == 2
    assert all(task.task_type == "csv" for task in tasks)
    assert any("/excavator/sensors/gnss_position" in task.description for task in tasks)
    assert any("/excavator/sensors/imu" in task.description for task in tasks)


def test_build_export_tasks_laz(export_tab, mock_session_dir, tmp_path, monkeypatch):
    """Test building LAZ export task."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    export_tab.output_dir_edit.setText(str(tmp_path / "output"))
    
    export_tab.csv_checkbox.setChecked(False)
    export_tab.laz_checkbox.setChecked(True)
    export_tab.image_checkbox.setChecked(False)
    
    tasks = export_tab._build_export_tasks()
    
    assert len(tasks) == 1
    assert tasks[0].task_type == "laz"
    assert "LAZ" in tasks[0].description


def test_export_button_requires_output_dir(export_tab, mock_session_dir, monkeypatch):
    """Test that export button requires output directory."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    export_tab.output_dir_edit.setText("")
    export_tab._update_export_state()
    
    assert not export_tab.export_btn.isEnabled()
    
    export_tab.output_dir_edit.setText("/tmp/output")
    export_tab._update_export_state()
    
    assert export_tab.export_btn.isEnabled()


def test_browse_session_dialog(export_tab, monkeypatch):
    """Test browse session dialog."""
    from PySide6.QtWidgets import QFileDialog
    
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *args, **kwargs: "/tmp/test_session"
    )
    
    export_tab._on_browse_session()
    
    assert export_tab.session_path_edit.text() == "/tmp/test_session"


def test_browse_output_dialog(export_tab, monkeypatch):
    """Test browse output dialog."""
    from PySide6.QtWidgets import QFileDialog
    
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *args, **kwargs: "/tmp/output"
    )
    
    export_tab._on_browse_output()
    
    assert export_tab.output_dir_edit.text() == "/tmp/output"


def test_load_session_invalid_path(export_tab, monkeypatch):
    """Test loading session with invalid path shows error."""
    from PySide6.QtWidgets import QMessageBox
    
    warning_called = []
    monkeypatch.setattr(
        QMessageBox,
        'warning',
        lambda *args, **kwargs: warning_called.append(True)
    )
    
    export_tab.session_path_edit.setText("/nonexistent/path")
    export_tab._on_load_session()
    
    assert len(warning_called) == 1


def test_load_session_empty_path(export_tab, monkeypatch):
    """Test loading session with empty path shows error."""
    from PySide6.QtWidgets import QMessageBox
    
    warning_called = []
    monkeypatch.setattr(
        QMessageBox,
        'warning',
        lambda *args, **kwargs: warning_called.append(True)
    )
    
    export_tab.session_path_edit.setText("")
    export_tab._on_load_session()
    
    assert len(warning_called) == 1


def test_get_selected_topics(export_tab, mock_session_dir, monkeypatch):
    """Test getting selected topics from tree."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    export_tab.topic_tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    export_tab.topic_tree.topLevelItem(1).setCheckState(0, Qt.CheckState.Unchecked)
    
    selected = export_tab._get_selected_topics()
    
    assert len(selected) == 1
    assert selected[0].name == '/excavator/sensors/gnss_position'


def test_export_button_disabled_no_selection(export_tab, mock_session_dir, tmp_path, monkeypatch):
    """Test that export button is disabled when no export options selected."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    export_tab.session_path_edit.setText(str(mock_session_dir))
    export_tab._on_load_session()
    
    export_tab.output_dir_edit.setText(str(tmp_path / "output"))
    
    for i in range(export_tab.topic_tree.topLevelItemCount()):
        export_tab.topic_tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Unchecked)
    
    export_tab.csv_checkbox.setChecked(True)
    export_tab.laz_checkbox.setChecked(False)
    export_tab.image_checkbox.setChecked(False)
    
    export_tab._update_export_state()
    
    assert not export_tab.export_btn.isEnabled()


def test_export_completed_signal(export_tab, qtbot, monkeypatch):
    """Test that export_completed signal is emitted."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args, **kwargs: None)
    
    received_signals = []
    export_tab.export_completed.connect(
        lambda success, summary: received_signals.append((success, summary))
    )
    
    export_tab._on_export_finished(True, "Export successful")
    
    assert len(received_signals) == 1
    assert received_signals[0] == (True, "Export successful")


def test_laz_checkbox_disabled_when_no_pointcloud(export_tab, tmp_path, monkeypatch):
    """Test that LAZ checkbox is disabled when no pointcloud data."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    
    session_dir = tmp_path / "no_pointcloud_session"
    session_dir.mkdir()
    
    rosbag_dir = session_dir / "rosbag"
    rosbag_dir.mkdir()
    
    metadata = {
        'rosbag2_bagfile_information': {
            'duration': {'nanoseconds': 100000000000},
            'starting_time': {'nanoseconds_since_epoch': 1733824508000000000},
            'storage_identifier': 'sqlite3',
            'relative_file_paths': ['test_0.db3'],
            'topics_with_message_count': [
                {
                    'topic_metadata': {
                        'name': '/test/topic',
                        'type': 'std_msgs/msg/String',
                        'serialization_format': 'cdr'
                    },
                    'message_count': 100
                }
            ]
        }
    }
    
    metadata_path = rosbag_dir / "metadata.yaml"
    with open(metadata_path, 'w') as f:
        yaml.dump(metadata, f)
    
    db3_file = rosbag_dir / "test_0.db3"
    db3_file.touch()
    
    export_tab.session_path_edit.setText(str(session_dir))
    export_tab._on_load_session()
    
    assert not export_tab.laz_checkbox.isEnabled()
    assert not export_tab.laz_checkbox.isChecked()
    assert "No pointcloud data" in export_tab.laz_status_label.text()
