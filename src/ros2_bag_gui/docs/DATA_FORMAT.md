# 2026-10-23 Excavator Dataset: Data Guide

Version 1.1.0 (2026-10-26). Describes the sessions ros2_bag_gui records. The reference dataset is the 2026-10-23 share package (recorded with commit cbd1702, `sync_info.json` format 1.0.0); its README.md and versions.md travel with the data. The tools named below are in this package's `scripts/` folder (`tools/` in a share package).

## 1. What this data is

- Data recorded on 2026-10-23 during autonomous digging tests with KIMM's HR35 excavator.
- Sensors: a boom Ouster OS-0-128 LiDAR (10 Hz), ZED X cameras on the boom and cabin (15 fps), excavator sensors, and GNSS.
- There are 3 short test sessions (exp0) and 8 experiments (exp1~exp8), 2.8 hours in total.
- The 4 Ouster image topics and the Ontario Tech terrain mapping outputs were excluded. All image values remain in the LiDAR packets, and the mapping outputs aren't needed for this research.

## 2. Session folders and files

Each session folder (e.g. `exp1/`) holds the 4 files below. `exp0_1026_test2` has only the cabin SVO2.

| File | Contents | How to open |
|---|---|---|
| `20261023_<session>_rosbag.tar.zst` | Light ROS 2 bag (`rosbag_light/`) and `sync_info.json` | Extract with `tar -I zstd -xf`, then read with ROS 2 or Python `rosbags` |
| `20261023_<session>_pointcloud.tar` | One LAZ file per LiDAR frame (`pointcloud/<timestamp>.laz`) | Extract with `tar -xf`, then read with laspy and lazrs |
| `20261023_<session>_zedx_boom.svo2` | Boom camera video | `tools/extract_svo2.py` or the ZED SDK |
| `20261023_<session>_zedx_cabin.svo2` | Cabin camera video | Same as above |

The bags use SQLite storage (ROS 2 Humble). They don't contain message definitions, so use the definitions in `interfaces/` with them. Bags are split into 3 GiB chunks, so open the `rosbag_light/` folder, not a single file. Every archive uses the same internal names, so extract each session into its own folder.

First check that the files you received are intact.

```bash
sha256sum -c MANIFEST.sha256        # macOS: shasum -a 256 -c MANIFEST.sha256
```

On Windows, open `.tar.zst` with 7-Zip ZS or a recent Windows 11 File Explorer.

## 3. Time reference

All timestamps are UTC epoch nanoseconds (ns counted from 1970-01-01). The values are large, so converting them to floating point corrupts the last digits. Subtract them as integers, then convert the difference to seconds.

A bag carries two kinds of timestamp.

- Receive time: when the recording PC received the message. It includes transport and queueing delay.
- Header time: the time the sender stamped inside the message (`header.stamp`).

Use header time to align sensors. Use receive time only for topics without a header, and keep in mind that it includes delay.

A LAZ file name is the header time of that point cloud, not the file modification time. SVO2 frame times are the image times stamped by the ZED.

Here's how to align LiDAR, camera and vehicle data. For LiDAR frame times, use the LAZ file name or the `/lidar_boom/scan` header time. Packet receive times can be off by up to 23.6 ms. For cameras, use the frame time CSV. Find the nearest pair between the two time series, record the difference, and discard pairs beyond your tolerance. Don't compute times from the nominal period or match by frame index, because some intervals have dropped frames. Hardware synchronization between devices isn't guaranteed.

## 4. Key topics

Rates are the minimum and maximum of the per-session average (message count / session length). All 90 topics are listed in Appendix A. Angles are in degrees unless noted otherwise.

| Topic | Contents | Rate (Hz) | Notes |
|---|---|---:|---|
| `/lidar_boom/lidar_packets` | Raw LiDAR packets | 319.6-320.0 | Build point clouds with the tool in Section 5 |
| `/lidar_boom/imu_packets` | Raw LiDAR IMU packets | 79.9-80.0 | Several samples per packet |
| `/lidar_boom/metadata` | LiDAR configuration JSON | 1 per session | Required to decode packets |
| `/lidar_boom/imu` | LiDAR IMU (m/s², rad/s) | 632.6-637.0 | |
| `/lidar_boom/scan` | 2D single-line range (m) | 10.0 | Reference for LiDAR frame times |
| `/tf` | Transforms between frames | 6.4-10.0 | Includes the boom LiDAR mounting pose |
| `/tf_static` | Static transforms | A few at start | |
| `/excavator/state/complete_status` | Bundled excavator state | 19.7-20.0 | Some values are fixed defaults |
| `/excavator/sensors/joint_boom` (`joint_arm`, `joint_bucket`) | Boom, arm and bucket joint angles | 59.8-60.0 | `data=[angle]` |
| `/excavator/sensors/pressure_data` | 6 cylinder pressures | 19.7-20.0 | Raw CAN values, physical unit unconfirmed |
| `/excavator/sensors/swing_angle` | Swing angle | 19.7-20.0 | |
| `/excavator/remote_controller/feedback` | Remote controller input (normalized) | 19.6-20.0 | Actual values received over CAN |
| `/excavator/work_anchor/status` | Work anchor status: mode, anchor heading (deg), anchor time, undercarriage drift (deg) | 19.7-20.0 | |
| `/upper_controller/stuck_status` | Stuck detection status | 5.0 | |
| `/excavator/sensors/gnss_position` | GNSS latitude, longitude, altitude | 9.9-10.0 | |
| `/excavator/sensors/gps_attitude` | GNSS roll, pitch, heading | 9.9-10.0 | `/gps_att` has the same content |
| `/gps_msg` | GNSS position and status | 9.9-10.0 | `speed` is in knots |
| `/kine_data` | Joint and GNSS bundle | 9.9-10.0 | Some position fields are 0 |
| `/height_array` | Terrain height grid used by the AI model | 6.4-10.0 | Height 67 x width 34 = 2,278 values |
| `/zedx_cabin/zedx_cabin_node/imu/data` | Cabin camera IMU | 10.0 | |
| `/zedx_cabin/zedx_cabin_node/status/health` | Cabin camera status | 10.1-15.0 | |

For `/height_array`, the value order, axes and origin are unconfirmed. Don't derive positions from indices alone.

## 5. Building LiDAR point clouds

The bags contain no point clouds, only raw LiDAR packets. The LAZ files are point clouds, but reduced ones: coordinates are rounded to 1 mm, empty points are dropped, and some fields are missing. If you need all attributes, rebuild the point clouds from the packets.

```bash
pip install ouster-sdk==0.16.2 numpy
python3 tools/decode_ouster_packets.py rosbag_light --npz frames/ --start 60 --end 70      # one .npz per frame, no ROS needed
python3 tools/decode_ouster_packets.py rosbag_light --bag points_bag --merge                # ROS 2 bag containing /lidar_boom/points
```

`--bag` requires ROS 2 Humble. `--merge` also copies the other topics but leaves out the 2 raw packet topics. `--start` and `--end` are seconds counted from the first packet. On Jetson (aarch64, Python 3.10) you may need `pip install --no-deps ouster-sdk==0.16.2` and `pip install rosbags "numpy<2"`.

The result is a 128 x 512 array, and each point has the 9 fields below.

| Field | Type | Meaning |
|---|---|---|
| x, y, z | float32 | Position in the LiDAR frame (m) |
| intensity | float32 | Received signal strength (raw SIGNAL) |
| t | uint32 | ns since scan start. Not an epoch time |
| reflectivity | uint16 | Reflectivity code |
| ring | uint16 | Laser ring number 0-127 |
| ambient | uint16 | Ambient light (NEAR_IR) |
| range | uint32 | Range (mm), 0 means no return |

Points with no return have NaN x, y, z. The frame is `lidar_boom/os_lidar`. The header time is restored from `/lidar_boom/scan`, so it matches the LAZ file name. If `stamp_source` in the npz is `estimated`, no time was found and it was estimated. Point cloud bags are large: about 3.1 MB per frame, or 31 MB per second of recording.

## 6. Extracting camera video

An SVO2 file contains H.265 video. Each frame is 3840x1200 with the left and right images side by side, and it isn't rectified. To extract without the ZED SDK, install lz4 and ffmpeg.

```bash
pip install lz4
python3 tools/extract_svo2.py exp1/20261023_exp1_zedx_boom.svo2 boom/ --images png --every 15 --split
```

The output is:

- `<name>.h265`: full video stream
- `<name>_frames.csv`: per-frame times (`frame_index,log_time_ns,publish_time_ns,bytes`)
- `<name>_images/left/`, `right/`: PNGs named by image time

`--start` and `--every` apply only to images; the stream and CSV are always complete. The PNGs are pixel-identical to the ZED SDK's unrectified images. Depth isn't computed.

With the ZED SDK you can open SVO2 directly. Depth needs an NVIDIA GPU. The SDK may rewrite the original when opening a file that wasn't closed properly, so open a copy. Factory calibration for rectification is in `calibration/SN45233238.conf` (boom) and `SN49749405.conf` (cabin).

## 7. Known issues

- exp1 lost LiDAR packets: 33 packets (0.03%) in 14 of 3,532 frames. Those frames have some NaN columns, flagged in the npz `missing_columns`. Other sessions were checked by message count only.
- The boom camera ran at 7.5 fps for the whole session in exp0_1015_test, exp3 and exp8. The cabin camera averaged 10.1 fps in exp2. The rest are 15 fps. Use the actual frame times.
- In exp0_1015_test, exp1 and exp7, the cabin ZED driver was terminated when recording stopped (`forced_stop` in `sync_info.json`). The exp7 cabin SVO2 is a version recovered by the ZED SDK, and all 31,449 frames are readable.
- `/excavator/safety/operator_alert` has no messages.
- The cabin LiDAR was off that day. Only boom LiDAR data exists.
- LAZ isn't the original data. Coordinates are in 1 mm steps, intensity is normalized per frame, and t, ring, reflectivity, ambient and range are missing.

## Appendix A. Full topic list

Topics with no messages show the rate as '-'. Types are shortened from `package/msg/Type` to `package/Type`.

| Topic | Type | Rate (Hz) |
|---|---|---:|
| `/ai_coordinate_diagnostics` | `std_msgs/String` | 1.971-2.000 |
| `/ai_status/action` | `excavator_msgs/AiActionStatus` | - |
| `/ai_status/episode_result` | `excavator_msgs/AiEpisodeResult` | - |
| `/ai_status/run_active` | `std_msgs/Bool` | 4.78e-4-0.014 |
| `/ai_status/run_config` | `std_msgs/String` | - |
| `/ai_status/stage_j_shadow` | `std_msgs/String` | - |
| `/diagnostics` | `diagnostic_msgs/DiagnosticArray` | 0.999-1.001 |
| `/excavator/kinematics/bucket_orientation` | `std_msgs/Float32` | 19.699-20.001 |
| `/excavator/kinematics/bucket_position` | `geometry_msgs/PointStamped` | 19.699-20.000 |
| `/excavator/kinematics/bucket_target_position` | `geometry_msgs/PointStamped` | 4.914-5.001 |
| `/excavator/remote_controller/feedback` | `excavator_msgs/RemoteControllerFeedback` | 19.642-20.001 |
| `/excavator/safety/operator_alert` | `std_msgs/String` | - |
| `/excavator/sensors/arm_inclino` | `std_msgs/Float32MultiArray` | 19.929-19.998 |
| `/excavator/sensors/boom_inclino` | `std_msgs/Float32MultiArray` | 19.943-19.998 |
| `/excavator/sensors/bucket_inclino` | `std_msgs/Float32MultiArray` | 19.932-19.999 |
| `/excavator/sensors/gnss_position` | `sensor_msgs/NavSatFix` | 9.856-10.000 |
| `/excavator/sensors/gnss_velocity` | `geometry_msgs/TwistWithCovariance` | 9.856-10.000 |
| `/excavator/sensors/gps_attitude` | `msg_gps_interface/GPSMsgAtt` | 9.856-10.000 |
| `/excavator/sensors/heading_track` | `std_msgs/Float32` | 19.727-20.005 |
| `/excavator/sensors/joint_arm` | `std_msgs/Float32MultiArray` | 59.837-60.019 |
| `/excavator/sensors/joint_boom` | `std_msgs/Float32MultiArray` | 59.829-60.021 |
| `/excavator/sensors/joint_bucket` | `std_msgs/Float32MultiArray` | 59.831-59.996 |
| `/excavator/sensors/pressure_data` | `excavator_msgs/PressureData` | 19.699-20.001 |
| `/excavator/sensors/status` | `excavator_msgs/SensorStatus` | 19.727-20.001 |
| `/excavator/sensors/swing_angle` | `std_msgs/Float32` | 19.713-20.001 |
| `/excavator/sensors/swing_encoder_output` | `std_msgs/Float32` | 19.727-20.001 |
| `/excavator/sensors/swing_encoder_raw` | `std_msgs/Float32` | 19.656-20.001 |
| `/excavator/state/complete_status` | `excavator_msgs/ExcavatorCompleteStatus` | 19.699-20.005 |
| `/excavator/work_anchor/status` | `excavator_msgs/WorkAnchorStatus` | 19.727-20.001 |
| `/gps_att` | `msg_gps_interface/GPSMsgAtt` | 9.870-10.000 |
| `/gps_msg` | `msg_gps_interface/GPSMsg` | 9.870-10.000 |
| `/height_array` | `std_msgs/Float32MultiArray` | 6.440-10.003 |
| `/hr35/bit_control_cmd` | `std_msgs/String` | - |
| `/hr35/emergency_stop` | `std_msgs/Bool` | - |
| `/hr35/start_button` | `std_msgs/Bool` | - |
| `/kine_data` | `msg_excavator_kine_interface/KineMsg` | 9.856-10.000 |
| `/lidar_boom/imu` | `sensor_msgs/Imu` | 632.576-636.982 |
| `/lidar_boom/imu_packets` | `ouster_sensor_msgs/PacketMsg` | 79.879-80.024 |
| `/lidar_boom/lidar_packets` | `ouster_sensor_msgs/PacketMsg` | 319.641-320.002 |
| `/lidar_boom/metadata` | `std_msgs/String` | 4.78e-4-0.014 |
| `/lidar_boom/os_driver/transition_event` | `lifecycle_msgs/TransitionEvent` | - |
| `/lidar_boom/rgb_image` | `sensor_msgs/Image` | - |
| `/lidar_boom/scan` | `sensor_msgs/LaserScan` | 9.995-10.001 |
| `/parameter_events` | `rcl_interfaces/ParameterEvent` | - |
| `/task_info` | `excavator_msgs/TaskInfo` | - |
| `/tf` | `tf2_msgs/TFMessage` | 6.422-10.003 |
| `/tf_static` | `tf2_msgs/TFMessage` | 0.001-0.042 |
| `/track_controller/align_heading` | `std_msgs/Float32` | - |
| `/track_controller/align_heading_status` | `std_msgs/Bool` | - |
| `/track_controller/control_cmd` | `excavator_msgs/TrackControlCmd` | - |
| `/track_controller/control_enable` | `std_msgs/Bool` | - |
| `/track_controller/goal` | `sensor_msgs/NavSatFix` | - |
| `/track_controller/goal_heading` | `std_msgs/Float32` | - |
| `/track_controller/goal_relative` | `geometry_msgs/PoseStamped` | - |
| `/track_controller/projection_position` | `geometry_msgs/Point` | - |
| `/track_controller/reverse_mode` | `std_msgs/Bool` | - |
| `/track_controller/status` | `std_msgs/Bool` | 9.870-10.000 |
| `/track_controller/traveled_heading` | `std_msgs/Float32` | - |
| `/track_controller/utm_position` | `geometry_msgs/Point` | 9.870-10.000 |
| `/track_controller/utm_target_goal_position` | `geometry_msgs/Point` | - |
| `/track_controller/utm_target_start_position` | `geometry_msgs/Point` | - |
| `/upper_controller/active_task` | `std_msgs/String` | 4.78e-4-0.014 |
| `/upper_controller/anti_windup_status` | `std_msgs/Float32MultiArray` | - |
| `/upper_controller/control_cmd` | `excavator_msgs/UpperControlCmd` | - |
| `/upper_controller/feedforward_diagnostics` | `std_msgs/Float32MultiArray` | - |
| `/upper_controller/joint_control_target` | `std_msgs/Float32MultiArray` | - |
| `/upper_controller/stuck_recovery_done` | `std_msgs/Bool` | 4.928-5.000 |
| `/upper_controller/stuck_status` | `excavator_msgs/StuckDetectionStatus` | 4.983-5.000 |
| `/upper_controller/swing_governor_event` | `excavator_msgs/SwingGovernorEvent` | - |
| `/zedx_cabin/robot_description` | `std_msgs/String` | 4.78e-4-0.014 |
| `/zedx_cabin/zedx_cabin_node/confidence/camera_info` | `sensor_msgs/CameraInfo` | - |
| `/zedx_cabin/zedx_cabin_node/imu/data` | `sensor_msgs/Imu` | 9.966-9.997 |
| `/zedx_cabin/zedx_cabin_node/imu/data_raw` | `sensor_msgs/Imu` | 9.967-9.997 |
| `/zedx_cabin/zedx_cabin_node/left/camera_info` | `sensor_msgs/CameraInfo` | 8.344-9.971 |
| `/zedx_cabin/zedx_cabin_node/left_cam_imu_transform` | `geometry_msgs/TransformStamped` | 9.967-10.011 |
| `/zedx_cabin/zedx_cabin_node/left_gray/camera_info` | `sensor_msgs/CameraInfo` | 8.09e-4-0.028 |
| `/zedx_cabin/zedx_cabin_node/left_raw/camera_info` | `sensor_msgs/CameraInfo` | 8.09e-4-0.028 |
| `/zedx_cabin/zedx_cabin_node/left_raw_gray/camera_info` | `sensor_msgs/CameraInfo` | 8.09e-4-0.028 |
| `/zedx_cabin/zedx_cabin_node/rgb/camera_info` | `sensor_msgs/CameraInfo` | 8.09e-4-0.028 |
| `/zedx_cabin/zedx_cabin_node/rgb_gray/camera_info` | `sensor_msgs/CameraInfo` | 8.09e-4-0.028 |
| `/zedx_cabin/zedx_cabin_node/rgb_raw/camera_info` | `sensor_msgs/CameraInfo` | 8.09e-4-0.028 |
| `/zedx_cabin/zedx_cabin_node/rgb_raw_gray/camera_info` | `sensor_msgs/CameraInfo` | 0-0.028 |
| `/zedx_cabin/zedx_cabin_node/right/camera_info` | `sensor_msgs/CameraInfo` | 0-0.014 |
| `/zedx_cabin/zedx_cabin_node/right_gray/camera_info` | `sensor_msgs/CameraInfo` | 0-0.014 |
| `/zedx_cabin/zedx_cabin_node/right_raw/camera_info` | `sensor_msgs/CameraInfo` | 0-0.028 |
| `/zedx_cabin/zedx_cabin_node/right_raw_gray/camera_info` | `sensor_msgs/CameraInfo` | 0-0.014 |
| `/zedx_cabin/zedx_cabin_node/roi_mask/camera_info` | `sensor_msgs/CameraInfo` | - |
| `/zedx_cabin/zedx_cabin_node/status/health` | `zed_msgs/HealthStatusStamped` | 10.096-15.000 |
| `/zedx_cabin/zedx_cabin_node/status/heartbeat` | `zed_msgs/Heartbeat` | 0.999-1.002 |
| `/zedx_cabin/zedx_cabin_node/temperature/imu` | `sensor_msgs/Temperature` | 0.999-1.002 |

## Appendix B. Key fields in sync_info.json

A summary file written when recording stops. It isn't a frame pairing table. Counts and paths refer to the original bag, so check actual counts in `rosbag_light/metadata.yaml`.

| Field | Meaning |
|---|---|
| `session_id` | Recording folder name. May differ from the shared session name |
| `start_time_ns`, `end_time_ns` | Recording start and stop times (epoch ns). An approximate range |
| `time_reference` | Common time reference. `"ros_epoch_ns"` |
| `recording_modes.lidar` | Recording mode per LiDAR position (`bag`, `laz`, `both`) |
| `recording_modes.camera` | Camera recording mode (`bag`, `svo2`, `both`) |
| `data_sources.rosbag.topic_count` | Topic count in the original bag |
| `data_sources.pointcloud.file_count` | Number of LAZ files saved |
| `data_sources.pointcloud.dropped_frames` | Frames dropped by the LAZ writer. Not the same as packet loss |
| `data_sources.svo2.path` | Original SVO2 file name |
| `topic_message_counts` | Per-topic message counts in the original bag. Includes excluded topics |
| `forced_stop`, `stop_reason` | Whether it was force-stopped, and why |
| `recorder_warnings` | First 50 lines of recorder warnings |
| `format_version` | Format version of the session's output. Absent in sessions written before the field existed, which are format 1.0.0 (the 2026-10-23 dataset); 1.1.0 from ros2_bag_gui 15d22a6 |
| `logger_commit` | Short git commit of ros2_bag_gui that wrote the session, `-dirty` when it had uncommitted changes, `unknown` outside a git checkout. Format 1.1.0 and later |

## Version history

- 1.1.0 (2026-10-26): `sync_info.json` gains `format_version` and `logger_commit` (ros2_bag_gui 15d22a6).
- 1.0.0 (2026-10-26): first version, written for the 2026-10-23 dataset.
