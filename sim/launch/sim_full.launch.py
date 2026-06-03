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


def _world_sdf(project_root: Path, px4_dir: str, world: str) -> tuple[str, str]:
    sim_worlds = project_root / "sim" / "worlds"
    px4_worlds = Path(px4_dir) / "Tools" / "simulation" / "gz" / "worlds"
    if (sim_worlds / f"{world}.sdf").exists():
        return str(sim_worlds / f"{world}.sdf"), str(sim_worlds)
    return str(px4_worlds / f"{world}.sdf"), str(px4_worlds)


def _gz_paths(project_root: Path, px4_dir: str) -> str:
    return ":".join(
        filter(
            None,
            [
                str(project_root / "sim" / "worlds"),
                f"{px4_dir}/Tools/simulation/gz/worlds",
                f"{px4_dir}/Tools/simulation/gz/models",
                os.environ.get("GZ_SIM_RESOURCE_PATH", ""),
            ],
        )
    )


def _px4_build(px4_dir: str) -> str:
    return str(Path(px4_dir) / "build" / "px4_sitl_default")



def _pose_setup(context, *args, **kwargs):
    """Gazebo pose/info -> sim_pose_adapter (Harmonic has no per-model pose topic)."""
    world = LaunchConfiguration("world").perform(context)
    model = LaunchConfiguration("model").perform(context)
    return [
        Node(
            package="px4_ros_sim",
            executable="sim_pose_adapter",
            name="sim_pose_adapter",
            output="screen",
            parameters=[
                {
                    "world": world,
                    "model_name": f"{model}_0",
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
    """Start Gazebo then PX4 in non-standalone mode (proven lockstep path).

    Gazebo is started with -r so the world is ready for service calls, but the
    vehicle model (and thus its IMU) is not spawned until PX4's gz_bridge attaches,
    so the brief pre-spawn free-run produces no backward-timestamped sensor data.
    PX4 runs WITHOUT PX4_GZ_STANDALONE so its gz_bridge spawns the model into the
    running world and drives lockstep stepping. This eliminates the backward-IMU-
    timestamp race (standalone PX4 does not drive lockstep) that blocked EKF2 init.
    PX4_SIM_SPEED_FACTOR is applied by PX4's gz_bridge natively after attach.
    """
    world = LaunchConfiguration("world").perform(context)
    model = LaunchConfiguration("model").perform(context)
    headless = LaunchConfiguration("headless").perform(context).lower() == "true"
    speed = float(LaunchConfiguration("speed").perform(context))
    if speed <= 0 or speed > 1.0:
        print(f"[sim_full] WARNING: speed factor {speed} is invalid, capping to 1.0", flush=True)
        speed = 1.0

    project_root = Path(__file__).resolve().parents[2]
    px4_dir = _require_px4_dir()
    build = _px4_build(px4_dir)
    world_sdf, px4_gz_worlds = _world_sdf(project_root, px4_dir, world)
    gz_paths = _gz_paths(project_root, px4_dir)
    plugins = f"{build}/src/modules/simulation/gz_plugins"
    server_config = f"{px4_dir}/Tools/simulation/gz/server.config"

    common_env = (
        "set -e; "
        "export GZ_IP=127.0.0.1; "
        f"export PX4_SIM_SPEED_FACTOR={speed}; "
        f'export GZ_SIM_RESOURCE_PATH="{gz_paths}"; '
        f'export PX4_GZ_WORLDS="{px4_gz_worlds}"; '
        f'export PX4_GZ_PLUGINS="{plugins}"; '
        f'export PX4_GZ_SERVER_CONFIG="{server_config}"; '
        f'export GZ_SIM_SERVER_CONFIG_PATH="{server_config}"; '
        f'export GZ_SIM_SYSTEM_PLUGIN_PATH="{plugins}"; '
        f'export LD_LIBRARY_PATH="{plugins}:${{LD_LIBRARY_PATH}}"; '
    )

    print(f"[sim_full] Starting Gazebo then PX4 (non-standalone) world='{world}' model='{model}'", flush=True)
    headless_export = "export HEADLESS=1; " if headless else ""

    # Start Gazebo running (-r) so it is fully ready for service calls when PX4 starts.
    # No IMU data exists yet (model not spawned), so the brief free-run is harmless.
    # PX4's gz_bridge (non-standalone) spawns the model and immediately drives lockstep.
    # Server-only when headless (-s flag), full GUI otherwise.
    gz_server_flag = "-s " if headless else ""
    gz_start = f'setsid gz sim -r {gz_server_flag}"{world_sdf}"'

    cmd = (
        common_env
        + f"{gz_start} & "
        "GZPID=$!; "
        # Wait up to 90s for the Gazebo scene service to become available.
        f"for _ in $(seq 1 900); do "
        f'  if gz service -i --service "/world/{world}/scene/info" 2>&1 | '
        f'grep -q "Service providers"; then '
        "    break; "
        "  fi; "
        "  sleep 0.1; "
        "done; "
        # Now start PX4 without PX4_GZ_STANDALONE so it uses gz_bridge lockstep.
        f'cd "{build}"; '
        + headless_export
        + f'PX4_GZ_WORLD="{world}" PX4_SIM_MODEL=gz_{model} ./bin/px4; '
        "PX4_EXIT=$?; kill $GZPID 2>/dev/null || true; exit $PX4_EXIT"
    )

    return [ExecuteProcess(cmd=["bash", "-c", cmd], name="gz_px4_stack", output="screen")]


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
            DeclareLaunchArgument("speed", default_value="1.0"),
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
