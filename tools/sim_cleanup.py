#!/usr/bin/env python3
"""Violent sim teardown — SIGKILL everything, no grace period."""

from __future__ import annotations

import glob
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_PIDFILE = Path(os.environ.get("SIM_PIDFILE", "logs/sim.pid"))

_PATTERNS = [
    r"ros2 launch.*sim_full",
    r"sim/launch/sim_full\.launch\.py",
    r"hardware/launch/hardware\.launch\.py",
    r"gz_px4_stack",
    r"/bin/px4$",
    r"parameter_bridge",
    r"MicroXRCEAgent",
    r"rosbridge_websocket",
    r"gcs_heartbeat",
    r"wait_ready",
    r"e2e_sim_test",
    r"install/ros_px4_template_core/lib/ros_px4_template_core/",
    r"ruby.*ros",
    r"ruby.*gz",
    r"ruby.*sim",
    r"component_container",
    r"tests/scenarios/",
    r"scratch/",
    r"pose_monitor",
    r"debug_setpoints",
    r"offboard_controller",
    r"mission_manager",
    r"position_node",
    r"aruco_pose_publisher",
    r"ros_gz_bridge",
    r"pytest",
    r"ros2 run",
    r"ros2 topic",
    r"ros2 service",
    r"ros2 node",
    r"ros2 param",
    r"ros2 action",
    r"ros2 daemon",
    r"gz sim",
    r"gz server",
    r"gzserver",
    r"gz client",
    r"gzclient",
    r"gz-sim-server",
    r"gz-sim-gui",
]

_EXACT_NAMES = [
    "px4",
    "MicroXRCEAgent",
    "parameter_bridge",
    "ros_gz_bridge",
    "component_container",
    "component_container_mt",
    "rosbridge_websocket",
    "rosapi_node",
    "zenoh",
    "zenoh-bridge-dds",
    "gz-sim-server",
    "gz-sim-gui",
    "gzserver",
    "gzclient",
    "gz",
]

_MY_PID = os.getpid()


def _get_ancestor_pids() -> set[int]:
    pids = {os.getpid()}
    try:
        pid = os.getpid()
        while True:
            stat_path = Path(f"/proc/{pid}/stat")
            if not stat_path.exists():
                break
            parts = stat_path.read_text().split()
            ppid = int(parts[3])
            if ppid <= 0 or ppid in pids:
                break
            pids.add(ppid)
            pid = ppid
    except Exception:
        try:
            pids.add(os.getppid())
        except Exception:
            pass
    return pids


def _find_pids(pattern: str, ancestor_pids: set[int]) -> list[int]:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        return [int(p) for p in r.stdout.split() if p.isdigit() and int(p) not in ancestor_pids]
    except Exception:
        return []


def _find_pids_by_name(name: str, ancestor_pids: set[int]) -> list[int]:
    try:
        r = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True)
        return [int(p) for p in r.stdout.split() if p.isdigit() and int(p) not in ancestor_pids]
    except Exception:
        return []


def _sigkill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _all_live_pids(ancestor_pids: set[int]) -> set[int]:
    found: set[int] = set()
    with ThreadPoolExecutor(max_workers=max(1, len(_PATTERNS))) as ex:
        for pids in ex.map(lambda p: _find_pids(p, ancestor_pids), _PATTERNS):
            found.update(pids)
    with ThreadPoolExecutor(max_workers=max(1, len(_EXACT_NAMES))) as ex:
        for pids in ex.map(lambda n: _find_pids_by_name(n, ancestor_pids), _EXACT_NAMES):
            found.update(pids)
    return found


def _kill_pidfile_group() -> int | None:
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
    for i in range(4):
        for p in [Path(f"/tmp/px4_lock-{i}"), Path(f"/tmp/px4-sock-{i}")]:
            p.unlink(missing_ok=True)
    for p in glob.glob("/tmp/launch_params_*"):
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    for p in glob.glob("/dev/shm/fastrtps_*"):
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            pass
    Path("/tmp/gcs_params_flag").unlink(missing_ok=True)


def _stop_ros2_daemon() -> None:
    try:
        subprocess.run(["ros2", "daemon", "stop"], capture_output=True, timeout=5)
    except Exception:
        pass


def _proc_name(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return "?"


def main() -> None:
    ancestor_pids = _get_ancestor_pids()

    with ThreadPoolExecutor(max_workers=3) as ex:
        pgid_future = ex.submit(_kill_pidfile_group)
        initial_future = ex.submit(_all_live_pids, ancestor_pids)
        ex.submit(_clean_artifacts)

    pgid_hit = pgid_future.result()
    initial = initial_future.result()
    names: dict[int, str] = {pid: _proc_name(pid) for pid in initial}

    with ThreadPoolExecutor(max_workers=16) as ex:
        ex.map(_sigkill, initial)

    if initial or pgid_hit is not None:
        time.sleep(0.4)

    survivors = _all_live_pids(ancestor_pids)
    if survivors:
        names.update({pid: _proc_name(pid) for pid in survivors - initial})
        with ThreadPoolExecutor(max_workers=16) as ex:
            ex.map(_sigkill, survivors)
        time.sleep(0.3)

    _stop_ros2_daemon()

    remaining = _all_live_pids(ancestor_pids)
    killed = sorted((initial | survivors) - remaining)

    if killed:
        col = max(len(names.get(p, "?")) for p in killed)
        for pid in killed:
            print(f"{names.get(pid, '?'):<{col}}  {pid}")
    else:
        print("nothing to kill")

    sys.exit(0 if not remaining else 1)


if __name__ == "__main__":
    main()
