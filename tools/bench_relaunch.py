#!/usr/bin/env python3
"""Honest warm-relaunch benchmark: stop → relaunch → stack ready at 1× physics.

Usage:
    uv run python tools/bench_relaunch.py            # 1× physics throughout
    uv run python tools/bench_relaunch.py --fast-ekf2  # 5× pre-arm, disclosed
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_ROSBRIDGE_PORT = 9090
_REQUIRED_TOPIC = "/fmu/out/vehicle_local_position"


def _port_open(port: int) -> bool:
    """Return True if a TCP listener is accepting connections on port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def _topic_live(topic: str) -> bool:
    """Return True if topic appears in ros2 topic list."""
    try:
        result = subprocess.run(
            ["ros2", "topic", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return topic in result.stdout.splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _px4_standby() -> bool:
    """Return True if PX4 vehicle_status shows arming_state == DISARMED (1) — ready to arm."""
    try:
        result = subprocess.run(
            [
                "ros2",
                "topic",
                "echo",
                "--once",
                "--qos-reliability",
                "best_effort",
                "/fmu/out/vehicle_status",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return "arming_state: 1" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _set_gz_physics(rtf: float) -> None:
    """Set Gazebo physics real-time factor. Silently ignores errors (gz may not be running)."""
    update_rate = int(rtf * 250)
    try:
        subprocess.run(
            [
                "gz",
                "service",
                "-s",
                "/world/default/set_physics",
                "--reqtype",
                "gz.msgs.Physics",
                "--reptype",
                "gz.msgs.Boolean",
                "--timeout",
                "3000",
                "--req",
                f"real_time_factor: {rtf}, real_time_update_rate: {update_rate}, max_step_size: 0.004",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


def _format_milestone(label: str, t_abs: float, t0: float, t_launch: float | None = None) -> str:
    """Format a single benchmark milestone line."""
    elapsed = t_abs - t0
    if t_launch is not None:
        from_launch = t_abs - t_launch
        return f"  {label:<38} +{elapsed:.1f}s  (+{from_launch:.1f}s from launch)"
    return f"  {label:<38} +{elapsed:.1f}s"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Honest warm-relaunch benchmark (Scenario B: edit src/, warm Gazebo)."
    )
    ap.add_argument(
        "--fast-ekf2",
        action="store_true",
        help="Use 5× Gazebo physics pre-arm for faster EKF2 convergence. "
        "Disclosed in output. 1× restored at stack-ready.",
    )
    args = ap.parse_args()

    mode_label = "pre-arm: 5× physics" if args.fast_ekf2 else "1× physics throughout"
    print(f"\n=== Warm Relaunch Benchmark [{mode_label}] ===\n", flush=True)
    print("Scenario B: edit src/ → sim stop → sim bg (warm Gazebo) → stack ready\n", flush=True)

    t0 = time.monotonic()

    # ── Step 1: Stop sim (kills ROS nodes + PX4, Gazebo stays warm) ──────────
    print("Stopping sim (Gazebo stays warm)...", flush=True)
    result = subprocess.run(
        ["uv", "run", "python", "tasks.py", "sim", "stop"],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print("WARNING: sim stop returned non-zero (may not have been running)", flush=True)
    t_stop = time.monotonic()
    print(_format_milestone("sim stop complete", t_stop, t0), flush=True)

    # ── Step 2: Optionally set 5× pre-arm physics ─────────────────────────────
    if args.fast_ekf2:
        _set_gz_physics(5.0)
        print("  [5× pre-arm physics set on Gazebo]", flush=True)

    # ── Step 3: Launch ────────────────────────────────────────────────────────
    subprocess.Popen(
        ["uv", "run", "python", "tasks.py", "sim", "bg", "--no-build"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    t_launch = time.monotonic()
    print(_format_milestone("sim bg launched", t_launch, t0), flush=True)

    # ── Step 4: Poll all three gates ─────────────────────────────────────────
    topic_ok = rosbridge_ok = standby_ok = False
    t_xrce = t_rosbridge = t_standby = None
    deadline = t_launch + 180.0

    while time.monotonic() < deadline:
        if not topic_ok and _topic_live(_REQUIRED_TOPIC):
            t_xrce = time.monotonic()
            topic_ok = True
            print(_format_milestone("XRCE / first topic live", t_xrce, t0, t_launch), flush=True)

        if not rosbridge_ok and _port_open(_ROSBRIDGE_PORT):
            t_rosbridge = time.monotonic()
            rosbridge_ok = True
            print(_format_milestone("rosbridge :9090 open", t_rosbridge, t0, t_launch), flush=True)

        if not standby_ok and _px4_standby():
            t_standby = time.monotonic()
            standby_ok = True
            print(_format_milestone("PX4 ready to arm (DISARMED)", t_standby, t0, t_launch), flush=True)

        if topic_ok and rosbridge_ok and standby_ok:
            t_ready = max(t_xrce, t_rosbridge, t_standby)  # type: ignore[type-var]

            if args.fast_ekf2:
                _set_gz_physics(1.0)
                print("  [1× physics restored at stack-ready]", flush=True)

            print(flush=True)
            print(
                _format_milestone("STACK READY", t_ready, t0, t_launch),
                flush=True,
            )
            print(flush=True)
            return

        time.sleep(0.2)

    print(
        f"\nTIMEOUT after 180s — topic={topic_ok} rosbridge={rosbridge_ok} standby={standby_ok}",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
