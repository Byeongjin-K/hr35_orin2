from enum import Enum
from typing import Any
import numpy as np


class ArrayFormat(Enum):
    EXPAND = "expand"
    JSON = "json"
    COMMA = "comma"


def flatten_message(
    msg: Any,
    prefix: str,
    array_format: ArrayFormat = ArrayFormat.EXPAND
) -> dict[str, Any]:
    result = {}
    _flatten_recursive(msg, prefix, result, array_format)
    return result


def _flatten_recursive(
    obj: Any,
    prefix: str,
    result: dict[str, Any],
    array_format: ArrayFormat
) -> None:
    if obj is None:
        result[prefix] = None
        return
    
    if isinstance(obj, (int, float, bool, str)):
        result[prefix] = obj
        return
    
    if isinstance(obj, np.ndarray):
        _handle_numpy_array(obj, prefix, result, array_format)
        return
    
    if isinstance(obj, (list, tuple)):
        _handle_array(obj, prefix, result, array_format)
        return
    
    if isinstance(obj, bytes):
        return
    
    fields = _get_fields(obj)
    for field_name in fields:
        try:
            value = getattr(obj, field_name)
            field_prefix = f"{prefix}.{field_name}"
            _flatten_recursive(value, field_prefix, result, array_format)
        except AttributeError:
            continue


def _handle_numpy_array(
    arr: np.ndarray,
    prefix: str,
    result: dict[str, Any],
    array_format: ArrayFormat
) -> None:
    flat = arr.flatten().tolist()
    
    if array_format == ArrayFormat.EXPAND:
        for i, val in enumerate(flat):
            result[f"{prefix}_{i}"] = val
    elif array_format == ArrayFormat.JSON:
        result[prefix] = "[" + ", ".join(str(x) for x in flat) + "]"
    elif array_format == ArrayFormat.COMMA:
        result[prefix] = ";".join(str(x) for x in flat)


def _handle_array(
    arr: list | tuple,
    prefix: str,
    result: dict[str, Any],
    array_format: ArrayFormat
) -> None:
    if len(arr) == 0:
        return
    
    if array_format == ArrayFormat.EXPAND:
        for i, item in enumerate(arr):
            if isinstance(item, (int, float, bool, str, type(None))):
                result[f"{prefix}_{i}"] = item
            else:
                _flatten_recursive(item, f"{prefix}_{i}", result, array_format)
    
    elif array_format == ArrayFormat.JSON:
        if all(isinstance(x, (int, float, bool, str, type(None))) for x in arr):
            result[prefix] = "[" + ", ".join(str(x) for x in arr) + "]"
        else:
            result[prefix] = str(arr)
    
    elif array_format == ArrayFormat.COMMA:
        if all(isinstance(x, (int, float, bool, str, type(None))) for x in arr):
            result[prefix] = ";".join(str(x) for x in arr)
        else:
            result[prefix] = str(arr)


# ROS2 internal fields to exclude from output
_EXCLUDED_FIELDS = frozenset({
    '_check_fields',
    '_full_text',
    '_type_support',
    'SLOT_TYPES',
})


def _get_fields(obj: Any) -> list[str]:
    if hasattr(obj, '__slots__'):
        # Filter out ROS2 internal fields from __slots__
        return [f for f in obj.__slots__ if f not in _EXCLUDED_FIELDS]
    
    fields = []
    for name in dir(obj):
        if name.startswith('_'):
            continue
        try:
            val = getattr(obj, name)
            if not callable(val):
                fields.append(name)
        except AttributeError:
            continue
    return fields
