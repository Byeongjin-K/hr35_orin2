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
