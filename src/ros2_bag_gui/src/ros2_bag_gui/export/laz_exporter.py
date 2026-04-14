from dataclasses import dataclass
from typing import Optional, Callable
import logging
import os
import shutil
from pathlib import Path
import numpy as np


logger = logging.getLogger(__name__)


@dataclass
class LAZExportConfig:
    pointcloud_dir: str           # Source: {session}/pointcloud/
    output_dir: str               # Destination directory
    start_time_ns: Optional[int] = None   # Filter start (None = all)
    end_time_ns: Optional[int] = None     # Filter end (None = all)
    merge: bool = False           # If True, merge all LAZ into single file


@dataclass
class LAZExportResult:
    success: bool
    output_dir: str
    file_count: int               # Number of files exported
    total_size_bytes: int         # Total size of exported files
    merged_file: Optional[str] = None  # Path to merged file (if merge=True)
    error: Optional[str] = None


@dataclass
class LAZFromBagConfig:
    bag_path: str
    topic_names: list[str]
    output_dir: str
    start_time_ns: Optional[int] = None
    end_time_ns: Optional[int] = None


class LAZExporter:
    """Exports LAZ files from recording sessions with time filtering."""
    
    def export(
        self, 
        config: LAZExportConfig,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> LAZExportResult:
        """Export LAZ files within time range.
        
        1. List all .laz files in pointcloud_dir
        2. Parse timestamp from filename ({timestamp_ns}.laz)
        3. Filter by time range
        4. Copy matching files to output_dir
        5. Optionally merge into single LAZ
        
        Args:
            config: Export configuration
            progress_callback: Optional callback(current, total) for progress updates
            
        Returns:
            LAZExportResult with export status and statistics
        """
        try:
            if not os.path.isdir(config.pointcloud_dir):
                return LAZExportResult(
                    success=False,
                    output_dir=config.output_dir,
                    file_count=0,
                    total_size_bytes=0,
                    error=f"Pointcloud directory does not exist: {config.pointcloud_dir}"
                )
            
            files_in_range = self.get_laz_files_in_range(
                config.pointcloud_dir,
                config.start_time_ns,
                config.end_time_ns
            )
            
            if not files_in_range:
                return LAZExportResult(
                    success=True,
                    output_dir=config.output_dir,
                    file_count=0,
                    total_size_bytes=0,
                    error="No LAZ files found in specified time range"
                )
            
            os.makedirs(config.output_dir, exist_ok=True)
            
            total_size = 0
            total_files = len(files_in_range)
            
            for idx, (file_path, timestamp_ns) in enumerate(files_in_range):
                if progress_callback:
                    progress_callback(idx, total_files)
                
                dest_path = os.path.join(config.output_dir, os.path.basename(file_path))
                shutil.copy2(file_path, dest_path)
                total_size += os.path.getsize(dest_path)
            
            if progress_callback:
                progress_callback(total_files, total_files)
            
            merged_file = None
            if config.merge and files_in_range:
                try:
                    merged_file = os.path.join(config.output_dir, "merged.laz")
                    copied_files = [
                        os.path.join(config.output_dir, os.path.basename(fp))
                        for fp, _ in files_in_range
                    ]
                    self.merge_laz_files(copied_files, merged_file)
                    
                    total_size += os.path.getsize(merged_file)
                except Exception as e:
                    return LAZExportResult(
                        success=False,
                        output_dir=config.output_dir,
                        file_count=len(files_in_range),
                        total_size_bytes=total_size,
                        error=f"Failed to merge LAZ files: {str(e)}"
                    )
            
            return LAZExportResult(
                success=True,
                output_dir=config.output_dir,
                file_count=len(files_in_range),
                total_size_bytes=total_size,
                merged_file=merged_file
            )
            
        except Exception as e:
            return LAZExportResult(
                success=False,
                output_dir=config.output_dir,
                file_count=0,
                total_size_bytes=0,
                error=f"Export failed: {str(e)}"
            )

    def export_from_bag(
        self,
        config: LAZFromBagConfig,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> LAZExportResult:
        try:
            import laspy
            import rosbag2_py
            from rclpy.serialization import deserialize_message
            from rosidl_runtime_py.utilities import get_message
        except ImportError as e:
            return LAZExportResult(
                success=False,
                output_dir=config.output_dir,
                file_count=0,
                total_size_bytes=0,
                error=f"Missing dependency for rosbag export: {str(e)}"
            )

        if not os.path.isdir(config.bag_path):
            return LAZExportResult(
                success=False,
                output_dir=config.output_dir,
                file_count=0,
                total_size_bytes=0,
                error=f"Rosbag directory does not exist: {config.bag_path}"
            )

        if not config.topic_names:
            return LAZExportResult(
                success=False,
                output_dir=config.output_dir,
                file_count=0,
                total_size_bytes=0,
                error="No pointcloud topics provided"
            )

        os.makedirs(config.output_dir, exist_ok=True)

        topic_names = set(config.topic_names)

        def open_reader() -> "rosbag2_py.SequentialReader":
            reader = rosbag2_py.SequentialReader()
            storage_options = rosbag2_py.StorageOptions(uri=config.bag_path, storage_id='')
            converter_options = rosbag2_py.ConverterOptions('', '')
            reader.open(storage_options, converter_options)
            return reader

        try:
            initial_reader = open_reader()
        except Exception as e:
            return LAZExportResult(
                success=False,
                output_dir=config.output_dir,
                file_count=0,
                total_size_bytes=0,
                error=f"Failed to open rosbag: {str(e)}"
            )

        topics_and_types = initial_reader.get_all_topics_and_types()
        topic_type_map = {topic.name: topic.type for topic in topics_and_types}
        pointcloud_topics = {
            topic for topic in topic_names
            if topic_type_map.get(topic) == 'sensor_msgs/msg/PointCloud2'
        }

        if not pointcloud_topics:
            return LAZExportResult(
                success=False,
                output_dir=config.output_dir,
                file_count=0,
                total_size_bytes=0,
                error="No PointCloud2 topics found in bag for requested topic names"
            )

        try:
            msg_type = get_message('sensor_msgs/msg/PointCloud2')
        except Exception as e:
            return LAZExportResult(
                success=False,
                output_dir=config.output_dir,
                file_count=0,
                total_size_bytes=0,
                error=f"Failed to resolve PointCloud2 type: {str(e)}"
            )

        total_messages = 0
        count_reader = open_reader()
        count_reader.set_filter(rosbag2_py.StorageFilter(topics=list(pointcloud_topics)))
        while count_reader.has_next():
            topic_name, _raw, timestamp_ns = count_reader.read_next()
            if topic_name not in pointcloud_topics:
                continue
            if config.start_time_ns is not None and timestamp_ns < config.start_time_ns:
                continue
            if config.end_time_ns is not None and timestamp_ns > config.end_time_ns:
                continue
            total_messages += 1

        DTYPE_MAP = {
            1: ('i1', 1), 2: ('u1', 1), 3: ('i2', 2), 4: ('u2', 2),
            5: ('i4', 4), 6: ('u4', 4), 7: ('f4', 4), 8: ('f8', 8),
        }

        def pointcloud2_to_laz(msg, timestamp_ns: int, output_dir: str) -> Optional[str]:
            fields = {f.name: (f.offset, f.datatype, f.count) for f in msg.fields}
            if not all(name in fields for name in ('x', 'y', 'z')):
                logger.warning("Skipping message at %d: missing x/y/z fields", timestamp_ns)
                return None

            total_points = msg.width * msg.height
            if total_points <= 0:
                return None

            data = np.frombuffer(bytes(msg.data), dtype=np.uint8)
            required_size = total_points * msg.point_step
            if len(data) < required_size:
                logger.warning("Skipping message at %d: data buffer too small", timestamp_ns)
                return None

            data = data[:required_size].reshape(-1, msg.point_step)
            is_big = msg.is_bigendian

            def extract(name: str) -> np.ndarray:
                offset, dtype_id, _count = fields[name]
                if dtype_id not in DTYPE_MAP:
                    raise ValueError(f"Unsupported datatype id: {dtype_id}")

                dtype_str, byte_size = DTYPE_MAP[dtype_id]
                if offset + byte_size > msg.point_step:
                    raise ValueError(f"Field {name} exceeds point_step")

                prefix = '>' if is_big else '<'
                return data[:, offset:offset + byte_size].view(np.dtype(prefix + dtype_str)).flatten()

            try:
                x = extract('x').astype(np.float64)
                y = extract('y').astype(np.float64)
                z = extract('z').astype(np.float64)
            except Exception as e:
                logger.warning("Skipping message at %d: failed xyz extraction: %s", timestamp_ns, e)
                return None

            if len(x) == 0:
                return None

            intensity = None
            if 'intensity' in fields:
                try:
                    intensity = extract('intensity').astype(np.float32)
                except Exception:
                    intensity = None

            point_format = 1 if intensity is not None else 0
            header = laspy.LasHeader(point_format=point_format, version="1.4")
            header.offsets = np.array([float(x.mean()), float(y.mean()), float(z.mean())])
            header.scales = np.array([0.001, 0.001, 0.001])

            las = laspy.LasData(header)
            las.x = x
            las.y = y
            las.z = z

            if intensity is not None and intensity.size > 0 and float(np.max(intensity)) > 0:
                las.intensity = (intensity * 65535 / np.max(intensity)).astype(np.uint16)

            output_path = os.path.join(output_dir, f"{timestamp_ns}.laz")
            las.write(output_path)
            return output_path

        export_reader = open_reader()
        export_reader.set_filter(rosbag2_py.StorageFilter(topics=list(pointcloud_topics)))

        file_count = 0
        total_size_bytes = 0
        processed_messages = 0

        while export_reader.has_next():
            topic_name, raw_data, timestamp_ns = export_reader.read_next()
            if topic_name not in pointcloud_topics:
                continue
            if config.start_time_ns is not None and timestamp_ns < config.start_time_ns:
                continue
            if config.end_time_ns is not None and timestamp_ns > config.end_time_ns:
                continue

            if progress_callback:
                progress_callback(processed_messages, total_messages)
            processed_messages += 1

            try:
                msg = deserialize_message(raw_data, msg_type)
                output_path = pointcloud2_to_laz(msg, timestamp_ns, config.output_dir)
                if output_path is None:
                    continue

                file_count += 1
                total_size_bytes += os.path.getsize(output_path)
            except Exception as e:
                logger.warning("Failed to convert message at %d on %s: %s", timestamp_ns, topic_name, e)

        if progress_callback:
            progress_callback(total_messages, total_messages)

        return LAZExportResult(
            success=True,
            output_dir=config.output_dir,
            file_count=file_count,
            total_size_bytes=total_size_bytes,
        )
    
    @staticmethod
    def get_laz_files_in_range(
        pointcloud_dir: str, 
        start_ns: Optional[int] = None, 
        end_ns: Optional[int] = None
    ) -> list[tuple[str, int]]:
        """Get LAZ files within time range.
        
        Args:
            pointcloud_dir: Directory containing LAZ files
            start_ns: Start time in nanoseconds (None = from beginning)
            end_ns: End time in nanoseconds (None = to end)
            
        Returns:
            List of (file_path, timestamp_ns) sorted by timestamp.
            Filename format: {timestamp_ns}.laz
        """
        if not os.path.isdir(pointcloud_dir):
            return []
        
        files_with_timestamps = []
        
        for filename in os.listdir(pointcloud_dir):
            if not filename.endswith('.laz'):
                continue
            
            timestamp = LAZExporter.parse_timestamp_from_filename(filename)
            if timestamp is None:
                continue
            
            if start_ns is not None and timestamp < start_ns:
                continue
            if end_ns is not None and timestamp > end_ns:
                continue
            
            file_path = os.path.join(pointcloud_dir, filename)
            files_with_timestamps.append((file_path, timestamp))
        
        files_with_timestamps.sort(key=lambda x: x[1])
        
        return files_with_timestamps
    
    @staticmethod
    def parse_timestamp_from_filename(filename: str) -> Optional[int]:
        """Extract nanosecond timestamp from LAZ filename.
        
        Args:
            filename: LAZ filename (e.g., '1733824508854518630.laz')
            
        Returns:
            Timestamp in nanoseconds, or None if filename doesn't match pattern.
            
        Example:
            '1733824508854518630.laz' → 1733824508854518630
        """
        try:
            name_without_ext = os.path.splitext(filename)[0]
            timestamp_ns = int(name_without_ext)
            
            if timestamp_ns < 946684800000000000 or timestamp_ns > 4102444800000000000:
                return None
            
            return timestamp_ns
        except (ValueError, TypeError):
            return None
    
    @staticmethod
    def merge_laz_files(input_files: list[str], output_path: str) -> None:
        """Merge multiple LAZ files into a single LAZ file.
        
        Uses laspy to read all files and write combined output.
        
        Args:
            input_files: List of LAZ file paths to merge
            output_path: Output path for merged LAZ file
            
        Raises:
            ImportError: If laspy is not available
            Exception: If merge operation fails
        """
        try:
            import laspy
            import numpy as np
        except ImportError as e:
            raise ImportError("laspy is required for merging LAZ files") from e
        
        if not input_files:
            raise ValueError("No input files provided for merging")
        
        first_las = laspy.read(input_files[0])
        all_points = [first_las.points.array]
        
        for file_path in input_files[1:]:
            las = laspy.read(file_path)
            all_points.append(las.points.array)
        
        merged_array = np.concatenate(all_points)
        merged_las = laspy.LasData(first_las.header)
        merged_points = laspy.ScaleAwarePointRecord.zeros(len(merged_array), header=first_las.header)
        merged_points.array[:] = merged_array
        merged_las.points = merged_points
        merged_las.write(output_path)
