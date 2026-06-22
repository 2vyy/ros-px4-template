#!/usr/bin/env python3
"""Per-run ROS 2 MCAP bag recorder for `just sim`.

Starts `ros2 bag record` detached in its own process group, writing an MCAP bag
under logs/runs/<run-id>/bag/. Stops it with SIGINT (graceful — required so the
open MCAP is finalized, not truncated) and only SIGKILLs the group as a last
resort. Recording is best-effort: a failure here never aborts the sim.
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
RUNS_DIR = LOG_DIR / "runs"
BAG_PIDFILE = LOG_DIR / "bag.pid"

# Subset of docs/TOPICS.md recorded for cross-clock analysis. /clock feeds skein's
# SIM_ELAPSED domain; vehicle_local_position is the common signal skein
# cross-correlates against the PX4 ULog for PX4_BOOT alignment. Keep in sync with
# docs/TOPICS.md (this is the minimum useful set, not `-a`).
_BAG_TOPICS: list[str] = [
    "/clock",
    "/fmu/out/vehicle_local_position_v1",
    "/fmu/out/vehicle_status_v1",
    "/fmu/in/trajectory_setpoint",
    "/fmu/in/offboard_control_mode",
    "/fmu/in/vehicle_command",
    "/drone/odom",
    "/drone/target_pose",
    "/drone/mission_status",
]


def _ros_setup_path() -> str:
    return os.environ.get("ROS_SETUP", "/opt/ros/jazzy/setup.bash")


def new_run_dir(now: datetime | None = None) -> Path:
    """Create and return logs/runs/<YYYYmmdd_HHMMSS>/ and update the
    logs/runs/latest symlink to point at it."""
    run_id = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    latest = RUNS_DIR / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(run_id)  # relative target
    except OSError:
        pass
    return run_dir


def _record_argv(run_dir: Path, topics: list[str]) -> list[str]:
    """A `bash -lc` that sources ROS (+ workspace if built), then EXECs
    `ros2 bag record` so SIGINT to the process group reaches ros2 directly."""
    ros_setup = _ros_setup_path()
    ws_setup = ROOT / "install" / "setup.bash"
    sources = [f"source {shlex.quote(ros_setup)}"]
    if ws_setup.exists():
        sources.append(f"source {shlex.quote(str(ws_setup))}")
    rec = (
        "ros2 bag record -s mcap -o "
        + shlex.quote(str(run_dir / "bag"))
        + " "
        + " ".join(shlex.quote(t) for t in topics)
    )
    inner = " && ".join([*sources, f"exec {rec}"])
    return ["bash", "-lc", inner]


def start(
    run_dir: Path,
    env: dict[str, str],
    *,
    topics: list[str] | None = None,
    spawn=subprocess.Popen,
) -> subprocess.Popen[bytes] | None:
    """Spawn the detached recorder into its own setsid group; record its pid in
    logs/bag.pid. Best-effort: returns None and prints a warning on failure
    (never raises, so a missing mcap storage plugin can't abort the sim)."""
    topics = topics or _BAG_TOPICS
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_fh = (run_dir / "bag_record.log").open("w", encoding="utf-8")
    try:
        proc = spawn(
            _record_argv(run_dir, topics),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
            cwd=str(ROOT),
        )
    except Exception as e:
        print(f"Warning: bag recorder failed to start: {e}", file=sys.stderr)
        return None
    BAG_PIDFILE.write_text(str(proc.pid))
    return proc


def _getpgid(pid: int) -> int:
    return os.getpgid(pid)


def _killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop(*, timeout: float = 15.0) -> bool:
    """SIGINT the recorder's process group and wait up to `timeout`s for it to
    finalize the MCAP. SIGKILL the group only as a last resort. Returns True if
    it stopped cleanly (or nothing was recording). Never raises."""
    if not BAG_PIDFILE.exists():
        return True
    try:
        pid = int(BAG_PIDFILE.read_text().strip())
    except (ValueError, OSError):
        BAG_PIDFILE.unlink(missing_ok=True)
        return True
    try:
        pgid = _getpgid(pid)
    except ProcessLookupError:
        BAG_PIDFILE.unlink(missing_ok=True)
        return True

    _killpg(pgid, signal.SIGINT)
    deadline = time.monotonic() + timeout
    clean = False
    while time.monotonic() < deadline:
        if not _alive(pid):
            clean = True
            break
        time.sleep(0.2)
    if not clean:
        _killpg(pgid, signal.SIGKILL)
    BAG_PIDFILE.unlink(missing_ok=True)
    return clean
