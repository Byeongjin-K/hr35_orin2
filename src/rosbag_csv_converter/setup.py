from setuptools import setup, find_packages

package_name = 'rosbag_csv_converter'

setup(
    name=package_name,
    version='1.0.0',
    packages=find_packages(exclude=['tests']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/converter.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='user',
    maintainer_email='user@example.com',
    description='ROS2 Rosbag to CSV Converter with PyQt6 GUI',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'converter = rosbag_csv_converter.main:main',
        ],
    },
)
