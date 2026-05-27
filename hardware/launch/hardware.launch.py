"""Launch ROS 2 core nodes (sim/hardware blind)."""

from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _rosbridge():
    share = Path(get_package_share_directory("rosbridge_server"))
    launch_file = share / "launch" / "rosbridge_websocket_launch.xml"
    return IncludeLaunchDescription(AnyLaunchDescriptionSource(str(launch_file)))


def _launch_setup(context, *args, **kwargs):
    config_name = LaunchConfiguration("config").perform(context)
    log_dir = LaunchConfiguration("log_dir").perform(context)
    use_sim_time = LaunchConfiguration("use_sim_time").perform(context).lower() == "true"

    project_root = Path(__file__).resolve().parents[2]
    common_file = project_root / "config" / "params" / "common.yaml"
    params_file = project_root / "config" / "params" / f"{config_name}.yaml"

    base_params = [
        str(common_file),
        str(params_file),
        {"log_dir": log_dir, "use_sim_time": use_sim_time},
    ]

    nodes = [_rosbridge()]
    executables = ("px4_topic_relay", "offboard_controller", "mission_manager", "state_estimator")
    nodes.extend(
        [
            Node(
                package="ros_px4_template_core",
                executable=exe,
                name=exe,
                output="screen",
                parameters=base_params,
            )
            for exe in executables
        ]
    )
    return nodes


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("config", default_value="common"),
            DeclareLaunchArgument("log_dir", default_value="./logs"),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("serial_port", default_value="/dev/ttyUSB0"),
            DeclareLaunchArgument("baudrate", default_value="921600"),
            OpaqueFunction(function=_launch_setup),
        ]
    )
