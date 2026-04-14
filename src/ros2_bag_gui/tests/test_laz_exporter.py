import pytest
import os
import tempfile
import shutil
from pathlib import Path

from ros2_bag_gui.export.laz_exporter import (
    LAZExporter,
    LAZExportConfig,
    LAZExportResult
)


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing."""
    temp_base = tempfile.mkdtemp()
    pointcloud_dir = os.path.join(temp_base, "pointcloud")
    output_dir = os.path.join(temp_base, "output")
    os.makedirs(pointcloud_dir)
    
    yield pointcloud_dir, output_dir
    
    shutil.rmtree(temp_base, ignore_errors=True)


@pytest.fixture
def sample_laz_files(temp_dirs):
    """Create sample LAZ files for testing."""
    pointcloud_dir, _ = temp_dirs
    
    try:
        import laspy
        import numpy as np
    except ImportError:
        pytest.skip("laspy not available")
    
    timestamps = [
        1733824508854518630,
        1733824509854518630,
        1733824510854518630,
        1733824511854518630,
        1733824512854518630,
    ]
    
    created_files = []
    
    for ts in timestamps:
        filename = f"{ts}.laz"
        filepath = os.path.join(pointcloud_dir, filename)
        
        header = laspy.LasHeader(point_format=0, version="1.4")
        header.offsets = [0, 0, 0]
        header.scales = [0.01, 0.01, 0.01]
        
        las = laspy.LasData(header)
        
        x = np.random.randint(0, 1000, 100)
        y = np.random.randint(0, 1000, 100)
        z = np.random.randint(0, 100, 100)
        
        las.x = x
        las.y = y
        las.z = z
        
        las.write(filepath)
        created_files.append((filepath, ts))
    
    return created_files


class TestLAZExporter:
    
    def test_parse_timestamp_from_filename_valid(self):
        """Test parsing valid timestamp from filename."""
        exporter = LAZExporter()
        
        filename = "1733824508854518630.laz"
        timestamp = exporter.parse_timestamp_from_filename(filename)
        
        assert timestamp == 1733824508854518630
    
    def test_parse_timestamp_from_filename_invalid(self):
        """Test parsing invalid filenames returns None."""
        exporter = LAZExporter()
        
        assert exporter.parse_timestamp_from_filename("invalid.laz") is None
        assert exporter.parse_timestamp_from_filename("abc123.laz") is None
        assert exporter.parse_timestamp_from_filename("123.txt") is None
        assert exporter.parse_timestamp_from_filename("") is None
    
    def test_parse_timestamp_from_filename_out_of_range(self):
        """Test parsing timestamps outside reasonable range returns None."""
        exporter = LAZExporter()
        
        assert exporter.parse_timestamp_from_filename("100.laz") is None
        assert exporter.parse_timestamp_from_filename("999999999999999999999.laz") is None
    
    def test_get_laz_files_in_range_all(self, sample_laz_files):
        """Test getting all LAZ files without time filter."""
        pointcloud_dir = os.path.dirname(sample_laz_files[0][0])
        exporter = LAZExporter()
        
        files = exporter.get_laz_files_in_range(pointcloud_dir)
        
        assert len(files) == 5
        assert all(fp.endswith('.laz') for fp, _ in files)
        assert [ts for _, ts in files] == sorted([ts for _, ts in sample_laz_files])
    
    def test_get_laz_files_in_range_with_start(self, sample_laz_files):
        """Test filtering LAZ files with start time."""
        pointcloud_dir = os.path.dirname(sample_laz_files[0][0])
        exporter = LAZExporter()
        
        start_ns = 1733824510854518630
        files = exporter.get_laz_files_in_range(pointcloud_dir, start_ns=start_ns)
        
        assert len(files) == 3
        assert all(ts >= start_ns for _, ts in files)
    
    def test_get_laz_files_in_range_with_end(self, sample_laz_files):
        """Test filtering LAZ files with end time."""
        pointcloud_dir = os.path.dirname(sample_laz_files[0][0])
        exporter = LAZExporter()
        
        end_ns = 1733824510854518630
        files = exporter.get_laz_files_in_range(pointcloud_dir, end_ns=end_ns)
        
        assert len(files) == 3
        assert all(ts <= end_ns for _, ts in files)
    
    def test_get_laz_files_in_range_with_both(self, sample_laz_files):
        """Test filtering LAZ files with both start and end time."""
        pointcloud_dir = os.path.dirname(sample_laz_files[0][0])
        exporter = LAZExporter()
        
        start_ns = 1733824509854518630
        end_ns = 1733824511854518630
        files = exporter.get_laz_files_in_range(pointcloud_dir, start_ns=start_ns, end_ns=end_ns)
        
        assert len(files) == 3
        assert all(start_ns <= ts <= end_ns for _, ts in files)
    
    def test_get_laz_files_in_range_empty_dir(self, temp_dirs):
        """Test getting LAZ files from empty directory."""
        pointcloud_dir, _ = temp_dirs
        exporter = LAZExporter()
        
        files = exporter.get_laz_files_in_range(pointcloud_dir)
        
        assert files == []
    
    def test_get_laz_files_in_range_nonexistent_dir(self):
        """Test getting LAZ files from nonexistent directory."""
        exporter = LAZExporter()
        
        files = exporter.get_laz_files_in_range("/nonexistent/path")
        
        assert files == []
    
    def test_export_all_files(self, sample_laz_files, temp_dirs):
        """Test exporting all LAZ files."""
        pointcloud_dir, output_dir = temp_dirs
        exporter = LAZExporter()
        
        config = LAZExportConfig(
            pointcloud_dir=pointcloud_dir,
            output_dir=output_dir
        )
        
        result = exporter.export(config)
        
        assert result.success is True
        assert result.file_count == 5
        assert result.total_size_bytes > 0
        assert result.merged_file is None
        assert result.error is None
        
        exported_files = os.listdir(output_dir)
        assert len(exported_files) == 5
        assert all(f.endswith('.laz') for f in exported_files)
    
    def test_export_with_time_filter(self, sample_laz_files, temp_dirs):
        """Test exporting LAZ files with time filter."""
        pointcloud_dir, output_dir = temp_dirs
        exporter = LAZExporter()
        
        config = LAZExportConfig(
            pointcloud_dir=pointcloud_dir,
            output_dir=output_dir,
            start_time_ns=1733824509854518630,
            end_time_ns=1733824511854518630
        )
        
        result = exporter.export(config)
        
        assert result.success is True
        assert result.file_count == 3
        assert result.total_size_bytes > 0
        
        exported_files = os.listdir(output_dir)
        assert len(exported_files) == 3
    
    def test_export_with_merge(self, sample_laz_files, temp_dirs):
        """Test exporting and merging LAZ files."""
        pointcloud_dir, output_dir = temp_dirs
        exporter = LAZExporter()
        
        config = LAZExportConfig(
            pointcloud_dir=pointcloud_dir,
            output_dir=output_dir,
            merge=True
        )
        
        result = exporter.export(config)
        
        assert result.success is True
        assert result.file_count == 5
        assert result.merged_file is not None
        assert os.path.exists(result.merged_file)
        assert result.merged_file.endswith("merged.laz")
        
        exported_files = os.listdir(output_dir)
        assert "merged.laz" in exported_files
    
    def test_export_progress_callback(self, sample_laz_files, temp_dirs):
        """Test export with progress callback."""
        pointcloud_dir, output_dir = temp_dirs
        exporter = LAZExporter()
        
        progress_calls = []
        
        def progress_callback(current, total):
            progress_calls.append((current, total))
        
        config = LAZExportConfig(
            pointcloud_dir=pointcloud_dir,
            output_dir=output_dir
        )
        
        result = exporter.export(config, progress_callback=progress_callback)
        
        assert result.success is True
        assert len(progress_calls) > 0
        assert progress_calls[-1] == (5, 5)
    
    def test_export_nonexistent_directory(self, temp_dirs):
        """Test export from nonexistent directory."""
        _, output_dir = temp_dirs
        exporter = LAZExporter()
        
        config = LAZExportConfig(
            pointcloud_dir="/nonexistent/path",
            output_dir=output_dir
        )
        
        result = exporter.export(config)
        
        assert result.success is False
        assert result.file_count == 0
        assert "does not exist" in result.error
    
    def test_export_empty_directory(self, temp_dirs):
        """Test export from empty directory."""
        pointcloud_dir, output_dir = temp_dirs
        exporter = LAZExporter()
        
        config = LAZExportConfig(
            pointcloud_dir=pointcloud_dir,
            output_dir=output_dir
        )
        
        result = exporter.export(config)
        
        assert result.success is True
        assert result.file_count == 0
        assert "No LAZ files found" in result.error
    
    def test_export_creates_output_directory(self, sample_laz_files, temp_dirs):
        """Test that export creates output directory if it doesn't exist."""
        pointcloud_dir, output_dir = temp_dirs
        exporter = LAZExporter()
        
        new_output_dir = os.path.join(output_dir, "nested", "path")
        
        config = LAZExportConfig(
            pointcloud_dir=pointcloud_dir,
            output_dir=new_output_dir
        )
        
        result = exporter.export(config)
        
        assert result.success is True
        assert os.path.isdir(new_output_dir)
        assert len(os.listdir(new_output_dir)) == 5
    
    def test_merge_laz_files(self, sample_laz_files, temp_dirs):
        """Test merging LAZ files directly."""
        try:
            import laspy
        except ImportError:
            pytest.skip("laspy not available")
        
        _, output_dir = temp_dirs
        os.makedirs(output_dir, exist_ok=True)
        exporter = LAZExporter()
        
        input_files = [fp for fp, _ in sample_laz_files]
        output_path = os.path.join(output_dir, "merged.laz")
        
        exporter.merge_laz_files(input_files, output_path)
        
        assert os.path.exists(output_path)
        
        merged = laspy.read(output_path)
        assert len(merged.points) == 500
    
    def test_merge_laz_files_empty_list(self):
        """Test merging with empty file list raises error."""
        exporter = LAZExporter()
        
        with pytest.raises(ValueError, match="No input files"):
            exporter.merge_laz_files([], "/tmp/output.laz")
    
    def test_export_preserves_file_metadata(self, sample_laz_files, temp_dirs):
        """Test that export preserves file metadata."""
        pointcloud_dir, output_dir = temp_dirs
        exporter = LAZExporter()
        
        original_file = sample_laz_files[0][0]
        original_mtime = os.path.getmtime(original_file)
        
        config = LAZExportConfig(
            pointcloud_dir=pointcloud_dir,
            output_dir=output_dir
        )
        
        result = exporter.export(config)
        
        assert result.success is True
        
        exported_file = os.path.join(output_dir, os.path.basename(original_file))
        exported_mtime = os.path.getmtime(exported_file)
        
        assert abs(original_mtime - exported_mtime) < 0.01
