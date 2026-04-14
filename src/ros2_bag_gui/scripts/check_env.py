#!/usr/bin/env python3
"""Environment verification script for ros2_bag_gui

This script checks:
1. ROS2 core imports (rclpy, rosbag2_py)
2. Custom message package availability
3. System message packages (ouster, zed)

Usage:
    source /opt/ros/kilted/setup.bash
    python3 scripts/check_env.py
"""

import sys


def check_ros2_core():
    """Check ROS2 core imports"""
    print("=" * 60)
    print("ROS2 Core Imports")
    print("=" * 60)
    
    all_ok = True
    
    try:
        import rclpy
        print("✓ rclpy")
    except ImportError as e:
        print(f"✗ rclpy: {e}")
        all_ok = False
    
    try:
        import rosbag2_py
        print("✓ rosbag2_py")
    except ImportError as e:
        print(f"✗ rosbag2_py: {e}")
        all_ok = False
    
    try:
        from rosbag2_py import SequentialWriter, SequentialReader, TopicMetadata
        print("✓ rosbag2_py classes (SequentialWriter, SequentialReader, TopicMetadata)")
    except ImportError as e:
        print(f"✗ rosbag2_py classes: {e}")
        all_ok = False
    
    try:
        from rclpy.serialization import serialize_message, deserialize_message
        print("✓ rclpy.serialization")
    except ImportError as e:
        print(f"✗ rclpy.serialization: {e}")
        all_ok = False
    
    print()
    return all_ok


def check_custom_messages():
    """Check custom message packages"""
    print("=" * 60)
    print("Custom Message Packages")
    print("=" * 60)
    
    packages = {
        'excavator_msgs': ['RemoteControllerFeedback', 'ExcavatorCompleteStatus'],
        'msg_gps_interface': ['GPSMsg', 'GPSMsgAtt'],
    }
    
    found = []
    missing = []
    
    for pkg, msgs in packages.items():
        try:
            __import__(pkg)
            print(f"✓ {pkg}")
            found.append(pkg)
            
            # Try to import specific messages
            for msg in msgs:
                try:
                    exec(f"from {pkg}.msg import {msg}")
                    print(f"  ✓ {msg}")
                except ImportError:
                    print(f"  ✗ {msg} (package found but message missing)")
        except ImportError:
            print(f"✗ {pkg} (NOT FOUND)")
            missing.append(pkg)
    
    print()
    return found, missing


def check_system_messages():
    """Check system message packages (available via apt)"""
    print("=" * 60)
    print("System Message Packages")
    print("=" * 60)
    
    packages = {
        'ouster_sensor_msgs': ['PacketMsg'],
        'zed_interfaces': ['PlaneStamped', 'DepthInfoStamped'],
    }
    
    found = []
    missing = []
    
    for pkg, msgs in packages.items():
        try:
            __import__(pkg)
            print(f"✓ {pkg}")
            found.append(pkg)
            
            # Try to import specific messages
            for msg in msgs:
                try:
                    exec(f"from {pkg}.msg import {msg}")
                    print(f"  ✓ {msg}")
                except ImportError:
                    print(f"  ✗ {msg} (package found but message missing)")
        except ImportError:
            print(f"✗ {pkg} (NOT FOUND)")
            missing.append(pkg)
    
    print()
    return found, missing


def main():
    """Main verification routine"""
    print("\n" + "=" * 60)
    print("ROS2 Environment Verification")
    print("=" * 60)
    print()
    
    # Check ROS2 core
    ros2_ok = check_ros2_core()
    
    # Check custom messages
    custom_found, custom_missing = check_custom_messages()
    
    # Check system messages
    system_found, system_missing = check_system_messages()
    
    # Summary
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    
    if ros2_ok:
        print("✓ ROS2 core imports: OK")
    else:
        print("✗ ROS2 core imports: FAILED")
        print("  → Make sure to source ROS2: source /opt/ros/kilted/setup.bash")
    
    print(f"\nCustom message packages:")
    print(f"  Found: {len(custom_found)}")
    print(f"  Missing: {len(custom_missing)}")
    if custom_missing:
        print(f"  → Missing packages: {', '.join(custom_missing)}")
        print(f"  → These need to be built from source or obtained from project")
    
    print(f"\nSystem message packages:")
    print(f"  Found: {len(system_found)}")
    print(f"  Missing: {len(system_missing)}")
    if system_missing:
        print(f"  → Missing packages: {', '.join(system_missing)}")
        print(f"  → Install with: sudo apt install ros-kilted-<package>")
        print(f"  → Available packages:")
        print(f"     - ros-kilted-ouster-sensor-msgs")
        print(f"     - ros-kilted-zed-msgs")
    
    print()
    
    # Exit code
    if not ros2_ok:
        return 1
    
    # Custom messages missing is OK (soft block)
    # System messages missing is OK (can be installed later)
    return 0


if __name__ == "__main__":
    sys.exit(main())
