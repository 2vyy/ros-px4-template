#!/usr/bin/env python3
"""Scenario 09 — REAL ArUco detection from rendered camera pixels.

Unlike 05/06/08 (which fabricate `/drone/marker_detection`), this boots the
camera-equipped model `x500_mono_cam_down` in the `marker_field` world and flies
the demo path to (8, 0, 3), directly over rendered marker 0. It asserts that the
real perception pipeline (gz camera -> /camera/image_raw -> aruco_pose_publisher
-> solvePnP) produces a burst of valid detections whose MEDIAN body-FLU
horizontal offset is within tolerance.

Best sustained window, not a fixed snapshot: the detector assumes a
perfectly-aligned nadir camera and ignores vehicle attitude, so while the
vehicle arrives/decelerates over the marker it pitches and throws large lateral
offsets (see plans/062-findings.md), and even in hover it oscillates. We track
the BEST (lowest-median) trailing window of detections the flight achieves — the
vehicle's most-stable moment — which proves the pipeline ACHIEVED accurate
detection, and is robust to where in the oscillation any single snapshot lands.

Pass: some window of _WINDOW consecutive valid detections of marker 0 has a
median body-FLU horizontal offset <= _MAX_MED_HORIZ_M at ~3 m altitude. Fail:
timeout before any such window (never decoded, or never settled below tolerance).
"""

from __future__ import annotations

import math
import statistics

from _common import Scenario, run_main
from px4_ros_msgs.msg import MarkerDetection
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rich.console import Console

console = Console()
_TIMEOUT_S = 150.0
_TARGET_ID = 0
_WINDOW = 20  # sustained valid detections per assessed window (~1.3 s at ~15 Hz)
# Collect a fixed sample (the vehicle hovers over the marker until the scenario
# ends, so this is reliably reached), then judge the BEST sustained window over
# it. A fixed-count SNAPSHOT of the trailing window varied 0.14-0.25 m across runs
# (dynamic station-keeping + active marker_localizer pose-override feedback), too
# close to any threshold to be non-flaky. The best-window over the sample is
# instead stable: its floor is ~0.087 m (measured over 80 detections, plans/062)
# and it varies ~0.08-0.12 m over a 70-sample collection.
_MIN_TOTAL = 70  # valid detections to collect before judging (~5 s of the hover)
# 0.20 m clears the worst observed best-window with ~0.08 m margin (non-flaky) yet
# stays a genuine accuracy assertion far stricter than the 0.5 m "wildly wrong"
# bar from plans/062: any real breakage (no detection, wrong marker_size scale, an
# extrinsic sign error) yields >0.5 m or nothing. min_horiz_m in the report shows
# the true best single-frame accuracy.
_MAX_MED_HORIZ_M = 0.20


class _Node(Node):
    def __init__(self) -> None:
        super().__init__("scenario_09_aruco_hover_real")
        # Horizontal (Forward, Left) offset magnitude of each valid id-0 detection.
        self.horiz: list[float] = []
        # Best (lowest) trailing-_WINDOW median seen, i.e. the most-stable moment.
        self.best_window: float = math.inf
        # aruco_pose_publisher publishes RELIABLE (see nodes/qos.RELIABLE_QOS).
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self.create_subscription(MarkerDetection, "/drone/marker_detection", self._cb, qos)

    def _cb(self, msg: MarkerDetection) -> None:
        if msg.valid and msg.id == _TARGET_ID:
            self.horiz.append(math.hypot(msg.offset_body_flu.x, msg.offset_body_flu.y))
            if len(self.horiz) >= _WINDOW:
                self.best_window = min(self.best_window, statistics.median(self.horiz[-_WINDOW:]))


class ArucoHoverRealScenario(Scenario):
    name = "09_aruco_hover_real"
    timeout_s = _TIMEOUT_S

    def make_node(self) -> Node:
        self._node = _Node()
        console.print(
            f"[cyan]Collecting {_MIN_TOTAL} REAL detections of marker {_TARGET_ID} "
            f"(camera model), judging best {_WINDOW}-window ({_TIMEOUT_S:.0f}s max)...[/cyan]"
        )
        return self._node

    def done(self) -> bool:
        # Collect a fixed sample of the hover, then judge (in fail_reason) the best
        # sustained window over it. Base class writes a timeout fail if the vehicle
        # never delivers _MIN_TOTAL valid detections (never decoded / never hovered).
        return len(self._node.horiz) >= _MIN_TOTAL

    def fail_reason(self) -> str | None:
        if not self._node.horiz:
            return "no valid real detection of marker 0 (camera pixels never decoded)"
        best = self._node.best_window
        if best > _MAX_MED_HORIZ_M:
            return f"best sustained window {best:.2f}m exceeds {_MAX_MED_HORIZ_M}m"
        return None

    def report_detail(self) -> dict:
        h = self._node.horiz
        best = self._node.best_window
        return {
            "valid_detections": len(h),
            "best_window_median_horiz_m": round(best, 3) if best != math.inf else None,
            "min_horiz_m": round(min(h), 3) if h else None,
        }


if __name__ == "__main__":
    run_main(ArucoHoverRealScenario)
