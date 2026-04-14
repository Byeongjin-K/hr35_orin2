from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Callable, Optional
import rosbag2_py
from rclpy.serialization import deserialize_message
from rosidl_runtime_py.utilities import get_message

from rosbag_csv_converter.core.topic_filter import parse_metadata, TopicInfo
from rosbag_csv_converter.core.message_flattener import flatten_message, ArrayFormat


@dataclass
class MessageData:
    timestamp_ns: int
    topic: str
    data: dict


class BagReader:
    def __init__(
        self,
        bag_path: Path | str,
        array_format: ArrayFormat = ArrayFormat.EXPAND,
        db3_files: Optional[list[str]] = None,
        log_callback: Optional[Callable[[str], None]] = None
    ):
        self.bag_path = Path(bag_path)
        self.array_format = array_format
        self.db3_files = db3_files
        self._log = log_callback or (lambda x: None)
        
        if not self.bag_path.exists():
            raise FileNotFoundError(f"Bag folder not found: {self.bag_path}")
        
        self._metadata_path = self.bag_path / "metadata.yaml"
        self._topics: Optional[list[TopicInfo]] = None
        self._type_map: dict[str, type] = {}
        self._failed_types: set[str] = set()
    
    def get_available_topics(self) -> list[TopicInfo]:
        if self._topics is None:
            self._topics = parse_metadata(self._metadata_path)
        return self._topics
    
    def read_messages(
        self,
        topics: list[str],
        limit: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Iterator[MessageData]:
        if self.db3_files:
            yield from self._read_from_specific_files(topics, limit, progress_callback)
        else:
            yield from self._read_from_folder(topics, limit, progress_callback)
    
    def _read_from_folder(
        self,
        topics: list[str],
        limit: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Iterator[MessageData]:
        storage_options = rosbag2_py.StorageOptions(
            uri=str(self.bag_path),
            storage_id='sqlite3'
        )
        converter_options = rosbag2_py.ConverterOptions(
            input_serialization_format='cdr',
            output_serialization_format='cdr'
        )
        
        reader = rosbag2_py.SequentialReader()
        reader.open(storage_options, converter_options)
        
        topic_filter = rosbag2_py.StorageFilter(topics=topics)
        reader.set_filter(topic_filter)
        
        topic_types = {tm.name: tm.type for tm in reader.get_all_topics_and_types()}
        
        count = 0
        total = sum(t.message_count for t in self.get_available_topics() if t.name in topics)
        if limit:
            total = min(total, limit)
        
        while reader.has_next():
            if limit and count >= limit:
                break
            
            topic_name, data, timestamp = reader.read_next()
            
            try:
                msg_type = self._get_message_type(topic_types.get(topic_name, ''))
                if msg_type is None:
                    continue
                
                msg = deserialize_message(data, msg_type)
                flattened = flatten_message(msg, topic_name, self.array_format)
                
                yield MessageData(
                    timestamp_ns=timestamp,
                    topic=topic_name,
                    data=flattened
                )
                
                count += 1
                
                if progress_callback and count % 100 == 0:
                    progress_callback(count, total)
                    
            except Exception:
                continue
        
        if progress_callback:
            progress_callback(count, total)
    
    def _read_from_specific_files(
        self,
        topics: list[str],
        limit: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> Iterator[MessageData]:
        all_topics = self.get_available_topics()
        topic_type_map = {t.name: t.type for t in all_topics}
        
        total = sum(t.message_count for t in all_topics if t.name in topics)
        if limit:
            total = min(total, limit)
        
        count = 0
        topic_set = set(topics)
        topic_counts: dict[str, int] = {}
        
        for db3_file in self.db3_files or []:
            storage_options = rosbag2_py.StorageOptions(
                uri=db3_file,
                storage_id='sqlite3'
            )
            converter_options = rosbag2_py.ConverterOptions(
                input_serialization_format='cdr',
                output_serialization_format='cdr'
            )
            
            reader = rosbag2_py.SequentialReader()
            try:
                reader.open(storage_options, converter_options)
            except Exception as e:
                self._log(f"  [ERROR] Cannot open {db3_file}: {e}")
                continue
            
            topic_filter = rosbag2_py.StorageFilter(topics=topics)
            reader.set_filter(topic_filter)
            
            while reader.has_next():
                if limit and count >= limit:
                    break
                
                topic_name, data, timestamp = reader.read_next()
                
                if topic_name not in topic_set:
                    continue
                
                try:
                    type_str = topic_type_map.get(topic_name, '')
                    msg_type = self._get_message_type(type_str)
                    if msg_type is None:
                        continue
                    
                    msg = deserialize_message(data, msg_type)
                    flattened = flatten_message(msg, topic_name, self.array_format)
                    
                    yield MessageData(
                        timestamp_ns=timestamp,
                        topic=topic_name,
                        data=flattened
                    )
                    
                    count += 1
                    topic_counts[topic_name] = topic_counts.get(topic_name, 0) + 1
                    
                    if progress_callback and count % 100 == 0:
                        progress_callback(count, total)
                        
                except Exception as e:
                    self._log(f"  [ERROR] Deserialize failed for {topic_name}: {e}")
                    continue
            
            if limit and count >= limit:
                break
        
        if progress_callback:
            progress_callback(count, total)
    
    def _get_message_type(self, type_str: str) -> Optional[type]:
        if not type_str:
            return None
        
        if type_str in self._type_map:
            return self._type_map[type_str]
        
        if type_str in self._failed_types:
            return None
        
        try:
            msg_type = get_message(type_str)
            self._type_map[type_str] = msg_type
            return msg_type
        except Exception as e:
            self._failed_types.add(type_str)
            self._log(f"  [WARN] Cannot load message type: {type_str} ({e})")
            return None
