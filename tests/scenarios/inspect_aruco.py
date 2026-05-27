#!/usr/bin/env python3
"""Scenario — Inspect path and hover over ArUco when seen."""

from __future__ import annotations

import asyncio
import os
import sys

import rclpy
from _common import spin_until
from px4_ros_msgs.msg import MissionStatus
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rich.console import Console

console = Console()
_TIMEOUT_S = float(os.environ.get("SCENARIO_TIMEOUT_S", "180"))


class _MissionListener(Node):
    def __init__(self) -> None:
        super().__init__("scenario_inspect_aruco")
        self.phase: str | None = None
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(MissionStatus, "/drone/mission_status", self._cb, qos)

    def _cb(self, msg: MissionStatus) -> None:
        self.phase = msg.phase


async def run(timeout_s: float = _TIMEOUT_S) -> bool:
    if os.environ.get("SKIP_SCENARIO", "").lower() in ("1", "true", "yes"):
        console.print("[yellow]SKIP — SKIP_SCENARIO set[/yellow]")
        return True
    rclpy.init()
    node = _MissionListener()

    def done() -> bool:
        return node.phase in ("hover_marker", "done")

    console.print(f"[cyan]Waiting for hover_marker or done ({timeout_s:.0f}s max)...[/cyan]")
    try:
        await asyncio.wait_for(spin_until(node, done), timeout=timeout_s)
    except TimeoutError:
        console.print(f"[red]✗ FAIL — timeout after {timeout_s}s (last phase={node.phase!r})[/red]")
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        return False
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()
    console.print(f"[green]✓ PASS — phase {node.phase!r}[/green]")
    return True


def main() -> None:
    passed = asyncio.run(run())
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
