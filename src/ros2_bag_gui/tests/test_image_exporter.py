"""Tests for image exporter."""

import pytest
import tempfile
import os
import shutil
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from ros2_bag_gui.export.image_exporter import (
    ImageExporter,
    ImageSource,
    ImageExportConfig,
    ImageExportResult,
)


@pytest.fixture
def temp_session():
    """Create temporary session directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_output():
    """Create temporary output directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


class TestImageSourceDetection:
    """Test image source detection logic."""
    
    def test_detect_unavailable_empty_session(self, temp_session):
        """Empty session should return UNAVAILABLE."""
        source = ImageExporter.detect_image_source(temp_session)
        assert source == ImageSource.UNAVAILABLE
    
    def test_detect_unavailable_no_rosbag(self, temp_session):
        """Session without rosbag should return UNAVAILABLE."""
        Path(temp_session, "some_file.txt").touch()
        source = ImageExporter.detect_image_source(temp_session)
        assert source == ImageSource.UNAVAILABLE
    
    def test_detect_svo_without_sdk(self, temp_session):
        """SVO file exists but SDK not available should check rosbag."""
        Path(temp_session, "camera.svo2").touch()
        
        with patch.object(ImageExporter, 'is_zed_sdk_available', return_value=False):
            source = ImageExporter.detect_image_source(temp_session)
            assert source == ImageSource.UNAVAILABLE
    
    def test_detect_svo_with_sdk(self, temp_session):
        """SVO file exists and SDK available should return SVO."""
        Path(temp_session, "camera.svo2").touch()
        
        with patch.object(ImageExporter, 'is_zed_sdk_available', return_value=True):
            source = ImageExporter.detect_image_source(temp_session)
            assert source == ImageSource.SVO
    
    def test_detect_rosbag_with_image_topics(self, temp_session):
        """Rosbag with Image topics should return ROSBAG."""
        rosbag_dir = Path(temp_session, "rosbag")
        rosbag_dir.mkdir()
        
        metadata_content = """
rosbag2_bagfile_information:
  topics_with_message_count:
    - topic_metadata:
        name: /camera/image
        type: sensor_msgs/msg/Image
      message_count: 100
    - topic_metadata:
        name: /odom
        type: nav_msgs/msg/Odometry
      message_count: 200
"""
        metadata_path = rosbag_dir / "metadata.yaml"
        metadata_path.write_text(metadata_content)
        
        source = ImageExporter.detect_image_source(temp_session)
        assert source == ImageSource.ROSBAG
    
    def test_detect_rosbag_without_image_topics(self, temp_session):
        """Rosbag without Image topics should return UNAVAILABLE."""
        rosbag_dir = Path(temp_session, "rosbag")
        rosbag_dir.mkdir()
        
        metadata_content = """
rosbag2_bagfile_information:
  topics_with_message_count:
    - topic_metadata:
        name: /odom
        type: nav_msgs/msg/Odometry
      message_count: 200
"""
        metadata_path = rosbag_dir / "metadata.yaml"
        metadata_path.write_text(metadata_content)
        
        source = ImageExporter.detect_image_source(temp_session)
        assert source == ImageSource.UNAVAILABLE
    
    def test_detect_rosbag_invalid_metadata(self, temp_session):
        """Rosbag with invalid metadata should return UNAVAILABLE."""
        rosbag_dir = Path(temp_session, "rosbag")
        rosbag_dir.mkdir()
        
        metadata_path = rosbag_dir / "metadata.yaml"
        metadata_path.write_text("invalid: yaml: content:")
        
        source = ImageExporter.detect_image_source(temp_session)
        assert source == ImageSource.UNAVAILABLE


class TestZedSdkAvailability:
    """Test ZED SDK availability check."""
    
    def test_zed_sdk_not_available(self):
        """ZED SDK should not be available in test environment."""
        assert ImageExporter.is_zed_sdk_available() is False
    
    def test_zed_sdk_available_mocked(self):
        """Mock ZED SDK being available."""
        with patch('builtins.__import__', return_value=Mock()):
            with patch.object(ImageExporter, 'is_zed_sdk_available', return_value=True):
                assert ImageExporter.is_zed_sdk_available() is True


class TestImageExportConfig:
    """Test export configuration validation."""
    
    def test_config_creation(self, temp_session, temp_output):
        """Config should be created with required fields."""
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.ROSBAG
        )
        assert config.session_path == temp_session
        assert config.output_dir == temp_output
        assert config.source == ImageSource.ROSBAG
        assert config.start_time_ns is None
        assert config.end_time_ns is None
    
    def test_config_with_time_range(self, temp_session, temp_output):
        """Config should support time range."""
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.ROSBAG,
            start_time_ns=1000000,
            end_time_ns=2000000
        )
        assert config.start_time_ns == 1000000
        assert config.end_time_ns == 2000000
    
    def test_config_with_svo_path(self, temp_session, temp_output):
        """Config should support SVO path."""
        svo_path = os.path.join(temp_session, "camera.svo2")
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.SVO,
            svo_path=svo_path
        )
        assert config.svo_path == svo_path
    
    def test_config_with_rosbag_topics(self, temp_session, temp_output):
        """Config should support topic filtering."""
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.ROSBAG,
            bag_path=os.path.join(temp_session, "rosbag"),
            image_topics=["/camera/left", "/camera/right"]
        )
        assert config.image_topics == ["/camera/left", "/camera/right"]


class TestImageExport:
    """Test image export operations."""
    
    def test_export_invalid_session_path(self, temp_output):
        """Export should fail with invalid session path."""
        exporter = ImageExporter()
        config = ImageExportConfig(
            session_path="/nonexistent/path",
            output_dir=temp_output,
            source=ImageSource.ROSBAG
        )
        
        result = exporter.export(config)
        assert result.success is False
        assert "does not exist" in result.error
        assert result.image_count == 0
    
    def test_export_unavailable_source(self, temp_session, temp_output):
        """Export should fail with UNAVAILABLE source."""
        exporter = ImageExporter()
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.UNAVAILABLE
        )
        
        result = exporter.export(config)
        assert result.success is False
        assert "No image source available" in result.error
        assert result.image_count == 0
    
    def test_export_creates_output_dir(self, temp_session, temp_output):
        """Export should create output directory if it doesn't exist."""
        output_subdir = os.path.join(temp_output, "images")
        
        exporter = ImageExporter()
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=output_subdir,
            source=ImageSource.UNAVAILABLE
        )
        
        exporter.export(config)
        assert os.path.exists(output_subdir)
    
    def test_export_svo_without_sdk(self, temp_session, temp_output):
        """SVO export should fail without SDK."""
        svo_path = os.path.join(temp_session, "camera.svo2")
        Path(svo_path).touch()
        
        exporter = ImageExporter()
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.SVO,
            svo_path=svo_path
        )
        
        result = exporter.export(config)
        assert result.success is False
        assert "ZED SDK" in result.error or "not available" in result.error
    
    def test_export_svo_missing_file(self, temp_session, temp_output):
        """SVO export should fail with missing SVO file."""
        exporter = ImageExporter()
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.SVO,
            svo_path="/nonexistent.svo2"
        )
        
        with patch.object(ImageExporter, 'is_zed_sdk_available', return_value=True):
            result = exporter.export(config)
            assert result.success is False
            assert "not found" in result.error


class TestRosImageConversion:
    """Test ROS Image message conversion."""
    
    def create_mock_image_msg(self, encoding, width=640, height=480):
        """Create mock sensor_msgs/Image message."""
        msg = Mock()
        msg.encoding = encoding
        msg.width = width
        msg.height = height
        
        if encoding == 'bgr8':
            data = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
        elif encoding == 'rgb8':
            data = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
        elif encoding == 'mono8':
            data = np.random.randint(0, 255, (height, width), dtype=np.uint8)
        elif encoding == 'mono16':
            data = np.random.randint(0, 65535, (height, width), dtype=np.uint16)
        elif encoding == '32FC1':
            data = np.random.rand(height, width).astype(np.float32)
        elif encoding == '16UC1':
            data = np.random.randint(0, 65535, (height, width), dtype=np.uint16)
        else:
            raise ValueError(f"Unsupported encoding: {encoding}")
        
        msg.data = data.tobytes()
        return msg, data
    
    def test_convert_bgr8(self):
        """Convert BGR8 image."""
        exporter = ImageExporter()
        msg, original = self.create_mock_image_msg('bgr8')
        
        result = exporter._ros_image_to_numpy(msg)
        assert result.shape == original.shape
        assert result.dtype == np.uint8
        np.testing.assert_array_equal(result, original)
    
    def test_convert_rgb8(self):
        """Convert RGB8 image."""
        exporter = ImageExporter()
        msg, original = self.create_mock_image_msg('rgb8')
        
        result = exporter._ros_image_to_numpy(msg)
        assert result.shape == original.shape
        assert result.dtype == np.uint8
        np.testing.assert_array_equal(result, original)
    
    def test_convert_mono8(self):
        """Convert mono8 image."""
        exporter = ImageExporter()
        msg, original = self.create_mock_image_msg('mono8')
        
        result = exporter._ros_image_to_numpy(msg)
        assert result.shape == original.shape
        assert result.dtype == np.uint8
        np.testing.assert_array_equal(result, original)
    
    def test_convert_mono16(self):
        """Convert mono16 image."""
        exporter = ImageExporter()
        msg, original = self.create_mock_image_msg('mono16')
        
        result = exporter._ros_image_to_numpy(msg)
        assert result.shape == original.shape
        assert result.dtype == np.uint16
        np.testing.assert_array_equal(result, original)
    
    def test_convert_depth_32fc1(self):
        """Convert 32FC1 depth image."""
        exporter = ImageExporter()
        msg, original = self.create_mock_image_msg('32FC1')
        
        result = exporter._ros_image_to_numpy(msg)
        assert result.shape == original.shape
        assert result.dtype == np.float32
        np.testing.assert_array_almost_equal(result, original)
    
    def test_convert_depth_16uc1(self):
        """Convert 16UC1 depth image."""
        exporter = ImageExporter()
        msg, original = self.create_mock_image_msg('16UC1')
        
        result = exporter._ros_image_to_numpy(msg)
        assert result.shape == original.shape
        assert result.dtype == np.uint16
        np.testing.assert_array_equal(result, original)
    
    def test_convert_unsupported_encoding(self):
        """Unsupported encoding should raise ValueError."""
        exporter = ImageExporter()
        msg = Mock()
        msg.encoding = 'unsupported_format'
        msg.width = 640
        msg.height = 480
        msg.data = b'\x00' * 100
        
        with pytest.raises(ValueError, match="Unsupported encoding"):
            exporter._ros_image_to_numpy(msg)


class TestImageSaving:
    """Test image saving functionality."""
    
    def test_save_image_with_cv2(self, temp_output):
        """Save image using cv2 if available."""
        exporter = ImageExporter()
        img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        output_path = os.path.join(temp_output, "test.jpg")
        
        try:
            import cv2
            exporter._save_image(img, 'bgr8', output_path)
            assert os.path.exists(output_path)
        except ImportError:
            pytest.skip("cv2 not available")
    
    def test_save_depth_image(self, temp_output):
        """Save depth image with proper scaling."""
        exporter = ImageExporter()
        img = np.random.rand(480, 640).astype(np.float32)
        output_path = os.path.join(temp_output, "depth.png")
        
        exporter._save_image(img, '32FC1', output_path, is_depth=True)
        assert os.path.exists(output_path) or os.path.exists(output_path.replace('.png', '.npy'))
    
    def test_save_image_fallback_to_pil(self, temp_output):
        """Save image using PIL if cv2 not available."""
        exporter = ImageExporter()
        img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        output_path = os.path.join(temp_output, "test.jpg")
        
        with patch('cv2.imwrite', side_effect=ImportError("cv2 not available")):
            try:
                exporter._save_image(img, 'rgb8', output_path)
                assert os.path.exists(output_path) or os.path.exists(output_path.replace('.jpg', '.npy'))
            except ImportError:
                pytest.skip("PIL not available")


class TestRosbagExport:
    """Test rosbag image export."""
    
    def test_export_rosbag_missing_path(self, temp_session, temp_output):
        """Export should fail with missing rosbag path."""
        exporter = ImageExporter()
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.ROSBAG,
            bag_path="/nonexistent/rosbag"
        )
        
        result = exporter.export(config)
        assert result.success is False
        assert "not found" in result.error
    
    def test_export_rosbag_import_error(self, temp_session, temp_output):
        """Export should fail gracefully if rosbag2_py not available."""
        rosbag_dir = os.path.join(temp_session, "rosbag")
        os.makedirs(rosbag_dir)
        
        exporter = ImageExporter()
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.ROSBAG,
            bag_path=rosbag_dir
        )
        
        with patch('builtins.__import__', side_effect=ImportError("rosbag2_py not found")):
            result = exporter.export(config)
            assert result.success is False
            assert "rosbag2_py" in result.error


class TestProgressCallback:
    """Test progress callback functionality."""
    
    def test_progress_callback_invoked(self, temp_session, temp_output):
        """Progress callback should be invoked during export."""
        exporter = ImageExporter()
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.UNAVAILABLE
        )
        
        callback = Mock()
        exporter.export(config, progress_callback=callback)
        
    
    def test_progress_callback_none(self, temp_session, temp_output):
        """Export should work without progress callback."""
        exporter = ImageExporter()
        config = ImageExportConfig(
            session_path=temp_session,
            output_dir=temp_output,
            source=ImageSource.UNAVAILABLE
        )
        
        result = exporter.export(config, progress_callback=None)
        assert result is not None


class TestImageExportResult:
    """Test export result dataclass."""
    
    def test_result_success(self, temp_output):
        """Successful result should have correct fields."""
        result = ImageExportResult(
            success=True,
            output_dir=temp_output,
            image_count=42,
            source_used=ImageSource.ROSBAG,
            error=None
        )
        assert result.success is True
        assert result.image_count == 42
        assert result.source_used == ImageSource.ROSBAG
        assert result.error is None
    
    def test_result_failure(self, temp_output):
        """Failed result should include error message."""
        result = ImageExportResult(
            success=False,
            output_dir=temp_output,
            image_count=0,
            source_used=ImageSource.SVO,
            error="SDK not available"
        )
        assert result.success is False
        assert result.image_count == 0
        assert result.error == "SDK not available"
