"""Image exporter for recording sessions.

Exports images from SVO files (if ZED SDK available) or rosbag Image topics.
"""

from dataclasses import dataclass
from typing import Optional, Callable, List
from enum import Enum
import os
import json
import logging
import numpy as np
from pathlib import Path

from ros2_bag_gui.zed.sdk_check import is_zed_sdk_available, get_sl_module

logger = logging.getLogger(__name__)

class ImageSource(Enum):
    """Available image export sources."""
    SVO = "svo"              # ZED SDK SVO extraction
    ROSBAG = "rosbag"        # Image topics from .db3
    UNAVAILABLE = "unavailable"  # No image data available


@dataclass
class ImageExportConfig:
    """Configuration for image export."""
    session_path: str              # Session root path
    output_dir: str                # Output directory for images
    source: ImageSource            # Which source to use
    start_time_ns: Optional[int] = None
    end_time_ns: Optional[int] = None
    # SVO-specific
    svo_path: Optional[str] = None      # Path to .svo2 file
    svo_paths: Optional[List[str]] = None  # Paths to multiple .svo2 files
    # Rosbag-specific
    bag_path: Optional[str] = None      # Path to rosbag directory
    image_topics: Optional[List[str]] = None  # Topics to extract


@dataclass
class ImageExportResult:
    """Result of image export operation."""
    success: bool
    output_dir: str
    image_count: int           # Total images exported
    source_used: ImageSource
    error: Optional[str] = None


@dataclass
class StandaloneSVOExportConfig:
    svo_path: str
    output_dir: str


class ImageExporter:
    """Exports images from recording sessions."""
    
    @staticmethod
    def detect_image_source(session_path: str) -> ImageSource:
        """Detect available image source for a session.
        
        Priority:
        1. SVO file exists + ZED SDK installed → SVO
        2. Image topics in rosbag → ROSBAG
        3. Neither → UNAVAILABLE
        
        Args:
            session_path: Path to session root directory
            
        Returns:
            ImageSource enum indicating available source
        """
        session_path_obj = Path(session_path)
        
        # Check for SVO files
        svo_files = list(session_path_obj.glob("*.svo2"))
        if svo_files and ImageExporter.is_zed_sdk_available():
            return ImageSource.SVO
        
        # Check for rosbag with image topics
        rosbag_dir = session_path_obj / "rosbag"
        if rosbag_dir.exists():
            # Check metadata for image topics
            metadata_path = rosbag_dir / "metadata.yaml"
            if metadata_path.exists():
                try:
                    import yaml
                    with open(metadata_path, 'r') as f:
                        metadata = yaml.safe_load(f)
                    
                    # Look for sensor_msgs/msg/Image topics
                    if 'rosbag2_bagfile_information' in metadata:
                        topics = metadata['rosbag2_bagfile_information'].get('topics_with_message_count', [])
                        for topic in topics:
                            topic_type = topic.get('topic_metadata', {}).get('type', '')
                            if 'sensor_msgs/msg/Image' in topic_type:
                                return ImageSource.ROSBAG
                except Exception:
                    pass
        
        return ImageSource.UNAVAILABLE
    
    @staticmethod
    def is_zed_sdk_available() -> bool:
        """Check if ZED SDK (pyzed) is importable.
        
        Delegates to centralized zed.sdk_check module.
        """
        return is_zed_sdk_available()
    def export(
        self, 
        config: ImageExportConfig,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> ImageExportResult:
        """Export images based on configuration.
        
        Dispatches to appropriate method based on source.
        
        Args:
            config: Export configuration
            progress_callback: Optional callback(current, total) for progress updates
            
        Returns:
            ImageExportResult with export status and statistics
        """
        # Validate config
        if not os.path.exists(config.session_path):
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=config.source,
                error=f"Session path does not exist: {config.session_path}"
            )
        
        # Create output directory
        os.makedirs(config.output_dir, exist_ok=True)
        
        # Dispatch based on source
        if config.source == ImageSource.SVO:
            return self._export_from_svo(config, progress_callback)
        elif config.source == ImageSource.ROSBAG:
            return self._export_from_rosbag(config, progress_callback)
        else:
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=config.source,
                error="No image source available"
            )
    
    def export_standalone_svo(
        self,
        config: StandaloneSVOExportConfig,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> ImageExportResult:
        sl = get_sl_module()
        if sl is None:
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=ImageSource.SVO,
                error="ZED SDK (pyzed) is not available"
            )

        if not os.path.exists(config.svo_path):
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=ImageSource.SVO,
                error=f"SVO file not found: {config.svo_path}"
            )

        os.makedirs(config.output_dir, exist_ok=True)

        try:
            count = self._extract_svo_images(
                sl, config.svo_path, config.output_dir,
                None, None,
                progress_callback,
            )
            return ImageExportResult(
                success=count > 0,
                output_dir=config.output_dir,
                image_count=count,
                source_used=ImageSource.SVO,
            )
        except Exception as e:
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=ImageSource.SVO,
                error=f"SVO export failed: {e}"
            )

    def _export_from_svo(
        self, 
        config: ImageExportConfig, 
        progress_callback: Optional[Callable[[int, int], None]]
    ) -> ImageExportResult:
        """Extract images from one or more SVO2 files using ZED SDK."""
        sl = get_sl_module()
        if sl is None:
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=ImageSource.SVO,
                error="ZED SDK (pyzed) is not available"
            )

        svo_paths = config.svo_paths or ([config.svo_path] if config.svo_path else [])
        svo_paths = [p for p in svo_paths if p and os.path.exists(p)]

        if not svo_paths:
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=ImageSource.SVO,
                error="No valid SVO2 files found"
            )

        total_images = 0
        for svo_path in svo_paths:
            svo_name = Path(svo_path).stem
            cam_output_dir = os.path.join(config.output_dir, svo_name)
            os.makedirs(cam_output_dir, exist_ok=True)

            try:
                count = self._extract_svo_images(
                    sl,
                    svo_path,
                    cam_output_dir,
                    config.start_time_ns,
                    config.end_time_ns,
                    progress_callback,
                )
                total_images += count
            except Exception as exc:
                logger.error("SVO2 export error for %s: %s", svo_path, exc)

        return ImageExportResult(
            success=total_images > 0,
            output_dir=config.output_dir,
            image_count=total_images,
            source_used=ImageSource.SVO,
        )

    def _extract_svo_images(
        self,
        sl,
        svo_path: str,
        output_dir: str,
        start_ns: Optional[int],
        end_ns: Optional[int],
        progress_callback: Optional[Callable[[int, int], None]],
    ) -> int:
        """Extract images from a single SVO2 file. Returns image count."""
        cam = sl.Camera()

        init_params = sl.InitParameters()
        init_params.set_from_svo_file(svo_path)
        init_params.svo_real_time_mode = False
        init_params.depth_mode = sl.DEPTH_MODE.NONE

        status = cam.open(init_params)
        if status != sl.ERROR_CODE.SUCCESS:
            raise RuntimeError(f"Failed to open SVO2: {status}")

        cv2 = None
        pil_image = None
        try:
            import cv2 as cv2_mod

            cv2 = cv2_mod
        except ImportError:
            try:
                from PIL import Image as pil_image_mod

                pil_image = pil_image_mod
            except ImportError:
                pass

        try:
            image_mat = sl.Mat()
            total_frames = cam.get_svo_number_of_frames()
            image_count = 0

            for frame_idx in range(total_frames):
                err = cam.grab()
                if err != sl.ERROR_CODE.SUCCESS:
                    if err == sl.ERROR_CODE.END_OF_SVOFILE_REACHED:
                        break
                    continue

                ts_ns = cam.get_timestamp(sl.TIME_REFERENCE.IMAGE).get_nanoseconds()

                ros_ts_ns = ts_ns
                try:
                    svo_data = sl.SVOData()
                    if cam.retrieve_svo_data("ROS_TS", svo_data) == sl.ERROR_CODE.SUCCESS:
                        ros_ts_ns = int(svo_data.get_content().decode("utf-8"))
                except Exception:
                    pass

                if start_ns is not None and ros_ts_ns < start_ns:
                    continue
                if end_ns is not None and ros_ts_ns > end_ns:
                    continue

                cam.retrieve_image(image_mat, sl.VIEW.LEFT)
                img_np = image_mat.get_data()

                if cv2 is not None:
                    output_path = os.path.join(output_dir, f"{ros_ts_ns}.jpg")
                    bgr = img_np[:, :, :3]
                    if cv2.imwrite(output_path, bgr):
                        image_count += 1
                elif pil_image is not None:
                    output_path = os.path.join(output_dir, f"{ros_ts_ns}.jpg")
                    rgb = img_np[:, :, [2, 1, 0]]
                    pil_img = pil_image.fromarray(rgb)
                    pil_img.save(output_path, quality=95)
                    image_count += 1
                else:
                    output_path = os.path.join(output_dir, f"{ros_ts_ns}.npy")
                    np.save(output_path, img_np)
                    image_count += 1

                if progress_callback:
                    progress_callback(frame_idx + 1, total_frames)

            return image_count
        finally:
            cam.close()
    
    def _export_from_rosbag(
        self, 
        config: ImageExportConfig,
        progress_callback: Optional[Callable[[int, int], None]]
    ) -> ImageExportResult:
        """Extract images from rosbag Image topics.
        
        Uses rosbag2_py SequentialReader.
        sensor_msgs/msg/Image → JPEG (color) or PNG (depth/mono)
        
        Encoding handling:
        - bgr8, rgb8 → JPEG
        - mono8, mono16 → PNG
        - 32FC1 (depth) → 16-bit PNG (scaled)
        
        Args:
            config: Export configuration
            progress_callback: Optional progress callback
            
        Returns:
            ImageExportResult with export status
        """
        if not config.bag_path or not os.path.exists(config.bag_path):
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=ImageSource.ROSBAG,
                error=f"Rosbag path not found: {config.bag_path}"
            )
        
        try:
            from rosbag2_py import SequentialReader, StorageOptions, ConverterOptions
            from rclpy.serialization import deserialize_message
            from rosidl_runtime_py.utilities import get_message
        except ImportError as e:
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=ImageSource.ROSBAG,
                error=f"Failed to import rosbag2_py: {e}"
            )
        
        # Setup reader
        storage_options = StorageOptions(uri=config.bag_path, storage_id='sqlite3')
        converter_options = ConverterOptions(
            input_serialization_format='cdr',
            output_serialization_format='cdr'
        )
        
        reader = SequentialReader()
        reader.open(storage_options, converter_options)
        
        # Get topic type map
        topic_types = reader.get_all_topics_and_types()
        type_map = {t.name: t.type for t in topic_types}
        
        # Filter for requested image topics
        if config.image_topics:
            topics_to_extract = set(config.image_topics)
        else:
            # Extract all Image topics
            topics_to_extract = {
                name for name, type_str in type_map.items()
                if 'sensor_msgs/msg/Image' in type_str
            }
        
        if not topics_to_extract:
            return ImageExportResult(
                success=False,
                output_dir=config.output_dir,
                image_count=0,
                source_used=ImageSource.ROSBAG,
                error="No image topics found in rosbag"
            )
        
        # Create subdirectories for each topic
        topic_dirs = {}
        for topic in topics_to_extract:
            # Sanitize topic name for directory
            dir_name = topic.replace('/', '_').strip('_')
            topic_dir = os.path.join(config.output_dir, dir_name)
            os.makedirs(topic_dir, exist_ok=True)
            topic_dirs[topic] = topic_dir
        
        # Read and export images
        image_count = 0
        total_messages = 0
        
        # Count total messages for progress
        if reader.has_next():
            metadata = reader.get_metadata()
            total_messages = sum(
                t.message_count for t in metadata.topics_with_message_count
                if t.topic_metadata.name in topics_to_extract
            )
        
        processed = 0
        
        while reader.has_next():
            topic, data, timestamp = reader.read_next()
            
            if topic not in topics_to_extract:
                continue
            
            # Check time range
            if config.start_time_ns is not None and timestamp < config.start_time_ns:
                continue
            if config.end_time_ns is not None and timestamp > config.end_time_ns:
                continue
            
            # Deserialize message
            try:
                msg_type = get_message(type_map[topic])
                msg = deserialize_message(data, msg_type)
                
                # Convert and save image
                output_path = self._save_ros_image(
                    msg, 
                    timestamp, 
                    topic_dirs[topic]
                )
                
                if output_path:
                    image_count += 1
                
                processed += 1
                if progress_callback and total_messages > 0:
                    progress_callback(processed, total_messages)
                    
            except Exception as e:
                # Skip problematic messages
                continue
        
        return ImageExportResult(
            success=True,
            output_dir=config.output_dir,
            image_count=image_count,
            source_used=ImageSource.ROSBAG,
            error=None
        )
    
    def _save_ros_image(self, msg, timestamp: int, output_dir: str) -> Optional[str]:
        """Convert and save ROS Image message to file.
        
        Args:
            msg: sensor_msgs/msg/Image message
            timestamp: Timestamp in nanoseconds
            output_dir: Directory to save image
            
        Returns:
            Path to saved image, or None if failed
        """
        try:
            # Convert to numpy
            img = self._ros_image_to_numpy(msg)
            
            # Determine output format and filename
            if 'depth' in msg.encoding.lower() or msg.encoding in ['32FC1', '16UC1']:
                filename = f"{timestamp}_depth.png"
                is_depth = True
            elif msg.encoding in ['mono8', 'mono16', '8UC1']:
                filename = f"{timestamp}.png"
                is_depth = False
            else:
                filename = f"{timestamp}.jpg"
                is_depth = False
            
            output_path = os.path.join(output_dir, filename)
            
            # Save image
            self._save_image(img, msg.encoding, output_path, is_depth)
            
            return output_path
            
        except Exception as e:
            return None
    
    def _ros_image_to_numpy(self, msg) -> np.ndarray:
        """Convert sensor_msgs/Image to numpy array.
        
        Args:
            msg: sensor_msgs/msg/Image message
            
        Returns:
            Numpy array representation of image
            
        Raises:
            ValueError: If encoding is not supported
        """
        # Encoding → dtype + channels
        ENCODING_MAP = {
            'bgr8': (np.uint8, 3),
            'rgb8': (np.uint8, 3),
            'bgra8': (np.uint8, 4),
            'rgba8': (np.uint8, 4),
            'mono8': (np.uint8, 1),
            'mono16': (np.uint16, 1),
            '32FC1': (np.float32, 1),
            '16UC1': (np.uint16, 1),
            '8UC1': (np.uint8, 1),
            '8UC3': (np.uint8, 3),
        }
        
        if msg.encoding not in ENCODING_MAP:
            raise ValueError(f"Unsupported encoding: {msg.encoding}")
        
        dtype, channels = ENCODING_MAP[msg.encoding]
        
        # Convert bytes to numpy array
        img = np.frombuffer(msg.data, dtype=dtype)
        
        # Reshape
        if channels == 1:
            img = img.reshape(msg.height, msg.width)
        else:
            img = img.reshape(msg.height, msg.width, channels)
        
        return img
    
    def _save_image(
        self, 
        img: np.ndarray, 
        encoding: str, 
        output_path: str,
        is_depth: bool = False
    ):
        """Save numpy image to file.
        
        Tries cv2 first, falls back to PIL if cv2 not available.
        
        Args:
            img: Numpy array image
            encoding: Original ROS encoding
            output_path: Path to save image
            is_depth: Whether this is a depth image
        """
        # Try cv2 first
        try:
            import cv2
            
            # Handle depth images (convert float32 to uint16)
            if is_depth and img.dtype == np.float32:
                # Scale to 16-bit range (assuming meters, scale to mm)
                img = (img * 1000).astype(np.uint16)
            
            if encoding == 'bgra8':
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            elif encoding == 'rgba8':
                img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
            elif encoding == 'rgb8' or encoding == '8UC3':
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            cv2.imwrite(output_path, img)
            return
            
        except ImportError:
            pass
        
        # Fallback to PIL
        try:
            from PIL import Image
            
            # Handle depth images
            if is_depth and img.dtype == np.float32:
                img = (img * 1000).astype(np.uint16)
            
            if encoding in ('bgra8', 'rgba8'):
                img = img[:, :, :3]
                if encoding == 'bgra8':
                    img = img[:, :, ::-1]
            elif encoding == 'bgr8':
                img = img[:, :, ::-1]

            if len(img.shape) == 2:
                # Grayscale
                if img.dtype == np.uint16:
                    pil_img = Image.fromarray(img, mode='I;16')
                else:
                    pil_img = Image.fromarray(img, mode='L')
            else:
                # RGB
                pil_img = Image.fromarray(img, mode='RGB')
            
            pil_img.save(output_path)
            return
            
        except ImportError:
            pass
        
        # Last resort: raw numpy save
        np.save(output_path.replace('.jpg', '.npy').replace('.png', '.npy'), img)
