"""Centralized ZED SDK availability detection.

Caches the import check result so it's only performed once.
"""
from typing import Optional

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
