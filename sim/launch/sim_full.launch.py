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
    """Run PX4 (non-standalone); PX4's own rcS starts Gazebo and spawns the model.

    We do NOT pre-start `gz sim`. PX4 runs WITHOUT PX4_GZ_STANDALONE, so its rcS
    starts Gazebo late in boot via `${PX4_GZ_WORLDS}/${world}.sdf` (PX4_GZ_WORLDS
    points at our sim/worlds dir) and immediately attaches gz_bridge — giving a clean
    lockstep boot. Pre-starting gz ourselves let it free-run ~7-9 s before PX4 attached,
    corrupting IMU/baro timing → EKF2 divergence → phantom altitude runaway. Headless is
    controlled by the HEADLESS env; sensor systems come from PX4_GZ_SERVER_CONFIG. Flight
    uses stock thrust calibration (no SIM_GZ_EC_MIN / MPC_THR overrides) — verified to
    hold altitude. PX4_SIM_SPEED_FACTOR is exported ONLY for speed != 1.0 (see the
    critical note below the env block) — exporting it at all breaks physics at default
    speed.
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
    _world_sdf_path, px4_gz_worlds = _world_sdf(project_root, px4_dir, world)
    gz_paths = _gz_paths(project_root, px4_dir)
    plugins = f"{build}/src/modules/simulation/gz_plugins"
    server_config = f"{px4_dir}/Tools/simulation/gz/server.config"

    # CRITICAL: only export PX4_SIM_SPEED_FACTOR for non-realtime runs. Setting it at
    # all makes PX4's rcS (px4-rc.gzsim) call the gz set_physics service, which sends
    # real_time_factor but leaves max_step_size unset → protobuf defaults it to 0,
    # overwriting the world's 0.004 step. The zero step makes physics integration blow
    # up: after arming the vehicle climbs away uncontrollably (the altitude "runaway").
    # At the default speed=1.0 we simply omit it and the world's own real-time settings
    # apply, giving stable flight. (verified: omitting it → clean 3 m offboard hold.)
    speed_export = f"export PX4_SIM_SPEED_FACTOR={speed}; " if speed != 1.0 else ""

    common_env = (
        "set -e; "
        "export GZ_IP=127.0.0.1; " + speed_export + f'export GZ_SIM_RESOURCE_PATH="{gz_paths}"; '
        f'export PX4_GZ_WORLDS="{px4_gz_worlds}"; '
        f'export PX4_GZ_PLUGINS="{plugins}"; '
        f'export PX4_GZ_SERVER_CONFIG="{server_config}"; '
        f'export GZ_SIM_SERVER_CONFIG_PATH="{server_config}"; '
        f'export GZ_SIM_SYSTEM_PLUGIN_PATH="{plugins}"; '
        f'export LD_LIBRARY_PATH="{plugins}:${{LD_LIBRARY_PATH}}"; '
        # Applied at STARTUP (reliable) rather than via gcs_heartbeat over lossy UDP.
        # Arming/EKF reliability: allow GPS fusion without strict SITL checks, arm w/o GPS.
        "export PX4_PARAM_COM_ARM_WO_GPS=1; "
        "export PX4_PARAM_CBRK_SUPPLY_CHK=894281; "
        "export PX4_PARAM_COM_SPOOLUP_TIME=0.0; "
        "export PX4_PARAM_EKF2_GPS_CHECK=0; "
        "export PX4_PARAM_EKF2_GPS_CTRL=7; "
        # NOTE: do NOT override SIM_GZ_EC_MIN / MPC_THR_HOVER / MPC_THR_MIN here.
        # Stock x500 airframe defaults (EC_MIN=150, MPC_THR_HOVER=0.60) produce stable
        # offboard altitude hold — verified against bare PX4 SITL. The earlier overrides
        # (EC_MIN=0, MPC_THR_HOVER=0.15) came from a debunked "idle≈hover" theory and
        # actually broke flight (no liftoff / runaway). Keep stock thrust calibration.
    )

    print(
        f"[sim_full] Starting PX4 (it starts Gazebo in lockstep) world='{world}' model='{model}'",
        flush=True,
    )
    headless_export = "export HEADLESS=1; " if headless else ""

    # Let PX4's own rcS start Gazebo (stock non-standalone path). PX4 boots its modules
    # first and only then runs `gz sim -r -s ${PX4_GZ_WORLDS}/${world}.sdf` and
    # immediately attaches gz_bridge, so Gazebo free-runs for only a fraction of a second
    # before the EKF is fed sensors — a clean lockstep boot. Pre-starting gz ourselves let
    # it free-run ~7-9 s before PX4 attached, which corrupted IMU/baro timing and made
    # EKF2 diverge (attitude + height), producing a phantom altitude runaway even while
    # disarmed. PX4_GZ_WORLDS (exported above) points at our sim/worlds dir so PX4 picks
    # up our custom world; sensor systems come from PX4_GZ_SERVER_CONFIG. The clock bridge
    # waits for the world to exist (see _clock_bridge) so it cannot make PX4 mis-detect a
    # "running" world during its own startup check.
    cmd = (
        common_env + headless_export + f'cd "{build}"; '
        # Boot from stock airframe defaults every time (determinism): clear any params
        # persisted by a prior run so flight behaviour never drifts between launches.
        # Arming-enabler params come from the PX4_PARAM_* env above; everything else
        # (thrust calibration, EKF tuning) stays at the proven-stable stock defaults.
        "rm -f rootfs/parameters*.bson 2>/dev/null; "
        + f'exec env PX4_GZ_WORLD="{world}" PX4_SIM_MODEL=gz_{model} ./bin/px4'
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
