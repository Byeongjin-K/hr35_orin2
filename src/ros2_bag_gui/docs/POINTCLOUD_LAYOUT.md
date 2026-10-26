# PointCloud2 Field Layout

**Last verified:** 2026-10-26 against the 2026-10-23 recordings and live bringup.

## Topic: `/lidar_boom/points`

**Message Type:** `sensor_msgs/msg/PointCloud2`

**Source:** Ouster OS-0-128 LiDAR, boom-mounted (S/N 122411000861, firmware 3.2.0, driver `ouster-ros` 0.15.1)

**Sensor configuration:** `512x10` (512 columns at 10 Hz), LiDAR profile `RNG19_RFL8_SIG16_NIR16`, `point_type=original`, organized and destaggered.

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
| Data Size | 3,145,728 bytes = 3.15 MB of point data per message |
| Frequency | 10 Hz (`512x10`; 9.97 Hz measured live, 9.995-10.001 Hz on `/lidar_boom/scan` across the ten 2026-10-23 sessions) |

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
- Raw SIGNAL amplitude from the sensor; it is **not** normalized to 0.0 - 1.0
- Higher values = stronger return signal
- Useful for material classification
- The LAZ writer rescales it per frame (`uint16(signal * 65535 / frame_max)`); that scaling belongs to LAZ, not to this topic

#### Timestamp (t)
- Nanoseconds relative to the sensor's scan start (its first column), not to the epoch and not to the header stamp
- Allows per-point timing within scan
- Critical for motion compensation

#### Reflectivity
- Reflectivity code from the sensor
- Carried in a UINT16, but the `RFL8` profile fills only the low 8 bits (0-255)
- Material-dependent property

#### Ring
- Laser channel ID (0-127 for OS-0-128)
- Identifies which vertical laser emitted the point
- Used for ring-based filtering

#### Ambient
- NEAR_IR measurement at the point (`NIR16` in the profile)
- Useful for outdoor/indoor detection
- May affect intensity interpretation

#### Range
- Direct range measurement in millimeters; 0 means an invalid or missing return
- Carried in a UINT32, but the `RNG19` profile encodes 19 bits (up to 524,287 mm)
- More precise than computing from x/y/z

## Memory Layout Notes

### Alignment
- Point step is 48 bytes (aligned to 16-byte boundary)
- Padding exists at offsets 12-15 and 30-31
- Unused space at offsets 36-47

### Performance Implications
- Large message size (3.15 MB) requires efficient serialization
- 10 Hz × 3.15 MB = ~31.5 MB/s bandwidth for this topic alone (31.62 MB/s measured)
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

Rates below are message count divided by bag duration over the ten 2026-10-23 sessions.

- `/lidar_boom/lidar_packets` (320.0 Hz) - Raw Ouster packets: 32 packets of 16 columns make one 128 x 512 scan, 24,832 bytes of payload each
- `/lidar_boom/imu_packets` (80.0 Hz) - Raw IMU packets; one packet holds several samples
- `/lidar_boom/imu` (637 Hz) - IMU messages the driver decodes from those packets
- `/lidar_boom/scan` (10.0 Hz) - One ring of the same scan; its header carries the frame time
- `/lidar_boom/metadata` (one latched message per session) - Sensor metadata JSON, required to decode packets
- `/tf` (6.4-10.0 Hz) - Transform tree; published by the mapping stack, not by the sensor

## References

- [ROS sensor_msgs/PointCloud2](http://docs.ros.org/en/api/sensor_msgs/html/msg/PointCloud2.html)
- Factory metadata of this sensor: `192.168.0-metadata.json` in the workspace root, also published on `/lidar_boom/metadata`
- [ROS REP-103: Standard Units of Measure](https://www.ros.org/reps/rep-0103.html)
