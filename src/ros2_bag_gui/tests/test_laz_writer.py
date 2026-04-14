"""Tests for LAZ writer."""
import pytest
import numpy as np
import tempfile
import os
import time
from ros2_bag_gui.ros2.laz_writer import (
    LAZWriterThread, PointCloud2Payload, PointFieldInfo, DTYPE_MAP
)

@pytest.fixture
def temp_output_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir

@pytest.fixture
def sample_payload():
    num_points = 10
    point_step = 12
    
    np.random.seed(42)
    x = np.random.randn(num_points).astype(np.float32)
    y = np.random.randn(num_points).astype(np.float32)
    z = np.random.randn(num_points).astype(np.float32)
    
    data = np.column_stack([x, y, z]).tobytes()
    
    fields = [
        PointFieldInfo('x', 0, 7, 1),
        PointFieldInfo('y', 4, 7, 1),
        PointFieldInfo('z', 8, 7, 1),
    ]
    
    return PointCloud2Payload(
        data=data,
        fields=fields,
        point_step=point_step,
        row_step=num_points * point_step,
        width=num_points,
        height=1,
        is_bigendian=False,
        is_dense=True,
        timestamp_ns=1700000000000000000
    )

class TestLAZWriterThread:
    def test_initial_state(self, temp_output_dir):
        writer = LAZWriterThread(temp_output_dir)
        assert writer.file_count == 0
        assert writer.drop_count == 0
    
    def test_write_laz_file(self, temp_output_dir, sample_payload, qtbot):
        writer = LAZWriterThread(temp_output_dir)
        writer.start()
        
        assert writer.enqueue(sample_payload)
        
        time.sleep(0.5)
        
        writer.stop()
        
        laz_files = [f for f in os.listdir(temp_output_dir) if f.endswith('.laz')]
        assert len(laz_files) >= 1
    
    def test_parse_pointcloud_extracts_xyz(self, temp_output_dir, sample_payload):
        writer = LAZWriterThread(temp_output_dir)
        x, y, z, intensity = writer._parse_pointcloud(sample_payload)
        
        assert len(x) == 10
        assert len(y) == 10
        assert len(z) == 10
        assert intensity is None
    
    def test_parse_pointcloud_missing_fields_raises(self, temp_output_dir):
        writer = LAZWriterThread(temp_output_dir)
        
        payload = PointCloud2Payload(
            data=b'\x00' * 40,
            fields=[PointFieldInfo('x', 0, 7, 1)],
            point_step=4,
            row_step=40,
            width=10,
            height=1,
            is_bigendian=False,
            is_dense=True,
            timestamp_ns=0
        )
        
        with pytest.raises(ValueError, match="Missing x/y/z"):
            writer._parse_pointcloud(payload)

class TestDTYPEMap:
    def test_float32_mapping(self):
        dtype, size = DTYPE_MAP[7]
        assert dtype == 'f4'
        assert size == 4
    
    def test_int32_mapping(self):
        dtype, size = DTYPE_MAP[5]
        assert dtype == 'i4'
        assert size == 4
