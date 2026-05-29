#!/usr/bin/env python3
"""Scenario 03 — All waypoints in paths/demo.yaml are traversed.

Pass: waypoint_index reaches _WAYPOINT_COUNT or phase is done within _TIMEOUT_S.
Default sim loads paths/demo.yaml (no marker phase). Full ArUco flow: just sim inspect
then tests/scenarios/inspect_aruco.py.
"""

from __future__ import annotations

from _common import Scenario, run_main
from px4_ros_msgs.msg import MissionStatus
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rich.console import Console

console = Console()
_TIMEOUT_S = 300.0
# Matches waypoints count in config/paths/demo.yaml
_WAYPOINT_COUNT = 3


class _Node(Node):
    def __init__(self) -> None:
        super().__init__("scenario_03_waypoint")
        self.waypoint_index: int = 0
        self.phase: str | None = None
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(MissionStatus, "/drone/mission_status", self._cb, qos)

    def _cb(self, msg: MissionStatus) -> None:
        self.waypoint_index = msg.waypoint_index
        self.phase = msg.phase


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

    def report_detail(self) -> dict:
        return {"waypoints_done": self._node.waypoint_index, "phase": self._node.phase}


if __name__ == "__main__":
    run_main(WaypointScenario)
