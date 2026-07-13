"""Full simulation: PX4 SITL + Gazebo Harmonic + MicroXRCE + ROS core nodes."""

from __future__ import annotations

import os
import sys as _sys
from pathlib import Path

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
    SetEnvironmentVariable,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

_sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))


def _require_px4_dir() -> str:
    """Return PX4_DIR or raise with a clear, actionable error."""
    value = os.environ.get("PX4_DIR", "").strip()
    if not value:
        raise RuntimeError(
            "PX4_DIR is not set. Create .env with PX4_DIR=/path/to/PX4-Autopilot "
            "(see CLAUDE.md). The launch cannot continue without it."
        )
    if not Path(value).is_dir():
        raise RuntimeError(
            f"PX4_DIR={value!r} does not point to a directory. Check .env / your PX4 checkout."
        )
    return value


def _world_sdf(project_root: Path, px4_dir: str, world: str) -> tuple[str, str, bool]:
    """Resolve a world name to (sdf_path, worlds_dir, is_repo_world).

    is_repo_world is True when the SDF lives in our sim/worlds (PX4 does not ship
    it, so it needs the pre-start-paused boot path in _start_gz_px4.sh). A False
    result keeps the original PX4-starts-gz boot flow byte-identical.
    """
    sim_worlds = project_root / "sim" / "worlds"
    px4_worlds = Path(px4_dir) / "Tools" / "simulation" / "gz" / "worlds"
    if (sim_worlds / f"{world}.sdf").exists():
        return str(sim_worlds / f"{world}.sdf"), str(sim_worlds), True
    return str(px4_worlds / f"{world}.sdf"), str(px4_worlds), False


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


def _pose_setup(context, *args, **kwargs):
    """Single source of truth: position_node reading PX4's SITL estimate."""
    return [
        Node(
            package="ros_px4_template_core",
            executable="position_node",
            name="position_node",
            output="screen",
            parameters=[{"source": "sitl", "frame_id": "map"}],
        ),
    ]


def _clock_bridge(context, *args, **kwargs):
    world = LaunchConfiguration("world").perform(context)
    # Wait until PX4 has started Gazebo and the world clock is being published before
    # bridging it. Subscribing to the gz clock earlier can make PX4's rcS mis-detect a
    # "running" world during its own startup check and skip launching gz.
    wait_and_bridge = (
        f"for _ in $(seq 1 600); do "
        f'  if gz topic -l 2>/dev/null | grep -qx "/world/{world}/clock"; then break; fi; '
        f"  sleep 0.2; "
        f"done; "
        f"exec ros2 run ros_gz_bridge parameter_bridge "
        f'"/world/{world}/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock" '
        f'"/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock"'
    )
    return [
        ExecuteProcess(
            cmd=["bash", "-c", wait_and_bridge],
            name="clock_bridge",
            output="screen",
        ),
    ]


def _gz_px4_stack(context, *args, **kwargs):
    """Run PX4 (non-standalone); see sim/launch/_start_gz_px4.sh for the full boot rationale."""
    world = LaunchConfiguration("world").perform(context)
    model = LaunchConfiguration("model").perform(context)
    headless = LaunchConfiguration("headless").perform(context).lower() == "true"

    project_root = Path(__file__).resolve().parents[2]
    px4_dir = _require_px4_dir()
    build = _px4_build(px4_dir)
    world_sdf_path, px4_gz_worlds, world_is_repo = _world_sdf(project_root, px4_dir, world)
    gz_paths = _gz_paths(project_root, px4_dir)
    plugins = f"{build}/src/modules/simulation/gz_plugins"
    server_config = f"{px4_dir}/Tools/simulation/gz/server.config"

    script = Path(__file__).resolve().parent / "_start_gz_px4.sh"
    return [
        ExecuteProcess(
            cmd=["bash", str(script)],
            additional_env={
                "PX4_BUILD": build,
                "GZ_PATHS": gz_paths,
                "PX4_GZ_WORLDS_DIR": px4_gz_worlds,
                "PX4_GZ_PLUGINS_DIR": plugins,
                "PX4_GZ_SERVER_CFG": server_config,
                "SIM_WORLD": world,
                "SIM_WORLD_SDF": world_sdf_path,
                "WORLD_IS_REPO": "1" if world_is_repo else "",
                "SIM_MODEL": model,
                "HEADLESS_FLAG": "1" if headless else "",
            },
            name="gz_px4_stack",
            output="screen",
        )
    ]


def _vision_bridge(context, *args, **kwargs):
    world = LaunchConfiguration("world").perform(context)
    model = LaunchConfiguration("model").perform(context)
    vision = LaunchConfiguration("vision").perform(context)
    if vision != "aruco":
        return []

    camera_image_gz = f"/world/{world}/model/{model}_0/link/camera_link/sensor/camera/image"
    camera_info_gz = f"/world/{world}/model/{model}_0/link/camera_link/sensor/camera/camera_info"

    wait_and_bridge = (
        f"for _ in $(seq 1 120); do "
        f'if gz topic -i -t "{camera_image_gz}" 2>/dev/null | grep -qi "Publisher"; then break; fi; '
        f"sleep 0.5; "
        f"done; "
        f"exec ros2 run ros_gz_bridge parameter_bridge "
        f'"{camera_image_gz}@sensor_msgs/msg/Image[gz.msgs.Image" '
        f'"{camera_info_gz}@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo" '
        f"--ros-args "
        f"-r {camera_image_gz}:=/camera/image_raw "
        f"-r {camera_info_gz}:=/camera/camera_info"
    )
    return [
        ExecuteProcess(
            cmd=["bash", "-c", wait_and_bridge],
            name="gz_camera_bridge",
            output="screen",
        )
    ]


def generate_launch_description() -> LaunchDescription:
    project_root = Path(__file__).resolve().parents[2]
    px4_dir = _require_px4_dir()
    gz_paths = _gz_paths(project_root, px4_dir)

    # sim stop kills any prior agent; pkill here covers orphaned agents after manual kills.
    print("[sim_full] Starting MicroXRCEAgent", flush=True)
    agent_action = [
        ExecuteProcess(
            cmd=[
                "bash",
                "-c",
                "pkill -x MicroXRCEAgent 2>/dev/null || true; "
                "sleep 0.2; "
                "exec setsid MicroXRCEAgent udp4 -p 8888",
            ],
            name="micro_xrce_agent",
            output="screen",
        )
    ]

    hardware_launch = PythonLaunchDescriptionSource(
        str(project_root / "hardware" / "launch" / "hardware.launch.py")
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("world", default_value="default"),
            DeclareLaunchArgument("model", default_value="x500"),
            DeclareLaunchArgument("log_dir", default_value=str(project_root / "logs")),
            DeclareLaunchArgument("vision", default_value="none"),
            DeclareLaunchArgument("headless", default_value="false"),
            DeclareLaunchArgument("param_overlay", default_value=""),
            SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
            SetEnvironmentVariable(name="GZ_SIM_RESOURCE_PATH", value=gz_paths),
            *agent_action,
            OpaqueFunction(function=_gz_px4_stack),
            ExecuteProcess(
                # System python3 lacks pymavlink; project deps live in the uv venv.
                cmd=[
                    "bash",
                    "-lc",
                    f"cd '{project_root}' && exec uv run python tools/gcs_heartbeat.py",
                ],
                name="gcs_heartbeat",
                output="screen",
            ),
            OpaqueFunction(function=_clock_bridge),
            OpaqueFunction(function=_pose_setup),
            OpaqueFunction(function=_vision_bridge),
            IncludeLaunchDescription(
                hardware_launch,
                launch_arguments={
                    "use_sim_time": "true",
                    "config": "sim",
                    "log_dir": LaunchConfiguration("log_dir"),
                    "param_overlay": LaunchConfiguration("param_overlay"),
                    "vision": LaunchConfiguration("vision"),
                }.items(),
            ),
        ]
    )
