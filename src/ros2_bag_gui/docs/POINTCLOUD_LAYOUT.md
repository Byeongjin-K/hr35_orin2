# PointCloud2 Field Layout

## Topic: `/lidar_boom/points`

**Message Type:** `sensor_msgs/msg/PointCloud2`

**Source:** Ouster OS1-128 LiDAR (excavator boom-mounted)

## Message Structure

| Property | Value |
|----------|-------|
| Frame ID | `lidar_boom/os_lidar` |
| Height | 128 (number of laser channels) |
| Width | 512 (points per rotation) |
| Point Step | 48 bytes |
| Row Step | 24,576 bytes (512 × 48) |
| Is Bigendian | False |
| Is Dense | False |
| Data Size | ~3.1 MB per message |
| Frequency | 7.70 Hz |

## Field Layout (48 bytes per point)

| Field | Offset | Type | Size | Description |
|-------|--------|------|------|-------------|
| `x` | 0 | FLOAT32 | 4 bytes | X coordinate (meters) |
| `y` | 4 | FLOAT32 | 4 bytes | Y coordinate (meters) |
| `z` | 8 | FLOAT32 | 4 bytes | Z coordinate (meters) |
| *(padding)* | 12 | - | 4 bytes | Alignment padding |
| `intensity` | 16 | FLOAT32 | 4 bytes | Signal intensity |
| `t` | 20 | UINT32 | 4 bytes | Timestamp offset (nanoseconds) |
| `reflectivity` | 24 | UINT16 | 2 bytes | Surface reflectivity |
| `ring` | 26 | UINT16 | 2 bytes | Laser ring ID (0-127) |
| `ambient` | 28 | UINT16 | 2 bytes | Ambient light level |
| *(padding)* | 30 | - | 2 bytes | Alignment padding |
| `range` | 32 | UINT32 | 4 bytes | Range measurement (mm) |
| *(unused)* | 36 | - | 12 bytes | Reserved/padding |

## Data Characteristics

### Point Count per Message
- **Total points:** 128 × 512 = 65,536 points
- **Valid points:** Variable (is_dense = False means NaN/Inf may exist)

### Coordinate System
- **Frame:** `lidar_boom/os_lidar` (sensor frame)
- **Units:** Meters for x/y/z, millimeters for range
- **Orientation:** Follows ROS REP-103 (right-handed, Z-up)

### Field Semantics

#### Spatial Fields (x, y, z)
- Cartesian coordinates in sensor frame
- FLOAT32 allows ~7 decimal digits precision
- May contain NaN for invalid returns

#### Intensity
- Normalized signal strength (0.0 - 1.0 typical range)
- Higher values = stronger return signal
- Useful for material classification

#### Timestamp (t)
- Nanosecond offset from message header timestamp
- Allows per-point timing within scan
- Critical for motion compensation

#### Reflectivity
- Raw reflectivity value from sensor
- UINT16 range: 0-65535
- Material-dependent property

#### Ring
- Laser channel ID (0-127 for OS1-128)
- Identifies which vertical laser emitted the point
- Used for ring-based filtering

#### Ambient
- Ambient light measurement at point
- Useful for outdoor/indoor detection
- May affect intensity interpretation

#### Range
- Direct range measurement in millimeters
- UINT32 allows up to ~4.2 million mm (4.2 km)
- More precise than computing from x/y/z

## Memory Layout Notes

### Alignment
- Point step is 48 bytes (aligned to 16-byte boundary)
- Padding exists at offsets 12-15 and 30-31
- Unused space at offsets 36-47

### Performance Implications
- Large message size (~3.1 MB) requires efficient serialization
- 7.70 Hz × 3.1 MB = ~24 MB/s bandwidth for this topic alone
- Consider downsampling for real-time visualization

## Usage Examples

### Accessing Fields in Python
```python
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2

# Iterate over points
for point in point_cloud2.read_points(msg, field_names=("x", "y", "z", "intensity")):
    x, y, z, intensity = point
    # Process point...

# Access specific ring
ring_points = point_cloud2.read_points(msg, field_names=("x", "y", "z", "ring"), skip_nans=True)
ring_64_points = [p for p in ring_points if p[3] == 64]
```

### Filtering by Range
```python
# Get points within 10m
close_points = []
for point in point_cloud2.read_points(msg, field_names=("x", "y", "z", "range")):
    if point[3] < 10000:  # range in mm
        close_points.append(point[:3])
```

## Related Topics

- `/lidar_boom/lidar_packets` (310.77 Hz) - Raw Ouster packets
- `/lidar_boom/imu` (97.30 Hz) - IMU data from LiDAR unit
- `/tf` (273.64 Hz) - Transform tree including lidar_boom frame

## References

- [ROS sensor_msgs/PointCloud2](http://docs.ros.org/en/api/sensor_msgs/html/msg/PointCloud2.html)
- [Ouster OS1 Datasheet](https://ouster.com/products/scanning-lidar/os1-sensor/)
- [ROS REP-103: Standard Units of Measure](https://www.ros.org/reps/rep-0103.html)
