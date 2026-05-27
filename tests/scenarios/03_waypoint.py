#!/usr/bin/env python3
"""Scenario 03 — Mission completes (default inspect path on sim)."""

from __future__ import annotations

import asyncio
import sys

import rclpy
from _common import spin_until
from px4_ros_msgs.msg import MissionStatus
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rich.console import Console

console = Console()
_TIMEOUT_S = 300.0


class _Node(Node):
    def __init__(self) -> None:
        super().__init__("scenario_03_waypoint")
        self.phase: str | None = None
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(MissionStatus, "/drone/mission_status", self._cb, qos)

    def _cb(self, msg: MissionStatus) -> None:
        self.phase = msg.phase


async def run() -> bool:
    rclpy.init()
    node = _Node()
    console.print(f"[cyan]Waiting for mission phase done ({_TIMEOUT_S:.0f}s max)...[/cyan]")

    def done() -> bool:
        return node.phase == "done"

    try:
        await asyncio.wait_for(spin_until(node, done), timeout=_TIMEOUT_S)
    except TimeoutError:
        console.print(f"[red]✗ FAIL — timeout (phase={node.phase!r})[/red]")
        node.destroy_node()
        rclpy.shutdown()
        return False
    node.destroy_node()
    rclpy.shutdown()
    console.print("[green]✓ PASS — mission done[/green]")
    return True


def main() -> None:
    sys.exit(0 if asyncio.run(run()) else 1)


if __name__ == "__main__":
    main()
