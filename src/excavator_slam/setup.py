from glob import glob

from setuptools import setup

package_name = "excavator_slam"

setup(
    name=package_name,
    version="0.0.1",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/config/glim", glob("config/glim/*.json")),
        ("share/" + package_name + "/scripts", glob("scripts/*.sh")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Byeongjin Kim",
    maintainer_email="kimbj0607@gmail.com",
    description="LiDAR-inertial (+GNSS) SLAM integration for the HR35 excavator.",
    license="Proprietary",
    entry_points={"console_scripts": []},
)
