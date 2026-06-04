#!/usr/bin/env python3
"""Scenario 01 — Arm, position offboard climb, hold, and land/cleanup.

Pass: controller reaches OFFBOARD_TRACK and holds near target altitude for 10 s.
Fail: timeout, arm rejected, missing OFFBOARD handoff, or drift during hold.

Run: ``just scenario 01_arm_takeoff`` (requires ``just sim bg --no-auto-arm``).
"""

from __future__ import annotations

import asyncio
import sys
import time

import rclpy
from _common import PX4_QOS, spin_until, trigger_auto_arm, trigger_cleanup, write_report
from px4_msgs.msg import VehicleLocalPosition
from px4_ros_msgs.msg import ControllerStatus, MissionStatus
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rich.console import Console
from ros_px4_template_core.lib.frame_transforms import Px4ZFrameTracker, ned_to_enu

console = Console()

_TARGET_Z_M = 3.0
_CLIMB_THRESHOLD = 2.7
_TOLERANCE_M = 0.3
_TIMEOUT_S = 180.0
_ARM_FAIL_AFTER_S = 60.0
_STABILIZE_S = 2.0
_HOLD_S = 10.0
_ALT_TOL = 0.5
_XY_TOL = 0.75
_MAX_CONSEC_VIOLATIONS = 50

_RELIABLE_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)


class _ScenarioNode(Node):
    def __init__(self) -> None:
        super().__init__("scenario_01_arm_takeoff")
        self.x_enu = 0.0
        self.y_enu = 0.0
        self.z_enu = 0.0
        self.controller_state = ""
        self.mission_phase = ""
        self.saw_offboard_track = False
        self._z_frame = Px4ZFrameTracker()
        self.create_subscription(
            VehicleLocalPosition,
            "/fmu/out/vehicle_local_position",
            self._position_cb,
            PX4_QOS,
        )
        self.create_subscription(
            ControllerStatus,
            "/drone/controller_status",
            self._controller_cb,
            _RELIABLE_QOS,
        )
        self.create_subscription(
            MissionStatus,
            "/drone/mission_status",
            self._mission_cb,
            _RELIABLE_QOS,
        )

    def _position_cb(self, msg: VehicleLocalPosition) -> None:
        if not (msg.xy_valid and msg.z_valid):
            return
        local_z_ned = self._z_frame.observe(
            float(msg.z),
            z_global=bool(msg.z_global),
            z_reset_counter=int(msg.z_reset_counter),
            delta_z=float(msg.delta_z),
        )
        self.x_enu, self.y_enu, self.z_enu = ned_to_enu(msg.x, msg.y, local_z_ned)

    def _controller_cb(self, msg: ControllerStatus) -> None:
        self.controller_state = msg.state
        if msg.state == "OFFBOARD_TRACK":
            self.saw_offboard_track = True

    def _mission_cb(self, msg: MissionStatus) -> None:
        self.mission_phase = msg.phase


async def run(timeout_s: float = _TIMEOUT_S) -> bool:
    rclpy.init()
    trigger_auto_arm()
    node = _ScenarioNode()
    started = time.monotonic()
    passed = False
    reason = "timeout"

    try:
        await spin_until(
            node,
            lambda: node.z_enu != 0.0 or (time.monotonic() - started) > 5.0,
        )
        if node.z_enu >= _TARGET_Z_M - _TOLERANCE_M:
            console.print("[red]✗ FAIL — warm-start detected (drone already in the air)[/red]")
            write_report(
                "01_arm_takeoff",
                False,
                time.monotonic() - started,
                {"reason": "warm_start", "z_enu": node.z_enu},
            )
            return False

        console.print("[cyan]Waiting for OFFBOARD position tracking...[/cyan]")

        _in_band_since: list[float] = [0.0]
        _SETTLE_S = 1.5

        def climb_done() -> bool:
            near_target = _CLIMB_THRESHOLD <= node.z_enu <= _TARGET_Z_M + _ALT_TOL
            if near_target and (node.saw_offboard_track or node.mission_phase == "follow_path"):
                if _in_band_since[0] == 0.0:
                    _in_band_since[0] = time.monotonic()
                elif time.monotonic() - _in_band_since[0] >= _SETTLE_S:
                    return True
            else:
                _in_band_since[0] = 0.0
            elapsed = time.monotonic() - started
            if elapsed >= _ARM_FAIL_AFTER_S and not node.saw_offboard_track and node.z_enu < 0.5:
                return True
            return False

        try:
            await asyncio.wait_for(spin_until(node, climb_done), timeout=timeout_s)
        except TimeoutError:
            write_report(
                "01_arm_takeoff",
                False,
                time.monotonic() - started,
                {
                    "reason": "timeout",
                    "z_enu": node.z_enu,
                    "controller_state": node.controller_state,
                    "mission_phase": node.mission_phase,
                },
            )
            return False

        if not node.saw_offboard_track:
            console.print("[red]✗ FAIL — never reached OFFBOARD_TRACK[/red]")
            write_report(
                "01_arm_takeoff",
                False,
                time.monotonic() - started,
                {
                    "reason": "no_offboard_handoff",
                    "controller_state": node.controller_state,
                    "mission_phase": node.mission_phase,
                },
            )
            return False

        if node.z_enu < _CLIMB_THRESHOLD:
            console.print("[red]✗ FAIL — arming/takeoff rejected or never left ground[/red]")
            write_report(
                "01_arm_takeoff",
                False,
                time.monotonic() - started,
                {
                    "reason": "takeoff_failed",
                    "z_enu": node.z_enu,
                    "controller_state": node.controller_state,
                },
            )
            return False

        console.print(
            f"[cyan]Stabilizing for {_STABILIZE_S}s "
            f"(ctrl={node.controller_state}, phase={node.mission_phase})...[/cyan]"
        )
        stabilize_start = time.monotonic()
        await spin_until(node, lambda: time.monotonic() - stabilize_start >= _STABILIZE_S)

        anchor = (node.x_enu, node.y_enu, node.z_enu)
        console.print(
            f"[cyan]Holding at ({anchor[0]:.2f}, {anchor[1]:.2f}, {anchor[2]:.2f}) "
            f"for {_HOLD_S}s...[/cyan]"
        )
        hold_start = time.monotonic()
        consec_violations = 0

        def hold_ok() -> bool:
            nonlocal consec_violations
            if time.monotonic() - hold_start >= _HOLD_S:
                return True
            dx = abs(node.x_enu - anchor[0])
            dy = abs(node.y_enu - anchor[1])
            dz = abs(node.z_enu - anchor[2])
            if dx > _XY_TOL or dy > _XY_TOL or dz > _ALT_TOL:
                consec_violations += 1
                if consec_violations > _MAX_CONSEC_VIOLATIONS:
                    return True
            else:
                consec_violations = 0
            return False

        await spin_until(node, hold_ok)
        hold_elapsed = time.monotonic() - hold_start

        if consec_violations > _MAX_CONSEC_VIOLATIONS:
            console.print("[red]✗ FAIL — position drift during hold[/red]")
            reason = "drift"
        elif hold_elapsed < _HOLD_S - 1:
            console.print("[red]✗ FAIL — hold ended early[/red]")
            reason = "hold_too_short"
        elif abs(node.z_enu - _TARGET_Z_M) > _ALT_TOL:
            console.print(
                f"[red]✗ FAIL — altitude {node.z_enu:.2f} m outside "
                f"{_TARGET_Z_M} ± {_ALT_TOL} m[/red]"
            )
            reason = "altitude_out_of_band"
        else:
            console.print(
                f"[green]✓ PASS — OFFBOARD at {node.z_enu:.2f} m, "
                f"phase={node.mission_phase}[/green]"
            )
            passed = True
            reason = ""

        console.print("[cyan]Initiating land and disarm...[/cyan]")
        write_report(
            "01_arm_takeoff",
            passed,
            time.monotonic() - started,
            {
                "z_enu": node.z_enu,
                "reason": reason,
                "controller_state": node.controller_state,
                "mission_phase": node.mission_phase,
                "saw_offboard_track": node.saw_offboard_track,
                "anchor": list(anchor),
            }
            if not passed
            else {
                "z_enu": node.z_enu,
                "controller_state": node.controller_state,
                "mission_phase": node.mission_phase,
            },
        )

    finally:
        trigger_cleanup()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

    return passed


def main() -> None:
    passed = asyncio.run(run())
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
