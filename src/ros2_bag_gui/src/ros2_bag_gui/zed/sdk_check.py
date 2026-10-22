"""Centralized ZED SDK availability detection.

Caches the import check result so it's only performed once.
"""
from typing import List, Optional, Tuple

_zed_available: Optional[bool] = None


def is_zed_sdk_available() -> bool:
    """Check if ZED SDK (pyzed) is importable.

    Returns:
        True if pyzed.sl can be imported, False otherwise.
    """
    global _zed_available
    if _zed_available is None:
        try:
            import pyzed.sl  # noqa: F401
            _zed_available = True
        except ImportError:
            _zed_available = False
    return _zed_available


def get_sl_module():
    """Get pyzed.sl module if available.

    Returns:
        pyzed.sl module or None if ZED SDK is not installed.
    """
    if is_zed_sdk_available():
        import pyzed.sl as sl
        return sl
    return None


def list_zed_cameras() -> List[Tuple[str, str, bool]]:
    """(serial, model, available) of each connected ZED camera; [] without the SDK.

    A camera something else holds open (e.g. the ZED ROS wrapper) is not
    available: SVO2 recording cannot open it.
    """
    sl = get_sl_module()
    if sl is None:
        return []
    return [
        (str(d.serial_number), str(d.camera_model), d.camera_state == sl.CAMERA_STATE.AVAILABLE)
        for d in sl.Camera.get_device_list()
    ]
