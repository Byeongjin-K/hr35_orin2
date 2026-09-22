"""Run GLIM against the live sensor, beside a running deployment, without joining it.

slam_offline.launch.py answers "is this configuration any good" by replaying a recording.
This one answers the other half - "does the estimator hold up against the sensor as it
actually publishes" - which no bag can answer, because a bag has already survived
recording: it has no dropped UDP, no driver restart, no clock discontinuity.

Three things make running this next to a live deployment safe rather than merely quiet,
and all three are defaults here rather than instructions in a document:

  * A separate DDS domain. The host default is ROS_DOMAIN_ID=7, which carries the live
    sensors and the OT stack. GLIM publishes a map frame and a pose stream, so an
    instance on 7 would inject a second opinion into a running deployment.
  * A CPU ceiling. The estimator's thread counts are tuning knobs that multiply, and
    this host has a live experiment on it.
  * No sensor configuration of any kind. This file starts an estimator, never a driver,
    so it cannot reinitialise a sensor that something else is using.

The matching RMW is the one thing it cannot enforce for you. GLIM lives in the image and
the image is rmw_fastrtps_cpp; a driver publishing under the host's rmw_cyclonedds_cpp is
invisible to it, with no error on either side. Launch the sensor driver with
RMW_IMPLEMENTATION=rmw_fastrtps_cpp on this same domain, or the entry script's
NOT_VISIBLE line is the only warning you will get.

Example, cabin sensor on the isolated domain:

  ros2 launch excavator_slam slam_live.launch.py run_s:=20 cpus:=2
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.substitutions import LaunchConfiguration

DEFAULT_DOMAIN = "98"
DEFAULT_IMAGE = "excavator-slam-glim:humble"


def _run(context, *args, **kwargs):
    def arg(name):
        return LaunchConfiguration(name).perform(context)

    share = get_package_share_directory("excavator_slam")
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    config_dir = arg("config_dir")
    if not config_dir:
        config_dir = os.path.join(share, "config", "glim_cabin")
        if not os.path.isdir(config_dir):
            config_dir = os.path.join(package_root, "config", "glim_cabin")
    # colcon --symlink-install fills the share directory with symlinks into the build
    # tree, and a docker DIRECTORY mount does not carry those targets into the container:
    # the names list fine while every read fails. Measured - GLIM reported "failed to open
    # /cfg/config_sensors.json", fell back to empty topic names and died on
    # InvalidTopicNameError, which looks like a configuration mistake and is a mount one.
    probe = os.path.join(config_dir, "config.json")
    if os.path.islink(probe) or os.path.islink(config_dir):
        config_dir = os.path.dirname(os.path.realpath(probe))

    entry = os.path.join(share, "scripts", "glim_live_entry.sh")
    if not os.path.exists(entry):
        entry = os.path.join(package_root, "scripts", "glim_live_entry.sh")

    out_host = os.path.abspath(arg("output_dir"))
    os.makedirs(out_host, exist_ok=True)

    cmd = [
        "docker", "run", "--rm", "--name", arg("container_name"),
        "--cpus", arg("cpus"),
        # These next two flags are one fix for one failure mode, and the way it fails is
        # the expensive part: discovery succeeds while data never arrives. FastDDS moves
        # samples between two processes on one host through SHARED MEMORY, while
        # discovery rides UDP - so sharing only the network namespace makes a broken
        # setup look healthy. Measured: "ros2 topic list" in the container listed both
        # cabin topics, GLIM advertised /glim_ros/lidar_odom, and node.log then recorded
        # NOTHING between module load and SIGINT 38 s later - no "estimate initial IMU
        # state", no callback, TRAJECTORY 0 poses.
        #
        # --ipc=host is necessary, since otherwise the container has a private /dev/shm,
        # but on its own it is NOT sufficient: with --ipc=host and the default root user
        # a plain subscriber in the container still measured 0 Hz on a topic the host
        # was publishing at 2.504 Hz. A FastDDS writer writes into the READER's segment,
        # and the reader creates it as root mode 0644, so a host publisher running as
        # uid 1000 has no write permission and drops every sample in silence. Running
        # the container as the invoking user fixes it - 1.801 Hz through the same probe -
        # and stops the outputs being root-owned as a bonus.
        #
        # If this ever has to run as root, the proven alternative is to take shared
        # memory out of the picture with a FastDDS profile whose participant declares
        # only a UDPv4 transport (measured 1.802 Hz). Not the default, because UDP
        # loopback costs real CPU on half-megabyte clouds and this machine is usually
        # running a field experiment at the same time.
        #
        # The offline sibling needs none of this: its estimator reads the bag itself and
        # no sample ever crosses a process boundary.
        "--ipc", "host",
        "--user", "%d:%d" % (os.getuid(), os.getgid()),
        "--network", "host", "--entrypoint", "bash",
        "-e", "HOME=/tmp",
        "-e", "RMW_IMPLEMENTATION=rmw_fastrtps_cpp",
        "-e", "ROS_DOMAIN_ID=" + arg("domain"),
        "-v", config_dir + ":/cfg:ro",
        "-v", out_host + ":/out",
        "-v", entry + ":/entry.sh:ro",
        arg("image"),
        "/entry.sh", "/cfg", "/out/slam_live", arg("run_s"),
    ]
    return [ExecuteProcess(cmd=cmd, output="screen")]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("output_dir", default_value="/tmp/ulw-slam-live",
                              description="host directory that receives the map and trajectory"),
        DeclareLaunchArgument("config_dir", default_value="",
                              description="GLIM config directory; blank uses the package's "
                                          "cabin config, which is the live SLAM sensor"),
        DeclareLaunchArgument("image", default_value=DEFAULT_IMAGE),
        DeclareLaunchArgument("container_name", default_value="excavator_slam_live"),
        DeclareLaunchArgument("domain", default_value=DEFAULT_DOMAIN,
                              description="never 7: that domain carries the live sensors "
                                          "and the OT stack"),
        DeclareLaunchArgument("cpus", default_value="2",
                              description="CPU ceiling, so a live run cannot starve the "
                                          "deployment sharing this host"),
        DeclareLaunchArgument("run_s", default_value="0",
                              description="seconds to run before a clean SIGINT shutdown; "
                                          "0 waits for a signal"),
        OpaqueFunction(function=_run),
    ])
