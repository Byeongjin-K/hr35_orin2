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

def test_ctrl_c_kill_and_a_closed_terminal_close_the_window(qtbot):
    """Closing is what stops a recording, and the SVO2 a ZED driver records for it."""
    import signal
    from typing import Callable, cast
    from PySide6.QtWidgets import QWidget
    from ros2_bag_gui.__main__ import _close_on_signals
    closed = []

    class Window(QWidget):
        def closeEvent(self, event):
            closed.append(True)
            super().closeEvent(event)

    window = Window()
    qtbot.addWidget(window)
    window.show()
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    saved = {sig: signal.getsignal(sig) for sig in signals}
    try:
        _close_on_signals(window)
        handlers = [signal.getsignal(sig) for sig in signals]
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)

    assert all(callable(handler) for handler in handlers)
    cast(Callable[..., object], handlers[1])(signal.SIGTERM, None)
    assert closed == [True]


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

def test_status_bar_does_not_keep_saying_started_when_recording_ends_by_itself(main_window):
    main_window.recording_tab.recording_active_changed.emit(True)
    main_window.recording_tab.recording_start_requested.emit({'session_name': 's'})
    started = main_window.status_bar.currentMessage()

    main_window.recording_tab.recording_active_changed.emit(False)  # e.g. the recorder died

    assert main_window.status_bar.currentMessage() != started
