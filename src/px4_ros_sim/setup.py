from setuptools import setup

package_name = "px4_ros_sim"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Developer",
    maintainer_email="dev@example.com",
    description="PX4 ROS sim-only nodes",
    license="BSD-3-Clause",
    entry_points={
        "console_scripts": [
            "aruco_detector = px4_ros_sim.aruco_detector:main",
        ],
    },
)
