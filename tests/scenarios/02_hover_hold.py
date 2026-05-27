#!/usr/bin/env python3
"""Scenario 02 — Hover hold at target altitude for 30 s."""

from __future__ import annotations

import asyncio
import sys
import time

import rclpy
from _common import PX4_QOS, spin_until
from px4_msgs.msg import VehicleLocalPosition
from rclpy.node import Node
from rich.console import Console

from ros_px4_template_core.lib.frame_transforms import ned_to_enu

console = Console()
_TARGET_Z = 3.0
_ALT_TOL = 0.3
_XY_TOL = 0.5
_HOLD_S = 30.0
_CLIMB_TIMEOUT_S = 60.0


class _Node(Node):
    def __init__(self) -> None:
        super().__init__("scenario_02_hover_hold")
        self.z = 0.0
        self.x = 0.0
        self.y = 0.0
        self.create_subscription(
            VehicleLocalPosition, "/fmu/out/vehicle_local_position", self._cb, PX4_QOS
        )

    def _cb(self, msg: VehicleLocalPosition) -> None:
        self.x, self.y, self.z = ned_to_enu(msg.x, msg.y, msg.z)


async def run() -> bool:
    rclpy.init()
    node = _Node()
    console.print("[cyan]Climbing to target altitude...[/cyan]")

    def at_alt() -> bool:
        return node.z >= _TARGET_Z - _ALT_TOL

    try:
        await asyncio.wait_for(spin_until(node, at_alt), timeout=_CLIMB_TIMEOUT_S)
    except TimeoutError:
        console.print("[red]✗ FAIL — never reached target altitude[/red]")
        node.destroy_node()
        rclpy.shutdown()
        return False

    anchor = (node.x, node.y, node.z)
    console.print(
        f"[cyan]Holding at ({anchor[0]:.1f}, {anchor[1]:.1f}, {anchor[2]:.1f}) "
        f"for {_HOLD_S}s...[/cyan]"
    )
    hold_start = time.monotonic()
    violations = 0

    def hold_ok() -> bool:
        nonlocal violations
        if time.monotonic() - hold_start >= _HOLD_S:
            return True
        dx = abs(node.x - anchor[0])
        dy = abs(node.y - anchor[1])
        dz = abs(node.z - anchor[2])
        if dx > _XY_TOL or dy > _XY_TOL or dz > _ALT_TOL:
            violations += 1
            if violations > 50:
                return True
        return False

    await spin_until(node, hold_ok)
    node.destroy_node()
    rclpy.shutdown()
    elapsed = time.monotonic() - hold_start
    if violations > 50:
        console.print("[red]✗ FAIL — position drift during hold[/red]")
        return False
    if elapsed < _HOLD_S - 1:
        console.print("[red]✗ FAIL — hold ended early[/red]")
        return False
    console.print("[green]✓ PASS — held position[/green]")
    return True


def main() -> None:
    sys.exit(0 if asyncio.run(run()) else 1)


if __name__ == "__main__":
    main()
