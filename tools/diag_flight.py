#!/usr/bin/env python3
"""Diagnostic: log nav_state, arming_state, and altitude every 0.5s to understand climb behavior."""

from __future__ import annotations

import time

import rclpy
from px4_msgs.msg import VehicleLocalPosition, VehicleStatus
from px4_ros_msgs.msg import ControllerStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from ros_px4_template_core.lib.frame_transforms import ned_to_enu

PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)

NAV_STATE_NAMES = {
    0: "MANUAL",
    1: "ALTCTL",
    2: "POSCTL",
    3: "AUTO_MISSION",
    4: "AUTO_LOITER",
    5: "AUTO_RTL",
    10: "ACRO",
    12: "DESCEND",
    13: "TERMINATION",
    14: "OFFBOARD",
    15: "STAB",
    17: "AUTO_TAKEOFF",
    18: "AUTO_LAND",
    19: "AUTO_FOLLOW_TARGET",
    20: "AUTO_PRECLAND",
}


class DiagNode(Node):
    def __init__(self) -> None:
        super().__init__("diag_flight")
        self.t0 = time.monotonic()
        self.z_enu = 0.0
        self.nav_state = -1
        self.arming_state = -1
        self.ctrl_state = "?"
        self.prev_nav = -1
        self.prev_arm = -1
        self.arm_wall_t: float | None = None
        self.offboard_wall_t: float | None = None

        self.create_subscription(
            VehicleLocalPosition, "/fmu/out/vehicle_local_position", self._pos_cb, PX4_QOS
        )
        self.create_subscription(VehicleStatus, "/fmu/out/vehicle_status", self._status_cb, PX4_QOS)
        self.create_subscription(
            ControllerStatus, "/drone/controller_status", self._ctrl_cb, RELIABLE_QOS
        )
        self.create_timer(0.5, self._print)

    def _pos_cb(self, msg: VehicleLocalPosition) -> None:
        _, _, self.z_enu = ned_to_enu(msg.x, msg.y, msg.z)

    def _status_cb(self, msg: VehicleStatus) -> None:
        self.nav_state = int(msg.nav_state)
        self.arming_state = int(msg.arming_state)
        if self.nav_state != self.prev_nav:
            name = NAV_STATE_NAMES.get(self.nav_state, str(self.nav_state))
            prev_name = NAV_STATE_NAMES.get(self.prev_nav, str(self.prev_nav))
            t = time.monotonic() - self.t0
            print(f"  [T+{t:5.1f}s] NAV_STATE: {prev_name} → {name}", flush=True)
            if self.nav_state == 14 and self.offboard_wall_t is None:
                self.offboard_wall_t = t
            self.prev_nav = self.nav_state
        if self.arming_state != self.prev_arm:
            name = "ARMED" if self.arming_state == 2 else f"state={self.arming_state}"
            t = time.monotonic() - self.t0
            print(f"  [T+{t:5.1f}s] ARM_STATE: → {name}", flush=True)
            if self.arming_state == 2 and self.arm_wall_t is None:
                self.arm_wall_t = t
            self.prev_arm = self.arming_state

    def _ctrl_cb(self, msg: ControllerStatus) -> None:
        self.ctrl_state = msg.state

    def _print(self) -> None:
        t = time.monotonic() - self.t0
        nav_name = NAV_STATE_NAMES.get(self.nav_state, str(self.nav_state))
        arm_name = "ARMED" if self.arming_state == 2 else f"arming={self.arming_state}"
        print(
            f"T+{t:5.1f}s  z={self.z_enu:5.2f}m  nav={nav_name:<12}  {arm_name}  ctrl={self.ctrl_state}",
            flush=True,
        )
        if self.z_enu >= 2.7:
            print(f"\n=== REACHED 2.7m at T+{t:.1f}s ===", flush=True)
            if self.arm_wall_t:
                print(f"    arm→altitude  = {t - self.arm_wall_t:.1f}s", flush=True)
            if self.offboard_wall_t:
                print(f"    offboard→alt  = {t - self.offboard_wall_t:.1f}s", flush=True)
            raise SystemExit(0)


def main() -> None:
    rclpy.init()
    node = DiagNode()
    print("=== diag_flight: watching nav_state + altitude ===", flush=True)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
