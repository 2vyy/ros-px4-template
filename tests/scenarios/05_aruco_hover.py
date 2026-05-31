#!/usr/bin/env python3
"""Scenario 05 — ArUco marker hover.

Pass: mission_manager enters phase 'marker_hover' within 180 s.
Fail: timeout, or mission completes without entering marker_hover.

Requires: a running sim with aruco_pose_publisher AND a visible marker.
Run: just scenario 05_aruco_hover
"""

from __future__ import annotations

import asyncio
import sys
import time

import rclpy
from _common import spin_until, write_report
from px4_ros_msgs.msg import MissionStatus
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_TIMEOUT_S = 180.0


class _ScenarioNode(Node):
    def __init__(self) -> None:
        super().__init__("scenario_05_aruco_hover")
        self.entered_marker_hover = False
        self.mission_done = False
        self.create_subscription(MissionStatus, "/drone/mission_status", self._cb, _RELIABLE_QOS)

    def _cb(self, msg: MissionStatus) -> None:
        if msg.phase == "marker_hover":
            self.entered_marker_hover = True
        if msg.phase == "done":
            self.mission_done = True


async def run(timeout_s: float = _TIMEOUT_S) -> bool:
    rclpy.init()
    node = _ScenarioNode()
    started = time.monotonic()

    def done() -> bool:
        return node.entered_marker_hover or node.mission_done

    from rich.console import Console

    console = Console()
    console.print("[cyan]Waiting for marker_hover phase...[/cyan]")

    try:
        await asyncio.wait_for(spin_until(node, done), timeout=timeout_s)
    except TimeoutError:
        elapsed = time.monotonic() - started
        console.print(f"[red]✗ FAIL — timeout after {timeout_s}s[/red]")
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        write_report("05_aruco_hover", False, elapsed, {"reason": "timeout"})
        return False

    elapsed = time.monotonic() - started
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()

    if node.entered_marker_hover:
        console.print(f"[green]✓ PASS — entered marker_hover in {elapsed:.1f}s[/green]")
        write_report("05_aruco_hover", True, elapsed, {})
        return True

    console.print("[red]✗ FAIL — mission completed without marker_hover[/red]")
    write_report("05_aruco_hover", False, elapsed, {"reason": "no_marker_detected"})
    return False


def main() -> None:
    passed = asyncio.run(run())
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
