from setuptools import setup, find_packages

setup(
    name='ros2_bag_gui',
    version='0.1.0',
    description='ROS2 Bag GUI for recording and exporting sensor data',
    package_dir={'': 'src'},
    packages=find_packages(where='src'),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/ros2_bag_gui']),
        ('share/ros2_bag_gui', ['package.xml']),
    ],
    install_requires=[
        'setuptools',
    ],
    entry_points={
        'console_scripts': [
            'ros2_bag_gui = ros2_bag_gui.__main__:main',
        ],
    },
)
