"""Pytest configuration and fixtures"""
import os
import stat
import sys
import pytest
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect config to temp dir so real user config is never touched."""
    config_dir = tmp_path / ".ros2_bag_gui"
    monkeypatch.setattr(
        "ros2_bag_gui.config.settings.SettingsManager.CONFIG_DIR", config_dir
    )
    monkeypatch.setattr(
        "ros2_bag_gui.config.settings.SettingsManager.CONFIG_FILE",
        config_dir / "config.json",
    )
    profiles_dir = str(config_dir / "profiles")
    monkeypatch.setattr(
        "ros2_bag_gui.config.profiles.ProfileManager.DEFAULT_PROFILES_DIR",
        profiles_dir,
    )


class FakeNode:
    """Stands in for the rclpy node: records subscriptions instead of creating them."""

    def __init__(self):
        self.subscriptions = []
        self.destroyed = []

    def create_subscription(self, msg_class, topic, callback, qos, **kwargs):
        sub = {'topic': topic, 'callback': callback}
        self.subscriptions.append(sub)
        return sub

    def destroy_subscription(self, sub):
        self.destroyed.append(sub)

    @property
    def live_subscriptions(self):
        return [s for s in self.subscriptions if s not in self.destroyed]


@pytest.fixture
def fake_node():
    return FakeNode()


# A stand-in for the `ros2` executable, so the real QProcess path of BagProcess
# runs without ROS. It behaves like `ros2 bag record`: creates the bag folder,
# runs until SIGINT/SIGTERM, then writes metadata.yaml and exits 0.
# FAKE_ROS2_MODE:
#   run (default)  | fail (exit 3 at once)       | warn (print a recorder warning at start)
#   info_lost      (an INFO line about a topic named /gps/lost)
#   warn_on_close  (report lost messages while closing, as rosbag2 does)
#   slowclose      (keep writing to the bag for a second before closing)
#   hang           (ignore the request to stop)
# FAKE_ROS2_COUNTS: JSON {topic: count} written into metadata.yaml on a clean stop.
# FAKE_ROS2_ARGS: file that receives the argument list as JSON.
_FAKE_ROS2 = r'''#!%(python)s
import json, os, signal, sys, time
args = sys.argv[1:]
if os.environ.get('FAKE_ROS2_ARGS'):
    with open(os.environ['FAKE_ROS2_ARGS'], 'w') as f:
        json.dump(args, f)
mode = os.environ.get('FAKE_ROS2_MODE', 'run')
if mode == 'fail':
    sys.stderr.write('[ERROR] [ros2bag]: could not open the bag\n')
    sys.exit(3)
out = args[args.index('-o') + 1]
os.makedirs(out)
open(os.path.join(out, 'rosbag_0.db3'), 'wb').close()

def close_bag(*_):
    if mode == 'slowclose':
        with open(os.path.join(out, 'rosbag_0.db3'), 'ab') as f:
            for _ in range(20):
                f.write(b'x' * 4096)
                f.flush()
                time.sleep(0.05)
    if mode == 'warn_on_close':
        sys.stderr.write('[WARN] [rosbag2_cpp]: Cache buffers lost messages per topic:\n')
        sys.stderr.write('\t/excavator/status: 12\nTotal lost: 12\n')
        sys.stderr.flush()
    counts = json.loads(os.environ.get('FAKE_ROS2_COUNTS', '{}'))
    with open(os.path.join(out, 'metadata.yaml'), 'w') as f:
        f.write('rosbag2_bagfile_information:\n  storage_identifier: sqlite3\n')
        f.write('  message_count: %%d\n  topics_with_message_count:\n' %% sum(counts.values()))
        for name, n in counts.items():
            f.write('    - topic_metadata:\n        name: %%s\n      message_count: %%d\n' %% (name, n))
    sys.exit(0)

stop_handler = signal.SIG_IGN if mode == 'hang' else close_bag
signal.signal(signal.SIGTERM, stop_handler)
signal.signal(signal.SIGINT, stop_handler)
if mode == 'warn':
    sys.stderr.write('[WARN] [rosbag2_cpp]: Cache buffers lost messages per topic:\n')
    sys.stderr.flush()
if mode == 'info_lost':
    sys.stderr.write("[INFO] [rosbag2_recorder]: Subscribed to topic '/gps/lost'\n")
    sys.stderr.flush()
open(os.path.join(out, 'ready'), 'w').close()
while True:
    time.sleep(0.02)
'''


@pytest.fixture
def fake_ros2(tmp_path, monkeypatch):
    """Put a fake `ros2` executable first on PATH; returns its path."""
    bin_dir = tmp_path / "fake_bin"
    bin_dir.mkdir()
    script = bin_dir / "ros2"
    script.write_text(_FAKE_ROS2 % {'python': sys.executable})
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    # The stand-in is up in milliseconds; tests of a recorder that gives up at
    # start set the real grace period themselves.
    from ros2_bag_gui.ros2.bag_process import BagProcess
    monkeypatch.setattr(BagProcess, "STARTUP_GRACE_MS", 100, raising=False)
    monkeypatch.delenv("FAKE_ROS2_MODE", raising=False)
    monkeypatch.delenv("FAKE_ROS2_COUNTS", raising=False)
    monkeypatch.delenv("FAKE_ROS2_ARGS", raising=False)
    return str(script)


@pytest.fixture
def sample_topic_list():
    """Sample topic list for testing"""
    return [
        ("/excavator/sensors/gnss_position", "sensor_msgs/msg/NavSatFix"),
        ("/lidar_boom/points", "sensor_msgs/msg/PointCloud2"),
        ("/tf", "tf2_msgs/msg/TFMessage"),
    ]
