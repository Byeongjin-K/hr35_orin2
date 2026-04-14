#!/usr/bin/env python3
"""Create test subset from full rosbag data"""
import os
import yaml
import argparse
from rosbag2_py import SequentialReader, SequentialWriter, StorageOptions, ConverterOptions, TopicMetadata


def create_subset(input_path: str, output_path: str, duration_sec: int = 60):
    """
    Create a subset of a rosbag by copying messages within a time range.
    
    Args:
        input_path: Path to source rosbag directory
        output_path: Path for output subset directory
        duration_sec: Duration in seconds to extract (default: 60)
    """
    # Read metadata.yaml to get starting time
    meta_path = os.path.join(input_path, 'metadata.yaml')
    with open(meta_path) as f:
        meta = yaml.safe_load(f)
    
    bag_info = meta['rosbag2_bagfile_information']
    start_ns = bag_info['starting_time']['nanoseconds_since_epoch']
    end_ns = start_ns + int(duration_sec * 1e9)
    
    print(f"Creating subset from: {input_path}")
    print(f"Output to: {output_path}")
    print(f"Duration: {duration_sec} seconds")
    print(f"Time range: {start_ns} to {end_ns}")
    print()
    
    # Setup reader
    reader = SequentialReader()
    storage_options = StorageOptions(uri=input_path, storage_id='sqlite3')
    converter_options = ConverterOptions(input_serialization_format='cdr', output_serialization_format='cdr')
    reader.open(storage_options, converter_options)
    
    # Setup writer
    import shutil
    if os.path.exists(output_path):
        shutil.rmtree(output_path)
    writer = SequentialWriter()
    writer.open(
        StorageOptions(uri=output_path, storage_id='sqlite3'),
        ConverterOptions(input_serialization_format='cdr', output_serialization_format='cdr')
    )
    
    # Copy topic metadata
    print("Creating topics:")
    all_topics = reader.get_all_topics_and_types()
    for topic_info in all_topics:
        print(f"  - {topic_info.name} ({topic_info.type})")
        writer.create_topic(topic_info)
    print()
    
    # Copy messages within time range
    print("Copying messages...")
    count = 0
    last_progress = 0
    
    while reader.has_next():
        topic, data, timestamp = reader.read_next()
        
        if timestamp > end_ns:
            break
        
        writer.write(topic, data, timestamp)
        count += 1
        
        # Progress indicator every 10000 messages
        if count % 10000 == 0:
            elapsed_sec = (timestamp - start_ns) / 1e9
            progress = int((elapsed_sec / duration_sec) * 100)
            if progress > last_progress:
                print(f"  Progress: {progress}% ({count:,} messages, {elapsed_sec:.1f}s)")
                last_progress = progress
    
    writer.close()
    reader.close()
    
    print()
    print(f"✓ Created subset: {count:,} messages, {duration_sec}s")
    print(f"✓ Output: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create a time-limited subset of a ROS2 bag for testing"
    )
    parser.add_argument("input_path", help="Path to source rosbag directory")
    parser.add_argument("output_path", help="Path for output subset directory")
    parser.add_argument(
        "--duration", 
        type=int, 
        default=60, 
        help="Duration in seconds (default: 60)"
    )
    
    args = parser.parse_args()
    
    # Validate input path
    if not os.path.exists(args.input_path):
        print(f"Error: Input path does not exist: {args.input_path}")
        exit(1)
    
    if not os.path.exists(os.path.join(args.input_path, 'metadata.yaml')):
        print(f"Error: No metadata.yaml found in: {args.input_path}")
        exit(1)
    
    create_subset(args.input_path, args.output_path, args.duration)
