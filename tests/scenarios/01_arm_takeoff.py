#!/usr/bin/env python3
"""Scenario 01 — Arm and takeoff.

Pass: vehicle reaches 3.0 m ± 0.3 m (ENU z) within 30 s.
Fail: timeout, or still disarmed on ground after 15 s.

Run: ``just scenario 01_arm_takeoff`` (requires ``just sim``).
"""

from __future__ import annotations

import asyncio
import sys
import time

import rclpy
from _common import PX4_QOS, spin_until
from px4_msgs.msg import VehicleLocalPosition, VehicleStatus
from rclpy.node import Node
from rich.console import Console

from ros_px4_template_core.lib.frame_transforms import ned_to_enu

console = Console()

_TARGET_Z_M = 3.0
_TOLERANCE_M = 0.3
_TIMEOUT_S = 90.0
_ARM_FAIL_AFTER_S = 45.0

_ARMING_DISARMED = 1
_ARMING_ARMED = 2


class _ScenarioNode(Node):
    def __init__(self) -> None:
        super().__init__("scenario_01_arm_takeoff")
        self.z_enu = 0.0
        self.arming_state = _ARMING_DISARMED
        self.reached = False
        self.arming_rejected = False
        self.create_subscription(
            VehicleLocalPosition,
            "/fmu/out/vehicle_local_position",
            self._position_cb,
            PX4_QOS,
        )
        self.create_subscription(
            VehicleStatus,
            "/fmu/out/vehicle_status",
            self._status_cb,
            PX4_QOS,
        )

    def _position_cb(self, msg: VehicleLocalPosition) -> None:
        _, _, self.z_enu = ned_to_enu(msg.x, msg.y, msg.z)
        if self.z_enu >= _TARGET_Z_M - _TOLERANCE_M:
            self.reached = True

    def _status_cb(self, msg: VehicleStatus) -> None:
        self.arming_state = msg.arming_state


async def run(timeout_s: float = _TIMEOUT_S) -> bool:
    rclpy.init()
    node = _ScenarioNode()
    started = time.monotonic()

    def done() -> bool:
        if node.reached:
            return True
        elapsed = time.monotonic() - started
        if elapsed >= _ARM_FAIL_AFTER_S and node.arming_state != _ARMING_ARMED and node.z_enu < 0.5:
            node.arming_rejected = True
            return True
        return False

    console.print("[cyan]Waiting for 3.0 m altitude (±0.3 m)...[/cyan]")
    try:
        await asyncio.wait_for(spin_until(node, done), timeout=timeout_s)
    except TimeoutError:
        console.print(f"[red]✗ FAIL — timeout after {timeout_s}s[/red]")
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        return False

    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()

    if node.arming_rejected:
        console.print("[red]✗ FAIL — arming rejected or never left ground[/red]")
        return False
    if node.reached:
        console.print(f"[green]✓ PASS — reached {node.z_enu:.2f} m ENU z[/green]")
        return True
    console.print("[red]✗ FAIL — ended without reaching altitude[/red]")
    return False


def main() -> None:
    passed = asyncio.run(run())
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
