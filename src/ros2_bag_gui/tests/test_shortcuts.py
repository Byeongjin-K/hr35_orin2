"""Tests for keyboard shortcuts."""
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QKeySequence
from PySide6.QtCore import Qt
from ros2_bag_gui.main_window import MainWindow
from ros2_bag_gui.shortcuts import ShortcutManager


@pytest.fixture
def app(qtbot):
    return QApplication.instance() or QApplication([])


@pytest.fixture
def main_window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    return window


def test_shortcut_manager_created(main_window):
    assert hasattr(main_window, 'shortcut_manager')
    assert isinstance(main_window.shortcut_manager, ShortcutManager)


def test_shortcuts_registered(main_window):
    shortcuts = main_window.shortcut_manager.get_all_shortcuts()
    assert 'start_recording' in shortcuts
    assert 'stop_recording' in shortcuts
    assert 'quit' in shortcuts


def test_start_recording_shortcut_key(main_window):
    shortcut = main_window.shortcut_manager.get_shortcut('start_recording')
    assert shortcut is not None
    assert shortcut.key() == QKeySequence("Ctrl+R")


def test_stop_recording_shortcut_key(main_window):
    shortcut = main_window.shortcut_manager.get_shortcut('stop_recording')
    assert shortcut is not None
    assert shortcut.key() == QKeySequence("Ctrl+S")


def test_quit_shortcut_key(main_window):
    shortcut = main_window.shortcut_manager.get_shortcut('quit')
    assert shortcut is not None
    assert shortcut.key() == QKeySequence("Ctrl+Q")


def test_recording_menu_exists(main_window):
    menu_bar = main_window.menuBar()
    actions = menu_bar.actions()
    menu_titles = [action.text() for action in actions]
    assert '&Recording' in menu_titles


def test_start_recording_menu_item(main_window):
    assert hasattr(main_window, 'start_recording_action')
    assert main_window.start_recording_action.text() == "&Start Recording"
    assert main_window.start_recording_action.shortcut() == QKeySequence("Ctrl+R")


def test_stop_recording_menu_item(main_window):
    assert hasattr(main_window, 'stop_recording_action')
    assert main_window.stop_recording_action.text() == "S&top Recording"
    assert main_window.stop_recording_action.shortcut() == QKeySequence("Ctrl+S")


def test_start_recording_signal_emitted(main_window, qtbot):
    with qtbot.waitSignal(main_window.recording_started, timeout=1000):
        main_window._on_start_recording()


def test_stop_recording_signal_emitted(main_window, qtbot):
    with qtbot.waitSignal(main_window.recording_stopped, timeout=1000):
        main_window._on_stop_recording()


def test_start_recording_updates_status(main_window):
    main_window._on_start_recording()
    assert main_window.status_bar.currentMessage() == "Recording started"


def test_stop_recording_updates_status(main_window):
    main_window._on_stop_recording()
    assert main_window.status_bar.currentMessage() == "Recording stopped"


def test_shortcut_activation_triggers_callback(main_window, qtbot):
    with qtbot.waitSignal(main_window.recording_started, timeout=1000):
        shortcut = main_window.shortcut_manager.get_shortcut('start_recording')
        shortcut.activated.emit()


def test_get_nonexistent_shortcut_returns_none(main_window):
    shortcut = main_window.shortcut_manager.get_shortcut('nonexistent')
    assert shortcut is None
