#!/usr/bin/env python3
"""Aggressive sim process cleanup — SIGKILL-first, parallel, no grace period.

SITL processes hold no persistent state that needs flushing, so we skip the
SIGTERM grace window and go straight to SIGKILL.  Artifact cleanup (PX4 locks,
FastDDS shm) runs in parallel with the kill pass so the whole thing finishes
in well under 2 s.

Exit 0 if clean, 1 if processes remain after all kill passes.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_PIDFILE = Path(os.environ.get("SIM_PIDFILE", "logs/sim.pid"))

# Patterns are matched against the full command line (pgrep -f).
# Order doesn't matter — all are killed in one parallel pass.

# Patterns killed during normal `sim stop` — Gazebo intentionally excluded.
_PATTERNS = [
    r"ros2 launch.*sim_full",
    r"sim/launch/sim_full\.launch\.py",
    r"hardware/launch/hardware\.launch\.py",
    r"gz_px4_stack",
    r"/bin/px4$",
    r"MicroXRCEAgent",
    r"parameter_bridge",
    r"rosbridge_websocket",
    r"gcs_heartbeat",
    r"wait_ready",
    r"e2e_sim_test",
    r"install/ros_px4_template_core/lib/ros_px4_template_core/",
    r"install/px4_ros_sim/lib/px4_ros_sim/",
    r"ruby.*ros",      # any Ruby shim spawned by ros_gz_bridge
    r"component_container",
]

# Extra patterns added only when --full is passed (kills Gazebo too).
_FULL_PATTERNS = [*_PATTERNS, r"gz sim", r"gz server", r"gzserver"]

_MY_PID = os.getpid()


def _find_pids(pattern: str) -> list[int]:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        return [int(p) for p in r.stdout.split() if p.isdigit() and int(p) != _MY_PID]
    except Exception:
        return []


def _sigkill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _all_live_pids(patterns: list[str] | None = None) -> set[int]:
    if patterns is None:
        patterns = _PATTERNS
    found: set[int] = set()
    with ThreadPoolExecutor(max_workers=len(patterns)) as ex:
        for pids in ex.map(_find_pids, patterns):
            found.update(pids)
    return found


def _kill_pidfile_group() -> int | None:
    """SIGKILL the entire process group recorded in the pidfile."""
    if not _PIDFILE.exists():
        return None
    try:
        pid = int(_PIDFILE.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        _PIDFILE.unlink(missing_ok=True)
        return None
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    _PIDFILE.unlink(missing_ok=True)
    return pgid


def _clean_artifacts() -> None:
    """Remove PX4 lock files and FastDDS shared memory left behind after kills."""
    for i in range(4):
        for p in [Path(f"/tmp/px4_lock-{i}"), Path(f"/tmp/px4-sock-{i}")]:
            p.unlink(missing_ok=True)
    for p in glob.glob("/dev/shm/fastrtps_*"):
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass


def _stop_ros2_daemon() -> None:
    try:
        subprocess.run(["ros2", "daemon", "stop"], capture_output=True, timeout=5)
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="Stop sim processes.")
    ap.add_argument("--full", action="store_true",
                    help="Also kill Gazebo (full teardown). Default keeps Gazebo warm.")
    args = ap.parse_args()

    patterns = _FULL_PATTERNS if args.full else _PATTERNS

    if args.full:
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).parent))
            from gz_lifecycle import clear_world_record
            clear_world_record()
        except Exception:
            pass

    # --- Pass 1: kill pidfile group + all known patterns in parallel ---
    with ThreadPoolExecutor(max_workers=3) as ex:
        pgid_future = ex.submit(_kill_pidfile_group)
        initial_future = ex.submit(_all_live_pids, patterns)
        ex.submit(_clean_artifacts)

    pgid_hit = pgid_future.result()
    initial = initial_future.result()

    with ThreadPoolExecutor(max_workers=16) as ex:
        ex.map(_sigkill, initial)

    if initial or pgid_hit is not None:
        time.sleep(0.4)

    # --- Pass 2: sweep for survivors ---
    survivors = _all_live_pids(patterns)
    if survivors:
        with ThreadPoolExecutor(max_workers=16) as ex:
            ex.map(_sigkill, survivors)
        time.sleep(0.3)

    _stop_ros2_daemon()

    remaining = _all_live_pids(patterns)

    report = {
        "full": args.full,
        "stopped_via_pidfile": pgid_hit is not None,
        "stopped": sorted((initial | survivors) - remaining),
        "remaining": sorted(remaining),
        "clean": len(remaining) == 0,
    }
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["clean"] else 1)


if __name__ == "__main__":
    main()
