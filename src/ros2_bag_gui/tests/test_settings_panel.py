"""Tests for the settings panel: what it shows is what recording uses."""
import pytest
from ros2_bag_gui.config.settings import SettingsManager
from ros2_bag_gui.widgets.settings_panel import SettingsPanel


@pytest.fixture
def no_zed_sdk(monkeypatch):
    monkeypatch.setattr(
        'ros2_bag_gui.widgets.settings_panel.is_zed_sdk_available', lambda: False
    )


@pytest.mark.parametrize("stored_mode", ["svo2", "both"])
def test_stored_svo2_mode_without_sdk_is_not_used_behind_the_screen(qtbot, no_zed_sdk, stored_mode):
    SettingsManager().update(camera_mode=stored_mode)

    panel = SettingsPanel()
    qtbot.addWidget(panel)

    assert panel.camera_mode_combo.currentIndex() == 0
    assert panel.get_settings().camera_mode == "bag"
    assert SettingsManager().settings.camera_mode == "bag"


def test_set_camera_mode_without_sdk_falls_back_to_bag(qtbot, no_zed_sdk):
    panel = SettingsPanel()
    qtbot.addWidget(panel)

    assert panel.set_camera_mode("svo2") is False

    assert panel.camera_mode_combo.currentIndex() == 0
    assert panel.get_settings().camera_mode == "bag"


def test_set_camera_mode_with_sdk_selects_it(qtbot, monkeypatch):
    monkeypatch.setattr(
        'ros2_bag_gui.widgets.settings_panel.is_zed_sdk_available', lambda: True
    )
    panel = SettingsPanel()
    qtbot.addWidget(panel)

    assert panel.set_camera_mode("svo2") is True

    assert panel.get_settings().camera_mode == "svo2"


def _with_cameras(monkeypatch, cameras, names=None):
    monkeypatch.setattr('ros2_bag_gui.widgets.settings_panel.is_zed_sdk_available', lambda: True)
    monkeypatch.setattr('ros2_bag_gui.widgets.settings_panel.list_zed_cameras', lambda: cameras)
    monkeypatch.setattr(
        'ros2_bag_gui.widgets.settings_panel.camera_names_by_serial', lambda: names or {})


def test_svo2_camera_is_chosen_by_serial_and_kept(qtbot, monkeypatch):
    _with_cameras(monkeypatch, [('49749405', 'ZED X', False), ('45233238', 'ZED X', True)])
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    assert panel.svo2_camera_combo.currentData() == ""  # the first camera that opens

    panel.svo2_camera_combo.setCurrentIndex(panel.svo2_camera_combo.findData('45233238'))

    assert panel.get_settings().svo2_camera_serial == '45233238'
    assert SettingsManager().settings.svo2_camera_serial == '45233238'


def test_chosen_svo2_camera_that_is_not_connected_stays_chosen(qtbot, monkeypatch):
    _with_cameras(monkeypatch, [])
    SettingsManager().update(svo2_camera_serial='45233238')

    panel = SettingsPanel()
    qtbot.addWidget(panel)

    assert panel.svo2_camera_combo.currentData() == '45233238'
    assert panel.get_settings().svo2_camera_serial == '45233238'


def test_svo2_cameras_are_listed_by_where_they_are_mounted(qtbot, monkeypatch):
    _with_cameras(
        monkeypatch,
        [('49749405', 'ZED X', False), ('45233238', 'ZED X', True)],
        names={'49749405': 'zedx_cabin', '45233238': 'zedx_boom'},
    )
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    combo = panel.svo2_camera_combo

    cabin = combo.itemText(combo.findData('49749405'))
    boom = combo.itemText(combo.findData('45233238'))

    assert cabin.startswith('캐빈 카메라 (zedx_cabin, 49749405)') and '사용 불가' in cabin
    assert boom.startswith('붐 카메라 (zedx_boom, 45233238)') and '사용 가능' in boom
