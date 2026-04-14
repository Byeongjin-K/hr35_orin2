"""CSV exporter for ROS2 bag topics."""

import csv
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

from rosbag2_py import ConverterOptions, SequentialReader, StorageFilter, StorageOptions
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message


@dataclass
class CSVExportConfig:
    """Configuration for CSV export."""
    
    bag_path: str              # Path to rosbag directory (containing metadata.yaml)
    topic_name: str            # Topic to export
    topic_type: str            # Message type string
    output_path: str           # Output CSV file path
    start_time_ns: Optional[int] = None   # Time range start (None = from beginning)
    end_time_ns: Optional[int] = None     # Time range end (None = to end)


@dataclass
class CSVExportResult:
    """Result of CSV export operation."""
    
    success: bool
    output_path: str
    message_count: int         # Number of messages exported
    column_count: int          # Number of columns in CSV
    error: Optional[str] = None


class CSVExporter:
    """Exports rosbag topic data to CSV files."""
    
    # Maximum array size to expand into columns
    MAX_ARRAY_SIZE = 100
    
    def export_topic(
        self,
        config: CSVExportConfig,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> CSVExportResult:
        """Export a single topic to CSV.
        
        Uses rosbag2_py SequentialReader to read messages.
        Deserializes with rclpy.serialization.deserialize_message.
        Flattens message fields into CSV columns.
        
        Args:
            config: Export configuration
            progress_callback: Optional (current, total) callback
            
        Returns:
            CSVExportResult with export status and statistics
        """
        # Validate bag path
        if not os.path.exists(config.bag_path):
            return CSVExportResult(
                success=False,
                output_path=config.output_path,
                message_count=0,
                column_count=0,
                error=f"Bag path does not exist: {config.bag_path}"
            )
        
        # Try to load message type
        try:
            msg_class = get_message(config.topic_type)
        except (ModuleNotFoundError, AttributeError, ValueError) as e:
            return CSVExportResult(
                success=False,
                output_path=config.output_path,
                message_count=0,
                column_count=0,
                error=f"Message type not found: {config.topic_type} ({e})"
            )
        
        # Open bag reader
        reader = SequentialReader()
        try:
            storage_options = StorageOptions(uri=config.bag_path, storage_id='sqlite3')
            converter_options = ConverterOptions(
                input_serialization_format='cdr',
                output_serialization_format='cdr'
            )
            reader.open(storage_options, converter_options)
        except Exception as e:
            return CSVExportResult(
                success=False,
                output_path=config.output_path,
                message_count=0,
                column_count=0,
                error=f"Failed to open bag: {e}"
            )
        
        # Set topic filter
        reader.set_filter(StorageFilter(topics=[config.topic_name]))
        
        # Write to temporary file first
        temp_path = config.output_path + '.tmp'
        message_count = 0
        column_count = 0
        columns = None
        
        try:
            with open(temp_path, 'w', newline='') as csvfile:
                writer = None
                
                while reader.has_next():
                    topic, data, timestamp = reader.read_next()
                    
                    # Apply time range filter
                    if config.start_time_ns is not None and timestamp < config.start_time_ns:
                        continue
                    if config.end_time_ns is not None and timestamp > config.end_time_ns:
                        break
                    
                    # Deserialize message
                    try:
                        msg = deserialize_message(data, msg_class)
                    except Exception as e:
                        # Skip malformed messages
                        continue
                    
                    # Flatten message
                    row = self.flatten_message(msg, timestamp)
                    
                    # Initialize CSV writer with columns from first message
                    if writer is None:
                        columns = list(row.keys())
                        column_count = len(columns)
                        writer = csv.DictWriter(csvfile, fieldnames=columns)
                        writer.writeheader()
                    
                    # Write row
                    writer.writerow(row)
                    message_count += 1
                    
                    # Progress callback
                    if progress_callback is not None:
                        progress_callback(message_count, message_count)
            
            # If no messages were written, create empty CSV with just timestamp columns
            if message_count == 0:
                with open(temp_path, 'w', newline='') as csvfile:
                    columns = ['timestamp_sec', 'timestamp_nanosec']
                    column_count = 2
                    writer = csv.DictWriter(csvfile, fieldnames=columns)
                    writer.writeheader()
            
            # Rename temp file to final output
            if os.path.exists(config.output_path):
                os.remove(config.output_path)
            os.rename(temp_path, config.output_path)
            
            return CSVExportResult(
                success=True,
                output_path=config.output_path,
                message_count=message_count,
                column_count=column_count
            )
            
        except Exception as e:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            return CSVExportResult(
                success=False,
                output_path=config.output_path,
                message_count=0,
                column_count=0,
                error=f"Export failed: {e}"
            )
    
    @staticmethod
    def flatten_message(msg: Any, timestamp_ns: int) -> dict:
        """Flatten a ROS message into a flat dict for CSV.
        
        Rules:
        - Always include: timestamp_sec, timestamp_nanosec
        - Nested fields: header.stamp.sec → header_stamp_sec
        - Arrays: data[0] → data_0 (max 100 elements, skip larger)
        - Skip: bytes/large binary data
        
        Args:
            msg: ROS message object
            timestamp_ns: Message timestamp in nanoseconds
            
        Returns:
            Flattened dictionary with string keys and scalar values
        """
        result = {}
        
        # Add timestamp columns (always first)
        result['timestamp_sec'] = timestamp_ns // 1_000_000_000
        result['timestamp_nanosec'] = timestamp_ns % 1_000_000_000
        
        # Flatten message fields
        CSVExporter._flatten_recursive(msg, '', result)
        
        return result
    
    @staticmethod
    def _flatten_recursive(obj: Any, prefix: str, result: dict) -> None:
        """Recursively flatten an object into a dictionary.
        
        Args:
            obj: Object to flatten
            prefix: Current field name prefix
            result: Dictionary to accumulate results
        """
        # Handle None
        if obj is None:
            result[prefix] = ''
            return
        
        # Handle bytes (skip binary data)
        if isinstance(obj, (bytes, bytearray)):
            return
        
        # Handle lists/tuples/arrays (including numpy arrays)
        if isinstance(obj, (list, tuple)) or (hasattr(obj, '__len__') and hasattr(obj, '__getitem__') and not isinstance(obj, str)):
            # Skip large arrays
            if len(obj) > CSVExporter.MAX_ARRAY_SIZE:
                return
            
            # Expand small arrays
            for i, item in enumerate(obj):
                field_name = f"{prefix}_{i}" if prefix else str(i)
                
                # For scalar items, add directly
                if isinstance(item, (int, float, bool, str)):
                    result[field_name] = item
                elif isinstance(item, (bytes, bytearray)):
                    # Skip binary data in arrays
                    continue
                else:
                    # Recursively flatten nested objects in arrays
                    CSVExporter._flatten_recursive(item, field_name, result)
            return
        
        # Handle scalar types
        if isinstance(obj, (int, float, bool, str)):
            result[prefix] = obj
            return
        
        # Handle ROS2 messages (have get_fields_and_field_types method)
        if hasattr(obj, 'get_fields_and_field_types'):
            fields = obj.get_fields_and_field_types().keys()
        elif hasattr(obj, '__slots__'):
            fields = obj.__slots__
        elif hasattr(obj, '__dict__'):
            fields = obj.__dict__.keys()
        else:
            # Unknown type, try to convert to string
            result[prefix] = str(obj)
            return
        
        # Recursively process fields
        for field in fields:
            # Skip private fields
            if field.startswith('_'):
                continue
            
            try:
                value = getattr(obj, field)
            except AttributeError:
                continue
            
            # Build field name
            if prefix:
                field_name = f"{prefix}_{field}"
            else:
                field_name = field
            
            # Recursively flatten
            CSVExporter._flatten_recursive(value, field_name, result)
    
    @staticmethod
    def get_csv_columns(msg: Any) -> list:
        """Get column names from a message (for CSV header).
        
        Args:
            msg: ROS message object
            
        Returns:
            List of column names
        """
        # Flatten a sample message with dummy timestamp
        flattened = CSVExporter.flatten_message(msg, 0)
        return list(flattened.keys())
