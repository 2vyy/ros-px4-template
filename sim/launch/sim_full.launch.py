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
from gz_lifecycle import gazebo_matches, reset_world


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


def _xrce_agent_running() -> bool:
    """Return True if MicroXRCEAgent is already running (pgrep check)."""
    import subprocess as _subprocess

    try:
        result = _subprocess.run(
            ["pgrep", "-x", "MicroXRCEAgent"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _set_gz_physics(world: str, speed: float) -> None:
    """Set Gazebo physics real-time factor. No-op at 1.0. Non-fatal on failure."""
    if speed == 1.0:
        return
    import subprocess as _subprocess
    update_rate = int(speed * 250)
    try:
        _subprocess.run(
            [
                "gz", "service", "-s", f"/world/{world}/set_physics",
                "--reqtype", "gz.msgs.Physics",
                "--reptype", "gz.msgs.Boolean",
                "--timeout", "3000",
                "--req",
                f"real_time_factor: {speed}, real_time_update_rate: {update_rate}, max_step_size: 0.004",
            ],
            capture_output=True,
            timeout=5,
        )
        print(f"[sim_full] Physics speed set to {speed}×", flush=True)
    except Exception:
        print(f"[sim_full] WARNING: failed to set physics speed={speed}; running at default", flush=True)


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
    """Start PX4 in standalone mode. Starts Gazebo first if not already warm."""
    import time as _time

    world = LaunchConfiguration("world").perform(context)
    model = LaunchConfiguration("model").perform(context)
    headless = LaunchConfiguration("headless").perform(context).lower() == "true"
    speed = float(LaunchConfiguration("speed").perform(context))

    project_root = Path(__file__).resolve().parents[2]
    px4_dir = _require_px4_dir()
    build = _px4_build(px4_dir)
    world_sdf, px4_gz_worlds = _world_sdf(project_root, px4_dir, world)
    gz_paths = _gz_paths(project_root, px4_dir)
    plugins = f"{build}/src/modules/simulation/gz_plugins"
    server_config = f"{px4_dir}/src/modules/simulation/gz_bridge/server.config"

    _session_key = (
        _time.time_ns() // 1_000_000
    ) % 65534 + 1  # 1-65534, ms-resolution (65535 is XRCE broadcast key)

    common_env = (
        "set -e; "
        "export GZ_IP=127.0.0.1; "
        "export PX4_PARAM_COM_ARM_WO_GPS=1; "
        "export PX4_PARAM_CBRK_SUPPLY_CHK=894281; "
        "export PX4_PARAM_COM_SPOOLUP_TIME=0.0; "
        "export PX4_PARAM_EKF2_GPS_CHECK=0; "
        "export PX4_PARAM_EKF2_GPS_CTRL=7; "
        f"export PX4_PARAM_UXRCE_DDS_KEY={_session_key}; "
        f'export GZ_SIM_RESOURCE_PATH="{gz_paths}"; '
        f'export PX4_GZ_WORLDS="{px4_gz_worlds}"; '
        f'export PX4_GZ_MODELS="{px4_dir}/Tools/simulation/gz/models"; '
        f'export PX4_GZ_PLUGINS="{plugins}"; '
        f'export PX4_GZ_SERVER_CONFIG="{server_config}"; '
        f'export GZ_SIM_SYSTEM_PLUGIN_PATH="{plugins}"; '
        f'export GZ_SIM_SERVER_CONFIG_PATH="{server_config}"; '
        f'export LD_LIBRARY_PATH="{plugins}:${{LD_LIBRARY_PATH}}"; '
    )

    px4_launch = (
        "export PX4_GZ_STANDALONE=1; "
        f'cd "{build}"; '
        f'PX4_GZ_WORLD="{world}" PX4_SIM_MODEL=gz_{model} exec ./bin/px4'
    )

    if gazebo_matches(world):
        _reset_flag = Path("/tmp/gz_world_reset")
        already_reset = _reset_flag.exists() and _reset_flag.read_text().strip() == world
        if already_reset:
            _reset_flag.unlink(missing_ok=True)
            print(
                f"[sim_full] World '{world}' already reset during stop — skipping",
                flush=True,
            )
        else:
            print(
                f"[sim_full] Gazebo warm for world='{world}' — resetting world state",
                flush=True,
            )
            reset_ok = reset_world(world)
            if not reset_ok:
                print(
                    "[sim_full] WARNING: world reset failed; PX4 connecting to unreset state",
                    flush=True,
                )
        # The world reset deletes the dynamically spawned model, so we let PX4 spawn a new one.
        _set_gz_physics(world, speed)
        px4_warm_launch = (
            "export PX4_GZ_STANDALONE=1; "
            f'cd "{build}"; '
            f'PX4_GZ_WORLD="{world}" PX4_SIM_MODEL=gz_{model} exec ./bin/px4'
        )
        cmd = common_env + px4_warm_launch
    else:
        print(f"[sim_full] Gazebo cold — starting gz sim for world='{world}'", flush=True)
        headless_export = "export HEADLESS=1; " if headless else ""
        world_file = str(project_root / "logs" / "gz_world.txt")
        cmd = (
            common_env + f'setsid gz sim -r -s "{world_sdf}" & '
            "GZPID=$!; "
            f"for _ in $(seq 1 900); do "
            f'  if gz service -i --service "/world/{world}/scene/info" 2>&1 | '
            f'grep -q "Service providers"; then '
            "    break; "
            "  fi; "
            "  sleep 0.1; "
            "done; "
            f'echo "{world}" > "{world_file}"; '
            f'gz service -s /world/{world}/set_physics --reqtype gz.msgs.Physics --reptype gz.msgs.Boolean --timeout 3000 --req "real_time_factor: {speed}, real_time_update_rate: {int(speed * 250)}, max_step_size: 0.004" 2>/dev/null || true; '
            f"{headless_export}" + px4_launch + "; "
            "PX4_EXIT=$?; kill $GZPID 2>/dev/null || true; exit $PX4_EXIT"
        )

    return [ExecuteProcess(cmd=["bash", "-c", cmd], name="gz_px4_stack", output="screen")]


def generate_launch_description() -> LaunchDescription:
    project_root = Path(__file__).resolve().parents[2]
    px4_dir = _require_px4_dir()
    gz_paths = _gz_paths(project_root, px4_dir)

    agent_alive = _xrce_agent_running()
    if agent_alive:
        print("[sim_full] MicroXRCEAgent already running — reusing existing agent", flush=True)
    else:
        print("[sim_full] MicroXRCEAgent not running — starting fresh agent", flush=True)

    agent_action = (
        []
        if agent_alive
        else [
            ExecuteProcess(
                # setsid detaches agent from the launch process group so it survives sim stop
                cmd=["setsid", "MicroXRCEAgent", "udp4", "-p", "8888"],
                name="micro_xrce_agent",
                output="screen",
            )
        ]
    )

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
            DeclareLaunchArgument("speed", default_value="1.0"),
            SetEnvironmentVariable(name="GZ_IP", value="127.0.0.1"),
            SetEnvironmentVariable(name="GZ_SIM_RESOURCE_PATH", value=gz_paths),
            *agent_action,
            OpaqueFunction(function=_gz_px4_stack),
            ExecuteProcess(
                cmd=["python3", str(project_root / "tools" / "gcs_heartbeat.py")],
                name="gcs_heartbeat",
                output="screen",
            ),
            OpaqueFunction(function=_clock_bridge),
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
