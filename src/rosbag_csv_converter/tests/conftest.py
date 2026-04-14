import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

SAMPLE_DATA_DIR = Path("/home/kbj/data")
SAMPLE_ROSBAG_FOLDER = SAMPLE_DATA_DIR / "rosbag2_2025_12_10-10_55_08 (숙련자 원래 방식 관로파기, 50cm, 10블록(25m))"


@pytest.fixture
def sample_rosbag_path():
    if SAMPLE_ROSBAG_FOLDER.exists():
        return SAMPLE_ROSBAG_FOLDER
    pytest.skip("Sample rosbag data not available")


@pytest.fixture
def sample_metadata_path(sample_rosbag_path):
    metadata = sample_rosbag_path / "metadata.yaml"
    if metadata.exists():
        return metadata
    pytest.skip("Sample metadata.yaml not available")


@pytest.fixture
def temp_output_dir(tmp_path):
    output_dir = tmp_path / "csv_output"
    output_dir.mkdir()
    return output_dir
