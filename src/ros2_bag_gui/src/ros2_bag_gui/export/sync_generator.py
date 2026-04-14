from dataclasses import dataclass
from typing import Optional, List
import csv
import os
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class SyncGeneratorConfig:
    output_path: str                    # Path for timestamps.csv
    pointcloud_dir: Optional[str] = None   # Path to exported LAZ files
    image_dirs: Optional[dict[str, str]] = None  # {topic_name: dir_path}
    start_time_ns: Optional[int] = None
    end_time_ns: Optional[int] = None


@dataclass
class SyncGeneratorResult:
    success: bool
    output_path: str
    row_count: int
    error: Optional[str] = None


class SyncGenerator:
    """Generates timestamps.csv for cross-sensor synchronization."""
    
    def generate(self, config: SyncGeneratorConfig) -> SyncGeneratorResult:
        """Generate timestamps.csv mapping all data sources.
        
        Columns:
        - timestamp_ns: nanosecond epoch timestamp
        - datetime_local: human-readable local time
        - pointcloud_file: corresponding .laz filename (or empty)
        - image_left: left camera image filename (or empty)
        - image_right: right camera image filename (or empty)
        - image_depth: depth image filename (or empty)
        
        Rows are generated from the UNION of all timestamps found across
        all data sources, sorted chronologically.
        """
        try:
            # Collect all timestamps from data sources
            timestamps = self.collect_timestamps(
                pointcloud_dir=config.pointcloud_dir,
                image_dirs=config.image_dirs
            )
            
            # Apply time range filter if specified
            if config.start_time_ns is not None:
                timestamps = [ts for ts in timestamps if ts >= config.start_time_ns]
            if config.end_time_ns is not None:
                timestamps = [ts for ts in timestamps if ts <= config.end_time_ns]
            
            # Collect file mappings for each source
            pointcloud_files = self._collect_files(config.pointcloud_dir, ['.laz']) if config.pointcloud_dir else []
            
            # Organize image files by category
            image_left_files = []
            image_right_files = []
            image_depth_files = []
            
            if config.image_dirs:
                for topic_name, dir_path in config.image_dirs.items():
                    files = self._collect_files(dir_path, ['.jpg', '.png', '.jpeg'])
                    
                    topic_lower = topic_name.lower()
                    if 'left' in topic_lower:
                        image_left_files.extend(files)
                    elif 'right' in topic_lower:
                        image_right_files.extend(files)
                    elif 'depth' in topic_lower:
                        image_depth_files.extend(files)
            
            # Create output directory if needed
            os.makedirs(os.path.dirname(os.path.abspath(config.output_path)), exist_ok=True)
            
            # Write CSV
            with open(config.output_path, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                
                # Write header
                writer.writerow([
                    'timestamp_ns',
                    'datetime_local',
                    'pointcloud_file',
                    'image_left',
                    'image_right',
                    'image_depth'
                ])
                
                # Write data rows
                for ts in timestamps:
                    row = [
                        str(ts),
                        self.ns_to_datetime_local(ts),
                        self.find_closest_file(ts, pointcloud_files),
                        self.find_closest_file(ts, image_left_files),
                        self.find_closest_file(ts, image_right_files),
                        self.find_closest_file(ts, image_depth_files)
                    ]
                    writer.writerow(row)
            
            return SyncGeneratorResult(
                success=True,
                output_path=config.output_path,
                row_count=len(timestamps),
                error=None
            )
            
        except Exception as e:
            return SyncGeneratorResult(
                success=False,
                output_path=config.output_path,
                row_count=0,
                error=str(e)
            )
    
    @staticmethod
    def collect_timestamps(
        pointcloud_dir: Optional[str] = None,
        image_dirs: Optional[dict[str, str]] = None
    ) -> list[int]:
        """Collect all unique timestamps from data sources.
        
        Sources:
        - LAZ files: parse timestamp from filename ({timestamp_ns}.laz)
        - Image files: parse timestamp from filename ({timestamp_ns}.jpg/png)
        
        Returns sorted list of unique nanosecond timestamps.
        """
        timestamps = set()
        
        # Collect from pointcloud directory
        if pointcloud_dir and os.path.exists(pointcloud_dir):
            for filename in os.listdir(pointcloud_dir):
                if filename.endswith('.laz'):
                    try:
                        ts = int(Path(filename).stem)
                        timestamps.add(ts)
                    except ValueError:
                        # Skip files that don't have numeric names
                        continue
        
        # Collect from image directories
        if image_dirs:
            for dir_path in image_dirs.values():
                if not os.path.exists(dir_path):
                    continue
                    
                for filename in os.listdir(dir_path):
                    if filename.endswith(('.jpg', '.png', '.jpeg')):
                        try:
                            # Handle depth images: {timestamp}_depth.png
                            stem = Path(filename).stem
                            if stem.endswith('_depth'):
                                stem = stem[:-6]  # Remove '_depth' suffix
                            
                            ts = int(stem)
                            timestamps.add(ts)
                        except ValueError:
                            # Skip files that don't have numeric names
                            continue
        
        return sorted(list(timestamps))
    
    @staticmethod
    def ns_to_datetime_local(timestamp_ns: int) -> str:
        """Convert nanosecond timestamp to local datetime string.
        
        Format: 'YYYY-MM-DD HH:MM:SS.mmm'
        """
        # Convert nanoseconds to seconds
        timestamp_s = timestamp_ns / 1_000_000_000
        
        # Create datetime object in local timezone
        dt = datetime.fromtimestamp(timestamp_s)
        
        # Format with milliseconds
        return dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # Trim to milliseconds
    
    @staticmethod
    def find_closest_file(
        timestamp_ns: int, 
        file_timestamps: list[tuple[str, int]], 
        max_delta_ns: int = 100_000_000  # 100ms tolerance
    ) -> str:
        """Find the closest file to a given timestamp.
        
        Returns filename if within tolerance, empty string otherwise.
        """
        if not file_timestamps:
            return ''
        
        closest_file = ''
        min_delta = float('inf')
        
        for filename, file_ts in file_timestamps:
            delta = abs(timestamp_ns - file_ts)
            if delta < min_delta:
                min_delta = delta
                closest_file = filename
        
        # Return filename only if within tolerance
        if min_delta <= max_delta_ns:
            return closest_file
        else:
            return ''
    
    @staticmethod
    def _collect_files(directory: str, extensions: list[str]) -> list[tuple[str, int]]:
        """Collect files with timestamps from a directory.
        
        Returns list of (filename, timestamp_ns) tuples.
        """
        files = []
        
        if not os.path.exists(directory):
            return files
        
        for filename in os.listdir(directory):
            if any(filename.endswith(ext) for ext in extensions):
                try:
                    # Handle depth images: {timestamp}_depth.png
                    stem = Path(filename).stem
                    if stem.endswith('_depth'):
                        stem = stem[:-6]  # Remove '_depth' suffix
                    
                    ts = int(stem)
                    files.append((filename, ts))
                except ValueError:
                    # Skip files that don't have numeric names
                    continue
        
        return files
