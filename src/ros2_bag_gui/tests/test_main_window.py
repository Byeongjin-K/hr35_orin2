"""Tests for main window."""
import pytest
from PySide6.QtWidgets import QApplication
from ros2_bag_gui.main_window import MainWindow

@pytest.fixture
def app(qtbot):
    """Create application instance."""
    return QApplication.instance() or QApplication([])

@pytest.fixture
def main_window(qtbot):
    """Create main window instance."""
    window = MainWindow()
    qtbot.addWidget(window)
    return window

def test_window_title(main_window):
    """Test window has correct title."""
    assert main_window.windowTitle() == "ROS2 Bag GUI"

def test_has_tabs(main_window):
    """Test window has Recording and Export tabs."""
    assert main_window.tab_widget.count() == 2
    assert main_window.tab_widget.tabText(0) == "Recording"
    assert main_window.tab_widget.tabText(1) == "Export"

def test_status_bar_ready(main_window):
    """Test status bar shows Ready."""
    assert main_window.status_bar.currentMessage() == "Ready"

def test_menu_bar_exists(main_window):
    """Test menu bar has File and Help menus."""
    menu_bar = main_window.menuBar()
    assert menu_bar is not None

def test_recording_menu_follows_recording_state(main_window):
    """Start is not offered while recording, Stop is not offered while idle."""
    assert main_window.start_recording_action.isEnabled()
    assert not main_window.stop_recording_action.isEnabled()

    main_window.recording_tab.recording_active_changed.emit(True)
    assert not main_window.start_recording_action.isEnabled()
    assert main_window.stop_recording_action.isEnabled()

    main_window.recording_tab.recording_active_changed.emit(False)
    assert main_window.start_recording_action.isEnabled()
    assert not main_window.stop_recording_action.isEnabled()
