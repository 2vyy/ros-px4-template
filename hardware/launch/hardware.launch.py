"""Launch ROS 2 core nodes (sim/hardware blind)."""

from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _rosbridge():
    share = Path(get_package_share_directory("rosbridge_server"))
    launch_file = share / "launch" / "rosbridge_websocket_launch.xml"
    return IncludeLaunchDescription(AnyLaunchDescriptionSource(str(launch_file)))


def _microxrce_serial(serial_port: str, baudrate: str) -> ExecuteProcess:
    """Launch MicroXRCEAgent with serial transport for a physical FC."""
    return ExecuteProcess(
        cmd=["MicroXRCEAgent", "serial", "--dev", serial_port, "-b", baudrate],
        output="screen",
        name="microxrce_agent_serial",
    )


def _launch_setup(context, *args, **kwargs):
    config_name = LaunchConfiguration("config").perform(context)
    log_dir = LaunchConfiguration("log_dir").perform(context)
    use_sim_time = LaunchConfiguration("use_sim_time").perform(context).lower() == "true"
    serial_port = LaunchConfiguration("serial_port").perform(context)
    baudrate = LaunchConfiguration("baudrate").perform(context)

    project_root = Path(__file__).resolve().parents[2]
    common_file = project_root / "config" / "params" / "common.yaml"
    params_file = project_root / "config" / "params" / f"{config_name}.yaml"

    overlay_name = LaunchConfiguration("param_overlay").perform(context).strip()
    params_files = [str(common_file), str(params_file)]
    if overlay_name:
        overlay_path = project_root / "config" / "params" / "overlays" / f"{overlay_name}.yaml"
        if not overlay_path.is_file():
            msg = f"param overlay not found: {overlay_path}"
            raise RuntimeError(msg)
        params_files.append(str(overlay_path))

    vehicle_name = LaunchConfiguration("vehicle").perform(context).strip()
    if vehicle_name:
        vehicle_path = project_root / "vehicles" / f"{vehicle_name}.yaml"
        if not vehicle_path.is_file():
            msg = f"vehicle overlay not found: {vehicle_path}"
            raise RuntimeError(msg)
        params_files.append(str(vehicle_path))

    base_params = [*params_files, {"log_dir": log_dir, "use_sim_time": use_sim_time}]

    nodes = [_rosbridge()]
    if config_name != "sim":
        nodes.append(_microxrce_serial(serial_port, baudrate))
    # position_node is the single source of truth: it reads PX4's versioned
    # local-position estimate directly in both sim and hardware (same v1.17 wire format).
    executables = ("offboard_controller", "mission_manager", "position_node")
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

    vision = LaunchConfiguration("vision").perform(context)
    if vision == "aruco":
        nodes.append(
            Node(
                package="ros_px4_template_core",
                executable="aruco_pose_publisher",
                name="aruco_pose_publisher",
                output="screen",
                parameters=base_params,
            )
        )
        # Known-marker relocalization: detection + odom + marker map -> /drone/pose_override.
        nodes.append(
            Node(
                package="ros_px4_template_core",
                executable="marker_localizer",
                name="marker_localizer",
                output="screen",
                parameters=base_params,
            )
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
            DeclareLaunchArgument("param_overlay", default_value=""),
            DeclareLaunchArgument(
                "vehicle",
                default_value="",
                description="Vehicle overlay name (e.g. x500). Must match vehicles/<name>.yaml",
            ),
            DeclareLaunchArgument(
                "vision", default_value="none", description="Vision mode: none, aruco"
            ),
            OpaqueFunction(function=_launch_setup),
        ]
    )
