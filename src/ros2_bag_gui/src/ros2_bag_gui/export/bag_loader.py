"""Bag file loader module for loading ROS2 bag recording sessions."""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import yaml


@dataclass
class TopicInfo:
    """Information about a single ROS2 topic in a bag file."""
    
    name: str                  # e.g., "/excavator/sensors/gnss_position"
    type: str                  # e.g., "sensor_msgs/msg/NavSatFix"
    message_count: int         # e.g., 536
    serialization_format: str  # e.g., "cdr"


@dataclass
class BagSessionInfo:
    """Complete information about a ROS2 bag recording session."""
    
    session_path: str              # Absolute path to session folder
    metadata_path: str             # Path to metadata.yaml
    rosbag_path: str               # Path to the rosbag directory (where .db3 files are)
    topics: List[TopicInfo]        # List of all topics
    total_message_count: int       # Sum of all topic message counts
    duration_ns: int               # Duration in nanoseconds
    start_time_ns: int             # Start time (nanoseconds since epoch)
    end_time_ns: int               # Computed: start_time_ns + duration_ns
    db3_files: List[str]           # List of .db3 file absolute paths
    storage_identifier: str        # e.g., "sqlite3"
    has_pointcloud: bool           # True if pointcloud/ folder exists
    has_pointcloud_topics: bool     # True if rosbag contains PointCloud2 topics
    has_svo: bool                  # True if any .svo2 file exists
    pointcloud_files: List[str]    # List of .laz files in pointcloud/
    pointcloud_topic_names: List[str]  # PointCloud2 topic names from rosbag
    svo_files: List[str]           # List of .svo2 files


class BagLoader:
    """Loader for ROS2 bag recording sessions."""
    
    # Message types to exclude from CSV export (binary/large data)
    NON_NUMERIC_TYPES = {
        "sensor_msgs/msg/Image",
        "sensor_msgs/msg/PointCloud2",
        "sensor_msgs/msg/CompressedImage",
        "stereo_msgs/msg/DisparityImage",
        "nav_msgs/msg/Path",
        "rcl_interfaces/msg/Log",
    }
    
    @staticmethod
    def load_session(session_path: str) -> BagSessionInfo:
        """Load a recording session from a folder path.
        
        Searches for metadata.yaml in:
        1. {session_path}/rosbag/metadata.yaml (our format)
        2. {session_path}/metadata.yaml (standard rosbag2 format)
        
        Args:
            session_path: Path to the session folder
            
        Returns:
            BagSessionInfo with all session metadata
            
        Raises:
            FileNotFoundError: if metadata.yaml not found
            ValueError: if metadata.yaml is malformed
        """
        session_path = os.path.abspath(session_path)
        
        # Try to find metadata.yaml
        metadata_path = None
        rosbag_path = None
        
        # Option 1: {session_path}/rosbag/metadata.yaml (our format)
        candidate1 = os.path.join(session_path, "rosbag", "metadata.yaml")
        if os.path.exists(candidate1):
            metadata_path = candidate1
            rosbag_path = os.path.join(session_path, "rosbag")
        else:
            # Option 2: {session_path}/metadata.yaml (standard rosbag2 format)
            candidate2 = os.path.join(session_path, "metadata.yaml")
            if os.path.exists(candidate2):
                metadata_path = candidate2
                rosbag_path = session_path
            else:
                raise FileNotFoundError(
                    f"metadata.yaml not found in {session_path} or {session_path}/rosbag"
                )
        
        # Parse metadata.yaml
        try:
            with open(metadata_path, 'r') as f:
                metadata = yaml.safe_load(f)
        except Exception as e:
            raise ValueError(f"Failed to parse metadata.yaml: {e}")
        
        # Extract root key
        if 'rosbag2_bagfile_information' not in metadata:
            raise ValueError("metadata.yaml missing 'rosbag2_bagfile_information' key")
        
        bag_info = metadata['rosbag2_bagfile_information']
        
        # Extract duration
        if 'duration' not in bag_info or 'nanoseconds' not in bag_info['duration']:
            raise ValueError("metadata.yaml missing duration.nanoseconds")
        duration_ns = bag_info['duration']['nanoseconds']
        
        # Extract start time
        if 'starting_time' not in bag_info or 'nanoseconds_since_epoch' not in bag_info['starting_time']:
            raise ValueError("metadata.yaml missing starting_time.nanoseconds_since_epoch")
        start_time_ns = bag_info['starting_time']['nanoseconds_since_epoch']
        
        # Calculate end time
        end_time_ns = start_time_ns + duration_ns
        
        # Extract storage identifier
        storage_identifier = bag_info.get('storage_identifier', 'sqlite3')
        
        # Extract topics
        topics = []
        if 'topics_with_message_count' not in bag_info:
            raise ValueError("metadata.yaml missing topics_with_message_count")
        
        for topic_entry in bag_info['topics_with_message_count']:
            if 'topic_metadata' not in topic_entry:
                continue
            
            topic_meta = topic_entry['topic_metadata']
            topics.append(TopicInfo(
                name=topic_meta.get('name', ''),
                type=topic_meta.get('type', ''),
                message_count=topic_entry.get('message_count', 0),
                serialization_format=topic_meta.get('serialization_format', 'cdr')
            ))
        
        # Calculate total message count
        total_message_count = sum(t.message_count for t in topics)
        
        # Extract DB3 files
        db3_files = []
        if 'relative_file_paths' in bag_info:
            for rel_path in bag_info['relative_file_paths']:
                abs_path = os.path.join(rosbag_path, rel_path)
                db3_files.append(abs_path)
        
        # Check for pointcloud files
        pointcloud_dir = os.path.join(session_path, "pointcloud")
        has_pointcloud = os.path.isdir(pointcloud_dir)
        pointcloud_files = []
        if has_pointcloud:
            for file in os.listdir(pointcloud_dir):
                if file.endswith('.laz'):
                    pointcloud_files.append(os.path.join(pointcloud_dir, file))
            pointcloud_files.sort()
        
        # Detect PointCloud2 topics in rosbag
        pointcloud_topic_names = [
            t.name for t in topics
            if t.type == 'sensor_msgs/msg/PointCloud2'
        ]
        has_pointcloud_topics = len(pointcloud_topic_names) > 0
        
        # Check for SVO files
        svo_files = []
        for file in os.listdir(session_path):
            if file.endswith('.svo2'):
                svo_files.append(os.path.join(session_path, file))
        svo_files.sort()
        has_svo = len(svo_files) > 0
        
        return BagSessionInfo(
            session_path=session_path,
            metadata_path=metadata_path,
            rosbag_path=rosbag_path,
            topics=topics,
            total_message_count=total_message_count,
            duration_ns=duration_ns,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            db3_files=db3_files,
            storage_identifier=storage_identifier,
            has_pointcloud=has_pointcloud,
            has_pointcloud_topics=has_pointcloud_topics,
            has_svo=has_svo,
            pointcloud_files=pointcloud_files,
            pointcloud_topic_names=pointcloud_topic_names,
            svo_files=svo_files
        )
    
    @staticmethod
    def get_topics_by_type(session: BagSessionInfo, type_filter: str) -> List[TopicInfo]:
        """Filter topics by message type (partial match).
        
        Args:
            session: BagSessionInfo to filter
            type_filter: String to match against topic types (case-sensitive)
            
        Returns:
            List of TopicInfo matching the filter
        """
        return [t for t in session.topics if type_filter in t.type]
    
    @staticmethod
    def get_numeric_topics(session: BagSessionInfo) -> List[TopicInfo]:
        """Get topics suitable for CSV export (exclude Image, PointCloud2, etc.).
        
        Args:
            session: BagSessionInfo to filter
            
        Returns:
            List of TopicInfo suitable for CSV export
        """
        return [
            t for t in session.topics 
            if t.type not in BagLoader.NON_NUMERIC_TYPES
        ]
    
    @staticmethod
    def format_time_range(session: BagSessionInfo) -> str:
        """Format time range as 'YYYY-MM-DD HH:MM:SS ~ HH:MM:SS'.
        
        Args:
            session: BagSessionInfo with time information
            
        Returns:
            Formatted time range string
        """
        # Convert nanoseconds to seconds
        start_sec = session.start_time_ns / 1e9
        end_sec = session.end_time_ns / 1e9
        
        # Convert to datetime
        start_dt = datetime.fromtimestamp(start_sec)
        end_dt = datetime.fromtimestamp(end_sec)
        
        # Format
        if start_dt.date() == end_dt.date():
            # Same day: show date once
            return f"{start_dt.strftime('%Y-%m-%d %H:%M:%S')} ~ {end_dt.strftime('%H:%M:%S')}"
        else:
            # Different days: show full timestamps
            return f"{start_dt.strftime('%Y-%m-%d %H:%M:%S')} ~ {end_dt.strftime('%Y-%m-%d %H:%M:%S')}"
    
    @staticmethod
    def format_duration(duration_ns: int) -> str:
        """Format duration as 'Xh Ym Zs' or 'Xm Ys'.
        
        Args:
            duration_ns: Duration in nanoseconds
            
        Returns:
            Formatted duration string
        """
        # Convert to seconds
        total_seconds = int(duration_ns / 1e9)
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"
