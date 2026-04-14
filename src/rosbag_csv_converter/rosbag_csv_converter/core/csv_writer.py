import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Any
from collections import defaultdict

from rosbag_csv_converter.core.bag_reader import MessageData


@dataclass
class ConversionStats:
    total_messages: int = 0
    total_rows: int = 0
    total_columns: int = 0
    files_created: int = 0
    topics_included: int = 0
    resample_rate_hz: int = 0
    time_range_sec: float = 0.0


class CsvWriter:
    def __init__(self, output_path: Path | str, resample_rate_hz: int = 10):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.resample_rate_hz = resample_rate_hz
        self.resample_interval_ns = int(1e9 / resample_rate_hz)
    
    def write(self, messages: Iterable[MessageData]) -> ConversionStats:
        messages_list = list(messages)
        
        if not messages_list:
            self.output_path.touch()
            return ConversionStats(files_created=1)
        
        messages_list.sort(key=lambda m: m.timestamp_ns)
        
        topics = sorted(set(msg.topic for msg in messages_list))
        
        topic_fields: dict[str, list[str]] = {}
        for msg in messages_list:
            if msg.topic not in topic_fields:
                topic_fields[msg.topic] = []
            for field_name in msg.data.keys():
                short_name = self._shorten_field_name(field_name, msg.topic)
                if short_name not in topic_fields[msg.topic]:
                    topic_fields[msg.topic].append(short_name)
        
        for topic in topic_fields:
            topic_fields[topic].sort()
        
        fieldnames = ["timestamp"]
        for topic in topics:
            for field_name in topic_fields[topic]:
                fieldnames.append(self._format_column_name(topic, field_name))
        
        rows = self._resample_with_ffill(messages_list, topics, topic_fields)
        
        with open(self.output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            
            for row in rows:
                writer.writerow(row)
        
        time_range_sec = 0.0
        if len(rows) > 1:
            time_range_sec = (rows[-1]["timestamp"] - rows[0]["timestamp"]) / 1e9
        
        return ConversionStats(
            total_messages=len(messages_list),
            total_rows=len(rows),
            total_columns=len(fieldnames),
            files_created=1,
            topics_included=len(topics),
            resample_rate_hz=self.resample_rate_hz,
            time_range_sec=time_range_sec
        )
    
    def _shorten_field_name(self, field_name: str, topic: str) -> str:
        prefix = topic + "."
        if field_name.startswith(prefix):
            return field_name[len(prefix):]
        prefix = topic.replace("/", "_") + "."
        if field_name.startswith(prefix):
            return field_name[len(prefix):]
        return field_name
    
    def _format_column_name(self, topic: str, field_name: str) -> str:
        topic_prefix = topic.lstrip("/")
        full_name = f"{topic_prefix}/{field_name}"
        formatted = full_name.replace("._", "/").replace(".", "/")
        parts = formatted.split("/")
        cleaned_parts = [p.lstrip("_") for p in parts]
        return "/".join(cleaned_parts)
    
    def _resample_with_ffill(
        self, 
        messages: list[MessageData], 
        topics: list[str],
        topic_fields: dict[str, list[str]]
    ) -> list[dict]:
        if not messages:
            return []
        
        start_ts = messages[0].timestamp_ns
        end_ts = messages[-1].timestamp_ns
        
        start_bucket = (start_ts // self.resample_interval_ns) * self.resample_interval_ns
        end_bucket = (end_ts // self.resample_interval_ns) * self.resample_interval_ns
        
        buckets: dict[int, dict[str, dict[str, Any]]] = defaultdict(lambda: defaultdict(dict))
        
        for msg in messages:
            bucket_ts = (msg.timestamp_ns // self.resample_interval_ns) * self.resample_interval_ns
            
            for original_field, value in msg.data.items():
                short_name = self._shorten_field_name(original_field, msg.topic)
                column_name = self._format_column_name(msg.topic, short_name)
                buckets[bucket_ts][msg.topic][column_name] = value
        
        rows: list[dict] = []
        last_values: dict[str, Any] = {}
        
        current_ts = start_bucket
        while current_ts <= end_bucket:
            row = {"timestamp": current_ts}
            
            if current_ts in buckets:
                for topic_data in buckets[current_ts].values():
                    for col, val in topic_data.items():
                        row[col] = val
                        last_values[col] = val
            
            for col, val in last_values.items():
                if col not in row:
                    row[col] = val
            
            rows.append(row)
            current_ts += self.resample_interval_ns
        
        return rows
