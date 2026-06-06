#!/usr/bin/env python3
"""Scenario 02 — Hover hold at target altitude for 30 s and land/cleanup."""

from __future__ import annotations

import asyncio
import sys
import time

import rclpy
from _common import PX4_QOS, spin_until, trigger_auto_arm, trigger_cleanup, write_report
from px4_msgs.msg import VehicleLocalPosition
from rclpy.node import Node
from rich.console import Console
from ros_px4_template_core.lib.frames import ned_to_enu

console = Console()
_TARGET_Z = 3.0
_CLIMB_THRESHOLD = 2.7  # anchor only after reaching 90% of target (avoids anchoring mid-climb)
_ALT_TOL = 0.5  # widened: SITL position control has ~0.3-0.4 m steady-state error
_XY_TOL = 0.75  # widened: wind/EKF noise in headless SITL can push 0.5-0.6 m
_HOLD_S = 30.0
_CLIMB_TIMEOUT_S = 180.0
_STABILIZE_S = 3.0  # wait this long after reaching altitude before anchoring
# Number of *consecutive* out-of-bounds samples before we call it a drift failure.
# At 20 Hz spin rate this is ~2.5 s of sustained drift, not momentary spikes.
_MAX_CONSEC_VIOLATIONS = 50


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
    trigger_auto_arm()
    node = _Node()
    started = time.monotonic()
    passed = False
    reason = "timeout"

    try:
        console.print("[cyan]Climbing to target altitude...[/cyan]")

        def at_alt() -> bool:
            return node.z >= _CLIMB_THRESHOLD

        try:
            await asyncio.wait_for(spin_until(node, at_alt), timeout=_CLIMB_TIMEOUT_S)
        except TimeoutError:
            console.print("[red]✗ FAIL — never reached target altitude[/red]")
            write_report(
                "02_hover_hold", False, time.monotonic() - started, {"reason": "climb_timeout"}
            )
            return False

        console.print(f"[cyan]Stabilizing for {_STABILIZE_S}s before anchoring...[/cyan]")
        stabilize_start = time.monotonic()
        await spin_until(node, lambda: time.monotonic() - stabilize_start >= _STABILIZE_S)

        anchor = (node.x, node.y, node.z)
        console.print(
            f"[cyan]Holding at ({anchor[0]:.1f}, {anchor[1]:.1f}, {anchor[2]:.1f}) "
            f"for {_HOLD_S}s...[/cyan]"
        )
        hold_start = time.monotonic()
        consec_violations = 0

        def hold_ok() -> bool:
            nonlocal consec_violations
            if time.monotonic() - hold_start >= _HOLD_S:
                return True
            dx = abs(node.x - anchor[0])
            dy = abs(node.y - anchor[1])
            dz = abs(node.z - anchor[2])
            if dx > _XY_TOL or dy > _XY_TOL or dz > _ALT_TOL:
                consec_violations += 1
                if consec_violations > _MAX_CONSEC_VIOLATIONS:
                    return True
            else:
                consec_violations = 0  # reset on recovery — transient spikes don't accumulate
            return False

        await spin_until(node, hold_ok)
        hold_elapsed = time.monotonic() - hold_start

        if consec_violations > _MAX_CONSEC_VIOLATIONS:
            console.print("[red]✗ FAIL — position drift during hold[/red]")
            reason = "drift"
        elif hold_elapsed < _HOLD_S - 1:
            console.print("[red]✗ FAIL — hold ended early[/red]")
            reason = "hold_too_short"
        else:
            console.print("[green]✓ PASS — held position[/green]")
            passed = True
            reason = ""

        write_report(
            "02_hover_hold",
            passed,
            time.monotonic() - started,
            {"anchor": list(anchor), "reason": reason, "violations": consec_violations},
        )

    finally:
        trigger_cleanup()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    return passed


def main() -> None:
    sys.exit(0 if asyncio.run(run()) else 1)


if __name__ == "__main__":
    main()
