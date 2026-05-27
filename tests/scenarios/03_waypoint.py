#!/usr/bin/env python3
"""Scenario 03 — All waypoints in the default mission are traversed.

Pass: waypoint_index reaches _WAYPOINT_COUNT within _TIMEOUT_S.
Note: the default inspect_aruco mission has a marker phase after the path.
This scenario validates path completion only — not the full mission (use
sim-inspect + inspect_aruco.py for end-to-end marker testing).
"""

from __future__ import annotations

import asyncio
import sys
import time

import rclpy
from _common import spin_until, write_report
from px4_ros_msgs.msg import MissionStatus
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rich.console import Console

console = Console()
_TIMEOUT_S = 300.0
# Matches waypoints count in config/missions/inspect_aruco.yaml
_WAYPOINT_COUNT = 3


class _Node(Node):
    def __init__(self) -> None:
        super().__init__("scenario_03_waypoint")
        self.waypoint_index: int = 0
        self.phase: str | None = None
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(MissionStatus, "/drone/mission_status", self._cb, qos)

    def _cb(self, msg: MissionStatus) -> None:
        self.waypoint_index = msg.waypoint_index
        self.phase = msg.phase


async def run() -> bool:
    rclpy.init()
    node = _Node()
    started = time.monotonic()
    console.print(
        f"[cyan]Waiting for all {_WAYPOINT_COUNT} waypoints ({_TIMEOUT_S:.0f}s max)...[/cyan]"
    )

    def done() -> bool:
        return node.waypoint_index >= _WAYPOINT_COUNT

    try:
        await asyncio.wait_for(spin_until(node, done), timeout=_TIMEOUT_S)
    except TimeoutError:
        elapsed = time.monotonic() - started
        console.print(f"[red]✗ FAIL — timeout (wp={node.waypoint_index}/{_WAYPOINT_COUNT})[/red]")
        node.destroy_node()
        rclpy.shutdown()
        write_report(
            "03_waypoint",
            False,
            elapsed,
            {"reason": "timeout", "waypoint_index": node.waypoint_index},
        )
        return False
    elapsed = time.monotonic() - started
    node.destroy_node()
    rclpy.shutdown()
    console.print(
        f"[green]✓ PASS — traversed {_WAYPOINT_COUNT} waypoints (phase={node.phase!r})[/green]"
    )
    write_report(
        "03_waypoint",
        True,
        elapsed,
        {"waypoints_done": node.waypoint_index, "phase": node.phase},
    )
    return True


def main() -> None:
    sys.exit(0 if asyncio.run(run()) else 1)


if __name__ == "__main__":
    main()
