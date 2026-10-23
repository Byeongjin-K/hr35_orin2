"""Which camera a serial number is, from the bringup parameters that pin the hardware."""
import glob
import os
from typing import Dict

import yaml

from ros2_bag_gui.logging_config import get_logger

logger = get_logger(__name__)

# The bringup package names each camera by where it is mounted
BRINGUP_PACKAGE = 'hr35_bringup'
CAMERA_PARAM_GLOB = 'config/zedx_*_params.yaml'
POSITION_LABELS = {'boom': '붐', 'cabin': '캐빈'}


def camera_names_by_serial() -> Dict[str, str]:
    """Serial number -> camera name (e.g. "45233238" -> "zedx_boom"); {} if unknown here."""
    try:
        from ament_index_python.packages import get_package_share_directory
        share = get_package_share_directory(BRINGUP_PACKAGE)
    except Exception as e:
        logger.info("No %s to read camera names from: %s", BRINGUP_PACKAGE, e)
        return {}
    names = {}
    for path in sorted(glob.glob(os.path.join(share, CAMERA_PARAM_GLOB))):
        try:
            # The files hold Korean comments, and once the ZED SDK has opened a camera
            # the process locale is C: the default encoding would then be ASCII.
            with open(path, encoding='utf-8') as f:
                params = yaml.safe_load(f)
            general = params['/**']['ros__parameters']['general']
            names[str(general['serial_number'])] = str(general['camera_name'])
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as e:
            logger.warning("Cannot read the camera name in %s: %s", path, e)
    return names


def camera_position(name: str) -> str | None:
    """Where a camera is mounted ('boom', 'cabin'), from its name; None if the name does not say."""
    return next((token for token in POSITION_LABELS if token in name.lower()), None)


def camera_label(serial: str, name: str = "") -> str:
    """How to call a camera on screen: its position, its name and its serial number."""
    name = name or camera_names_by_serial().get(serial, "")
    position = camera_position(name)
    if position:
        return f"{POSITION_LABELS[position]} 카메라 ({name}, {serial})"
    return f"{name} ({serial})" if name else serial
