#!/usr/bin/env python3
"""Scenario 03 — All waypoints in paths/demo.yaml are actually traversed.

Pass: waypoint_index reaches _WAYPOINT_COUNT (or phase is done) within _TIMEOUT_S
AND the vehicle's own PX4 position came within _REACH_TOL_M of each declared
waypoint. The second check is independent of mission_manager's reach logic, so a
bug that advances the index without the airframe flying the path is caught.
"""

from __future__ import annotations

import math

from _common import PX4_QOS, Scenario, run_main
from px4_msgs.msg import VehicleLocalPosition
from px4_ros_msgs.msg import MissionStatus
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rich.console import Console
from ros_px4_template_core.lib.frames import ned_to_enu

console = Console()
_TIMEOUT_S = 300.0
# Anchored-ENU waypoints in config/paths/demo.yaml (PX4 local origin == takeoff in SITL).
_WAYPOINTS_ENU = [(0.0, 0.0, 3.0), (5.0, 0.0, 3.0), (8.0, 0.0, 3.0)]
_WAYPOINT_COUNT = len(_WAYPOINTS_ENU)
_REACH_TOL_M = 0.8  # mission tolerance 0.4 m + estimator/discretization margin


class _Node(Node):
    def __init__(self) -> None:
        super().__init__("scenario_03_waypoint")
        self.waypoint_index: int = 0
        self.phase: str | None = None
        # Minimum ENU distance the vehicle actually achieved to each declared waypoint.
        self.wp_min_dist: list[float] = [math.inf] * _WAYPOINT_COUNT
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(MissionStatus, "/drone/mission_status", self._cb, qos)
        self.create_subscription(
            VehicleLocalPosition, "/fmu/out/vehicle_local_position_v1", self._pos_cb, PX4_QOS
        )

    def _cb(self, msg: MissionStatus) -> None:
        self.waypoint_index = msg.waypoint_index
        self.phase = msg.phase

    def _pos_cb(self, msg: VehicleLocalPosition) -> None:
        pos = ned_to_enu(msg.x, msg.y, msg.z)
        for i, wp in enumerate(_WAYPOINTS_ENU):
            d = math.dist(pos, wp)
            if d < self.wp_min_dist[i]:
                self.wp_min_dist[i] = d


class WaypointScenario(Scenario):
    name = "03_waypoint"
    timeout_s = _TIMEOUT_S

    def make_node(self) -> Node:
        self._node = _Node()
        console.print(
            f"[cyan]Waiting for all {_WAYPOINT_COUNT} waypoints ({_TIMEOUT_S:.0f}s max)...[/cyan]"
        )
        return self._node

    def done(self) -> bool:
        return self._node.waypoint_index >= _WAYPOINT_COUNT or self._node.phase == "done"

    def fail_reason(self) -> str | None:
        for i, d in enumerate(self._node.wp_min_dist):
            if d > _REACH_TOL_M:
                return f"index advanced but vehicle missed wp{i} (min {d:.2f}m)"
        return None

    def report_detail(self) -> dict:
        return {
            "waypoints_done": self._node.waypoint_index,
            "phase": self._node.phase,
            "wp_min_dists": [round(d, 2) for d in self._node.wp_min_dist],
        }


if __name__ == "__main__":
    run_main(WaypointScenario)
