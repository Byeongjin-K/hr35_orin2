"""Tests for recording status panel."""
import pytest
from PySide6.QtCore import Qt
from ros2_bag_gui.widgets.recording_status import (
    RecordingStatusPanel, RecordingState, DiskSpaceState
)

@pytest.fixture
def status_panel(qtbot):
    panel = RecordingStatusPanel()
    qtbot.addWidget(panel)
    return panel

def test_initial_state(status_panel):
    assert status_panel._state == RecordingState.READY
    assert status_panel.state_label.text() == "Ready"
    assert status_panel.elapsed_label.text() == "00:00:00"

def test_set_recording_state(status_panel):
    status_panel.set_state(RecordingState.RECORDING)
    assert status_panel.state_label.text() == "Recording"

def test_set_stopped_state(status_panel):
    status_panel.set_state(RecordingState.STOPPED)
    assert status_panel.state_label.text() == "Stopped"

def test_elapsed_timer(status_panel, qtbot):
    status_panel.set_state(RecordingState.RECORDING)
    status_panel._elapsed_seconds = 90
    status_panel._update_elapsed_display()
    assert status_panel.elapsed_label.text() == "00:01:30"

def test_update_topic_stats(status_panel):
    stats = {
        '/topic1': {'count': 100, 'hz': 10.0},
        '/topic2': {'count': 200, 'hz': 20.0}
    }
    status_panel.update_topic_stats(stats)
    assert status_panel.stats_table.rowCount() == 2
    
    assert status_panel.stats_table.item(0, 0).text() == "/topic1"
    assert status_panel.stats_table.item(0, 1).text() == "100"
    assert status_panel.stats_table.item(0, 2).text() == "10.0"

def test_format_size(status_panel):
    assert 'MB' in status_panel._format_size(1024 * 1024)
    assert 'GB' in status_panel._format_size(1024 * 1024 * 1024)

def test_reset(status_panel):
    status_panel.set_state(RecordingState.RECORDING)
    status_panel._elapsed_seconds = 100
    status_panel.reset()
    assert status_panel._state == RecordingState.READY
    assert status_panel._elapsed_seconds == 0
