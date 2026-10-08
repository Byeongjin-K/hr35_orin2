"""Sync info generation for recording sessions."""
import os
import json
from datetime import datetime
from typing import Dict, List, Optional


def read_bag_message_counts(rosbag_dir: str) -> Optional[Dict[str, int]]:
    """Per-topic message counts of a closed bag, from its metadata.yaml.

    Returns None when the bag has no readable metadata (it was not closed
    properly); the counts are then unknown, not zero.
    """
    try:
        import yaml
        with open(os.path.join(rosbag_dir, 'metadata.yaml')) as f:
            info = yaml.safe_load(f)['rosbag2_bagfile_information']
        return {
            t['topic_metadata']['name']: int(t['message_count'])
            for t in info.get('topics_with_message_count') or []
        }
    except Exception:
        return None


def create_sync_info(
    session_folder: str,
    start_time: datetime,
    end_time: datetime,
    topic_counts: Dict[str, int],
    lidar_modes: Optional[Dict[str, str]] = None,
    camera_mode: str = "bag",
    laz_file_count: int = 0,
    svo2_files: Optional[List[str]] = None,
    forced_stop: bool = False,
    stop_reason: Optional[str] = None,
    notices: Optional[List[str]] = None,
    bag_message_counts: Optional[Dict[str, int]] = None,
    recorder_warnings: Optional[List[str]] = None,
    laz_summary: Optional[Dict] = None,
) -> str:
    """Create sync_info.json in session folder.

    Args:
        session_folder: Path to session folder.
        start_time: Recording start time.
        end_time: Recording end time.
        topic_counts: Dict of topic_name → messages the GUI's own monitoring
            subscription received. Not what is in the bag.
        bag_message_counts: Dict of topic_name → messages in the bag (from its
            metadata), or None when the bag could not be read.
        lidar_modes: Per lidar ("boom", "cabin"), the "bag", "laz" or "both"
            really in effect.
        camera_mode: "bag", "svo2", or "both" (the mode really in effect).
        notices: What was done differently from what was asked (mode fallbacks).
        recorder_warnings: Problem lines printed by ros2 bag record (first 50).
        laz_summary: LAZ writer totals: dropped_frames, write_errors and, per
            topic, the folder and file count.
        laz_file_count: Number of LAZ files written (if any lidar is on LAZ).
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
    modes = dict(lidar_modes or {})

    data_sources: Dict = {
        "rosbag": {
            "path": "rosbag/",
            "topic_count": len(
                topic_counts if bag_message_counts is None else bag_message_counts
            ),
            # rosbag2 stamps each message with the time the recorder received it
            "time_source": "receive_time",
            "message_counts_source": (
                "unavailable" if bag_message_counts is None else "rosbag_metadata"
            ),
        }
    }

    # Pointcloud (LAZ) source — present when lidar writes LAZ files
    if any(mode in ("laz", "both") for mode in modes.values()):
        data_sources["pointcloud"] = {
            "path": "pointcloud/",
            "file_count": laz_file_count,
            "time_source": "filename_epoch_ns"
        }
        if laz_summary:
            data_sources["pointcloud"].update(laz_summary)

    # SVO2 camera source — present when camera writes SVO2 files
    if camera_mode in ("svo2", "both") and svo2_files:
        data_sources["svo2"] = {
            "path": [os.path.basename(p) for p in svo2_files],
            "file_count": len(svo2_files),
            # No ROS timestamps are embedded: frames carry the camera's own time
            "time_source": "camera_image_timestamp"
        }

    sync_info: Dict = {
        "session_id": session_id,
        "start_time_ns": start_ns,
        "end_time_ns": end_ns,
        "time_reference": "ros_epoch_ns",
        "recording_modes": {
            "lidar": modes,
            "camera": camera_mode
        },
        "data_sources": data_sources,
        # What is in the bag; null when the bag has no metadata to read it from
        "topic_message_counts": bag_message_counts,
        # What the GUI saw on its own best-effort subscription while recording
        "gui_received_counts": topic_counts
    }

    if notices:
        sync_info["notices"] = list(notices)

    if recorder_warnings:
        sync_info["recorder_warnings"] = list(recorder_warnings[:50])
        sync_info["recorder_warning_count"] = len(recorder_warnings)

    if forced_stop:
        sync_info["forced_stop"] = True
        sync_info["stop_reason"] = stop_reason or "unknown"

    sync_path = os.path.join(session_folder, 'sync_info.json')
    with open(sync_path, 'w') as f:
        json.dump(sync_info, f, indent=2)

    return sync_path
