from glob import glob

from setuptools import setup

package_name = "ros_px4_template_core"

setup(
    name=package_name,
    version="0.1.0",
    packages=[
        package_name,
        f"{package_name}.lib",
        f"{package_name}.lib.mission",
        f"{package_name}.nodes",
    ],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", ["../../config/markers.yaml"]),
        (f"share/{package_name}/config/marker_maps", glob("../../config/marker_maps/*.yaml")),
        (f"share/{package_name}/config/missions", glob("../../config/missions/*.yaml")),
        (f"share/{package_name}/config/params", glob("../../config/params/*.yaml")),
        (
            f"share/{package_name}/config/params/overlays",
            glob("../../config/params/overlays/*.yaml"),
        ),
        (f"share/{package_name}/config/paths", glob("../../config/paths/*.yaml")),
        (f"share/{package_name}/config/rviz", glob("../../config/rviz/*.rviz")),
    ],
    install_requires=[
        "setuptools",
        "numpy>=1.26,<2.0",
        "pyyaml>=6.0",
        "opencv-python-headless>=4.7.0",
    ],
    zip_safe=True,
    maintainer="Developer",
    maintainer_email="dev@example.com",
    description="PX4 ROS 2 template core nodes",
    license="BSD-3-Clause",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "offboard_controller = ros_px4_template_core.nodes.offboard_controller:main",
            "position_node = ros_px4_template_core.nodes.position_node:main",
            "mission_manager = ros_px4_template_core.nodes.mission_manager:main",
            "aruco_pose_publisher = ros_px4_template_core.nodes.aruco_pose_publisher:main",
            "marker_localizer = ros_px4_template_core.nodes.marker_localizer:main",
        ],
    },
)
