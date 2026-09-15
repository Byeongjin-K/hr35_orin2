#!/usr/bin/env python3
"""The ZED node must get enough time to close the camera before launch escalates
SIGINT -> SIGTERM -> SIGKILL.

Why this is a test and not a comment: an unclean kill leaves the ZED SDK capture
session and its EGL buffers behind. The ZED-X daemon then sees the camera FROZEN
and restarts nvargus while the sensor is still streaming; tegracam's stop path
errors out ("Error turning off streaming") and leaks a module_put(), which drives
/sys/module/sl_zedx/refcnt negative and locks out every no-reboot recovery.

Observed on exca-orin-2, 2026-09-09 12:00:
  process[component_container_isolated-2] failed to terminate '5' seconds after
  receiving 'SIGINT', escalating to 'SIGTERM'

launch's default sigterm_timeout is 5 s, which is not enough for sl::Camera::close().
"""
import importlib.util
import sys

from launch import LaunchContext
from launch.actions import SetLaunchConfiguration

MIN_SIGTERM_SEC = 20.0
MIN_SIGKILL_SEC = 5.0
# Every launch file that starts a ZED node. They all share the sl_zedx module, so an
# unclean kill of ANY of them wedges the module for ALL cameras.
LAUNCH_FILES = [
    "/home/kimm/robot_ws/src/hr35_bringup/launch/zedx_cabin.launch.py",
    "/home/kimm/robot_ws/src/hr35_bringup/launch/zedx_boom.launch.py",
    "/home/kimm/robot_ws/src/hr35_bringup/launch/dual_zedx.launch.py",
]


def launch_configurations(path):
    spec = importlib.util.spec_from_file_location("_lf", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ld = mod.generate_launch_description()
    ctx = LaunchContext()
    for entity in ld.entities:
        if isinstance(entity, SetLaunchConfiguration):
            entity.execute(ctx)
    return dict(ctx.launch_configurations)


def main():
    passed = failed = 0
    for path in LAUNCH_FILES:
        name = path.rsplit("/", 1)[-1]
        try:
            cfg = launch_configurations(path)
        except Exception as exc:                      # noqa: BLE001
            print(f"FAIL {name}: could not build the launch description: {exc}")
            failed += 1
            continue
        for key, floor in (("sigterm_timeout", MIN_SIGTERM_SEC),
                           ("sigkill_timeout", MIN_SIGKILL_SEC)):
            raw = cfg.get(key)
            if raw is None:
                print(f"FAIL {name}: {key} is not set (launch would use its 5 s default)")
                failed += 1
                continue
            try:
                value = float(raw)
            except ValueError:
                print(f"FAIL {name}: {key}={raw!r} is not a number")
                failed += 1
                continue
            if value < floor:
                print(f"FAIL {name}: {key}={value} is below the {floor} s floor")
                failed += 1
            else:
                print(f"PASS {name}: {key}={value} >= {floor}")
                passed += 1

    print("----")
    print(f"passed={passed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
