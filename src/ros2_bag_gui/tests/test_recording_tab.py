"""Tests for recording tab widget."""
import pytest
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ros2_bag_gui.widgets.recording_tab import RecordingTab
from ros2_bag_gui.widgets.recording_status import RecordingState
from ros2_bag_gui.config.profiles import RecordingProfile
from ros2_bag_gui.ros2.ros2_thread import ROS2Thread


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


class FakeRecorder:
    """Stands in for Recorder: notes what the tab asks for, starts no process."""

    def __init__(self):
        self.recording = False
        self.start_result = True
        self.started_with = None
        self.start_calls = 0
        self.stop_calls = 0
        self.stop_reason = None
        self.topic_counts = {}
        self.session_path = ""
        self.last_bag_counts = {}
        self.last_bag_topics = []

    @property
    def is_recording(self):
        return self.recording

    def start_recording(self, config, node):
        self.started_with = config
        self.start_calls += 1
        self.recording = self.start_result
        return self.start_result

    def stop_recording(self, node=None, reason=None):
        self.stop_calls += 1
        self.stop_reason = reason
        self.recording = False
        return "/tmp/fake_session"

    def get_topic_hz(self):
        return {}

    def check_health(self):
        pass


@pytest.fixture
def recording_tab(qtbot, tmp_path, monkeypatch, fake_node):
    # Widget tests run without rclpy and without a recorder process: the tab
    # talks to stand-ins. The real recording path is covered in test_recorder.py.
    monkeypatch.setattr(ROS2Thread, "start", lambda self: None)
    monkeypatch.setattr(ROS2Thread, "node", property(lambda self: fake_node))
    monkeypatch.setattr("ros2_bag_gui.widgets.recording_tab.find_other_recorders", lambda: [], raising=False)
    widget = RecordingTab()
    widget._recorder = FakeRecorder()
    widget.settings_panel._settings_manager.update(output_path=str(tmp_path / "recordings"))
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
    assert config['lidar_mode'] == "bag"
    assert config['camera_mode'] == "bag"
    assert recording_tab._recorder.started_with.topics[0]['name'] == config['topics'][0]


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


def test_recorder_error_leaves_recording_state(recording_tab, qtbot, monkeypatch):
    """When the recorder reports that it is no longer recording, the screen says so."""
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: shown.append(args[2]))
    recording_tab.topic_list.list_btn.setChecked(True)
    recording_tab.topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()

    recording_tab._recorder.recording = False
    recording_tab._on_recorder_error("recorder ended")

    assert shown == ["recorder ended"]
    assert recording_tab.status_panel._state == RecordingState.ERROR
    assert recording_tab.start_btn.isEnabled()
    assert not recording_tab.stop_btn.isEnabled()


def test_failed_start_does_not_show_recording(recording_tab, qtbot):
    recording_tab.topic_list.list_btn.setChecked(True)
    recording_tab.topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    recording_tab._recorder.start_result = False
    received = []
    recording_tab.recording_start_requested.connect(received.append)

    recording_tab._on_start_clicked()

    assert received == []
    assert recording_tab.start_btn.isEnabled()
    assert recording_tab.status_panel._state != RecordingState.RECORDING


def test_stop_still_stops_when_ros_node_is_gone(recording_tab, qtbot, monkeypatch):
    recording_tab.topic_list.list_btn.setChecked(True)
    recording_tab.topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()
    monkeypatch.setattr(ROS2Thread, "node", property(lambda self: None))

    recording_tab._on_stop_clicked()

    assert recording_tab._recorder.stop_calls == 1
    assert not recording_tab._recorder.is_recording


def test_start_while_recording_does_not_start_again(recording_tab, qtbot):
    """Menu and shortcut reach the same slot as the button; a second Start must be a no-op."""
    recording_tab.topic_list.list_btn.setChecked(True)
    recording_tab.topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    active = []
    recording_tab.recording_active_changed.connect(active.append)

    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()
    recording_tab._on_start_clicked()

    assert recording_tab._recorder.start_calls == 1
    assert active == [True]


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
    )
    recording_tab.profile_manager.save_profile(profile)
    recording_tab._load_profile_list()
    
    index = recording_tab.profile_combo.findText("test_load_profile")
    recording_tab.profile_combo.setCurrentIndex(index)
    
    recording_tab._on_load_profile()
    
    assert recording_tab.settings_panel.path_edit.text() == "/tmp/test_load"
    assert recording_tab.settings_panel.session_name_edit.text() == "loaded_session"
    assert recording_tab.settings_panel.split_size_spin.value() == 5.0
    
    selected_topics = recording_tab.topic_list.get_selected_topics()
    assert MOCK_TOPICS[0]['name'] in selected_topics
    assert MOCK_TOPICS[1]['name'] in selected_topics


def test_load_profile_with_svo2_without_sdk_uses_bag(recording_tab, qtbot, monkeypatch):
    """A profile cannot switch on a camera mode that this machine cannot record."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', lambda *args, **kwargs: None)
    monkeypatch.setattr(recording_tab.settings_panel, '_zed_available', False)
    recording_tab.profile_manager.save_profile(RecordingProfile(
        name="svo2_profile", selected_topics=[], save_path="/tmp/test_load", camera_mode="svo2",
    ))
    recording_tab._load_profile_list()
    recording_tab.profile_combo.setCurrentIndex(recording_tab.profile_combo.findText("svo2_profile"))

    recording_tab._on_load_profile()

    assert recording_tab.settings_panel.camera_mode_combo.currentIndex() == 0
    assert recording_tab.settings_panel.get_settings().camera_mode == "bag"


def test_recorder_warning_stays_on_screen(recording_tab, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args, **kwargs: shown.append(args[2]))

    recording_tab._on_recorder_warning("images go to the bag")

    assert shown == ["images go to the bag"]
    assert "images go to the bag" in recording_tab.status_panel.notice_label.text()
    assert not recording_tab.status_panel.notice_label.isHidden()


def _table(panel):
    table = panel.stats_table
    headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
    rows = [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount())]
    return headers, rows


def test_after_stop_the_table_shows_what_is_in_the_bag(recording_tab, qtbot):
    recorder = recording_tab._recorder
    recorder.topic_counts = {'/excavator/joints': 2600, '/zedx_boom/left/image': 70}
    recorder.last_bag_counts = {'/excavator/joints': 1360}
    recorder.last_bag_topics = ['/excavator/joints', '/zedx_boom/left/image']

    recording_tab._on_recorder_stopped()

    headers, rows = _table(recording_tab.status_panel)
    assert headers == recording_tab.status_panel.FINAL_HEADERS
    assert rows == [['/excavator/joints', '1360', '2600'], ['/zedx_boom/left/image', '0', '70']]
    assert '/zedx_boom/left/image' in recording_tab.status_panel.notice_label.text()


def test_after_stop_unreadable_bag_counts_are_shown_as_unknown(recording_tab, qtbot):
    recorder = recording_tab._recorder
    recorder.topic_counts = {'/excavator/joints': 2600}
    recorder.last_bag_counts = None

    recording_tab._on_recorder_stopped()

    assert _table(recording_tab.status_panel)[1] == [['/excavator/joints', 'unknown', '2600']]
    assert not recording_tab.status_panel.notice_label.isHidden()


def test_live_numbers_are_labelled_as_received_by_the_gui(recording_tab, qtbot):
    recording_tab.status_panel.update_topic_stats({'/excavator/joints': {'count': 5, 'hz': 1.0}})

    assert _table(recording_tab.status_panel)[0] == recording_tab.status_panel.LIVE_HEADERS
    assert recording_tab.status_panel.LIVE_HEADERS != recording_tab.status_panel.FINAL_HEADERS


def _load_profile(recording_tab, monkeypatch, topics):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', lambda *args, **kwargs: None)
    save_path = recording_tab.settings_panel.get_settings().output_path
    recording_tab.profile_manager.save_profile(RecordingProfile(
        name="early_profile", selected_topics=topics, save_path=save_path,
    ))
    recording_tab._load_profile_list()
    recording_tab.profile_combo.setCurrentIndex(recording_tab.profile_combo.findText("early_profile"))
    recording_tab._on_load_profile()


def test_profile_loaded_before_all_topics_are_up_keeps_them_selected(recording_tab, qtbot, monkeypatch):
    wanted = [MOCK_TOPICS[0]['name'], MOCK_TOPICS[2]['name'], MOCK_TOPICS[4]['name']]
    recording_tab.set_topics(MOCK_TOPICS[:2])  # the sensors are not up yet

    _load_profile(recording_tab, monkeypatch, wanted)
    recording_tab.set_topics(MOCK_TOPICS)  # a later refresh finds them

    assert sorted(recording_tab.topic_list.get_selected_topics()) == sorted(wanted)


@pytest.mark.parametrize("answer_yes", [False, True])
def test_start_asks_about_selected_topics_that_are_not_available(
        recording_tab, qtbot, monkeypatch, answer_yes):
    from PySide6.QtWidgets import QMessageBox
    asked = []

    def question(parent, title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.StandardButton.Yes if answer_yes else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, 'question', question)
    present, absent = MOCK_TOPICS[0]['name'], MOCK_TOPICS[2]['name']
    recording_tab.set_topics(MOCK_TOPICS[:2])
    _load_profile(recording_tab, monkeypatch, [present, absent])

    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()

    assert len(asked) == 1 and absent in asked[0]
    if answer_yes:
        recorded = [t['name'] for t in recording_tab._recorder.started_with.topics]
        assert recorded == [present, absent]
    else:
        assert recording_tab._recorder.start_calls == 0


@pytest.mark.parametrize("answer_yes", [False, True])
def test_start_asks_when_another_recorder_is_running(recording_tab, qtbot, monkeypatch, answer_yes):
    from PySide6.QtWidgets import QMessageBox
    asked = []

    def question(parent, title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.StandardButton.Yes if answer_yes else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, 'question', question)
    monkeypatch.setattr(
        "ros2_bag_gui.widgets.recording_tab.find_other_recorders", lambda: [4242], raising=False)
    recording_tab.topic_list.list_btn.setChecked(True)
    recording_tab.topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)

    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()

    assert len(asked) == 1 and "4242" in asked[0]
    assert recording_tab._recorder.start_calls == (1 if answer_yes else 0)


@pytest.mark.parametrize("split_mode, expected_bytes, expected_seconds", [
    ("size", 2 * 1024**3, 0),
    ("time", 0, 45 * 60),
    ("none", 0, 0),
])
def test_split_mode_reaches_the_recorder(
        recording_tab, qtbot, split_mode, expected_bytes, expected_seconds):
    recording_tab.settings_panel._settings_manager.update(
        split_mode=split_mode, split_size_gb=2.0, split_time_minutes=45)
    recording_tab.topic_list.list_btn.setChecked(True)
    recording_tab.topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)

    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()

    config = recording_tab._recorder.started_with
    assert config.max_bagfile_size == expected_bytes
    assert getattr(config, 'max_bag_duration', None) == expected_seconds


def _disk_with(monkeypatch, free_gb):
    from collections import namedtuple
    usage = namedtuple('usage', 'total used free')
    monkeypatch.setattr(
        'shutil.disk_usage',
        lambda path: usage(100 * 1024**3, int((100 - free_gb) * 1024**3), int(free_gb * 1024**3)),
    )


def _start_with_one_topic(recording_tab):
    recording_tab.topic_list.list_btn.setChecked(True)
    recording_tab.topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.stop()


@pytest.mark.parametrize("answer_yes", [False, True])
def test_start_asks_when_the_disk_is_nearly_full(recording_tab, qtbot, monkeypatch, answer_yes):
    from PySide6.QtWidgets import QMessageBox
    asked = []

    def question(parent, title, text, *args, **kwargs):
        asked.append(text)
        return QMessageBox.StandardButton.Yes if answer_yes else QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, 'question', question)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args, **kwargs: None)
    _disk_with(monkeypatch, free_gb=3)

    _start_with_one_topic(recording_tab)

    assert len(asked) == 1
    assert recording_tab._recorder.start_calls == (1 if answer_yes else 0)


def test_start_is_refused_when_the_output_path_cannot_be_created(recording_tab, qtbot, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: shown.append(args[2]))
    blocker = tmp_path / "a_file"
    blocker.write_text("")
    recording_tab.settings_panel._settings_manager.update(output_path=str(blocker / "recordings"))

    _start_with_one_topic(recording_tab)

    assert len(shown) == 1
    assert recording_tab._recorder.start_calls == 0


def test_recording_is_stopped_once_when_the_disk_runs_full(recording_tab, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: shown.append(args[2]))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args, **kwargs: shown.append(args[2]))
    _start_with_one_topic(recording_tab)
    recording_tab.status_panel.set_state(RecordingState.RECORDING)
    recording_tab.status_panel._timer.stop()
    _disk_with(monkeypatch, free_gb=0.5)

    for _ in range(5):  # five one-second ticks with the disk nearly full
        recording_tab.status_panel._on_timer_tick()
    QApplication.processEvents()

    assert recording_tab._recorder.stop_calls == 1
    assert recording_tab._recorder.stop_reason
    assert len(shown) == 1
    assert recording_tab.start_btn.isEnabled()


def test_a_later_recording_is_stopped_automatically_too(recording_tab, qtbot, monkeypatch):
    """The disk can stay below the warning level between two recordings."""
    from PySide6.QtWidgets import QMessageBox
    for dialog in ('critical', 'warning'):
        monkeypatch.setattr(QMessageBox, dialog, lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    for recording_number in (1, 2):
        _disk_with(monkeypatch, free_gb=3)
        _start_with_one_topic(recording_tab)
        assert recording_tab._recorder.is_recording
        _disk_with(monkeypatch, free_gb=0.5)
        recording_tab.status_panel._on_timer_tick()
        QApplication.processEvents()

        assert recording_tab._recorder.stop_calls == recording_number


def test_recording_is_stopped_while_the_low_space_warning_is_still_open(recording_tab, qtbot, monkeypatch):
    """Driven by the panel's real timer: an open dialog must not hold it back."""
    from PySide6.QtWidgets import QMessageBox
    recorder = recording_tab._recorder
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    stopped_while_open = []

    def warning_left_open(*args, **kwargs):
        # The operator does not dismiss it; meanwhile the disk runs full.
        _disk_with(monkeypatch, free_gb=0.5)
        qtbot.waitUntil(lambda: recorder.stop_calls == 1, timeout=5000)
        stopped_while_open.append(True)

    monkeypatch.setattr(QMessageBox, 'warning', warning_left_open)
    _disk_with(monkeypatch, free_gb=3)
    recording_tab.topic_list.list_btn.setChecked(True)
    recording_tab.topic_list.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    recording_tab._on_start_clicked()
    recording_tab.status_panel._timer.setInterval(20)

    qtbot.waitUntil(lambda: stopped_while_open == [True], timeout=10000)

    assert recorder.stop_calls == 1


def test_elapsed_time_starts_at_zero_for_each_recording(recording_tab, qtbot):
    panel = recording_tab.status_panel
    panel.set_state(RecordingState.RECORDING)
    panel._timer.stop()
    panel._on_timer_tick()
    panel._on_timer_tick()
    panel.set_state(RecordingState.STOPPED)

    panel.set_state(RecordingState.RECORDING)
    panel._timer.stop()

    assert panel.elapsed_label.text() == "00:00:00"


def test_disk_critical_is_reported_once_not_every_second(recording_tab, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args, **kwargs: shown.append(args[2]))
    _start_with_one_topic(recording_tab)
    _disk_with(monkeypatch, free_gb=3)

    for _ in range(5):
        recording_tab.status_panel._on_timer_tick()
    QApplication.processEvents()

    assert len(shown) == 1
    assert recording_tab._recorder.stop_calls == 0

    _disk_with(monkeypatch, free_gb=50)
    recording_tab.status_panel._on_timer_tick()
    _disk_with(monkeypatch, free_gb=3)
    recording_tab.status_panel._on_timer_tick()
    QApplication.processEvents()

    assert len(shown) == 2  # a new fall below the limit is a new warning


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
