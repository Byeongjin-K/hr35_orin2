"""Sync info generation for recording sessions."""
import os
import json
from datetime import datetime
from typing import Dict, List, Optional


def create_sync_info(
    session_folder: str,
    start_time: datetime,
    end_time: datetime,
    topic_counts: Dict[str, int],
    lidar_mode: str = "bag",
    camera_mode: str = "bag",
    laz_file_count: int = 0,
    svo2_files: Optional[List[str]] = None,
    forced_stop: bool = False,
    stop_reason: Optional[str] = None
) -> str:
    """Create sync_info.json in session folder.

    Args:
        session_folder: Path to session folder.
        start_time: Recording start time.
        end_time: Recording end time.
        topic_counts: Dict of topic_name → message count.
        lidar_mode: "bag", "laz", or "both".
        camera_mode: "bag", "svo2", or "both".
        laz_file_count: Number of LAZ files written (if lidar_mode != "bag").
        svo2_files: List of SVO2 file paths (if camera_mode != "bag").
        forced_stop: Whether recording was force-stopped.
        stop_reason: Reason for force stop.

    Returns:
        Path to created sync_info.json.
    """
    session_id = os.path.basename(session_folder)
    start_ns = int(start_time.timestamp() * 10**9)
    end_ns = int(end_time.timestamp() * 10**9)

    # --- data_sources ---
    data_sources: Dict = {
        "rosbag": {
            "path": "rosbag/",
            "topic_count": len(topic_counts),
            "time_source": "message_header_stamp"
        }
    }

    # Pointcloud (LAZ) source — present when lidar writes LAZ files
    if lidar_mode in ("laz", "both"):
        data_sources["pointcloud"] = {
            "path": "pointcloud/",
            "file_count": laz_file_count,
            "time_source": "filename_epoch_ns"
        }

    # SVO2 camera source — present when camera writes SVO2 files
    if camera_mode in ("svo2", "both") and svo2_files:
        data_sources["svo2"] = {
            "path": [os.path.basename(p) for p in svo2_files],
            "file_count": len(svo2_files),
            "time_source": "embedded_ros_ts",
            "timestamp_key": "ROS_TS"
        }

    sync_info: Dict = {
        "session_id": session_id,
        "start_time_ns": start_ns,
        "end_time_ns": end_ns,
        "time_reference": "ros_epoch_ns",
        "recording_modes": {
            "lidar": lidar_mode,
            "camera": camera_mode
        },
        "data_sources": data_sources,
        "topic_message_counts": topic_counts
    }

    if forced_stop:
        sync_info["forced_stop"] = True
        sync_info["stop_reason"] = stop_reason or "unknown"

    sync_path = os.path.join(session_folder, 'sync_info.json')
    with open(sync_path, 'w') as f:
        json.dump(sync_info, f, indent=2)

    return sync_path
