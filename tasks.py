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

app = typer.Typer(help="Hypermodern ROS 2 + PX4 Task Runner")
ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"

# Prevent uv environment mismatch warnings in sub-processes
if "VIRTUAL_ENV" in os.environ and not os.environ["VIRTUAL_ENV"].endswith(".venv"):
    del os.environ["VIRTUAL_ENV"]


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
            print(f"Warning: failed to source workspace env: {e}", file=sys.stderr)


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

    Seed ``PYTHONPATH`` with the uv venv site-packages so nodes can import project
    Python dependencies declared in ``pyproject.toml`` (e.g. ``opencv-python>=4.7.0``).
    The ROS ``source`` commands prepend their own paths on top, so this acts as a
    low-priority fallback that never shadows ROS packages.
    """
    import glob as _glob

    env = _get_clean_env()
    env.pop("PYTHONPATH", None)

    venv_site_pkgs = _glob.glob(str(ROOT / ".venv" / "lib" / "python3*" / "site-packages"))
    if venv_site_pkgs:
        env["PYTHONPATH"] = venv_site_pkgs[0]

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


def _ros2_launch_capture_argv(
    launch_args: list[str], out_file: Path, *, append: bool, cwd: Path = ROOT
) -> list[str]:
    """``bash -lc`` that sources ROS, then pipes ``ros2 launch`` stdout through the
    live capture filter into ``out_file`` (logfmt session log). Not ``exec`` because
    a pipeline cannot be exec'd; the whole pipeline lives in the caller's setsid group.
    """
    ros_setup = _ros_setup_path()
    ws_setup = cwd / "install" / "setup.bash"
    sources = [f"source {shlex.quote(ros_setup)}"]
    if ws_setup.exists():
        sources.append(f"source {shlex.quote(str(ws_setup))}")
    redirect = ">>" if append else ">"
    launch = "ros2 launch " + " ".join(shlex.quote(a) for a in launch_args)
    capture = "uv run python tools/log_capture.py"
    inner = " && ".join(
        [
            *sources,
            f"cd {shlex.quote(str(cwd))}",
            f"{launch} 2>&1 | {capture} {redirect} {shlex.quote(str(out_file))}",
        ]
    )
    return ["bash", "-lc", inner]


# Ensure tools/ is on path to import sub-apps
sys.path.append(str(ROOT / "tools"))
from capabilities import app as cap_app, scenario_sim_configs
from log_summary import build_run_summary
from log_query import app as log_app

# Register sub-apps
app.add_typer(log_app, name="log", help="Query, merge, tail, or view logs/status/topics.")
app.add_typer(cap_app, name="cap", help="Manage verified capabilities registry.")


def _summarize_logs_silent() -> None:
    """Regenerate latest_summary.json from latest.log; non-fatal if absent."""
    try:
        summary = build_run_summary(LOG_DIR / "latest.log")
        (LOG_DIR / "latest_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as e:
        print(f"Warning: log summary skipped: {e}", file=sys.stderr)


def _resolve_scenario_script(name: str) -> Path:
    """Return scenario script path or exit with available names."""
    script = ROOT / "tests" / "scenarios" / f"{name}.py"
    if script.is_file():
        return script
    available = sorted(
        p.stem for p in (ROOT / "tests" / "scenarios").glob("*.py") if not p.name.startswith("_")
    )
    print(f"Error: scenario not found: {name}.py", file=sys.stderr)
    if available:
        print(f"Available: {', '.join(available)}", file=sys.stderr)
    raise typer.Exit(1) from None


def _needs_build() -> bool:
    """Return True if colcon build is required (install missing or manifests changed)."""
    install_dir = ROOT / "install"
    if not install_dir.exists():
        return True
    install_mtime = install_dir.stat().st_mtime
    manifests = list(ROOT.glob("src/**/setup.py")) + list(ROOT.glob("src/**/package.xml"))
    return any(f.stat().st_mtime > install_mtime for f in manifests)


def _build_workspace() -> None:
    print("Building workspace")
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
                "--event-handlers",
                "status-",
            ],
            check=True,
            cwd=str(ROOT),
            env=_get_clean_env(),
        )
        print("Workspace built successfully")
        _source_workspace_env()
    except subprocess.CalledProcessError:
        print("Build failed.", file=sys.stderr)
        raise typer.Exit(1) from None


@app.command()
def setup():
    """One-time workspace setup (auto-detects PX4 version, runs uv sync, rosdep)."""
    print("Setting up workspace")

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
                print(f"Auto-detected PX4 version '{version_str}'. Using branch '{px4_msgs_branch}' for px4_msgs.")
            else:
                print(f"PX4 version '{version_str}' could not be parsed. Defaulting to '{px4_msgs_branch}'.")
        except Exception as e:
            print(f"Could not determine PX4 version from PX4_DIR: {e}. Defaulting to '{px4_msgs_branch}'.")
    else:
        print(f"PX4_DIR is not set or not a directory. Defaulting to branch '{px4_msgs_branch}'.")

    px4_msgs_dir = ROOT / "src" / "px4_msgs"
    if not px4_msgs_dir.exists():
        print(f"Cloning px4_msgs ({px4_msgs_branch}) into src/px4_msgs...")
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
            print("Failed to clone px4_msgs.", file=sys.stderr)
            raise typer.Exit(1) from None
    else:
        print("src/px4_msgs already exists, skipping clone.")

    print("Syncing Python dev tools with uv (not pip)...")
    try:
        subprocess.run(["uv", "sync", "--group", "dev"], check=True, cwd=str(ROOT))
    except subprocess.CalledProcessError:
        print("Failed to sync Python dependencies.", file=sys.stderr)
        raise typer.Exit(1) from None

    print(
        "ROS bridge (port 9090): install via apt, e.g. "
        "`sudo apt install ros-jazzy-rosbridge-suite` inside your ROS environment."
    )

    print("Installing rosdep dependencies...")
    try:
        subprocess.run(
            ["rosdep", "install", "--from-paths", "src", "--ignore-src", "-r", "-y"],
            check=True,
            cwd=str(ROOT),
        )
    except subprocess.CalledProcessError:
        print("rosdep install completed with warnings/failures (continuing).")

    _build_workspace()
    print("setup complete.")


@app.command()
def build():
    """Compile the workspace using colcon build."""
    _build_workspace()


@app.command()
def clean():
    """Wipe build artifacts, build logs, and per-run logs."""
    print("Cleaning build outputs and log files")
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
    print("Cleanup complete.")


@app.command()
def check():
    """Format, lint-fix, typecheck, compile, and run unit tests."""
    print("Running checks")

    ruff_paths = ["src/core", "tests", "tools", "sim", "hardware"]
    ruff_paths_str = [str(ROOT / p) for p in ruff_paths]
    env = _get_clean_env()

    failed_steps: list[str] = []

    print("Running ruff format and lint auto-fixes")
    res = subprocess.run(
        ["uv", "run", "ruff", "check", "--fix"] + ruff_paths_str, cwd=str(ROOT), env=env
    )
    if res.returncode != 0:
        failed_steps.append("ruff check")

    res = subprocess.run(
        ["uv", "run", "ruff", "format"] + ruff_paths_str, cwd=str(ROOT), env=env
    )
    if res.returncode != 0:
        failed_steps.append("ruff format")

    print("Checking branch invariants...")
    res = subprocess.run(
        ["uv", "run", "python", "tools/check_invariants.py"], cwd=str(ROOT), env=env
    )
    if res.returncode != 0:
        failed_steps.append("branch invariants")

    print("Running static typecheck...")
    res = subprocess.run(
        [
            "uv", "run", "ty", "check",
            "src/core/ros_px4_template_core/lib",
            "tests/unit",
            "tools/",
            "--exclude", "tools/gcs_heartbeat.py",
        ],
        cwd=str(ROOT),
        env=env,
    )
    if res.returncode != 0:
        failed_steps.append("static typecheck")

    if failed_steps:
        print(f"Quality gate failed on static checks: {', '.join(failed_steps)}", file=sys.stderr)
        raise typer.Exit(1)

    if _needs_build():
        _build_workspace()
    else:
        print("Skipping colcon build — install/ is up-to-date.")
        _source_workspace_env()

    print("Running pytest unit tests...")
    try:
        subprocess.run(
            ["uv", "run", "pytest", "tests/unit/", "-q", "--tb=short"],
            check=True,
            cwd=str(ROOT),
            env=_get_clean_env(),
        )
        print("all checks passed.")
    except subprocess.CalledProcessError:
        print("Unit tests failed.", file=sys.stderr)
        raise typer.Exit(1) from None



def _sim_launch_overlay_args(mode: str) -> list[str]:
    if mode == "inspect":
        return ["param_overlay:=inspect"]
    return []


@app.command()
def sim(
    mode: str = typer.Argument(
        "headless", help="Mode: gui, headless, bg, stop"
    ),
    world: str = typer.Option("default", "--world", help="World file name"),
    model: str = typer.Option("x500", "--model", help="Airframe model"),
    vision: str = typer.Option("false", "--vision", help="Enable vision/aruco detection"),
    port: str = typer.Option("/dev/ttyUSB0", "--port", help="Serial port for hardware"),
    baud: int = typer.Option(921600, "--baud", help="Baudrate for hardware serial"),
    vehicle: str = typer.Option("", "--vehicle", help="Vehicle overlay name for hardware mode (e.g. x500)"),
    build: bool = typer.Option(True, "--build/--no-build", help="Build workspace before running"),
    speed: float = typer.Option(1.0, "--speed", help="Gazebo physics speed multiplier (headless/bg only). Must not exceed 1.0."),
    auto_arm: bool = typer.Option(None, "--auto-arm/--no-auto-arm", help="Enable/disable auto-arming on startup (defaults to True for bg mode, False otherwise)."),
):
    """Simulation runner. Modes: gui, headless, bg, stop."""
    if speed <= 0 or speed > 1.0:
        print(f"--speed must be between 0 (exclusive) and 1.0 (inclusive), got {speed}", file=sys.stderr)
        raise typer.Exit(1) from None
    if mode in ("gui", "inspect") and speed != 1.0:
        print(f"--speed {speed} ignored for '{mode}' mode (only applies to headless/bg)")
        speed = 1.0

    if auto_arm is None:
        auto_arm = (mode == "bg")

    overlay_args = _sim_launch_overlay_args(mode)
    if auto_arm and not any(a.startswith("param_overlay:=") for a in overlay_args):
        overlay_args.append("param_overlay:=auto_arm")

    if mode == "stop":
        subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))
        return

    if mode == "hardware":
        res = subprocess.run(
            ["uv", "run", "python", "tools/preflight.py", "--mode=hw"],
            cwd=str(ROOT),
        )
        if res.returncode != 0:
            print("Preflight check failed. Aborting hardware launch.", file=sys.stderr)
            raise typer.Exit(1) from None
        if vehicle:
            vehicle_path = ROOT / "vehicles" / f"{vehicle}.yaml"
            if not vehicle_path.is_file():
                print(f"Vehicle overlay not found: {vehicle_path}", file=sys.stderr)
                raise typer.Exit(1) from None
        if build:
            _build_workspace()
        print(f"Connecting to hardware on port {port} at {baud} baud...")
        launch_args = [
            str(ROOT / "hardware" / "launch" / "hardware.launch.py"),
            f"serial_port:={port}",
            f"baudrate:={baud}",
            "use_sim_time:=false",
            "config:=hardware",
            f"log_dir:={LOG_DIR}",
            f"vehicle:={vehicle}",
        ]
        try:
            argv = _ros2_launch_bash_argv(launch_args)
            subprocess.run(
                argv,
                check=True,
                env=_ros_launch_env(),
                cwd=str(ROOT),
            )
        except KeyboardInterrupt:
            print("Connection stopped by user.")
        except subprocess.CalledProcessError:
            print("Hardware connection closed with error.", file=sys.stderr)
        return

    # Check preflight first for all active sim modes
    res = subprocess.run(
        ["uv", "run", "python", "tools/preflight.py", f"--mode={mode}"], cwd=str(ROOT)
    )
    if res.returncode != 0:
        print("Preflight check failed. Aborting simulation launch.", file=sys.stderr)
        raise typer.Exit(1) from None

    if mode == "bg":
        pidfile = LOG_DIR / "sim.pid"
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
                os.kill(pid, 0)
                print(f"Simulation already running (PID {pid}). Stopping it first for idempotency...")
                subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))
            except (ProcessLookupError, ValueError):
                pass

        if build:
            _build_workspace()

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        latest = LOG_DIR / "latest.log"
        print(f"Starting headless simulation in background (-> {latest})...")

        gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
        vision_arg = "aruco" if vision.lower() in ("true", "aruco") else "none"
        launch_args = [
            str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
            f"world:={world}",
            f"model:={model}",
            "headless:=true",
            f"log_dir:={LOG_DIR}",
            f"speed:={speed}",
            f"vision:={vision_arg}",
            *overlay_args,
        ]
        env = _ros_launch_env(
            GZ_IP="127.0.0.1",
            GZ_SIM_RESOURCE_PATH=f"{gz_resource}:{os.environ.get('GZ_SIM_RESOURCE_PATH', '')}",
            HEADLESS="1",
        )

        try:
            proc = subprocess.Popen(
                _ros2_launch_capture_argv(launch_args, latest, append=False),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
                cwd=str(ROOT),
            )

            pidfile.write_text(str(proc.pid))
            status = {
                "started": True,
                "pid": proc.pid,
                "log": str(latest),
                "pidfile": str(pidfile),
            }
            print(json.dumps(status))

            # Block until simulation stack is ready
            try:
                subprocess.run(
                    ["uv", "run", "python", "tools/wait_ready.py", "--timeout", "180", "--speed", str(speed)],
                    check=True,
                    cwd=str(ROOT),
                )
            except subprocess.CalledProcessError:
                print("Simulation failed to stabilize or timed out.", file=sys.stderr)
                # Kill background process cleanly on failure so we don't leak processes
                subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))
                raise typer.Exit(1) from None
        except Exception as e:
            print(f"Failed to start background simulation: {e}", file=sys.stderr)
            raise typer.Exit(1) from None
        return

    # Foreground Simulation (gui, headless, inspect)
    if build:
        _build_workspace()

    world_val = world
    headless_val = "false"

    if mode == "headless":
        headless_val = "true"

    print(f"Starting simulation (mode: {mode}, world: {world_val}, model: {model})...")

    gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
    vision_arg = "aruco" if vision.lower() in ("true", "aruco") else "none"
    launch_args = [
        str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
        f"world:={world_val}",
        f"model:={model}",
        f"headless:={headless_val}",
        f"log_dir:={LOG_DIR}",
        f"speed:={speed}",
        f"vision:={vision_arg}",
        *overlay_args,
    ]
    env = _ros_launch_env(
        GZ_IP="127.0.0.1",
        GZ_SIM_RESOURCE_PATH=f"{gz_resource}:{os.environ.get('GZ_SIM_RESOURCE_PATH', '')}",
        **({"HEADLESS": "1"} if headless_val == "true" else {}),
    )

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        argv = _ros2_launch_capture_argv(launch_args, LOG_DIR / "latest.log", append=False)
        inner = argv[2] + f" ; cat {shlex.quote(str(LOG_DIR / 'latest.log'))}"
        subprocess.run(["bash", "-lc", inner], env=env, cwd=str(ROOT), check=True)
    except KeyboardInterrupt:
        print("Simulation stopped by user.")
    except subprocess.CalledProcessError:
        print("Simulation exited with error.", file=sys.stderr)


@app.command()
def hw(
    port: str = typer.Option("/dev/ttyUSB0", "--port", help="Serial port for hardware"),
    baud: int = typer.Option(921600, "--baud", help="Baudrate for hardware serial"),
    build: bool = typer.Option(True, "--build/--no-build", help="Build workspace before running"),
):
    """Connect to serial hardware flight controller."""
    if build:
        _build_workspace()
    print(f"Connecting to hardware on port {port} at {baud} baud...")
    launch_args = [
        str(ROOT / "hardware" / "launch" / "hardware.launch.py"),
        f"serial_port:={port}",
        f"baudrate:={baud}",
        "use_sim_time:=false",
        "config:=hardware",
        f"log_dir:={LOG_DIR}",
    ]
    try:
        argv = _ros2_launch_bash_argv(launch_args)
        subprocess.run(
            argv,
            check=True,
            env=_ros_launch_env(),
            cwd=str(ROOT),
        )
    except KeyboardInterrupt:
        print("Connection stopped by user.")
    except subprocess.CalledProcessError:
        print("Hardware connection closed with error.", file=sys.stderr)

def _run_e2e_sim_group(
    vision: str,
    overlay: str,
    scenarios: list[str],
    *,
    gz_resource: str,
    audit_topics: bool = False,
) -> int:
    """Launch one isolated headless sim for a ``(vision, overlay)`` config, wait for
    readiness, run the given scenarios sequentially, optionally audit the topic
    graph, then tear the sim down.

    Isolating each config keeps hold scenarios (hover overlay, no path) from racing
    the auto-flown waypoint mission that the demo path scenarios need. Returns the
    number of failed scenarios in this group (a sim that never becomes ready counts
    every scenario in the group as failed).
    """
    pidfile = LOG_DIR / "sim.pid"
    latest = LOG_DIR / "latest.log"
    banner = f"=== Sim group: vision={vision} overlay={overlay} ({', '.join(scenarios)}) ==="
    with latest.open("a", encoding="utf-8") as fh:
        fh.write(banner + "\n")
    print(f"\n{banner}")
    print("Starting background headless simulation (-> logs/latest.log)...")

    launch_args = [
        str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
        "world:=default",
        "model:=x500",
        "headless:=true",
        f"log_dir:={LOG_DIR}",
        f"vision:={vision}",
        f"param_overlay:={overlay}",
    ]
    env = _ros_launch_env(
        GZ_IP="127.0.0.1",
        GZ_SIM_RESOURCE_PATH=f"{gz_resource}:{os.environ.get('GZ_SIM_RESOURCE_PATH', '')}",
        HEADLESS="1",
    )

    proc = subprocess.Popen(
        _ros2_launch_capture_argv(launch_args, latest, append=True),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
        cwd=str(ROOT),
    )
    pidfile.write_text(str(proc.pid))

    fails = 0
    try:
        print("Waiting for simulation to stabilize...")
        try:
            subprocess.run(
                ["uv", "run", "python", "tools/wait_ready.py", "--timeout", "180", "--speed", "1.0"],
                check=True,
                cwd=str(ROOT),
            )
        except subprocess.CalledProcessError:
            print(
                f"  [FAIL] sim never became ready; failing {len(scenarios)} scenario(s) "
                f"in group (vision={vision} overlay={overlay})",
                file=sys.stderr,
            )
            return len(scenarios)

        for s in scenarios:
            print(f"Running scenario {s}...")
            res_s = subprocess.run(
                ["uv", "run", "python", f"tests/scenarios/{s}.py"], cwd=str(ROOT)
            )
            if res_s.returncode != 0:
                fails += 1

        if audit_topics:
            print("Auditing topic graph...")
            subprocess.run(
                ["uv", "run", "python", "tools/check_topics.py", "--manifest", "docs/TOPICS.md"],
                cwd=str(ROOT),
            )
    finally:
        print(f"Tearing down sim group (vision={vision} overlay={overlay})...")
        subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))

    return fails


@app.command()
def test(
    type: str = typer.Argument("unit", help="Test type: unit, scenario, e2e"),
    arg: str = typer.Option("", "--arg", help="Scenario name (required for scenario test)"),
):
    """Run tests. Types: unit (default), scenario (requires --arg=<name>), e2e."""

    if type == "unit":
        print("Running unit tests...")
        try:
            subprocess.run(["uv", "run", "pytest", "tests/unit/", "-q", "--tb=short"], check=True, cwd=str(ROOT))
        except subprocess.CalledProcessError:
            raise typer.Exit(1) from None
    elif type == "scenario":
        if not arg:
            print("Error: Scenario name required (e.g. just test scenario --arg 01_arm_takeoff)", file=sys.stderr)
            raise typer.Exit(1) from None
        _build_workspace()
        script = _resolve_scenario_script(arg)
        print(f"Running scenario test: {arg}...")
        try:
            subprocess.run(
                ["uv", "run", "python", str(script)], check=True, cwd=str(ROOT)
            )
        except subprocess.CalledProcessError:
            raise typer.Exit(1) from None

    elif type == "e2e":
        print("starting e2e headless cycle...")

        # Clear per-run logs, keeping build/install cache intact
        print("Clearing previous simulation logs...")
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
            print("Preflight check failed. Aborting E2E cycle.", file=sys.stderr)
            raise typer.Exit(1) from None

        gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"

        # Group scenarios by their required (vision, overlay) sim config and run
        # each group against its own freshly launched, isolated sim. Hold scenarios
        # (hover overlay) must not share a sim with the auto-flown demo mission that
        # path scenarios need, so each config gets a clean boot + teardown.
        configs = scenario_sim_configs("sim")
        if not configs:
            print("Warning: no sim scenarios found in capabilities.toml")
        groups: dict[tuple[str, str], list[str]] = {}
        for cfg in configs:
            groups.setdefault((cfg["vision"], cfg["overlay"]), []).append(cfg["scenario"])

        import atexit

        def cleanup():
            print("Cleaning up E2E simulation...")
            subprocess.run(["uv", "run", "python", "tools/sim_cleanup.py"], cwd=str(ROOT))

        # Safety net: ensure any leaked sim is reaped even if the process is killed
        # mid-group (each group also tears down its own sim in a finally block).
        atexit.register(cleanup)

        try:
            fails = 0
            (LOG_DIR / "latest.log").write_text("", encoding="utf-8")
            group_items = list(groups.items())
            for idx, ((vision, overlay), scenarios) in enumerate(group_items):
                is_last = idx == len(group_items) - 1
                fails += _run_e2e_sim_group(
                    vision,
                    overlay,
                    scenarios,
                    gz_resource=gz_resource,
                    audit_topics=is_last,
                )

            print("Summarizing execution log...")
            _summarize_logs_silent()

            print("Generating E2E Report...")
            subprocess.run(["uv", "run", "python", "tools/e2e_report.py"], cwd=str(ROOT))

            if fails > 0:
                print(f"E2E cycle finished with {fails} failures.", file=sys.stderr)
                raise typer.Exit(fails) from None
            else:
                print("E2E cycle finished successfully (all scenarios passed).")

        except Exception as e:
            print(f"E2E run interrupted: {e}", file=sys.stderr)
            raise typer.Exit(1) from None
        finally:
            cleanup()
            atexit.unregister(cleanup)


@app.command()
def scenario(
    name: str = typer.Argument(..., help="Scenario name (e.g. 01_arm_takeoff)"),
) -> None:
    """Run a live scenario test directly by name."""
    _build_workspace()
    script = _resolve_scenario_script(name)
    print(f"Running scenario test: {name}...")
    passed = False
    try:
        result = subprocess.run(
            ["uv", "run", "python", str(script)], cwd=str(ROOT)
        )
        passed = result.returncode == 0
    finally:
        _summarize_logs_silent()
    if not passed:
        raise typer.Exit(1)


@app.command()
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
