# ROS2 Humble Compatibility Guide

## Overview

This project is developed on **ROS2 Kilted** (Ubuntu 24.04, Python 3.12) but deployed on **ROS2 Humble** (Ubuntu 22.04, Python 3.10). This document tracks compatibility requirements and strategies.

## Environment Differences

| Aspect | Kilted (Development) | Humble (Deployment) |
|--------|---------------------|---------------------|
| Ubuntu | 24.04 | 22.04 |
| Python | 3.12 | 3.10 |
| ROS2 | Kilted | Humble |
| rosbag2_py | Latest | Humble version |

## Known API Differences

### rosbag2_py.TopicMetadata

**Kilted Signature:**
```python
TopicMetadata(
    id: int,
    name: str,
    type: str,
    serialization_format: str,
    offered_qos_profiles: list,
    type_description_hash: str
)
```

**Humble Signature (Expected):**
```python
TopicMetadata(
    name: str,
    type: str,
    serialization_format: str,
    offered_qos_profiles: list
)
```

**Key Differences:**
- `id` parameter: Required in Kilted, may not exist in Humble
- `type_description_hash` parameter: Present in Kilted, may not exist in Humble

**Solution:**
Use `compat.create_topic_metadata()` wrapper that tries Kilted signature first, falls back to Humble signature.

### rosbag2_py.SequentialWriter

**Potential Differences:**
- Method availability (e.g., `close()` method)
- Constructor parameters

**Verification Needed:**
Run `scripts/check_humble_compat.py` on Humble to confirm.

### rosbag2_py.SequentialReader

**Potential Differences:**
- Iterator protocol support
- Method availability (e.g., `has_next()`)

**Verification Needed:**
Run `scripts/check_humble_compat.py` on Humble to confirm.

## Python 3.10 Compatibility

### ✅ Safe Features (Available in Python 3.10)

- `match/case` statements (3.10+)
- `list[str]` type hints (3.9+)
- `dict | None` union syntax (3.10+)
- `TypeAlias` (3.10+)
- Structural pattern matching (3.10+)

### ❌ Unsafe Features (NOT Available in Python 3.10)

| Feature | Minimum Version | Alternative |
|---------|----------------|-------------|
| `tomllib` | 3.11 | Use `pyyaml` or `toml` package |
| `StrEnum` | 3.11 | Use `str, Enum` inheritance |
| `Self` type hint | 3.11 | Use `TypeVar` |
| `ExceptionGroup` | 3.11 | Use traditional exception handling |
| `TaskGroup` | 3.11 | Use `asyncio.gather()` |

### Code Examples

**❌ Don't Use (Python 3.11+):**
```python
import tomllib
from enum import StrEnum
from typing import Self

class Status(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"

class Node:
    def clone(self) -> Self:
        return Node()
```

**✅ Use Instead (Python 3.10 compatible):**
```python
import yaml  # or: import toml
from enum import Enum
from typing import TypeVar

T = TypeVar('T', bound='Node')

class Status(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"

class Node:
    def clone(self: T) -> T:
        return Node()
```

## Compatibility Layer Usage

### Import Pattern

```python
from ros2_bag_gui.compat import (
    create_topic_metadata,
    get_ros_distro,
    is_kilted,
    is_humble
)

topic_meta = create_topic_metadata(
    topic_id=1,
    name='/camera/image',
    type_='sensor_msgs/msg/Image'
)

if is_humble():
    print("Running on deployment environment")
```

### Version Detection

```python
from ros2_bag_gui.compat import get_ros_distro, get_python_version

print(f"ROS: {get_ros_distro()}")
print(f"Python: {'.'.join(map(str, get_python_version()))}")
```

## Verification Checklist

### Development (Kilted)

- [x] Compatibility layer created (`compat.py`)
- [x] API signature checker created (`check_humble_compat.py`)
- [ ] Tests pass on Kilted
- [ ] No Python 3.11+ features used
- [ ] Type hints compatible with Python 3.10

### Deployment (Humble)

- [ ] Run `check_humble_compat.py` on Humble environment
- [ ] Compare API signatures with Kilted
- [ ] Update `compat.py` if differences found
- [ ] Run full test suite on Humble
- [ ] Verify rosbag recording works
- [ ] Verify rosbag export works

## Testing Strategy

### On Kilted (Current)

```bash
source /opt/ros/kilted/setup.bash
cd /home/kbj/ros2_ws/src/ros2_bag_gui
python3 -m pytest tests/test_compat.py -v
```

### On Humble (Deployment)

```bash
source /opt/ros/humble/setup.bash
cd /path/to/ros2_bag_gui
python3 scripts/check_humble_compat.py > humble_api.json
python3 -m pytest tests/ -v
```

### Compare Results

```bash
diff kilted_api.json humble_api.json
```

## Known Issues

### Issue 1: TopicMetadata ID Parameter

**Status:** Mitigated with compatibility layer

**Description:** Kilted requires `id` parameter, Humble may not.

**Solution:** `compat.create_topic_metadata()` tries both signatures.

### Issue 2: Python Version Differences

**Status:** Monitored

**Description:** Python 3.12 vs 3.10 may have subtle behavior differences.

**Solution:** Avoid 3.11+ features, test on both versions.

## Future Considerations

### When Humble Support Ends

Once deployment moves to a newer ROS2 distribution:
1. Remove compatibility layer if no longer needed
2. Update to use native APIs directly
3. Remove Python 3.10 constraints

### When Adding New Features

Before adding new rosbag2_py API usage:
1. Check if API exists in Humble
2. Add compatibility wrapper if needed
3. Update this document
4. Add tests for both environments

## References

- [ROS2 Humble Documentation](https://docs.ros.org/en/humble/)
- [ROS2 Kilted Documentation](https://docs.ros.org/en/kilted/)
- [Python 3.10 Release Notes](https://docs.python.org/3/whatsnew/3.10.html)
- [rosbag2 API Documentation](https://github.com/ros2/rosbag2)

## Verification Status

| Component | Kilted | Humble |
|-----------|--------|--------|
| compat.py | ✅ Created | ⏳ Pending |
| check_humble_compat.py | ✅ Created | ⏳ Pending |
| test_compat.py | ⏳ Pending | ⏳ Pending |
| API signature check | ⏳ Pending | ⏳ Pending |
| Full test suite | ⏳ Pending | ⏳ Pending |

**Last Updated:** 2026-01-22 (Kilted environment)
