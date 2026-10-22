"""Tests for naming ZED cameras by where they are mounted, not by index."""
import pytest

from ros2_bag_gui.zed import camera_names
from ros2_bag_gui.zed.camera_names import camera_label, camera_names_by_serial

BOOM_PARAMS = """\
/**:
  ros__parameters:
    general:
      serial_number: 45233238
      camera_name: 'zedx_boom'
"""
CABIN_PARAMS = """\
/**:
  ros__parameters:
    general:
      serial_number: 49749405
      camera_name: 'zedx_cabin'
"""


@pytest.fixture
def bringup_config(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "zedx_boom_params.yaml").write_text(BOOM_PARAMS)
    (config / "zedx_cabin_params.yaml").write_text(CABIN_PARAMS)
    monkeypatch.setattr(
        "ament_index_python.packages.get_package_share_directory", lambda _pkg: str(tmp_path)
    )
    return config


def test_camera_names_come_from_the_bringup_parameters(bringup_config):
    assert camera_names_by_serial() == {'45233238': 'zedx_boom', '49749405': 'zedx_cabin'}


def test_a_broken_parameter_file_does_not_hide_the_others(bringup_config):
    (bringup_config / "zedx_boom_params.yaml").write_text("not: what we expect\n")

    assert camera_names_by_serial() == {'49749405': 'zedx_cabin'}


def test_no_bringup_package_leaves_the_names_unknown(monkeypatch):
    monkeypatch.setattr(
        "ament_index_python.packages.get_package_share_directory",
        lambda _pkg: (_ for _ in ()).throw(RuntimeError("not found")),
    )

    assert camera_names_by_serial() == {}


@pytest.mark.parametrize("serial, name, expected", [
    ('45233238', 'zedx_boom', '붐 카메라 (zedx_boom, 45233238)'),
    ('49749405', 'zedx_cabin', '캐빈 카메라 (zedx_cabin, 49749405)'),
    ('123', 'zedx_spare', 'zedx_spare (123)'),  # a camera mounted nowhere we know
    ('123', '', '123'),
])
def test_a_camera_is_named_by_where_it_is_mounted(serial, name, expected):
    assert camera_label(serial, name) == expected


def test_the_label_looks_the_name_up_when_it_is_not_given(bringup_config):
    assert camera_label('49749405') == '캐빈 카메라 (zedx_cabin, 49749405)'


def test_the_positions_are_the_ones_the_robot_has():
    assert set(camera_names.POSITION_LABELS) == {'boom', 'cabin'}
