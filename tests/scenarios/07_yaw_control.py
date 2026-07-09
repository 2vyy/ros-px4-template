#!/usr/bin/env python3
"""Scenario 07 — Command mission yaw through PX4 ``TrajectorySetpoint`` end to end.

Verifies the full yaw path: mission YAML ``yaw_deg`` -> ``GoTo.yaw`` (ENU
radians) -> ``/drone/target_pose`` quaternion -> ``offboard_controller`` ->
``/fmu/in/trajectory_setpoint`` (NED heading) -> actual vehicle ENU yaw.

Pass: setpoint yaw (NED, observed on ``/fmu/in/trajectory_setpoint``) converges
near 0 rad and vehicle ENU yaw (observed on ``/drone/odom``) converges near
pi/2 rad -- both simultaneously, for a stable interval. The mission (
``config/missions/yaw_demo.yaml``) commands ENU yaw 90 deg once ``yaw_hold``
is entered, which is NED heading 0.
Fail: timeout, setpoint yaw stays NaN, or observed yaw never converges.

Run: ``just scenario 07_yaw_control`` (requires overlay ``yaw_demo``).
"""

from __future__ import annotations

import asyncio
import math
import sys
import time

import rclpy
from _common import PX4_QOS, spin_until, trigger_auto_arm, trigger_cleanup, write_report
from nav_msgs.msg import Odometry
from px4_msgs.msg import TrajectorySetpoint
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rich.console import Console
from ros_px4_template_core.lib.frames import enu_yaw_from_quaternion

console = Console()

_TARGET_SETPOINT_YAW_NED = 0.0  # ENU 90 deg == NED heading 0
_TARGET_VEHICLE_YAW_ENU = math.pi / 2
_YAW_TOL_RAD = 0.2  # ~11.5 deg
_STABLE_S = 2.0
_TIMEOUT_S = 120.0
_ARM_FAIL_AFTER_S = 60.0

_RELIABLE_QOS = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)


def _angle_err(a: float, b: float) -> float:
    return abs(math.atan2(math.sin(a - b), math.cos(a - b)))


class _ScenarioNode(Node):
    def __init__(self) -> None:
        super().__init__("scenario_07_yaw_control")
        self.setpoint_yaw_ned: float | None = None
        self.vehicle_yaw_enu = 0.0
        self.z_enu = 0.0
        self.create_subscription(
            TrajectorySetpoint, "/fmu/in/trajectory_setpoint", self._setpoint_cb, PX4_QOS
        )
        self.create_subscription(Odometry, "/drone/odom", self._odom_cb, _RELIABLE_QOS)

    def _setpoint_cb(self, msg: TrajectorySetpoint) -> None:
        yaw = float(msg.yaw)
        self.setpoint_yaw_ned = yaw if math.isfinite(yaw) else None

    def _odom_cb(self, msg: Odometry) -> None:
        q = msg.pose.pose.orientation
        self.vehicle_yaw_enu = enu_yaw_from_quaternion(q.w, q.x, q.y, q.z)
        self.z_enu = float(msg.pose.pose.position.z)


async def run(timeout_s: float = _TIMEOUT_S) -> bool:
    rclpy.init()
    trigger_auto_arm()
    node = _ScenarioNode()
    started = time.monotonic()
    passed = False
    reason = "timeout"

    try:
        console.print("[cyan]Waiting for commanded yaw to converge...[/cyan]")

        _in_band_since = [0.0]

        def yaw_converged() -> bool:
            if node.setpoint_yaw_ned is None:
                _in_band_since[0] = 0.0
                return False
            setpoint_err = _angle_err(node.setpoint_yaw_ned, _TARGET_SETPOINT_YAW_NED)
            vehicle_err = _angle_err(node.vehicle_yaw_enu, _TARGET_VEHICLE_YAW_ENU)
            setpoint_ok = setpoint_err <= _YAW_TOL_RAD
            vehicle_ok = vehicle_err <= _YAW_TOL_RAD
            if setpoint_ok and vehicle_ok:
                if _in_band_since[0] == 0.0:
                    _in_band_since[0] = time.monotonic()
                elif time.monotonic() - _in_band_since[0] >= _STABLE_S:
                    return True
            else:
                _in_band_since[0] = 0.0
            elapsed = time.monotonic() - started
            if elapsed >= _ARM_FAIL_AFTER_S and node.z_enu < 0.5:
                return True
            return False

        try:
            await asyncio.wait_for(spin_until(node, yaw_converged), timeout=timeout_s)
        except TimeoutError:
            console.print("[red]✗ FAIL — timeout waiting for yaw convergence[/red]")
            write_report(
                "07_yaw_control",
                False,
                time.monotonic() - started,
                {
                    "reason": "timeout",
                    "setpoint_yaw_ned": node.setpoint_yaw_ned,
                    "vehicle_yaw_enu": round(node.vehicle_yaw_enu, 3),
                    "z_enu": round(node.z_enu, 2),
                },
            )
            return False

        setpoint_err = (
            _angle_err(node.setpoint_yaw_ned, _TARGET_SETPOINT_YAW_NED)
            if node.setpoint_yaw_ned is not None
            else None
        )
        vehicle_err = _angle_err(node.vehicle_yaw_enu, _TARGET_VEHICLE_YAW_ENU)

        if node.setpoint_yaw_ned is None:
            console.print("[red]✗ FAIL — setpoint yaw never went finite[/red]")
            reason = "setpoint_yaw_nan"
        elif node.z_enu < 0.5:
            console.print("[red]✗ FAIL — never left ground[/red]")
            reason = "takeoff_failed"
        elif setpoint_err > _YAW_TOL_RAD or vehicle_err > _YAW_TOL_RAD:
            console.print("[red]✗ FAIL — yaw did not converge[/red]")
            reason = "yaw_not_converged"
        else:
            console.print(
                f"[green]✓ PASS — setpoint_yaw_ned={node.setpoint_yaw_ned:.3f} rad, "
                f"vehicle_yaw_enu={node.vehicle_yaw_enu:.3f} rad[/green]"
            )
            passed = True
            reason = ""

        write_report(
            "07_yaw_control",
            passed,
            time.monotonic() - started,
            {
                "reason": reason,
                "setpoint_yaw_ned": node.setpoint_yaw_ned,
                "vehicle_yaw_enu": round(node.vehicle_yaw_enu, 3),
                "setpoint_yaw_err_rad": (
                    round(setpoint_err, 3) if setpoint_err is not None else None
                ),
                "vehicle_yaw_err_rad": round(vehicle_err, 3),
                "z_enu": round(node.z_enu, 2),
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
