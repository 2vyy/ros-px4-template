#!/usr/bin/env python3
"""Verified sim process cleanup.

Sends SIGTERM to all known sim process patterns, waits, SIGKILLs survivors,
then reports any processes that could not be stopped.
Exit 0 if clean, 1 if processes remain after SIGKILL.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_PIDFILE = Path(os.environ.get("SIM_PIDFILE", "logs/sim.pid"))

_PATTERNS = [
    r"ros2 launch.*sim_full",
    r"sim/launch/sim_full\.launch\.py",
    r"hardware/launch/hardware\.launch\.py",
    r"gz_px4_stack",
    r"/bin/px4$",
    r"MicroXRCEAgent",
    r"gz sim",
    r"parameter_bridge",
    r"rosbridge_websocket",
    r"gcs_heartbeat",
    r"e2e_sim_test",
    r"install/ros_px4_template_core/lib/ros_px4_template_core/",
    r"install/px4_ros_sim/lib/px4_ros_sim/",
]

_MY_PID = os.getpid()


def _find_pids(pattern: str) -> list[int]:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        return [int(p) for p in r.stdout.split() if p.isdigit() and int(p) != _MY_PID]
    except Exception:
        return []


def _kill_pids(pids: list[int], sig: signal.Signals) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            pass


def _all_live_pids() -> set[int]:
    found: set[int] = set()
    for pat in _PATTERNS:
        found.update(_find_pids(pat))
    return found


def _kill_pidfile_group() -> int | None:
    """If logs/sim.pid exists, SIGTERM that process group. Returns the pgid hit, or None."""
    if not _PIDFILE.exists():
        return None
    try:
        pid = int(_PIDFILE.read_text().strip())
    except (ValueError, OSError):
        return None
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        # stale pidfile
        _PIDFILE.unlink(missing_ok=True)
        return None
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    return pgid


def main() -> None:
    pgid_hit = _kill_pidfile_group()
    if pgid_hit is not None:
        time.sleep(2.0)
        # SIGKILL any survivors in the group
        try:
            os.killpg(pgid_hit, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        _PIDFILE.unlink(missing_ok=True)

    initial = _all_live_pids()
    if not initial:
        print(
            json.dumps(
                {
                    "stopped_via_pidfile": pgid_hit is not None,
                    "stopped": [],
                    "remaining": [],
                    "clean": True,
                }
            )
        )
        return

    _kill_pids(list(initial), signal.SIGTERM)
    time.sleep(3.0)

    survivors = _all_live_pids()
    if survivors:
        _kill_pids(list(survivors), signal.SIGKILL)
        time.sleep(1.0)

    remaining = _all_live_pids()

    # Stop ros2 daemon too
    try:
        subprocess.run(
            ["ros2", "daemon", "stop"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass

    report = {
        "stopped_via_pidfile": pgid_hit is not None,
        "stopped": sorted(initial - remaining),
        "remaining": sorted(remaining),
        "clean": len(remaining) == 0,
    }
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["clean"] else 1)


if __name__ == "__main__":
    main()
