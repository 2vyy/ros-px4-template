"""Full simulation: PX4 SITL + Gazebo Harmonic + MicroXRCE + ROS core nodes."""

from __future__ import annotations

import os
from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
    SetEnvironmentVariable,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _world_sdf(project_root: Path, px4_dir: str, world: str) -> tuple[str, str]:
    sim_worlds = project_root / "sim" / "worlds"
    px4_worlds = Path(px4_dir) / "Tools" / "simulation" / "gz" / "worlds"
    if world == "default" or not (sim_worlds / f"{world}.sdf").exists():
        return str(px4_worlds / f"{world}.sdf"), str(px4_worlds)
    return str(sim_worlds / f"{world}.sdf"), str(sim_worlds)


def _gz_paths(project_root: Path, px4_dir: str) -> str:
    return ":".join(
        filter(
            None,
            [
                str(project_root / "sim" / "worlds"),
                str(project_root / "sim" / "models"),
                f"{px4_dir}/Tools/simulation/gz/worlds",
                f"{px4_dir}/Tools/simulation/gz/models",
                os.environ.get("GZ_SIM_RESOURCE_PATH", ""),
            ],
        )
    )


def _px4_build(px4_dir: str) -> str:
    return str(Path(px4_dir) / "build" / "px4_sitl_default")


def _vision_setup(context, *args, **kwargs):
    world = LaunchConfiguration("world").perform(context)
    model = LaunchConfiguration("model").perform(context)
    enable = LaunchConfiguration("enable_vision").perform(context).lower() == "true"
    if not enable:
        return []

    camera_topic = f"/world/{world}/model/{model}_0/link/camera_link/sensor/camera/image"
    return [
        ExecuteProcess(
            cmd=[
                "ros2",
                "run",
                "ros_gz_bridge",
                "parameter_bridge",
                f"{camera_topic}@sensor_msgs/msg/Image[gz.msgs.Image",
            ],
            name="camera_bridge",
            output="screen",
        ),
        Node(
            package="px4_ros_sim",
            executable="aruco_detector",
            name="aruco_detector",
            output="screen",
            parameters=[
                {
                    "camera_topic": camera_topic,
                    "marker_id": 0,
                    "marker_world_x": 8.0,
                    "marker_world_y": 0.0,
                    "marker_world_z": 0.0,
                    "frame_id": "map",
                }
            ],
        ),
    ]


def _clock_bridge(context, *args, **kwargs):
    world = LaunchConfiguration("world").perform(context)
    return [
        ExecuteProcess(
            cmd=[
                "ros2",
                "run",
                "ros_gz_bridge",
                "parameter_bridge",
                f"/world/{world}/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
                "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
            ],
            name="clock_bridge",
            output="screen",
        ),
    ]


def _gz_px4_stack(context, *args, **kwargs):
    """Start Gazebo server, wait for scene/info, then PX4 in standalone mode."""
    world = LaunchConfiguration("world").perform(context)
    model = LaunchConfiguration("model").perform(context)
    headless = LaunchConfiguration("headless").perform(context).lower() == "true"

    project_root = Path(__file__).resolve().parents[2]
    px4_dir = os.environ.get("PX4_DIR", "/home/ivy/robotics/PX4-Autopilot")
    build = _px4_build(px4_dir)
    world_sdf, px4_gz_worlds = _world_sdf(project_root, px4_dir, world)
    gz_paths = _gz_paths(project_root, px4_dir)
    plugins = f"{build}/src/modules/simulation/gz_plugins"
    server_config = f"{px4_dir}/src/modules/simulation/gz_bridge/server.config"
    headless_export = "export HEADLESS=1; " if headless else ""

    cmd = (
        "set -e; "
        "export GZ_IP=127.0.0.1; "
        f'export GZ_SIM_RESOURCE_PATH="{gz_paths}"; '
        f'export PX4_GZ_WORLDS="{px4_gz_worlds}"; '
        f'export PX4_GZ_MODELS="{px4_dir}/Tools/simulation/gz/models"; '
        f'export PX4_GZ_PLUGINS="{plugins}"; '
        f'export PX4_GZ_SERVER_CONFIG="{server_config}"; '
        f'export GZ_SIM_SYSTEM_PLUGIN_PATH="{plugins}"; '
        f'export GZ_SIM_SERVER_CONFIG_PATH="{server_config}"; '
        f'export LD_LIBRARY_PATH="{plugins}:${{LD_LIBRARY_PATH}}"; '
        f'gz sim -r -s "{world_sdf}" & '
        "GZPID=$!; "
        f"for _ in $(seq 1 90); do "
        f'  if gz service -i --service "/world/{world}/scene/info" 2>&1 | '
        f'grep -q "Service providers"; then '
        "    break; "
        "  fi; "
        "  sleep 1; "
        "done; "
        f"{headless_export}"
        "export PX4_GZ_STANDALONE=1; "
        f'cd "{build}"; '
        f'PX4_GZ_WORLD="{world}" PX4_SIM_MODEL=gz_{model} exec ./bin/px4; '
        "PX4_EXIT=$?; kill $GZPID 2>/dev/null || true; exit $PX4_EXIT"
    )

    return [ExecuteProcess(cmd=["bash", "-c", cmd], name="gz_px4_stack", output="screen")]


def generate_launch_description() -> LaunchDescription:
    project_root = Path(__file__).resolve().parents[2]
    px4_dir = os.environ.get("PX4_DIR", "/home/ivy/robotics/PX4-Autopilot")
    gz_paths = _gz_paths(project_root, px4_dir)

    hardware_launch = PythonLaunchDescriptionSource(
        str(project_root / "hardware" / "launch" / "hardware.launch.py")
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("world", default_value="default"),
            DeclareLaunchArgument("model", default_value="x500"),
            DeclareLaunchArgument("log_dir", default_value=str(project_root / "logs")),
            DeclareLaunchArgument("enable_vision", default_value="false"),
            DeclareLaunchArgument("headless", default_value="false"),
            SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
            SetEnvironmentVariable(name="GZ_SIM_RESOURCE_PATH", value=gz_paths),
            ExecuteProcess(
                cmd=["MicroXRCEAgent", "udp4", "-p", "8888"],
                name="micro_xrce_agent",
                output="screen",
            ),
            OpaqueFunction(function=_gz_px4_stack),
            TimerAction(
                period=12.0,
                actions=[
                    ExecuteProcess(
                        cmd=["python3", str(project_root / "tools" / "gcs_heartbeat.py")],
                        name="gcs_heartbeat",
                        output="screen",
                    )
                ],
            ),
            TimerAction(period=8.0, actions=[OpaqueFunction(function=_clock_bridge)]),
            OpaqueFunction(function=_vision_setup),
            IncludeLaunchDescription(
                hardware_launch,
                launch_arguments={
                    "use_sim_time": "true",
                    "config": "sim",
                    "log_dir": LaunchConfiguration("log_dir"),
                }.items(),
            ),
        ]
    )
