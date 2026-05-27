#!/usr/bin/env python3
"""Verified sim process cleanup.

Sends SIGTERM to all known sim process patterns, waits, SIGKILLs survivors,
then reports any processes that could not be stopped.
Exit 0 if clean, 1 if processes remain after SIGKILL.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

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


def main() -> None:
    initial = _all_live_pids()
    if not initial:
        print('{"stopped": [], "remaining": [], "clean": true}')
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

    import json

    report = {
        "stopped": sorted(initial - remaining),
        "remaining": sorted(remaining),
        "clean": len(remaining) == 0,
    }
    print(json.dumps(report, indent=2))
    sys.exit(0 if report["clean"] else 1)


if __name__ == "__main__":
    main()
