from setuptools import setup

package_name = "ros_px4_template_core"

setup(
    name=package_name,
    version="0.1.0",
    packages=[
        package_name,
        f"{package_name}.lib",
        f"{package_name}.nodes",
    ],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Developer",
    maintainer_email="dev@example.com",
    description="PX4 ROS 2 template core nodes",
    license="BSD-3-Clause",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "offboard_controller = ros_px4_template_core.nodes.offboard_controller:main",
            "px4_pose_adapter = ros_px4_template_core.nodes.px4_pose_adapter:main",
            "mission_manager = ros_px4_template_core.nodes.mission_manager:main",
            "px4_topic_relay = ros_px4_template_core.nodes.px4_topic_relay:main",
        ],
    },
)
