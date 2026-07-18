#!/usr/bin/env uv run
# Runs in the project venv (pyproject.toml). `just _run` invokes `uv run
# tasks.py`, which resolves the project environment now that there is no
# inline script metadata.
# ruff: noqa: E402,S603

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
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


def _source_workspace_env() -> None:
    ws_setup = ROOT / "install" / "setup.bash"
    if not ws_setup.exists():
        return

    cache_file = ROOT / "install" / ".ws_env_cache.json"
    ros_setup = os.environ.get("ROS_SETUP", "/opt/ros/jazzy/setup.bash")
    ros_setup_path = Path(ros_setup)
    key = {
        "setup_mtime_ns": ws_setup.stat().st_mtime_ns,
        "ros_setup": ros_setup,
        "ros_setup_mtime_ns": ros_setup_path.stat().st_mtime_ns if ros_setup_path.exists() else 0,
    }

    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if isinstance(cached, dict) and cached.get("_key") == key:
            env = cached.get("env")
            if isinstance(env, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in env.items()
            ):
                for k, v in env.items():
                    os.environ[k] = v
                return
    except Exception:
        pass

    try:
        cmd = (
            f"source {ws_setup} && "
            "python3 -c 'import os, json; print(json.dumps(dict(os.environ)))'"
        )
        res = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(ROOT),
        )
        new_env = json.loads(res.stdout.strip())
        if isinstance(new_env, dict):
            for k, v in new_env.items():
                if isinstance(k, str) and isinstance(v, str):
                    os.environ[k] = v
            try:
                cache_file.write_text(json.dumps({"_key": key, "env": new_env}), encoding="utf-8")
            except Exception:
                pass
    except Exception as e:
        print(f"Warning: failed to source workspace env: {e}", file=sys.stderr)


@app.callback()
def _bootstrap() -> None:
    """Per-invocation env setup. Runs before every command."""
    _load_dotenv()
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


def _ros2_launch_capture_argv(launch_args: list[str], cwd: Path = ROOT) -> list[str]:
    """``bash -lc`` that sources ROS, then pipes ``ros2 launch`` stdout through the
    live capture filter into stdout. Not ``exec`` because
    a pipeline cannot be exec'd; the whole pipeline lives in the caller's setsid group.
    """
    ros_setup = _ros_setup_path()
    ws_setup = cwd / "install" / "setup.bash"
    sources = [f"source {shlex.quote(ros_setup)}"]
    if ws_setup.exists():
        sources.append(f"source {shlex.quote(str(ws_setup))}")
    launch = "ros2 launch " + " ".join(shlex.quote(a) for a in launch_args)
    capture = "uv run python tools/log_capture.py"
    inner = " && ".join(
        [
            *sources,
            f"cd {shlex.quote(str(cwd))}",
            f"{launch} 2>&1 | {capture}",
        ]
    )
    return ["bash", "-lc", "set -o pipefail; " + inner]


# Ensure tools/ is on path to import sub-apps
sys.path.append(str(ROOT / "tools"))
import bag_recorder
import check_docs
import check_invariants
import check_topics
import e2e_report
import e2e_status as e2e_status_tool
import preflight
import scenario_status as scenario_status_tool
import sim_cleanup
import skein_analyze
import status as status_tool
import ulog_retrieve
import wait_ready
from capabilities import app as cap_app
from capabilities import scenario_sim_configs
from cli_verdict import ExitCode, format_not_ready, format_ready, format_stopped
from log_query import app as log_app
from log_summary import build_run_summary, format_failure_digest
from mission_cli import app as mission_app
from scenario_scaffold import render_scenario

# Register sub-apps
app.add_typer(log_app, name="log", help="Query, merge, tail, or view logs/status/topics.")
app.add_typer(cap_app, name="cap", help="Manage verified capabilities registry.")
app.add_typer(mission_app, name="mission", help="List, validate, and describe mission YAML.")


def _summarize_logs_silent() -> None:
    """Regenerate latest_summary.json from latest.log; non-fatal if absent."""
    try:
        summary = build_run_summary(LOG_DIR / "latest.log")
        (LOG_DIR / "latest_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as e:
        print(f"Warning: log summary skipped: {e}", file=sys.stderr)


def _print_failure_digest() -> None:
    try:
        summary = json.loads((LOG_DIR / "latest_summary.json").read_text(encoding="utf-8"))
        print(format_failure_digest(summary), file=sys.stderr)
    except Exception as e:
        print(f"(failure digest unavailable: {e})", file=sys.stderr)


def _teardown() -> bool:
    """Exhaustive cold teardown of the whole stack. Prints a STOPPED verdict.

    Returns True if nothing survived. Used by `stop`, by failed launches, and at
    every e2e group boundary.
    """
    was_recording = bag_recorder.BAG_PIDFILE.exists()
    bag_recorder.stop()  # graceful SIGINT first; finalizes the MCAP. Non-fatal.
    result = sim_cleanup.teardown()
    if was_recording:
        # PX4 is dead now, so its ULog is final. Best-effort, SITL-only.
        ulog_retrieve.retrieve(bag_recorder.RUNS_DIR / "latest")
    print(format_stopped(result["killed"], result["survivors"]))
    return not result["survivors"]


def _spawn_stack(
    launch_args: list[str], env: dict[str, str], *, append: bool
) -> subprocess.Popen[bytes]:
    """Spawn a detached, captured ros2 launch into logs/latest.log. One launch path
    for sim, hw, and e2e groups. Caller owns readiness checking and teardown.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out_fh = (LOG_DIR / "latest.log").open("a" if append else "w", encoding="utf-8")
    return subprocess.Popen(
        _ros2_launch_capture_argv(launch_args),
        env=env,
        stdout=out_fh,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
        cwd=str(ROOT),
    )


def _resolve_scenario_config(name: str) -> dict | None:
    """Return the declared ``{"scenario", "vision", "overlay", "model", "world"}``
    config for a scenario name from ``tests/capabilities.toml``, or ``None`` if not
    declared.
    """
    for cfg in scenario_sim_configs("sim"):
        if cfg["scenario"] == name:
            return cfg
    return None


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
    raise typer.Exit(int(ExitCode.USAGE)) from None


E2E_STATE = LOG_DIR / "e2e_state.json"
E2E_PIDFILE = LOG_DIR / "e2e.pid"


def _e2e_write_state(state: dict) -> None:
    """Atomically persist e2e progress for `just e2e-status` polling."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = E2E_STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, E2E_STATE)


def _e2e_initial_state(configs: list[dict]) -> dict:
    """Fresh e2e progress state: one isolated sim group per declared scenario."""
    return {
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "groups": [
            {
                "vision": c["vision"],
                "overlay": c["overlay"],
                "model": c["model"],
                "world": c["world"],
                "scenarios": [c["scenario"]],
                "state": "pending",
                "fails": 0,
            }
            for c in configs
        ],
    }


def _pid_running(pidfile: Path) -> bool:
    try:
        os.kill(int(pidfile.read_text().strip()), 0)
        return True
    except (ValueError, ProcessLookupError, FileNotFoundError):
        return False
    except PermissionError:
        return True


def _load_e2e_configs() -> tuple[list[dict], dict]:
    """Topo-ordered e2e roster plus registry; prints excluded claims."""
    from cap_status import real_artifacts_ok
    from capabilities import _load as _load_registry
    from capabilities import e2e_roster

    registry = _load_registry()
    configs, excluded = e2e_roster(registry, real_artifacts_ok)
    for name in excluded:
        print(f"  [NOTE] claim '{name}' is below simulated (not scaffolded) — excluded from e2e")
    return configs, registry


def _e2e_run(configs: list[dict], registry: dict | None = None) -> None:
    """The e2e supervisor loop: one isolated sim per group, incremental state.

    Runs inline for `just test e2e --wait`; otherwise as the detached
    `e2e-worker` process. Raises typer.Exit with the run's exit code.
    """
    import atexit

    def cleanup():
        print("Cleaning up E2E simulation...")
        _teardown()

    # Safety net: ensure any leaked sim is reaped even if the process is killed
    # mid-group (each group also tears down its own sim in a finally block).
    atexit.register(cleanup)

    gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
    failed_claims: set[str] = set()
    state = _e2e_initial_state(configs)
    _e2e_write_state(state)

    try:
        fails = 0
        (LOG_DIR / "latest.log").write_text("", encoding="utf-8")
        for idx, cfg in enumerate(configs):
            state["groups"][idx]["state"] = "running"
            _e2e_write_state(state)
            group_fails = _run_e2e_sim_group(
                cfg["vision"],
                cfg["overlay"],
                [cfg["scenario"]],
                gz_resource=gz_resource,
                model=cfg["model"],
                world=cfg["world"],
                audit_topics=idx == len(configs) - 1,
                registry=registry,
                failed_claims=failed_claims,
            )
            fails += group_fails
            state["groups"][idx]["state"] = "done"
            state["groups"][idx]["fails"] = group_fails
            _e2e_write_state(state)

        print("Summarizing execution log...")
        _summarize_logs_silent()

        print("Generating E2E Report...")
        block, report_code = e2e_report.build_block(LOG_DIR)
        print(block)

        if fails > 0 or report_code != 0:
            state["status"] = "failed"
            _print_failure_digest()
            raise typer.Exit(int(ExitCode.FAIL))
        state["status"] = "passed"
        print("E2E cycle finished successfully (all scenarios passed).")

    except Exception as e:
        if state["status"] == "running":
            print(f"E2E run interrupted: {e}", file=sys.stderr)
            raise typer.Exit(1) from None
        raise
    finally:
        # A worker that dies with status still "running" (unhandled crash,
        # SIGTERM from `just stop`) is reported as aborted by e2e-status.
        if state["status"] == "running":
            state["status"] = "aborted"
        state["finished_at"] = time.time()
        _e2e_write_state(state)
        cleanup()
        atexit.unregister(cleanup)


def _blocked_by(data: dict, scenario: str, failed_claims: set[str]) -> str | None:
    """First transitively-required claim of `scenario` that already failed."""
    from capabilities import claim_for_scenario

    caps = data.get("capabilities", {})
    name = claim_for_scenario(data, scenario)
    if name is None:
        return None
    seen: set[str] = set()
    stack = list(caps.get(name, {}).get("requires", []))
    while stack:
        dep = stack.pop()
        if dep in seen:
            continue
        seen.add(dep)
        if dep in failed_claims:
            return dep
        stack.extend(caps.get(dep, {}).get("requires", []))
    return None


def _auto_record(
    registry: dict,
    scenario: str,
    *,
    vision: str,
    overlay: str,
    model: str,
    world: str,
) -> None:
    """Write evidence for a passing scenario unless the tree is dirty."""
    from cap_evidence import EVIDENCE_ROOT, build_record, dirty_flight_paths, write_record
    from capabilities import claim_for_scenario

    claim = claim_for_scenario(registry, scenario)
    if claim is None:
        return
    entry = registry["capabilities"].get(claim, {})
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    ).stdout
    dirty = dirty_flight_paths(porcelain, entry.get("scenario_file"))
    if dirty:
        print(
            f"  [NOTE] evidence not recorded for {scenario} (dirty tree): commit, then "
            f"just cap record {claim}"
        )
        return
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    ).stdout.strip()
    report = json.loads((LOG_DIR / f"scenario_{scenario}.json").read_text(encoding="utf-8"))
    rec = build_record(
        claim,
        "sim",
        commit,
        report,
        {"world": world, "model": model, "vision": vision},
    )
    write_record(rec, EVIDENCE_ROOT)
    print(f"  [EVIDENCE] {scenario} PASS recorded @ {commit}")


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


def _smart_build(force: bool = True) -> None:
    """Build only when install/ is stale, unless force is False (then never)."""
    if not force:
        _source_workspace_env()
        return
    if _needs_build():
        _build_workspace()
    else:
        print("Build skipped — install/ is up-to-date.")
        _source_workspace_env()


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
                print(
                    f"Auto-detected PX4 version '{version_str}'. "
                    f"Using branch '{px4_msgs_branch}' for px4_msgs."
                )
            else:
                print(
                    f"PX4 version '{version_str}' could not be parsed. "
                    f"Defaulting to '{px4_msgs_branch}'."
                )
        except Exception as e:
            print(
                f"Could not determine PX4 version from PX4_DIR: {e}. "
                f"Defaulting to '{px4_msgs_branch}'."
            )
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


def _clear_log_dir() -> None:
    """Wipe logs/ except .gitkeep (per-run artifacts only; build cache untouched)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for f in LOG_DIR.glob("*"):
        if f.name != ".gitkeep":
            if f.is_file() or f.is_symlink():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)


@app.command()
def clean():
    """Wipe build artifacts, build logs, and per-run logs."""
    print("Cleaning build outputs and log files")
    for folder in ("build", "install", "log"):
        p = ROOT / folder
        if p.exists():
            shutil.rmtree(p)

    _clear_log_dir()
    print("Cleanup complete.")


@app.command()
def check():
    """Format, lint-fix, typecheck, compile, and run unit tests."""
    print("Running checks")

    ruff_paths = ["src/core", "tests", "tools", "sim", "hardware", "tasks.py"]
    ruff_paths_str = [str(ROOT / p) for p in ruff_paths]
    env = _get_clean_env()

    failed_steps: list[str] = []

    print("Running ruff format and lint auto-fixes")
    for label, argv in (
        ("ruff check", ["uv", "run", "ruff", "check", "--fix", *ruff_paths_str]),
        ("ruff format", ["uv", "run", "ruff", "format", *ruff_paths_str]),
    ):
        if subprocess.run(argv, cwd=str(ROOT), env=env).returncode != 0:
            failed_steps.append(label)

    print("Checking branch invariants...")
    if not check_invariants.run():
        failed_steps.append("branch invariants")

    print("Validating claims registry...")
    res = subprocess.run(
        ["uv", "run", "python", "tools/check_capabilities.py"],
        cwd=str(ROOT),
        env=env,
    )
    if res.returncode != 0:
        failed_steps.append("claims registry")

    print("Checking agent docs identifiers...")
    if check_docs.run(ROOT) != 0:
        failed_steps.append("docs identifiers")

    print("Running static typecheck...")
    res = subprocess.run(
        [
            "uv",
            "run",
            "ty",
            "check",
            "src/core/ros_px4_template_core/lib",
            "tests/unit",
            "tools/",
            "tasks.py",
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


def _prepare_stack(preflight_mode: str, build: bool, abort_msg: str) -> None:
    """Teardown any existing stack, preflight, then smart-build. Shared by sim/hw."""
    if (LOG_DIR / "sim.pid").exists():
        print("Existing stack found — tearing it down first.")
        _teardown()
    if not preflight.run(preflight_mode):
        print(abort_msg, file=sys.stderr)
        raise typer.Exit(int(ExitCode.PRECONDITION))
    _smart_build(build)


def _spawn_and_wait(
    launch_args: list[str], env: dict[str, str], timeout: int, fail_reason: str
) -> float:
    """Spawn the detached stack, record sim.pid, block until ready.

    Returns elapsed seconds; on NOT READY prints the verdict, tears down, and
    exits FAIL.
    """
    started = time.monotonic()
    proc = _spawn_stack(launch_args, env, append=False)
    (LOG_DIR / "sim.pid").write_text(str(proc.pid))
    ready = wait_ready.wait(timeout)
    elapsed = time.monotonic() - started
    if not ready:
        print(format_not_ready(fail_reason, elapsed), file=sys.stderr)
        _teardown()
        raise typer.Exit(int(ExitCode.FAIL))
    return elapsed


@app.command()
def sim(
    gui: bool = typer.Option(False, "--gui", help="Show the Gazebo GUI (default headless)."),
    world: str = typer.Option("default", "--world", help="World file name"),
    model: str = typer.Option("x500", "--model", help="Airframe model"),
    vision: str = typer.Option("false", "--vision", help="Enable vision/aruco detection"),
    overlay: str = typer.Option(
        "",
        "--overlay",
        help="Param overlay name from config/params/overlays (default: none, disarmed).",
    ),
    record: bool = typer.Option(
        False, "--record", help="Record an MCAP bag + retrieve the PX4 ULog for `just analyze`."
    ),
    build: bool = typer.Option(True, "--build/--no-build", help="Smart-build before launch."),
    timeout: int = typer.Option(180, "--timeout", help="Seconds to wait for readiness."),
):
    """Boot the sim stack detached, wait until ready, print a verdict, and return.

    Never holds the terminal. Watch with `just log tail`; stop with `just stop`.
    """
    overlays_dir = ROOT / "config" / "params" / "overlays"
    valid = sorted(p.stem for p in overlays_dir.glob("*.yaml"))
    if overlay and overlay not in valid:
        print(f"UNKNOWN OVERLAY '{overlay}'. Valid: {', '.join(valid)}", file=sys.stderr)
        raise typer.Exit(int(ExitCode.USAGE))

    _prepare_stack("headless", build, "Preflight failed. Aborting launch.")

    gz_resource = f"{ROOT}/sim/worlds:{ROOT}/sim/models"
    vision_arg = "aruco" if vision.lower() in ("true", "aruco") else "none"
    headless_val = "false" if gui else "true"
    overlay_args = [f"param_overlay:={overlay}"] if overlay else []
    launch_args = [
        str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
        f"world:={world}",
        f"model:={model}",
        f"headless:={headless_val}",
        f"log_dir:={LOG_DIR}",
        f"vision:={vision_arg}",
        *overlay_args,
    ]
    env = _ros_launch_env(
        GZ_IP="127.0.0.1",
        GZ_SIM_RESOURCE_PATH=f"{gz_resource}:{os.environ.get('GZ_SIM_RESOURCE_PATH', '')}",
        **({"HEADLESS": "1"} if not gui else {}),
    )

    elapsed = _spawn_and_wait(
        launch_args,
        env,
        timeout,
        "stack did not reach readiness (topics/rosbridge/GCS params)",
    )

    # readiness confirmed past this point
    if record:
        run_dir = bag_recorder.new_run_dir()
        bag_proc = bag_recorder.start(run_dir, env)
        rec_detail = (
            f"recording -> {run_dir.relative_to(ROOT)}/bag"
            if bag_proc is not None
            else "recording: DISABLED (recorder failed to start)"
        )
    else:
        bag_recorder.BAG_PIDFILE.unlink(missing_ok=True)
        rec_detail = "recording: off (use --record)"
    print(
        format_ready(
            ["/fmu topics up", "rosbridge:9090", "GCS params committed", rec_detail],
            elapsed,
        )
    )


@app.command()
def stop():
    """Exhaustive cold teardown of the whole stack (no process survives)."""
    # Kill a detached e2e supervisor first so it cannot relaunch sims while
    # teardown runs; its state file records the abort for `just e2e-status`.
    if E2E_PIDFILE.exists():
        try:
            pid = int(E2E_PIDFILE.read_text().strip())
            os.killpg(pid, signal.SIGTERM)
            print(f"Stopped e2e supervisor (pid {pid}).")
        except (ValueError, ProcessLookupError, PermissionError):
            pass
        E2E_PIDFILE.unlink(missing_ok=True)
        if E2E_STATE.exists():
            try:
                state = json.loads(E2E_STATE.read_text(encoding="utf-8"))
                if state.get("status") == "running":
                    state["status"] = "aborted"
                    state["finished_at"] = time.time()
                    _e2e_write_state(state)
            except json.JSONDecodeError:
                pass
    ok = _teardown()
    raise typer.Exit(int(ExitCode.OK) if ok else int(ExitCode.FAIL))


@app.command()
def analyze(
    run: str = typer.Argument("latest", help="Run id under logs/runs/, or 'latest'."),
    query: str = typer.Option(
        "",
        "--query",
        "-q",
        help="Run `skein query --where <expr>` on the aligned MCAP after overlay.",
    ),
    channel: str = typer.Option(
        "vehicle_local_position", "--channel", "-c", help="Channel for --query."
    ),
    stats: bool = typer.Option(False, "--stats", help="Per-channel aggregates for --query."),
):
    """Overlay a recorded run's bag + ULog onto one timeline with skein, writing
    logs/runs/<run>/aligned.mcap. With --query, also query that aligned MCAP.

    skein is invoked as a separate uv project (uv run --project). Override its
    location with SKEIN_DIR (default: ../skein beside this repo).
    """
    try:
        skein_dir = skein_analyze.resolve_skein_dir()
        run_dir = skein_analyze.resolve_run_dir(run)
    except skein_analyze.AnalyzeError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(int(ExitCode.USAGE)) from None

    bag = skein_analyze.find_bag_mcap(run_dir)
    ulog = run_dir / "session.ulg"
    ulog = ulog if ulog.is_file() else None
    if bag is None and ulog is None:
        print(
            f"Error: run {run_dir.name} has neither a bag (logs/runs/<id>/bag/*.mcap) "
            "nor a session.ulg — did it record? (see plans 009/010)",
            file=sys.stderr,
        )
        raise typer.Exit(int(ExitCode.USAGE))
    if ulog is None:
        print("Warning: no session.ulg for this run — overlaying bag only.", file=sys.stderr)
    if bag is None:
        print("Warning: no bag for this run — overlaying ULog only.", file=sys.stderr)

    out = run_dir / "aligned.mcap"
    env = _get_clean_env()
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(skein_analyze.skein_venv_dir()))
    print(f"Overlaying {run_dir.name} -> {out.relative_to(ROOT)}")
    res = subprocess.run(
        skein_analyze.overlay_argv(skein_dir, bag=bag, ulog=ulog, out=out),
        cwd=str(ROOT),
        env=env,
    )
    if res.returncode != 0:
        print("skein overlay failed.", file=sys.stderr)
        raise typer.Exit(int(ExitCode.FAIL))

    if query:
        res = subprocess.run(
            skein_analyze.query_argv(skein_dir, out, channel=channel, where=query, stats=stats),
            cwd=str(ROOT),
            env=env,
        )
        if res.returncode != 0:
            print("skein query failed.", file=sys.stderr)
            raise typer.Exit(int(ExitCode.FAIL))

    print(f"ANALYZED {run_dir.name}: aligned.mcap written" + (" + query ok" if query else ""))


@app.command()
def hw(
    port: str = typer.Option("/dev/ttyUSB0", "--port", help="Serial port for the FC"),
    baud: int = typer.Option(921600, "--baud", help="Baudrate"),
    vehicle: str = typer.Option("", "--vehicle", help="Vehicle overlay name (e.g. x500)"),
    build: bool = typer.Option(True, "--build/--no-build", help="Smart-build before launch."),
    timeout: int = typer.Option(180, "--timeout", help="Seconds to wait for readiness."),
):
    """Boot the hardware stack detached, wait until ready, print a verdict, return.

    Same no-terminal-capture contract as `just sim`. Watch with `just log tail`,
    stop with `just stop`.
    """
    if vehicle:
        vehicle_path = ROOT / "vehicles" / f"{vehicle}.yaml"
        if not vehicle_path.is_file():
            print(f"Vehicle overlay not found: {vehicle_path}", file=sys.stderr)
            raise typer.Exit(int(ExitCode.USAGE))

    _prepare_stack("hw", build, "Preflight failed. Aborting hardware launch.")

    print(f"Connecting to hardware on {port} at {baud} baud...")
    launch_args = [
        str(ROOT / "hardware" / "launch" / "hardware.launch.py"),
        f"serial_port:={port}",
        f"baudrate:={baud}",
        "use_sim_time:=false",
        "config:=hardware",
        f"log_dir:={LOG_DIR}",
        f"vehicle:={vehicle}",
    ]
    env = _ros_launch_env()

    elapsed = _spawn_and_wait(
        launch_args, env, timeout, "hardware stack did not reach readiness (topics/rosbridge)"
    )
    print(format_ready([f"FC {port}@{baud}", "rosbridge:9090", "/fmu topics up"], elapsed))


def _fallback_scenario_report(scenario: str, reason: str, config: dict[str, str]) -> str:
    """JSON text for a scenario that produced no fresh report of its own.

    Same shape as ``write_report`` in tests/scenarios/_common.py so every
    consumer (e2e report block, log summary, scenario-status) reads it
    unchanged.
    """
    return (
        json.dumps(
            {
                "scenario": scenario,
                "passed": False,
                "elapsed_s": 0.0,
                "detail": {"reason": reason, **config},
            },
            indent=2,
        )
        + "\n"
    )


def _run_e2e_sim_group(
    vision: str,
    overlay: str,
    scenarios: list[str],
    *,
    gz_resource: str,
    model: str = "x500",
    world: str = "default",
    audit_topics: bool = False,
    registry: dict | None = None,
    failed_claims: set[str] | None = None,
) -> int:
    """Launch one isolated headless sim for a ``(vision, overlay, model, world)``
    config, wait for readiness, run the given scenarios sequentially, optionally
    audit the topic graph, then tear the sim down.

    Isolating each config keeps hold scenarios (hover overlay, no path) from racing
    the auto-flown waypoint mission that the demo path scenarios need. Returns the
    number of failed scenarios in this group (a sim that never becomes ready counts
    every scenario in the group as failed).
    """
    pidfile = LOG_DIR / "sim.pid"
    latest = LOG_DIR / "latest.log"
    banner = (
        f"=== Sim group: vision={vision} overlay={overlay} model={model} world={world} "
        f"({', '.join(scenarios)}) ==="
    )
    with latest.open("a", encoding="utf-8") as fh:
        fh.write(banner + "\n")
    print(f"\n{banner}")
    print("Starting background headless simulation (-> logs/latest.log)...")

    launch_args = [
        str(ROOT / "sim" / "launch" / "sim_full.launch.py"),
        f"world:={world}",
        f"model:={model}",
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

    proc = _spawn_stack(launch_args, env, append=True)
    pidfile.write_text(str(proc.pid))

    fails = 0
    try:
        print("Waiting for simulation to stabilize...")
        if not wait_ready.wait(180):
            print(
                f"  [FAIL] sim never became ready; failing {len(scenarios)} scenario(s) "
                f"in group (vision={vision} overlay={overlay} model={model} world={world})",
                file=sys.stderr,
            )
            # Write a failure report per scenario (same shape as write_report in
            # tests/scenarios/_common.py) so the e2e report block lists them
            # instead of silently omitting scenarios that never ran.
            if registry is not None and failed_claims is not None:
                from capabilities import claim_for_scenario

                for s in scenarios:
                    failed_claims.add(claim_for_scenario(registry, s) or s)
            for s in scenarios:
                (LOG_DIR / f"scenario_{s}.json").write_text(
                    _fallback_scenario_report(
                        s,
                        "sim_never_ready",
                        {
                            "vision": vision,
                            "overlay": overlay,
                            "model": model,
                            "world": world,
                        },
                    ),
                    encoding="utf-8",
                )
            return len(scenarios)

        for s in scenarios:
            if registry is not None and failed_claims is not None:
                blocker = _blocked_by(registry, s, failed_claims)
                if blocker is not None:
                    fails += 1
                    print(
                        f"  [SKIP] {s}: prerequisite claim '{blocker}' failed this run",
                        file=sys.stderr,
                    )
                    (LOG_DIR / f"scenario_{s}.json").write_text(
                        _fallback_scenario_report(
                            s,
                            f"prerequisite_failed:{blocker}",
                            {
                                "vision": vision,
                                "overlay": overlay,
                                "model": model,
                                "world": world,
                            },
                        ),
                        encoding="utf-8",
                    )
                    continue

            print(f"Running scenario {s}...")
            report = LOG_DIR / f"scenario_{s}.json"
            started_at = time.time()
            res_s = subprocess.run(
                ["uv", "run", "python", f"tests/scenarios/{s}.py"], cwd=str(ROOT)
            )
            fresh = report.exists() and report.stat().st_mtime >= started_at
            if res_s.returncode != 0:
                fails += 1
                if registry is not None and failed_claims is not None:
                    from capabilities import claim_for_scenario

                    failed_claims.add(claim_for_scenario(registry, s) or s)
                if not fresh:
                    print(
                        f"  [FAIL] {s} exited {res_s.returncode} without writing a report; "
                        "synthesizing crashed_before_report",
                        file=sys.stderr,
                    )
                    report.write_text(
                        _fallback_scenario_report(
                            s,
                            "crashed_before_report",
                            {
                                "vision": vision,
                                "overlay": overlay,
                                "model": model,
                                "world": world,
                            },
                        ),
                        encoding="utf-8",
                    )
            elif not fresh:
                # Exit 0 but no fresh report: never trust it as a pass.
                fails += 1
                if registry is not None and failed_claims is not None:
                    from capabilities import claim_for_scenario

                    failed_claims.add(claim_for_scenario(registry, s) or s)
                print(
                    f"  [FAIL] {s} exited 0 but wrote no report; counting as FAIL",
                    file=sys.stderr,
                )
                report.write_text(
                    _fallback_scenario_report(
                        s,
                        "no_report_written",
                        {
                            "vision": vision,
                            "overlay": overlay,
                            "model": model,
                            "world": world,
                        },
                    ),
                    encoding="utf-8",
                )
            elif registry is not None:
                _auto_record(
                    registry,
                    s,
                    vision=vision,
                    overlay=overlay,
                    model=model,
                    world=world,
                )

        if audit_topics:
            print("Auditing topic graph...")
            if check_topics.run(Path("docs/TOPICS.md")) != 0:
                print("  [FAIL] topic graph violates docs/TOPICS.md", file=sys.stderr)
                fails += 1
    finally:
        print(
            f"Tearing down sim group (vision={vision} overlay={overlay} "
            f"model={model} world={world})..."
        )
        _teardown()

    return fails


@app.command()
def test(
    type: str = typer.Argument("unit", help="Test type: unit, scenario, e2e"),
    arg: str = typer.Option("", "--arg", help="Scenario name (required for scenario test)"),
    detach: bool = typer.Option(
        False,
        "--detach",
        help="e2e only: run in a background supervisor; poll with just e2e-status.",
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        hidden=True,
        help="Deprecated: e2e blocks by default; this flag is a no-op.",
    ),
):
    """Run tests. Types: unit (default), scenario (requires --arg=<name>), e2e.

    e2e blocks by default: it captures the terminal for the whole cycle and ends
    with the aggregate PASS/FAIL verdict and exit code. Pass --detach to run it
    in a background supervisor instead (returns after an E2E STARTED verdict;
    poll with `just e2e-status`, stop with `just stop`).
    """

    if type == "unit":
        print("Running unit tests...")
        try:
            subprocess.run(
                ["uv", "run", "pytest", "tests/unit/", "-q", "--tb=short"],
                check=True,
                cwd=str(ROOT),
            )
        except subprocess.CalledProcessError:
            raise typer.Exit(int(ExitCode.FAIL)) from None
    elif type == "scenario":
        if not arg:
            print(
                "Error: Scenario name required (e.g. just test scenario --arg 01_arm_takeoff)",
                file=sys.stderr,
            )
            raise typer.Exit(int(ExitCode.USAGE)) from None
        _smart_build(True)
        script = _resolve_scenario_script(arg)
        print(f"Running scenario test: {arg}...")
        try:
            subprocess.run(["uv", "run", "python", str(script)], check=True, cwd=str(ROOT))
        except subprocess.CalledProcessError:
            raise typer.Exit(int(ExitCode.FAIL)) from None

    elif type == "e2e":
        print("starting e2e headless cycle...")

        if E2E_PIDFILE.exists() and _pid_running(E2E_PIDFILE):
            print(
                "An e2e run is already in progress (logs/e2e.pid). "
                "Watch: just e2e-status. Stop: just stop.",
                file=sys.stderr,
            )
            raise typer.Exit(int(ExitCode.PRECONDITION))

        # Clear per-run logs, keeping build/install cache intact
        print("Clearing previous simulation logs...")
        _clear_log_dir()

        _smart_build(True)

        if not preflight.run("gui"):
            print("Preflight check failed. Aborting E2E cycle.", file=sys.stderr)
            raise typer.Exit(int(ExitCode.PRECONDITION)) from None

        # Run each declared scenario against its own freshly launched, isolated sim.
        # Scenarios land, disarm, and mutate controller parameters during cleanup,
        # so sharing a sim can leak state into the next scenario even when the
        # requested vision/overlay config is identical.
        configs, registry = _load_e2e_configs()
        if not configs:
            print(
                "No sim scenarios declared in tests/capabilities.toml (platforms must "
                "include 'sim'). Refusing to report a vacuous e2e pass.",
                file=sys.stderr,
            )
            raise typer.Exit(int(ExitCode.PRECONDITION))

        if not detach:
            # Blocking by default: capture the terminal, end with the aggregate
            # verdict and exit code. `--wait` is the deprecated no-op alias.
            _e2e_run(configs, registry=registry)
            return

        # Seed the state file before spawning so `just e2e-status` never sees
        # a live pid with no state (the worker overwrites it on startup).
        _e2e_write_state(_e2e_initial_state(configs))
        out_fh = (LOG_DIR / "e2e.log").open("w", encoding="utf-8")
        proc = subprocess.Popen(
            ["uv", "run", "python", "tasks.py", "e2e-worker"],
            stdout=out_fh,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=str(ROOT),
        )
        E2E_PIDFILE.write_text(str(proc.pid))
        n = len(configs)
        print(
            f"E2E STARTED: {len(configs)} scenario(s) in {n} group(s), "
            f"est ~{max(1, round(n * 65 / 60))} min. "
            "Watch: just e2e-status | just log tail. Stop: just stop."
        )


@app.command("e2e-worker", hidden=True)
def e2e_worker() -> None:
    """Internal: the detached e2e supervisor. Launched by `just test e2e`."""
    configs, registry = _load_e2e_configs()
    _e2e_run(configs, registry=registry)


@app.command("e2e-status")
def e2e_status_cmd() -> None:
    """Print progress/verdict of the current or last e2e run (poll while detached)."""
    text, code = e2e_status_tool.build_status(
        LOG_DIR, e2e_status_tool._pid_alive(LOG_DIR / "e2e.pid")
    )
    print(text)
    raise typer.Exit(code)


@app.command()
def scenario(
    name: str = typer.Argument(..., help="Scenario name (e.g. 01_arm_takeoff)"),
) -> None:
    """Run a live scenario test directly by name.

    Boots the sim config (vision/overlay) the scenario declares in
    ``tests/capabilities.toml``, runs it in isolation, and tears the sim down
    afterward — matching the e2e harness so a manual single run can't be
    silently tested against the wrong mission. Scenarios with no declared
    config fall back to running against whatever sim is already up.
    """
    _smart_build(True)
    script = _resolve_scenario_script(name)
    cfg = _resolve_scenario_config(name)
    if cfg is None:
        print(
            f"No declared sim config for '{name}' in tests/capabilities.toml — "
            "running against the existing sim (start one with `just sim` first). "
            f"To make `just scenario {name}` boot the right sim, add the entry "
            'with platforms = ["sim"] (see `just scenario-new` output).'
        )
        print(f"Running scenario test: {name}...")
        try:
            result = subprocess.run(["uv", "run", "python", str(script)], cwd=str(ROOT))
            fails = 0 if result.returncode == 0 else 1
        finally:
            _summarize_logs_silent()
    else:
        print(f"Tearing down any existing stack before booting {name}'s declared sim...")
        _teardown()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR / "latest.log").write_text("", encoding="utf-8")
        try:
            fails = _run_e2e_sim_group(
                cfg["vision"],
                cfg["overlay"],
                [cfg["scenario"]],
                gz_resource=f"{ROOT}/sim/worlds:{ROOT}/sim/models",
                model=cfg["model"],
                world=cfg["world"],
            )
        finally:
            _summarize_logs_silent()
    if fails:
        _print_failure_digest()
        raise typer.Exit(int(ExitCode.FAIL))


@app.command("scenario-new")
def scenario_new(
    name: str = typer.Argument(..., help="Scenario name, e.g. 04_my_check"),
) -> None:
    """Scaffold a runnable Scenario stub at tests/scenarios/<name>.py.

    Writes a stub modeled on 03_waypoint.py (a `_Node` plus a `Scenario`
    subclass); edit the `done()` predicate, add a tests/capabilities.toml entry,
    then run `just scenario <name>`.
    """
    target = ROOT / "tests" / "scenarios" / f"{name}.py"
    if target.exists():
        print(f"refusing to overwrite existing {target}", file=sys.stderr)
        raise typer.Exit(int(ExitCode.USAGE))
    target.write_text(render_scenario(name), encoding="utf-8")
    cap_id = re.sub(r"^\d+_", "", name) or name
    print(f"Wrote {target}")
    print("Next steps:")
    print(f"  1. Edit the done() / report_detail() predicate in {target}")
    print("  2. Register it in tests/capabilities.toml, e.g.:\n")
    print(f"[capabilities.{cap_id}]")
    print('description = "TODO one-line claim"')
    print('requires = ["arm_takeoff"]')
    print(f'scenario_file = "{name}.py"')
    print('platforms = ["sim"]')
    print('sim_vision = "none"')
    print('sim_overlay = "auto_arm"')
    print('sim_world = "default"')
    print('sim_model = "x500"')
    print(f"  3. Run it:  just scenario {name}")


@app.command()
def status():
    """Concise English workspace snapshot (nodes, live status, capabilities)."""
    status_tool.main()


@app.command("scenario-status")
def scenario_status(
    name: str = typer.Argument("", help="Scenario name; default: the most recent run."),
) -> None:
    """Print the verdict of one scenario's last run from logs/scenario_<name>.json."""
    line, code = scenario_status_tool.format_scenario_status(LOG_DIR, name or None)
    print(line)
    raise typer.Exit(code)


@log_app.command()
def topics(
    vision: bool = typer.Option(
        False, "--vision", help="Also enforce vision-conditional topics (default: skip them)"
    ),
):
    """Audit live topics against docs/TOPICS.md."""
    raise typer.Exit(check_topics.run(Path("docs/TOPICS.md"), vision=vision))


if __name__ == "__main__":
    app()
