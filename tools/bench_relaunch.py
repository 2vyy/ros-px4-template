#!/usr/bin/env python3
"""Honest warm-relaunch benchmark: stop → relaunch → stack ready at 1× physics.

Usage:
    uv run python tools/bench_relaunch.py            # 1× physics throughout
    uv run python tools/bench_relaunch.py --fast-ekf2  # 5× pre-arm, disclosed
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"

_ROSBRIDGE_PORT = 9090
_REQUIRED_TOPIC = "/fmu/out/vehicle_local_position"
_PARAMS_MARKER = "Params committed"


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


def _params_sent(after_mtime: float) -> bool:
    """Return True if a sim log newer than after_mtime contains 'Params committed'."""
    sim_logs = sorted(LOG_DIR.glob("sim_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not sim_logs:
        return False
    newest = sim_logs[0]
    if newest.stat().st_mtime < after_mtime:
        return False
    try:
        return _PARAMS_MARKER in newest.read_text(errors="replace")
    except OSError:
        return False


def _set_gz_physics(rtf: float) -> None:
    """Set Gazebo physics real-time factor. Silently ignores errors (gz may not be running)."""
    update_rate = int(rtf * 250)
    try:
        subprocess.run(
            [
                "gz", "service", "-s", "/world/default/set_physics",
                "--reqtype", "gz.msgs.Physics",
                "--reptype", "gz.msgs.Boolean",
                "--timeout", "3000",
                "--req", f"real_time_factor: {rtf}, real_time_update_rate: {update_rate}, max_step_size: 0.004",
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
