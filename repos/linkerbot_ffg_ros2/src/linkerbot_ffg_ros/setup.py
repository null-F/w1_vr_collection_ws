from glob import glob
import os

from setuptools import find_packages, setup

package_name = "linkerbot_ffg_ros"

setup(
    name=package_name,
    version="1.0.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools"],
    tests_require=["pytest"],
    zip_safe=True,
    maintainer="yulingxin",
    maintainer_email="1379993737@qq.com",
    description="FFG glove teleoperation for LinkerH and LinkerZ dexterous hands.",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "teleop = linkerbot_ffg_ros.app.teleop_node:main",
            "calibrate = linkerbot_ffg_ros.app.calibrate_glove:main",
        ],
    },
)
