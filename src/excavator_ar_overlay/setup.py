from glob import glob
import os

from setuptools import find_packages, setup

package_name = "excavator_ar_overlay"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (os.path.join("share", package_name), ["package.xml"]),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "scripts"), glob("scripts/*.sh")),
        (os.path.join("share", package_name, "docs"), glob("docs/*.md")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Byeongjin Kim",
    maintainer_email="kimbj0607@gmail.com",
    description="AR overlay of LiDAR points and AI dig plan on the ZED X boom camera.",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "lidar_projection_node = excavator_ar_overlay.lidar_projection_node:main",
        ],
    },
)
