#!/usr/bin/env python3
"""Render a runnable `Scenario` stub (used by `just scenario-new`).

Pure (no ROS, no Typer) so the renderer is unit-testable. The output mirrors
`tests/scenarios/03_waypoint.py`: a `_Node` subscribing to `/drone/mission_status`
and a `Scenario` subclass with `name`/`timeout_s`/`make_node`/`done`/`report_detail`.
"""

from __future__ import annotations

import re

_TEMPLATE = '''#!/usr/bin/env python3
"""Scenario @@NAME@@ — TODO: describe what this scenario verifies.

Pass: TODO state the condition that makes this scenario succeed.
"""

from __future__ import annotations

from _common import Scenario, run_main
from px4_ros_msgs.msg import MissionStatus
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

_TIMEOUT_S = 60.0


class _Node(Node):
    def __init__(self) -> None:
        super().__init__("scenario_@@NAME@@")
        self.waypoint_index: int = 0
        self.phase: str | None = None
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(MissionStatus, "/drone/mission_status", self._cb, qos)

    def _cb(self, msg: MissionStatus) -> None:
        self.waypoint_index = msg.waypoint_index
        self.phase = msg.phase


class @@CLS@@Scenario(Scenario):
    name = "@@NAME@@"
    timeout_s = _TIMEOUT_S

    def make_node(self) -> Node:
        self._node = _Node()
        return self._node

    def done(self) -> bool:
        # TODO: replace with your real pass condition
        return self._node.phase == "done"

    def report_detail(self) -> dict:
        return {"phase": self._node.phase, "waypoints_done": self._node.waypoint_index}


if __name__ == "__main__":
    run_main(@@CLS@@Scenario)
'''


def class_name(name: str) -> str:
    """Derive a CamelCase class prefix from a scenario name (strips a leading ``NN_``)."""
    stem = re.sub(r"^\d+_", "", name)
    camel = "".join(part.capitalize() for part in stem.split("_") if part)
    return camel or "Scenario"


def render_scenario(name: str) -> str:
    """Return runnable source for a `Scenario` stub named ``name``."""
    return _TEMPLATE.replace("@@CLS@@", class_name(name)).replace("@@NAME@@", name)
