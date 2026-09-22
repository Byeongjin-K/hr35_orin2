"""Replay a recorded bag through GLIM and report what it produced.

The SLAM stack lives in a container because this host's apt needs a password that the
session does not have, while docker does not, and because the GLIM binaries come from a
PPA rather than from this workspace. The launch file's job is therefore orchestration:
it starts one container in which the estimator reads the bag itself, so no scan can be
lost to a player running faster than the config can absorb.

Everything of substance is in scripts/glim_offline_entry.sh, which is mounted in rather
than baked into the image, so the recipe is version controlled and a change does not
require a rebuild.

Example:

  ros2 launch excavator_slam slam_offline.launch.py \
      bag:=/home/kimm/data/ulw_slam_1104_restamped_v2

Note the bag must carry ONE clock. Recordings made before robot_ws f08b848 stamp the
LiDAR on the sensor's own oscillator while the GNSS runs on host time, and a SLAM tool
reading such a bag processes exactly one scan and discards the rest. Use
scripts/restamp_bag.py first; the restamped copy is what belongs here.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.substitutions import LaunchConfiguration

# Not the host default of 7. That domain carries the live sensors and the OT stack, so a
# replay there would feed recorded scans into the running global map.
DEFAULT_DOMAIN = "99"
DEFAULT_IMAGE = "excavator-slam-glim:humble"


def _run(context, *args, **kwargs):
    def arg(name):
        return LaunchConfiguration(name).perform(context)

    share = get_package_share_directory("excavator_slam")
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_dir = arg("config_dir")
    if not config_dir:
        config_dir = os.path.join(share, "config", "glim")
        if not os.path.isdir(config_dir):
            config_dir = os.path.join(package_root, "config", "glim")
    # colcon --symlink-install fills the share directory with symlinks into the build
    # tree, and a docker DIRECTORY mount does not carry those targets into the container:
    # the names list fine while every read fails. Measured - GLIM reported "failed to open
    # /cfg/config_sensors.json", fell back to empty topic names and died on
    # InvalidTopicNameError, which looks like a configuration mistake and is a mount one.
    # Resolving one known file gives the directory that actually holds the bytes.
    probe = os.path.join(config_dir, "config.json")
    if os.path.islink(probe) or os.path.islink(config_dir):
        config_dir = os.path.dirname(os.path.realpath(probe))

    entry = os.path.join(share, "scripts", "glim_offline_entry.sh")
    if not os.path.exists(entry):
        entry = os.path.join(package_root, "scripts", "glim_offline_entry.sh")

    bag = os.path.abspath(arg("bag"))
    out_host = os.path.abspath(arg("output_dir"))
    os.makedirs(out_host, exist_ok=True)

    cmd = [
        "docker", "run", "--rm", "--name", arg("container_name"),
        # This host also carries the live stack. An unbounded replay container competes
        # with it for the same 12 cores, and the estimator's thread counts are tuning
        # knobs that can multiply, so the ceiling belongs here rather than in the hope
        # that every config keeps its threads modest.
        "--cpus", arg("cpus"),
        # Run as the invoking user so the run outputs are not root-owned. This is not
        # cosmetic: the entry script starts with "rm -rf $OUT", and a root-owned $OUT
        # inside a user-owned parent cannot be removed by the user - measured, that made
        # a later run die with NODE_EXITED_EARLY and no output at all, for reasons that
        # have nothing to do with SLAM. The live sibling needs the same flag for a
        # different and much worse reason; see the comment there.
        "--user", "%d:%d" % (os.getuid(), os.getgid()),
        "--network", "host", "--entrypoint", "bash",
        "-e", "HOME=/tmp",
        "-e", "RMW_IMPLEMENTATION=rmw_fastrtps_cpp",
        "-e", "ROS_DOMAIN_ID=" + arg("domain"),
        "-v", os.path.dirname(bag) + ":" + os.path.dirname(bag) + ":ro",
        "-v", config_dir + ":/cfg:ro",
        "-v", out_host + ":/out",
        "-v", entry + ":/entry.sh:ro",
        arg("image"),
        "/entry.sh", bag, "/cfg", "/out/slam_offline",
    ]
    return [ExecuteProcess(cmd=cmd, output="screen")]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("bag", description="restamped rosbag2 directory to replay"),
        DeclareLaunchArgument("output_dir", default_value="/tmp/ulw-slam",
                              description="host directory that receives the map and trajectory"),
        DeclareLaunchArgument("config_dir", default_value="",
                              description="GLIM config directory; blank uses the package copy"),
        DeclareLaunchArgument("image", default_value=DEFAULT_IMAGE),
        DeclareLaunchArgument("container_name", default_value="excavator_slam_offline"),
        DeclareLaunchArgument("domain", default_value=DEFAULT_DOMAIN),
        DeclareLaunchArgument("cpus", default_value="4",
                              description="CPU ceiling for the replay container, so an "
                                          "offline run cannot starve the live stack"),
        OpaqueFunction(function=_run),
    ])
