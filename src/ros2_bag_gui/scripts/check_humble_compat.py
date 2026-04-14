#!/usr/bin/env python3
"""Check rosbag2_py API signatures for compatibility verification.

Run this script on BOTH Kilted and Humble to document differences.

Usage:
    python3 check_humble_compat.py > kilted_api.json
    # (On Humble machine)
    python3 check_humble_compat.py > humble_api.json
    # Compare the two JSON files
"""

import inspect
import json
import sys
import os


def check_api():
    results = {
        'ros_distro': os.environ.get('ROS_DISTRO', 'unknown'),
        'python_version': sys.version,
        'api_checks': {}
    }

    try:
        from rosbag2_py import TopicMetadata, SequentialWriter, SequentialReader

        try:
            test_meta = TopicMetadata(
                id=1,
                name='/test',
                type='std_msgs/msg/String',
                serialization_format='cdr',
                offered_qos_profiles=[],
                type_description_hash=''
            )
            has_id = True
            has_hash = True
        except TypeError as e:
            error_msg = str(e)
            has_id = 'id' not in error_msg
            has_hash = 'type_description_hash' not in error_msg
        
        results['api_checks']['TopicMetadata'] = {
            'has_id': has_id,
            'has_type_description_hash': has_hash,
            'constructor_test': 'success' if has_id else 'fallback_needed'
        }

        results['api_checks']['SequentialWriter'] = {
            'has_close': hasattr(SequentialWriter, 'close'),
            'methods': [m for m in dir(SequentialWriter) if not m.startswith('_')]
        }

        results['api_checks']['SequentialReader'] = {
            'has_has_next': hasattr(SequentialReader, 'has_next'),
            'methods': [m for m in dir(SequentialReader) if not m.startswith('_')]
        }

    except ImportError as e:
        results['error'] = str(e)

    return results


if __name__ == '__main__':
    results = check_api()
    print(json.dumps(results, indent=2))
