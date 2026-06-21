#!/usr/bin/env python3
"""Exhaustive cold sim teardown — SIGKILL everything, verify no survivor.

Importable: ``teardown()`` returns a result dict the CLI formats into a verdict.
Also runnable as a script (``main()``) for any remaining subprocess callers.
There is no warm/keep-Gazebo path: teardown is always fully cold.
"""

from __future__ import annotations

import glob
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

_PIDFILE = Path(os.environ.get("SIM_PIDFILE", "logs/sim.pid"))

# Matching is deliberately precise. A false positive here is catastrophic: this
# code runs INSIDE distrobox in normal use, where /proc may expose host processes
# (the podman/distrobox wrapper, the terminal, the agent itself). Killing one of
# those wedges the very session we are trying to keep healthy. So we match only
# (a) exact executable basenames of our stack, or (b) specific script-path
# fragments, and we NEVER touch an infrastructure process regardless of what its
# command line happens to contain (e.g. a wrapper bash whose argv includes the
# repo path "ros-px4-template" or "tests/scenarios/...").

# Killed when the process's argv[0] basename matches exactly.
_EXACT_BASENAMES: set[str] = {
    "px4",
    "MicroXRCEAgent",
    "gz",
    "gzserver",
    "gzclient",
    "gz-sim-server",
    "gz-sim-gui",
    "parameter_bridge",
    "ros_gz_bridge",
    "component_container",
    "component_container_mt",
    "rosbridge_websocket",
    "rosapi_node",
}

# Killed when the full command line contains one of these specific fragments
# (covers interpreter-hosted scripts and compiled node entry points). Each label
# is the short name reported in the verdict.
_CMDLINE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sim_full\.launch\.py"), "sim_launch"),
    (re.compile(r"hardware\.launch\.py"), "hw_launch"),
    (re.compile(r"gz_px4_stack"), "gz_px4_stack"),
    (re.compile(r"gcs_heartbeat"), "gcs_heartbeat"),
    (re.compile(r"wait_ready"), "wait_ready"),
    (re.compile(r"ruby.*\b(?:gz|sim)\b"), "gz_ruby"),
    (re.compile(r"python.*tests/scenarios/"), "scenario"),
    (re.compile(r"install/ros_px4_template_core/lib/ros_px4_template_core/"), "node"),
]

# Never killed, no matter what their command line contains. Protects the
# container runtime, shells, terminal, and init so teardown cannot end the
# agent's own distrobox session. Interpreters (python/ruby) are intentionally
# absent: an interpreter is only ever killed via a specific _CMDLINE_PATTERNS
# fragment, never on its bare name.
_NEVER_BASENAMES: set[str] = {
    "bash",
    "sh",
    "zsh",
    "fish",
    "dash",
    "login",
    "podman",
    "conmon",
    "distrobox",
    "distrobox-host-exec",
    "docker",
    "containerd",
    "runc",
    "crun",
    "systemd",
    "init",
    "sshd",
    "foot",
    "tmux",
    "screen",
}


def _match_label(cmd: str) -> str | None:
    """Return the short kill-label if ``cmd`` is one of our stack processes, else
    None. Infrastructure basenames are never matched."""
    argv = cmd.split()
    if not argv:
        return None
    base = os.path.basename(argv[0])
    if base in _NEVER_BASENAMES:
        return None
    if base in _EXACT_BASENAMES:
        return base
    for rx, label in _CMDLINE_PATTERNS:
        if rx.search(cmd):
            return label
    return None


def _proc_table() -> list[tuple[int, str]]:
    """Default process lister: (pid, cmdline) for every readable /proc entry."""
    out: list[tuple[int, str]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        cmd = raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        if cmd:
            out.append((pid, cmd))
    return out


def _ancestor_pids() -> set[int]:
    """PIDs of self + ancestors, so we never kill the teardown process itself."""
    pids = {os.getpid()}
    pid = os.getpid()
    try:
        while True:
            parts = Path(f"/proc/{pid}/stat").read_text().split()
            ppid = int(parts[3])
            if ppid <= 0 or ppid in pids:
                break
            pids.add(ppid)
            pid = ppid
    except Exception:
        pids.add(os.getppid())
    return pids


def scan_survivors(
    lister: Callable[[], list[tuple[int, str]]] | None = None,
) -> list[tuple[int, str]]:
    """Return (pid, cmdline) for every live process matching a straggler pattern,
    excluding this process and its ancestors. ``lister`` is injectable for tests.
    """
    table = (lister or _proc_table)()
    ancestors = _ancestor_pids()
    hits: list[tuple[int, str]] = []
    for pid, cmd in table:
        if pid in ancestors:
            continue
        if _match_label(cmd) is not None:
            hits.append((pid, cmd))
    return hits


def _sigkill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _kill_pidfile_group() -> int | None:
    """SIGKILL the recorded setsid process group, if any. Returns the pgid hit."""
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
        for p in (Path(f"/tmp/px4_lock-{i}"), Path(f"/tmp/px4-sock-{i}")):
            p.unlink(missing_ok=True)
    for pat in ("/tmp/launch_params_*", "/dev/shm/fastrtps_*"):
        for p in glob.glob(pat):
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


def _short_name(cmd: str) -> str:
    """A short label for a command line, for the verdict (e.g. 'px4', 'node')."""
    label = _match_label(cmd)
    if label is not None:
        return label
    argv = cmd.split()
    return os.path.basename(argv[0])[:24] if argv else "?"


def teardown() -> dict:
    """Exhaustive cold teardown. Returns ``{"killed": [...], "survivors": [...]}``
    (lists of short process labels). Never raises.
    """
    _kill_pidfile_group()
    initial = scan_survivors()
    for pid, _ in initial:
        _sigkill(pid)
    if initial:
        time.sleep(0.4)

    mid = scan_survivors()
    for pid, _ in mid:
        _sigkill(pid)
    if mid:
        time.sleep(0.3)

    _stop_ros2_daemon()
    _clean_artifacts()

    final = scan_survivors()
    final_pids = {pid for pid, _ in final}
    killed = sorted({_short_name(cmd) for pid, cmd in initial if pid not in final_pids})
    survivors = sorted({_short_name(cmd) for _, cmd in final})
    return {"killed": killed, "survivors": survivors}


def main() -> None:
    result = teardown()
    if result["killed"]:
        for name in result["killed"]:
            print(name)
    else:
        print("nothing to kill")
    sys.exit(0 if not result["survivors"] else 1)


if __name__ == "__main__":
    main()
