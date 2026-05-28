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
                ["bash", "-c", cmd],
                capture_output=True,
                text=True,
                check=True,
                cwd=str(ROOT)
            )
            new_env = json.loads(res.stdout.strip())
            for k, v in new_env.items():
                os.environ[k] = v
        except Exception as e:
            console.print(f"[yellow]Warning: failed to source workspace env: {e}[/yellow]")

_source_workspace_env()

def _get_clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    path_dirs = env.get("PATH", "").split(os.pathsep)
    cleaned_dirs = []
    for d in path_dirs:
        if ".cache/uv" in d or ".venv" in d:
            continue
        cleaned_dirs.append(d)
    env["PATH"] = os.pathsep.join(cleaned_dirs)
    return env

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

    console.print("Syncing Python dependencies with uv...")
    try:
        subprocess.run(["uv", "sync", "--group", "dev"], check=True, cwd=str(ROOT))
    except subprocess.CalledProcessError:
        console.print("[bold red]Failed to sync Python dependencies.[/bold red]")
        raise typer.Exit(1) from None

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


@app.command()
def sim(
    mode: str = typer.Argument("gui", help="Mode: gui, headless, bg, px4, edit, hardware, stop, kill"),
    world: str = typer.Option("default", "--world", help="World file name"),
    model: str = typer.Option("x500", "--model", help="Airframe model"),
    vision: str = typer.Option("false", "--vision", help="Enable vision/aruco detection"),
    port: str = typer.Option("/dev/ttyUSB0", "--port", help="Serial port for hardware"),
    baud: int = typer.Option(921600, "--baud", help="Baudrate for hardware serial"),
):
    """Simulation & hardware runner. Modes: gui, headless, bg, px4, edit, hardware, stop, kill.

    stop: kill PX4/ROS/XRCE but keep Gazebo warm for fast subsequent launches.
    kill: full teardown including Gazebo (use before changing worlds or for clean reboot).
    """
    if mode == "stop":
        console.print("[cyan]Stopping sim (Gazebo stays warm for next launch)...[/cyan]")
        subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))
        return

    if mode == "kill":
        console.print("[cyan]Full teardown — killing Gazebo too (next launch will be cold)...[/cyan]")
        subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py", "--full"], cwd=str(ROOT))
        return

    if mode == "hardware":
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
    res = subprocess.run(["uv", "run", "python", "tools/preflight.py"], cwd=str(ROOT))
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

        console.print(f"[cyan]Starting standalone PX4 SITL (world: {world}, model: {model})...[/cyan]")
        gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models:{px4_dir}/Tools/simulation/gz/worlds:{px4_dir}/Tools/simulation/gz/models"

        env = _get_clean_env()
        env["GZ_IP"] = "127.0.0.1"
        env["GZ_SIM_RESOURCE_PATH"] = f"{gz_resource}:{env.get('GZ_SIM_RESOURCE_PATH', '')}"
        env["PX4_GZ_WORLDS"] = f"{px4_dir}/Tools/simulation/gz/worlds"
        env["PX4_GZ_MODELS"] = f"{px4_dir}/Tools/simulation/gz/models"
        env["PX4_GZ_PLUGINS"] = f"{px4_dir}/build/px4_sitl_default/src/modules/simulation/gz_plugins"
        env["PX4_GZ_SERVER_CONFIG"] = f"{px4_dir}/src/modules/simulation/gz_bridge/server.config"
        env["GZ_SIM_SYSTEM_PLUGIN_PATH"] = env["PX4_GZ_PLUGINS"]
        env["GZ_SIM_SERVER_CONFIG_PATH"] = env["PX4_GZ_SERVER_CONFIG"]
        env["LD_LIBRARY_PATH"] = f"{env['PX4_GZ_PLUGINS']}:{env.get('LD_LIBRARY_PATH', '')}"

        cwd = Path(px4_dir) / "build" / "px4_sitl_default"
        try:
            subprocess.run(
                ["./bin/px4"],
                env={**env, "PX4_GZ_WORLD": world, "PX4_SIM_MODEL": f"gz_{model}"},
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

        _build_workspace()

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"sim_{datetime.now().strftime('%Y%m%dT%H%M%S')}.log"
        console.print(f"[cyan]Starting headless simulation in background (log: {log_file})...[/cyan]")

        gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
        env = _get_clean_env()
        env["GZ_IP"] = "127.0.0.1"
        env["GZ_SIM_RESOURCE_PATH"] = f"{gz_resource}:{env.get('GZ_SIM_RESOURCE_PATH', '')}"
        env["HEADLESS"] = "1"

        try:
            with Path(log_file).open("w", encoding="utf-8") as out:
                proc = subprocess.Popen(
                    [
                        "ros2",
                        "launch",
                        str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
                        f"world:={world}",
                        f"model:={model}",
                        f"enable_vision:={vision}",
                        "headless:=true",
                        f"log_dir:={LOG_DIR}",
                    ],
                    env=env,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid,
                    cwd=str(ROOT),
                )
            pidfile.write_text(str(proc.pid))
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
        f"[cyan]Starting simulation (mode: {mode}, world: {world_val}, model: {model}, vision: {vision_val})...[/cyan]"
    )

    gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
    env = _get_clean_env()
    env["GZ_IP"] = "127.0.0.1"
    env["GZ_SIM_RESOURCE_PATH"] = f"{gz_resource}:{env.get('GZ_SIM_RESOURCE_PATH', '')}"
    if headless_val == "true":
        env["HEADLESS"] = "1"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"sim_{datetime.now().strftime('%Y%m%dT%H%M%S')}.log"

    try:
        cmd = [
            "ros2",
            "launch",
            str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
            f"world:={world_val}",
            f"model:={model}",
            f"enable_vision:={vision_val}",
            f"headless:={headless_val}",
            f"log_dir:={LOG_DIR}",
        ]
        shell_cmd = " ".join(cmd) + f" 2>&1 | tee {log_file}"
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
        env = _get_clean_env()
        env["GZ_IP"] = "127.0.0.1"
        env["GZ_SIM_RESOURCE_PATH"] = f"{gz_resource}:{env.get('GZ_SIM_RESOURCE_PATH', '')}"
        env["HEADLESS"] = "1"

        proc = subprocess.Popen(
            [
                "ros2",
                "launch",
                str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
                "world:=default",
                "model:=x500",
                "enable_vision:=false",
                "headless:=true",
                f"log_dir:={LOG_DIR}",
            ],
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


if __name__ == "__main__":
    app()
