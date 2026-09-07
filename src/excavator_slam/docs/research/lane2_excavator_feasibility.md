<!-- source: librarian lane st_01a07a80, 2026-09-07; claims unverified unless marked in slam_candidates.md -->
st_01a07a80 [completed] model openai-codex/gpt-5.6-luna-fast (reasoning low, variant low)
# LiDAR-inertial SLAM feasibility for a crawler excavator

## A. Prior art on excavators/swing-cabin machines

Public evidence is much stronger for mobile construction-robotics platforms and tracked vehicles than for boom-mounted LiDAR specifically. A boom sensor is intrinsically non-rigid relative to the cabin and requires joint-state compensation or a separate moving-body estimator.

| Source | Machine | SLAM | Sensor placement | Self-occlusion handling | GNSS fusion | Accuracy | URL |
|---|---|---|---|---|---|---|---|
| ETH HEAP | Autonomous excavator | Construction-site perception and mapping using LiDAR/cameras | Excavator body/superstructure sensors | Object and machine geometry are handled in the perception stack; no evidence found of a generally reusable boom self-filter | GNSS/RTK used for outdoor localization in the platform architecture | Project-specific results; no directly comparable SLAM error located | https://ethz.ch/en/news-and-events/eth-news/news/2023/02/autonomous-excavator.html |
| FAST-LIO2 | UAV/UGV demonstrations; applicable to tracked vehicles | Tightly coupled iterated-EKF LiDAR-inertial odometry | Rigid LiDAR/IMU body | No excavator-arm model; dynamic/self points must be filtered externally | No native GNSS factor | Supports high-rate odometry; paper reports real-time operation, but not excavator accuracy | https://github.com/hku-mars/FAST_LIO |
| LIO-SAM | Walking, vehicle, and Ouster datasets | Factor-graph LiDAR-inertial smoothing | Rigid sensor platform | No arm-specific removal; loop closure and GPS are implemented | GPS odometry is added as a factor | Dataset-dependent; repository reports up to 10× real-time on its test platform | https://github.com/TixiaoShan/LIO-SAM |
| Point-LIO | Aggressive-motion platforms | Point-wise LiDAR-inertial odometry | Rigid LiDAR/IMU body | No construction-machine self-filter | No native GNSS fusion | Reports 4–8 kHz odometry output and robustness to degeneration/saturation | https://github.com/hku-mars/Point-LIO |
| DLIO | Ouster/Velodyne/Hesai/Livox mobile platforms | Direct continuous-time LiDAR-inertial odometry | Rigid LiDAR/IMU body | No boom or bucket model | No native GNSS fusion | Ouster datasets are provided; no excavator-specific accuracy | https://github.com/vectr-ucla/direct_lidar_inertial_odometry |

**Engineering conclusion from the prior art:** mount the primary SLAM LiDAR on the cabin/rigid superstructure. A boom LiDAR can provide local bucket/arm perception, but should not be the sole global odometry sensor unless boom joint encoders and a calibrated kinematic transform are incorporated. The excavator arm is a large, structured, moving occluder; generic SLAM packages do not automatically distinguish it from the environment.

Recommended self-occlusion treatment:

1. Publish the boom and bucket as a time-varying robot model and remove their predicted points using TF-aware geometric filtering.
2. Crop a conservative exclusion volume around the known arm envelope.
3. Reject points inconsistent with the static cabin map or use temporal consistency/dynamic-object removal.
4. During stationary swing or boom motion, rely on IMU/GNSS and avoid interpreting arm-only returns as vehicle motion.

## B. Jetson/Humble build feasibility

| Candidate | Build path and dependencies | ARM64 / Jetson evidence | CUDA | Main blockers | URL |
|---|---|---|---|---|---|
| **GLIM** | CMake; Eigen, nanoflann, GTSAM, `gtsam_points`; optional OpenCV, OpenMP, ROS 2, Iridescence | Upstream explicitly reports Ubuntu 22.04/24.04 and NVIDIA Jetson Orin with JetPack 6.1 | Native GPU acceleration; CUDA 12.2+ documented | JetPack 6/L4T version must match CUDA toolchain; ROS2 wrapper and extensions must be built from source | https://github.com/koide3/glim |
| **MOLA** | ROS 2 packages; likely easiest through available Humble binaries listed in the deployment context | No Jetson-specific upstream success evidence established here | Primarily CPU; no required CUDA path | Verify that the exact Humble ARM64 binary set includes `mola_lidar_odometry`, `mola_georeferencing`, and loop-closure packages; otherwise build source | https://github.com/MOLAorg/mola |
| **FAST-LIO2** | ROS1/catkin upstream; PCL, Eigen, `livox_ros_driver` and submodules | Upstream explicitly says ARM platforms are supported, including TX2, Khadas VIM3, and Raspberry Pi 4; this is positive Jetson evidence, but not ROS2 Humble evidence | No CUDA dependency | Original package is ROS1; ROS2 ports are community forks. Ouster 128-line support is not explicitly tested upstream; configure `t` field and `scan_line=128` carefully | https://github.com/hku-mars/FAST_LIO |
| **FAST-LIO-LC / FAST-LIO-SAM / FAST-LIO-SLAM** | Community extensions around FAST-LIO | Fork-specific status varies; no single maintained ROS2/Humble baseline established | Usually CPU | Maintenance, ROS2 compatibility, and GNSS interface must be audited per fork; do not assume upstream FAST-LIO features | https://github.com/hku-mars/FAST_LIO |
| **LIO-SAM ROS2 branch** | ROS2 port plus GTSAM, PCL, Eigen, ROS message packages | No verified Jetson/Humble build evidence from upstream | No CUDA | Upstream requires a 9-axis IMU for initialization and explicitly says Ouster’s internal 6-axis IMU is unsupported; ROS2 branch is not the primary documented implementation | https://github.com/TixiaoShan/LIO-SAM |
| **DLIO** | ROS2 `feature/ros2` branch; OpenMP, PCL >=1.10, Eigen >=3.3.7, CMake >=3.12.4, `sensor_msgs` and standard ROS interfaces | ROS2 branch exists, but no Jetson-specific success report was verified | CPU/OpenMP | ROS2 branch is less mature than default ROS1 path; no GNSS, loop closure, or map georeferencing included | https://github.com/vectr-ucla/direct_lidar_inertial_odometry |
| **Point-LIO** | ROS1/catkin; Eigen, PCL conversions, `livox_ros_driver` | Ubuntu 20.04/ROS Noetic is the documented environment; no ROS2 Humble/Jetson evidence | CPU | ROS1-only upstream, no GNSS or loop closure; Ouster configuration says 16/32/64 lines tested, not 128 | https://github.com/hku-mars/Point-LIO |

**Best build choice:** GLIM is the only candidate whose upstream README explicitly names Jetson Orin/JetPack 6.1 and CUDA. FAST-LIO2 is the strongest CPU fallback, but requires a ROS2 port or ROS1 bridge. MOLA is attractive if the supplied Humble ARM64 packages actually contain the required modules.

## C. GNSS fusion and georeferencing

| Candidate | Accepted GNSS input | Heading constraint | Map/georeferencing and sessions | URL |
|---|---|---|---|---|
| **GLIM** | Core GLIM exposes extensibility rather than a documented built-in `NavSatFix` factor. A custom extension can inject position factors into its factor graph. | Not documented as a built-in GNSS-heading constraint; custom factors are required for dual-antenna heading | Supports map correction and merging multiple mapping sessions, but GNSS georeferencing must be implemented or provided by an extension | https://github.com/koide3/glim and https://github.com/koide3/glim_ext |
| **MOLA** | `mola_georeferencing` is the relevant package for GNSS/map alignment; validate its exact ROS message and configuration schema against the installed version | Treat heading as unsupported until confirmed in the versioned configuration; dual-antenna heading may need a custom factor | Designed for georeferencing; `mola_sm_loop_closure` is the relevant loop-closure package if available in the target distribution | https://github.com/MOLAorg/mola |
| **LIO-SAM** | GPS is consumed as GPS odometry, documented on topic `odometry/gps`, with covariance thresholds | Native GPS factor constrains position; absolute heading is indirectly initialized from the IMU/GPS setup, not exposed as a dual-antenna yaw factor | GPS corrects the global factor graph; loop closure is included as an ICP proof of concept | https://github.com/TixiaoShan/LIO-SAM |
| **FAST-LIO2** | No native GNSS factor or `NavSatFix` fusion | No | Produces local odometry/map; add GNSS through robot_localization, a separate graph, or a localization extension | https://github.com/hku-mars/FAST_LIO |
| **FAST-LIO localization/extensions** | Fork-dependent; some add relocalization rather than GNSS | Fork-dependent | Treat as add-on localization, not a guaranteed georeferenced mapper | https://github.com/HViktorTsoi/FAST_LIO_LOCALIZATION |
| **DLIO** | No native GNSS interface documented | No | Local odometry/map only | https://github.com/vectr-ucla/direct_lidar_inertial_odometry |
| **Point-LIO** | No native GNSS interface documented | No | Local odometry/map only | https://github.com/hku-mars/Point-LIO |

For the excavator, convert RTK latitude/longitude/altitude to a local ENU frame and fuse position plus dual-antenna yaw in a supervisory factor graph or robot-localization layer. GNSS is mounted on the swinging cabin, so its pose must be transformed to the cabin LiDAR frame; it cannot directly georeference a boom LiDAR without boom kinematics.

## D. Recommendation

**Cabin-mounted LiDAR:** use this as the authoritative SLAM sensor. The cabin roof provides a rigid LiDAR/IMU/GNSS relationship, and cabin GNSS heading is directly useful for global yaw. GLIM is the preferred first prototype because Jetson Orin/JetPack support and CUDA are explicitly documented. Add GNSS position/yaw through a custom GLIM extension or MOLA georeferencing. Apply a TF-aware arm/bucket exclusion mask.

**Boom-mounted LiDAR:** use it as a secondary local sensor for bucket, trench, and obstacle perception, or run a separate odometry instance only when boom joint encoders provide accurate time-synchronized kinematics. Do not fuse its unmodeled points into the cabin global map: arm motion and self-occlusion can create false vehicle motion and map ghosts.

## E. Full URL list

- https://github.com/koide3/glim
- https://github.com/koide3/glim_ros2
- https://github.com/koide3/glim_ext
- https://github.com/koide3/gtsam_points
- https://github.com/MOLAorg/mola
- https://github.com/hku-mars/FAST_LIO
- https://github.com/TixiaoShan/LIO-SAM
- https://github.com/vectr-ucla/direct_lidar_inertial_odometry
- https://github.com/hku-mars/Point-LIO
- https://github.com/HViktorTsoi/FAST_LIO_LOCALIZATION
- https://ethz.ch/en/news-and-events/eth-news/news/2023/02/autonomous-excavator.html
- https://koide3.github.io/glim/
- https://arxiv.org/abs/2407.10344
- https://arxiv.org/abs/2010.08196