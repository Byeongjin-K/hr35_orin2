from setuptools import setup, find_packages

package_name = 'experi_analysis_gui'

setup(
    name=package_name,
    version='1.0.0',
    packages=find_packages(exclude=['tests']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='user',
    maintainer_email='user@example.com',
    description='Experiment point-cloud analysis GUI for excavator workspace',
    license='MIT',
    entry_points={
        'console_scripts': [
            'run_experi_analysis = experi_analysis_gui.run_experi_analysis:main',
        ],
    },
)
