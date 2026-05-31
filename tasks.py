#!/usr/bin/env uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer>=0.12.3",
#     "rich>=13.7.0",
#     "tomli-w>=1.0.0",
#     "tomli>=2.0.0",
#     "pyyaml>=6.0",
#     "lark>=1.1.9",
# ]
# ///

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(help="Hypermodern ROS 2 + PX4 Task Runner")
console = Console()
ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
_GZ_RESET_FLAG = Path("/tmp/gz_world_reset")


def _load_dotenv() -> None:
    dotenv_path = ROOT / ".env"
    if dotenv_path.is_file():
        for line in dotenv_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key not in os.environ:
                    os.environ[key] = val


_load_dotenv()


def _source_workspace_env() -> None:
    ws_setup = ROOT / "install" / "setup.bash"
    if ws_setup.exists():
        try:
            cmd = f"source {ws_setup} && python3 -c 'import os, json; print(json.dumps(dict(os.environ)))'"
            res = subprocess.run(
                ["bash", "-c", cmd], capture_output=True, text=True, check=True, cwd=str(ROOT)
            )
            new_env = json.loads(res.stdout.strip())
            for k, v in new_env.items():
                os.environ[k] = v
        except Exception as e:
            console.print(f"[yellow]Warning: failed to source workspace env: {e}[/yellow]")


_source_workspace_env()


def _get_clean_env() -> dict[str, str]:
    """Strip uv/venv from PATH so ROS nodes using ``/usr/bin/env python3`` get system Python."""
    env = dict(os.environ)
    venv = env.pop("VIRTUAL_ENV", None)
    path_dirs = env.get("PATH", "").split(os.pathsep)
    cleaned_dirs: list[str] = []
    for d in path_dirs:
        if not d:
            continue
        if ".cache/uv" in d or ".venv" in d:
            continue
        if venv and (d == venv or d.startswith(f"{venv}/")):
            continue
        cleaned_dirs.append(d)
    env["PATH"] = os.pathsep.join(cleaned_dirs)
    return env


def _ros_setup_path() -> str:
    return os.environ.get("ROS_SETUP", "/opt/ros/jazzy/setup.bash")


def _ros_launch_env(**extra: str) -> dict[str, str]:
    """Env for ``ros2 launch`` children.

    Drop inherited ``PYTHONPATH`` so the launch shell can re-source ROS + workspace.
    Prepend system + ROS ``bin`` dirs so ``#!/usr/bin/env python3`` (rosbridge) is not
    the uv project venv.
    """
    env = _get_clean_env()
    env.pop("PYTHONPATH", None)
    ros_setup = _ros_setup_path()
    ros_bin = str(Path(ros_setup).resolve().parent / "bin")
    system_bins = ("/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin")
    tail = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    ordered: list[str] = []
    for p in (*system_bins, ros_bin, *tail):
        if p and p not in ordered:
            ordered.append(p)
    env["PATH"] = os.pathsep.join(ordered)
    env.update(extra)
    return env


def _ros2_launch_bash_argv(launch_args: list[str], *, cwd: Path = ROOT) -> list[str]:
    """``bash -lc`` that sources ROS + workspace, then ``exec ros2 launch ...``."""
    ros_setup = _ros_setup_path()
    ws_setup = cwd / "install" / "setup.bash"
    sources = [f"source {shlex.quote(ros_setup)}"]
    if ws_setup.exists():
        sources.append(f"source {shlex.quote(str(ws_setup))}")
    inner = " && ".join(
        [
            *sources,
            f"cd {shlex.quote(str(cwd))}",
            "exec ros2 launch " + " ".join(shlex.quote(a) for a in launch_args),
        ]
    )
    return ["bash", "-lc", inner]


# Ensure tools/ is on path to import sub-apps
sys.path.append(str(ROOT / "tools"))
from capabilities import app as cap_app
from log_query import app as log_app

# Register sub-apps
app.add_typer(log_app, name="log", help="Query, merge, tail, or view logs/status/topics.")
app.add_typer(cap_app, name="cap", help="Manage verified capabilities registry.")


def _build_workspace() -> None:
    console.print("[cyan]Building workspace (colcon build)...[/cyan]")
    try:
        subprocess.run(
            [
                "colcon",
                "build",
                "--symlink-install",
                "--cmake-args",
                "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
                "--event-handlers",
                "console_direct+",
            ],
            check=True,
            cwd=str(ROOT),
            env=_get_clean_env(),
        )
        console.print("[green]Workspace built successfully.[/green]")
        _source_workspace_env()
    except subprocess.CalledProcessError:
        console.print("[bold red]Build failed.[/bold red]")
        raise typer.Exit(1) from None


@app.command()
def setup():
    """One-time workspace setup (auto-detects PX4 version, runs uv sync, rosdep)."""
    console.print("[cyan]=== Setting up workspace ===[/cyan]")

    px4_dir = os.environ.get("PX4_DIR", "").strip()
    px4_msgs_branch = "release/1.17"  # default fallback

    if px4_dir and Path(px4_dir).is_dir():
        try:
            res = subprocess.run(
                ["git", "-C", px4_dir, "describe", "--tags", "--always"],
                capture_output=True,
                text=True,
                check=True,
            )
            version_str = res.stdout.strip()
            m = re.match(r"v?(\d+\.\d+)", version_str)
            if m:
                px4_msgs_branch = f"release/{m.group(1)}"
                console.print(
                    f"Auto-detected PX4 version '{version_str}'. Using branch '{px4_msgs_branch}' for px4_msgs."
                )
            else:
                console.print(
                    f"PX4 version '{version_str}' could not be parsed. Defaulting to '{px4_msgs_branch}'."
                )
        except Exception as e:
            console.print(
                f"[yellow]Could not determine PX4 version from PX4_DIR: {e}. Defaulting to '{px4_msgs_branch}'.[/yellow]"
            )
    else:
        console.print(
            f"[yellow]PX4_DIR is not set or not a directory. Defaulting to branch '{px4_msgs_branch}'.[/yellow]"
        )

    px4_msgs_dir = ROOT / "src" / "px4_msgs"
    if not px4_msgs_dir.exists():
        console.print(f"Cloning px4_msgs ({px4_msgs_branch}) into src/px4_msgs...")
        try:
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--branch",
                    px4_msgs_branch,
                    "--depth",
                    "1",
                    "https://github.com/PX4/px4_msgs.git",
                    "src/px4_msgs",
                ],
                check=True,
                cwd=str(ROOT),
            )
        except subprocess.CalledProcessError:
            console.print("[bold red]Failed to clone px4_msgs.[/bold red]")
            raise typer.Exit(1) from None
    else:
        console.print("src/px4_msgs already exists, skipping clone.")

    console.print("Syncing Python dev tools with uv (not pip)...")
    try:
        subprocess.run(["uv", "sync", "--group", "dev"], check=True, cwd=str(ROOT))
    except subprocess.CalledProcessError:
        console.print("[bold red]Failed to sync Python dependencies.[/bold red]")
        raise typer.Exit(1) from None

    console.print(
        "[cyan]ROS bridge (port 9090): install via apt, e.g. "
        "`sudo apt install ros-jazzy-rosbridge-suite` inside your ROS environment.[/cyan]"
    )

    console.print("Installing rosdep dependencies...")
    try:
        subprocess.run(
            ["rosdep", "install", "--from-paths", "src", "--ignore-src", "-r", "-y"],
            check=True,
            cwd=str(ROOT),
        )
    except subprocess.CalledProcessError:
        console.print(
            "[yellow]rosdep install completed with warnings/failures (continuing).[/yellow]"
        )

    _build_workspace()
    console.print("[bold green]=== Setup complete! Run: just sim ===[/bold green]")


@app.command()
def build():
    """Compile the workspace using colcon build."""
    _build_workspace()


@app.command()
def clean():
    """Wipe build artifacts, build logs, and per-run logs."""
    console.print("[cyan]Cleaning build outputs and log files...[/cyan]")
    for folder in ("build", "install", "log"):
        p = ROOT / folder
        if p.exists():
            shutil.rmtree(p)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for f in LOG_DIR.glob("*"):
        if f.name != ".gitkeep":
            if f.is_file() or f.is_symlink():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)
    console.print("[green]Cleanup complete.[/green]")


@app.command()
def check():
    """Format, lint-fix, typecheck, compile, and run unit tests."""
    console.print("[cyan]=== Running Code Quality Gateway ===[/cyan]")

    ruff_paths = ["src/core", "src/px4_ros_sim", "tests", "tools", "sim", "hardware"]
    ruff_paths_str = [str(ROOT / p) for p in ruff_paths]

    console.print("Running ruff format and lint auto-fixes...")
    subprocess.run(["uv", "run", "ruff", "check", "--fix"] + ruff_paths_str, cwd=str(ROOT))
    subprocess.run(["uv", "run", "ruff", "format"] + ruff_paths_str, cwd=str(ROOT))

    console.print("Checking branch invariants...")
    subprocess.run(["uv", "run", "python", "tools/check_invariants.py"], cwd=str(ROOT))

    console.print("Running static typecheck...")
    subprocess.run(
        [
            "uv",
            "run",
            "ty",
            "check",
            "src/core/ros_px4_template_core/lib",
            "tests/unit",
            "tools/",
            "--exclude",
            "tools/gcs_heartbeat.py",
        ],
        cwd=str(ROOT),
    )

    _build_workspace()

    console.print("Running pytest unit tests...")
    try:
        subprocess.run(["uv", "run", "pytest", "tests/unit/", "-v"], check=True, cwd=str(ROOT))
        console.print("[bold green]=== All checks passed! ===[/bold green]")
    except subprocess.CalledProcessError:
        console.print("[bold red]Unit tests failed.[/bold red]")
        raise typer.Exit(1) from None


def _preemptive_world_reset(world: str) -> None:
    """Reset Gazebo world now (during stop) so the next launch can skip it."""
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from gz_lifecycle import gazebo_matches, reset_world  # type: ignore[import]

        if gazebo_matches(world):
            if reset_world(world):
                _GZ_RESET_FLAG.write_text(world)
                console.print(f"[green]World '{world}' reset preemptively.[/green]")
    except Exception:
        pass  # non-fatal — launch will reset on its own if flag absent


def _sim_launch_overlay_args(mode: str) -> list[str]:
    if mode == "inspect":
        return ["param_overlay:=inspect"]
    return []


@app.command()
def sim(
    mode: str = typer.Argument(
        "gui", help="Mode: gui, headless, bg, px4, edit, hardware, stop, kill"
    ),
    world: str = typer.Option("default", "--world", help="World file name"),
    model: str = typer.Option("x500", "--model", help="Airframe model"),
    vision: str = typer.Option("false", "--vision", help="Enable vision/aruco detection"),
    port: str = typer.Option("/dev/ttyUSB0", "--port", help="Serial port for hardware"),
    baud: int = typer.Option(921600, "--baud", help="Baudrate for hardware serial"),
    vehicle: str = typer.Option("", "--vehicle", help="Vehicle overlay name for hardware mode (e.g. x500)"),
    build: bool = typer.Option(True, "--build/--no-build", help="Build workspace before running"),
    speed: float = typer.Option(1.0, "--speed", help="Gazebo physics speed multiplier (headless/bg only). 1.0 = real time."),
    bag: bool = typer.Option(True, "--bag/--no-bag", help="Auto-record rosbag (bg mode only)"),
):
    """Simulation & hardware runner. Modes: gui, headless, bg, px4, edit, hardware, stop, kill.

    stop: kill PX4/ROS/XRCE but keep Gazebo warm for fast subsequent launches.
    kill: full teardown including Gazebo (use before changing worlds or for clean reboot).
    """
    if speed <= 0 or speed > 20:
        console.print(f"[bold red]--speed must be between 0 (exclusive) and 20 (inclusive), got {speed}[/bold red]")
        raise typer.Exit(1) from None
    if mode in ("gui", "hardware", "inspect") and speed != 1.0:
        console.print(f"[yellow]--speed {speed} ignored for '{mode}' mode (only applies to headless/bg)[/yellow]")
        speed = 1.0

    if mode == "stop":
        console.print("[cyan]Stopping sim (Gazebo stays warm for next launch)...[/cyan]")
        subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))
        _preemptive_world_reset(world)
        return

    if mode == "kill":
        console.print(
            "[cyan]Full teardown — killing Gazebo too (next launch will be cold)...[/cyan]"
        )
        subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py", "--full"], cwd=str(ROOT))
        return

    if mode == "hardware":
        res = subprocess.run(
            ["uv", "run", "python", "tools/preflight.py", "--mode=hw"],
            cwd=str(ROOT),
        )
        if res.returncode != 0:
            console.print("[bold red]Preflight check failed. Aborting hardware launch.[/bold red]")
            raise typer.Exit(1) from None
        if vehicle:
            vehicle_path = ROOT / "vehicles" / f"{vehicle}.yaml"
            if not vehicle_path.is_file():
                console.print(f"[bold red]Vehicle overlay not found: {vehicle_path}[/bold red]")
                raise typer.Exit(1) from None
        if build:
            _build_workspace()
        console.print(f"[cyan]Connecting to hardware on port {port} at {baud} baud...[/cyan]")
        try:
            subprocess.run(
                [
                    "ros2",
                    "launch",
                    str(ROOT / "hardware" / "launch" / "hardware.launch.py"),
                    f"serial_port:={port}",
                    f"baudrate:={baud}",
                    "use_sim_time:=false",
                    "config:=hardware",
                    f"log_dir:={LOG_DIR}",
                    f"vehicle:={vehicle}",
                ],
                check=True,
                cwd=str(ROOT),
            )
        except KeyboardInterrupt:
            console.print("[yellow]Connection stopped by user.[/yellow]")
        except subprocess.CalledProcessError:
            console.print("[bold red]Hardware connection closed with error.[/bold red]")
        return

    # Check preflight first for all active sim modes
    res = subprocess.run(
        ["uv", "run", "python", "tools/preflight.py", f"--mode={mode}"], cwd=str(ROOT)
    )
    if res.returncode != 0:
        console.print("[bold red]Preflight check failed. Aborting simulation launch.[/bold red]")
        raise typer.Exit(1) from None

    if mode == "edit":
        px4_dir = os.environ.get("PX4_DIR", "").strip()
        if not px4_dir or not Path(px4_dir).is_dir():
            console.print(
                "[bold red]PX4_DIR is not set or not a directory. Create .env with PX4_DIR=/path/to/PX4-Autopilot[/bold red]"
            )
            raise typer.Exit(1) from None

        console.print(f"[cyan]Opening Gazebo Harmonic editor for world '{world}'...[/cyan]")
        gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models:{px4_dir}/Tools/simulation/gz/worlds:{px4_dir}/Tools/simulation/gz/models"
        env = _get_clean_env()
        env["GZ_SIM_RESOURCE_PATH"] = f"{gz_resource}:{env.get('GZ_SIM_RESOURCE_PATH', '')}"

        local_world = ROOT / "sim" / "worlds" / f"{world}.sdf"
        px4_world = Path(px4_dir) / "Tools" / "simulation" / "gz" / "worlds" / f"{world}.sdf"

        world_path = ""
        if local_world.exists():
            world_path = str(local_world)
        elif px4_world.exists():
            world_path = str(px4_world)
        else:
            console.print(
                f"[bold red]No world SDF found for '{world}' (checked {local_world} and {px4_world})[/bold red]"
            )
            raise typer.Exit(1) from None

        try:
            subprocess.run(["gz", "sim", world_path], env=env, check=True)
        except KeyboardInterrupt:
            console.print("[yellow]Editor closed.[/yellow]")
        return

    if mode == "px4":
        px4_dir = os.environ.get("PX4_DIR", "").strip()
        if not px4_dir or not Path(px4_dir).is_dir():
            console.print(
                "[bold red]PX4_DIR is not set or not a directory. Create .env with PX4_DIR=/path/to/PX4-Autopilot[/bold red]"
            )
            raise typer.Exit(1) from None

        console.print(
            f"[cyan]Starting standalone PX4 SITL (world: {world}, model: {model})...[/cyan]"
        )
        gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models:{px4_dir}/Tools/simulation/gz/worlds:{px4_dir}/Tools/simulation/gz/models"

        env = _get_clean_env()
        env["GZ_IP"] = "127.0.0.1"
        env["GZ_SIM_RESOURCE_PATH"] = f"{gz_resource}:{env.get('GZ_SIM_RESOURCE_PATH', '')}"
        env["PX4_GZ_WORLDS"] = f"{px4_dir}/Tools/simulation/gz/worlds"
        env["PX4_GZ_MODELS"] = f"{px4_dir}/Tools/simulation/gz/models"
        env["PX4_GZ_PLUGINS"] = (
            f"{px4_dir}/build/px4_sitl_default/src/modules/simulation/gz_plugins"
        )
        env["PX4_GZ_SERVER_CONFIG"] = f"{px4_dir}/src/modules/simulation/gz_bridge/server.config"
        env["GZ_SIM_SYSTEM_PLUGIN_PATH"] = env["PX4_GZ_PLUGINS"]
        env["GZ_SIM_SERVER_CONFIG_PATH"] = env["PX4_GZ_SERVER_CONFIG"]
        env["LD_LIBRARY_PATH"] = f"{env['PX4_GZ_PLUGINS']}:{env.get('LD_LIBRARY_PATH', '')}"

        cwd = Path(px4_dir) / "build" / "px4_sitl_default"

        sys.path.insert(0, str(ROOT / "tools"))
        from gz_lifecycle import gazebo_matches, is_model_present

        px4_env = {
            **env,
            "PX4_GZ_WORLD": world,
            "PX4_SIM_MODEL": f"gz_{model}",
            "PX4_GZ_STANDALONE": "1",
            "PX4_PARAM_COM_ARM_WO_GPS": "1",
            "PX4_PARAM_CBRK_SUPPLY_CHK": "894281",
            "PX4_PARAM_COM_SPOOLUP_TIME": "0.0",
            "PX4_PARAM_EKF2_GPS_CHECK": "0",
            "PX4_PARAM_EKF2_GPS_CTRL": "7",
        }
        if gazebo_matches(world) and is_model_present(world, f"{model}_0"):
            console.print(
                f"[cyan]Gazebo warm for world '{world}' — attaching to existing '{model}_0' model...[/cyan]"
            )
            px4_env["PX4_GZ_MODEL_NAME"] = f"{model}_0"
        else:
            console.print(
                f"[cyan]Gazebo cold or model missing for world '{world}' — PX4 will spawn a new model...[/cyan]"
            )

        try:
            subprocess.run(
                ["./bin/px4"],
                env=px4_env,
                cwd=str(cwd),
                check=True,
            )
        except KeyboardInterrupt:
            console.print("[yellow]PX4 SITL stopped by user.[/yellow]")
        return

    if mode == "bg":
        pidfile = LOG_DIR / "sim.pid"
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
                os.kill(pid, 0)
                console.print(
                    f"[yellow]Simulation already running with PID {pid}. Run 'just sim stop' first.[/yellow]"
                )
                raise typer.Exit(1) from None
            except (ProcessLookupError, ValueError):
                pass

        if build:
            _build_workspace()

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"sim_{datetime.now().strftime('%Y%m%dT%H%M%S')}.log"
        console.print(
            f"[cyan]Starting headless simulation in background (log: {log_file})...[/cyan]"
        )

        gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
        launch_args = [
            str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
            f"world:={world}",
            f"model:={model}",
            f"enable_vision:={vision}",
            "headless:=true",
            f"log_dir:={LOG_DIR}",
            f"speed:={speed}",
            *_sim_launch_overlay_args(mode),
        ]
        env = _ros_launch_env(
            GZ_IP="127.0.0.1",
            GZ_SIM_RESOURCE_PATH=f"{gz_resource}:{os.environ.get('GZ_SIM_RESOURCE_PATH', '')}",
            HEADLESS="1",
        )

        try:
            with Path(log_file).open("w", encoding="utf-8") as out:
                proc = subprocess.Popen(
                    _ros2_launch_bash_argv(launch_args),
                    env=env,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid,
                    cwd=str(ROOT),
                )
            pidfile.write_text(str(proc.pid))
            if bag:
                bag_ts = datetime.now().strftime("%Y%m%dT%H%M%S")
                bag_dir = LOG_DIR / "bags" / f"run_{bag_ts}"
                bag_dir.parent.mkdir(parents=True, exist_ok=True)
                _ros_topics = [
                    "/drone/target_pose",
                    "/drone/pose_enu",
                    "/drone/controller_status",
                    "/drone/mission_status",
                    "/fmu/out/vehicle_local_position",
                    "/fmu/out/vehicle_status",
                ]
                ros_setup = _ros_setup_path()
                ws_setup = ROOT / "install" / "setup.bash"
                sources = [f"source {shlex.quote(ros_setup)}"]
                if ws_setup.exists():
                    sources.append(f"source {shlex.quote(str(ws_setup))}")
                bag_cmd = " && ".join([
                    *sources,
                    "exec ros2 bag record -o "
                    + shlex.quote(str(bag_dir))
                    + " "
                    + " ".join(shlex.quote(t) for t in _ros_topics),
                ])
                bag_log = LOG_DIR / f"bag_{bag_ts}.log"
                with bag_log.open("w") as bag_out:
                    bag_proc = subprocess.Popen(
                        ["bash", "-lc", bag_cmd],
                        env=env,
                        stdout=bag_out,
                        stderr=subprocess.STDOUT,
                        preexec_fn=os.setsid,
                        cwd=str(ROOT),
                    )
                bag_pidfile = LOG_DIR / "bag.pid"
                bag_pidfile.write_text(str(bag_proc.pid))
                console.print(f"[green]Rosbag recording to {bag_dir}[/green]")
            console.print(
                json.dumps(
                    {
                        "started": True,
                        "pid": proc.pid,
                        "log": str(log_file),
                        "pidfile": str(pidfile),
                    }
                )
            )
        except Exception as e:
            console.print(f"[bold red]Failed to start background simulation: {e}[/bold red]")
            raise typer.Exit(1) from None
        return

    # Foreground Simulation (gui, headless, inspect)
    if build:
        _build_workspace()

    world_val = world
    vision_val = vision
    headless_val = "false"

    if mode == "inspect":
        world_val = "inspect_aruco"
        vision_val = "true"
    elif mode == "headless":
        headless_val = "true"

    console.print(
        f"[cyan]Starting simulation (mode: {mode}, world: {world_val}, model: {model})...[/cyan]"
    )

    gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
    launch_args = [
        str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
        f"world:={world_val}",
        f"model:={model}",
        f"enable_vision:={vision_val}",
        f"headless:={headless_val}",
        f"log_dir:={LOG_DIR}",
        f"speed:={speed}",
        *_sim_launch_overlay_args(mode),
    ]
    env = _ros_launch_env(
        GZ_IP="127.0.0.1",
        GZ_SIM_RESOURCE_PATH=f"{gz_resource}:{os.environ.get('GZ_SIM_RESOURCE_PATH', '')}",
        **({"HEADLESS": "1"} if headless_val == "true" else {}),
    )

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"sim_{datetime.now().strftime('%Y%m%dT%H%M%S')}.log"

    try:
        argv = _ros2_launch_bash_argv(launch_args)
        shell_cmd = " ".join(shlex.quote(a) for a in argv) + f" 2>&1 | tee {shlex.quote(str(log_file))}"
        subprocess.run(shell_cmd, shell=True, env=env, cwd=str(ROOT), check=True)
    except KeyboardInterrupt:
        console.print("[yellow]Simulation stopped by user.[/yellow]")
    except subprocess.CalledProcessError:
        console.print("[bold red]Simulation exited with error.[/bold red]")


@app.command()
def test(
    type: str = typer.Argument("unit", help="Test type: unit, scenario, e2e"),
    arg: str = typer.Option("", "--arg", help="Scenario name (required for scenario test)"),
):
    """Run tests. Types: unit (default), scenario (requires --arg=<name>), e2e."""
    if type == "unit":
        console.print("[cyan]Running unit tests...[/cyan]")
        try:
            subprocess.run(["uv", "run", "pytest", "tests/unit/", "-v"], check=True, cwd=str(ROOT))
        except subprocess.CalledProcessError:
            raise typer.Exit(1) from None

    elif type == "scenario":
        if not arg:
            console.print(
                "[bold red]Error: Scenario name required (e.g. just test scenario --arg 01_arm_takeoff)[/bold red]"
            )
            raise typer.Exit(1) from None
        _build_workspace()
        console.print(f"[cyan]Running scenario test: {arg}...[/cyan]")
        try:
            subprocess.run(
                ["uv", "run", "python", f"tests/scenarios/{arg}.py"], check=True, cwd=str(ROOT)
            )
        except subprocess.CalledProcessError:
            raise typer.Exit(1) from None

    elif type == "e2e":
        console.print("[cyan]=== Starting E2E Headless Cycle ===[/cyan]")

        # Clear per-run logs, keeping build/install cache intact
        console.print("[cyan]Clearing previous simulation logs...[/cyan]")
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        for f in LOG_DIR.glob("*"):
            if f.name != ".gitkeep":
                if f.is_file() or f.is_symlink():
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f)

        _build_workspace()

        res = subprocess.run(["uv", "run", "python", "tools/preflight.py"], cwd=str(ROOT))
        if res.returncode != 0:
            console.print("[bold red]Preflight check failed. Aborting E2E cycle.[/bold red]")
            raise typer.Exit(1) from None

        pidfile = LOG_DIR / "sim.pid"
        log_file = LOG_DIR / f"sim_{datetime.now().strftime('%Y%m%dT%H%M%S')}.log"
        console.print("Starting background headless simulation...")

        gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
        launch_args = [
            str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
            "world:=default",
            "model:=x500",
            "enable_vision:=false",
            "headless:=true",
            f"log_dir:={LOG_DIR}",
        ]
        env = _ros_launch_env(
            GZ_IP="127.0.0.1",
            GZ_SIM_RESOURCE_PATH=f"{gz_resource}:{os.environ.get('GZ_SIM_RESOURCE_PATH', '')}",
            HEADLESS="1",
        )

        proc = subprocess.Popen(
            _ros2_launch_bash_argv(launch_args),
            env=env,
            stdout=Path(log_file).open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=str(ROOT),
        )
        pidfile.write_text(str(proc.pid))

        def cleanup():
            console.print("Cleaning up E2E simulation...")
            subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))

        import atexit

        atexit.register(cleanup)

        try:
            console.print("Waiting for simulation to stabilize...")
            subprocess.run(
                ["uv", "run", "python", "tools/wait_ready.py", "--timeout", "180"],
                check=True,
                cwd=str(ROOT),
            )

            fails = 0
            scenarios = ["01_arm_takeoff", "03_waypoint", "02_hover_hold"]
            for s in scenarios:
                console.print(f"Running scenario {s}...")
                res_s = subprocess.run(
                    ["uv", "run", "python", f"tests/scenarios/{s}.py"], cwd=str(ROOT)
                )
                if res_s.returncode != 0:
                    fails += 1

            console.print("Auditing topic graph...")
            subprocess.run(
                ["uv", "run", "python", "tools/check_topics.py", "--manifest", "docs/TOPICS.md"],
                cwd=str(ROOT),
            )

            console.print("Merging execution logs...")
            try:
                subprocess.run(
                    [
                        "uv",
                        "run",
                        "python",
                        "tools/log_merger.py",
                        "--log-dir",
                        str(LOG_DIR),
                        "--output-log",
                        str(LOG_DIR / "merged.log"),
                        "--output-jsonl",
                        str(LOG_DIR / "merged.jsonl"),
                        "--summary",
                        str(LOG_DIR / "run_summary.json"),
                    ],
                    check=True,
                    cwd=str(ROOT),
                )
            except Exception as e:
                console.print(f"Failed to merge logs: {e}")

            console.print("Generating E2E Report...")
            subprocess.run(["uv", "run", "python", "tools/e2e_report.py"], cwd=str(ROOT))

            if fails > 0:
                console.print(f"[bold red]E2E cycle finished with {fails} failures.[/bold red]")
                raise typer.Exit(fails) from None
            else:
                console.print(
                    "[bold green]E2E cycle finished successfully (all scenarios passed).[/bold green]"
                )

        except Exception as e:
            console.print(f"[bold red]E2E run interrupted: {e}[/bold red]")
            raise typer.Exit(1) from None
        finally:
            cleanup()
            atexit.unregister(cleanup)


@app.command()
def rviz(config: str = typer.Option("default", "--config", help="RViz config: default, inspect")):
    """Open RViz with the selected configuration profile."""
    cfg = "default.rviz"
    if config == "inspect":
        cfg = "inspect_mission.rviz"
    elif (ROOT / "config" / "rviz" / f"{config}.rviz").exists():
        cfg = f"{config}.rviz"

    console.print(f"[cyan]Opening RViz (config: {cfg})...[/cyan]")
    try:
        subprocess.run(
            ["ros2", "run", "rviz2", "rviz2", "-d", str(ROOT / "config" / "rviz" / cfg)],
            check=True,
            cwd=str(ROOT),
        )
    except KeyboardInterrupt:
        console.print("[yellow]RViz closed.[/yellow]")
    except subprocess.CalledProcessError:
        console.print("[bold red]Failed to launch RViz.[/bold red]")


# Extend the log sub-app with status and topics commands
@log_app.command()
def status():
    """View JSON workspace status snapshot (nodes, live status, capabilities)."""
    subprocess.run(["uv", "run", "python", "tools/status.py"], cwd=str(ROOT))


@log_app.command()
def topics():
    """Audit live topics against docs/TOPICS.md."""
    subprocess.run(
        ["uv", "run", "python", "tools/check_topics.py", "--manifest", "docs/TOPICS.md"],
        cwd=str(ROOT),
    )


@app.command()
def replay(
    bag: str = typer.Argument(..., help="Path to rosbag directory (e.g. logs/bags/run_20260530T120000)"),
    speed: float = typer.Option(1.0, "--speed", help="Playback speed multiplier"),
) -> None:
    """Replay a recorded rosbag against the live ROS graph.

    Requires a running sim (just sim bg) to receive the replayed topics.
    Clock is published from the bag so nodes use bag time.
    """
    bag_path = Path(bag)
    if not bag_path.exists():
        console.print(f"[bold red]Bag not found: {bag_path}[/bold red]")
        raise typer.Exit(1) from None
    console.print(f"[cyan]Replaying bag: {bag_path} at {speed}x...[/cyan]")
    try:
        subprocess.run(
            ["ros2", "bag", "play", str(bag_path), "--rate", str(speed), "--clock"],
            env=_ros_launch_env(),
            check=True,
            cwd=str(ROOT),
        )
    except KeyboardInterrupt:
        console.print("[yellow]Replay stopped.[/yellow]")
    except subprocess.CalledProcessError:
        console.print("[bold red]Replay ended with error.[/bold red]")


if __name__ == "__main__":
    app()
