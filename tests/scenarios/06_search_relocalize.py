#!/usr/bin/env python3
"""Scenario 06 — search + known-marker relocalization + return to origin.

The drone flies a lawnmower search whose first leg overflies a KNOWN marker
(id 0 at world (8, 0)). A synthetic nadir camera renders that marker from the
drone's live pose; aruco_pose_publisher detects it and marker_localizer turns
the known position into a /drone/pose_override fix. Once the detection is stable
the FSM transitions search -> return_to_origin -> done.

Pass: a /drone/pose_override is published (relocalization fired) AND the mission
      reaches phase 'done' (having passed through 'return_to_origin').
Fail: timeout, no override, or mission never returns/completes.

Requires: a running sim with vision=aruco (aruco_pose_publisher + marker_localizer).
Run: just scenario 06_search_relocalize
"""

from __future__ import annotations

import asyncio
import sys
import time

import cv2
import numpy as np
import rclpy
from _common import spin_until, write_report
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from px4_ros_msgs.msg import MissionStatus
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from ros_px4_template_core.lib.frames import enu_offset_to_body_flu, enu_yaw_from_quaternion
from sensor_msgs.msg import CameraInfo, Image

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_TIMEOUT_S = 240.0

# Known marker world position (must match config/markers.yaml marker id 0).
_MARKER_X = 8.0
_MARKER_Y = 0.0


class _ScenarioNode(Node):
    def __init__(self) -> None:
        super().__init__("scenario_06_search_relocalize")
        self.entered_return = False
        self.mission_done = False
        self.override_count = 0
        self.last_override: PoseStamped | None = None
        self.drone_pose: Odometry | None = None

        self.create_subscription(
            MissionStatus, "/drone/mission_status", self._status_cb, _RELIABLE_QOS
        )
        self.create_subscription(Odometry, "/drone/odom", self._pose_cb, _RELIABLE_QOS)
        self.create_subscription(
            PoseStamped, "/drone/pose_override", self._override_cb, _RELIABLE_QOS
        )

        # Synthetic nadir camera feed.
        self.pub_image = self.create_publisher(Image, "/camera/image_raw", _RELIABLE_QOS)
        self.pub_info = self.create_publisher(CameraInfo, "/camera/camera_info", _RELIABLE_QOS)
        self.create_timer(0.1, self._timer_cb)

    def _status_cb(self, msg: MissionStatus) -> None:
        if msg.phase == "return_to_origin":
            self.entered_return = True
        if msg.phase == "done":
            self.mission_done = True

    def _pose_cb(self, msg: Odometry) -> None:
        self.drone_pose = msg

    def _override_cb(self, msg: PoseStamped) -> None:
        self.override_count += 1
        self.last_override = msg

    def _timer_cb(self) -> None:
        if self.drone_pose is None:
            return

        x = self.drone_pose.pose.pose.position.x
        y = self.drone_pose.pose.pose.position.y
        z = self.drone_pose.pose.pose.position.z

        q = self.drone_pose.pose.pose.orientation
        yaw = enu_yaw_from_quaternion(q.w, q.x, q.y, q.z)

        # ENU offset drone -> marker, rotated into body FLU.
        dx_enu = _MARKER_X - x
        dy_enu = _MARKER_Y - y
        dx_body, dy_body = enu_offset_to_body_flu((dx_enu, dy_enu, 0.0), yaw)
        dz_body = -z

        # Body FLU -> camera frame (nadir alignment).
        x_c = -dy_body
        y_c = -dx_body
        z_c = -dz_body

        width = 640
        height = 640
        img = np.ones((height, width, 3), dtype=np.uint8) * 255

        if z_c > 0.1:
            fx = fy = 500.0
            cx = cy = 320.0
            u = int(fx * x_c / z_c + cx)
            v = int(fy * y_c / z_c + cy)
            if 0 <= u < width and 0 <= v < height:
                aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
                size_px = int(fx * 0.2 / z_c)
                size_px = max(10, min(200, size_px))
                half_size = size_px // 2
                u0 = max(0, u - half_size)
                u1 = min(width, u + half_size)
                v0 = max(0, v - half_size)
                v1 = min(height, v + half_size)
                m_u0 = u0 - (u - half_size)
                m_u1 = m_u0 + (u1 - u0)
                m_v0 = v0 - (v - half_size)
                m_v1 = m_v0 + (v1 - v0)
                if (u1 > u0) and (v1 > v0):
                    marker_img = cv2.aruco.generateImageMarker(aruco_dict, 0, size_px)
                    marker_bgr = cv2.cvtColor(marker_img, cv2.COLOR_GRAY2BGR)
                    img[v0:v1, u0:u1] = marker_bgr[m_v0:m_v1, m_u0:m_u1]

        img_msg = Image()
        img_msg.header.stamp = self.get_clock().now().to_msg()
        img_msg.header.frame_id = "camera_link"
        img_msg.height = height
        img_msg.width = width
        img_msg.encoding = "bgr8"
        img_msg.is_bigendian = 0
        img_msg.step = width * 3
        img_msg.data = img.tobytes()
        self.pub_image.publish(img_msg)

        info_msg = CameraInfo()
        info_msg.header.stamp = img_msg.header.stamp
        info_msg.header.frame_id = "camera_link"
        info_msg.width = width
        info_msg.height = height
        info_msg.k = [500.0, 0.0, 320.0, 0.0, 500.0, 320.0, 0.0, 0.0, 1.0]
        info_msg.d = [0.0, 0.0, 0.0, 0.0, 0.0]
        self.pub_info.publish(info_msg)


async def run(timeout_s: float = _TIMEOUT_S) -> bool:
    rclpy.init()
    from _common import trigger_auto_arm, trigger_cleanup

    trigger_auto_arm()
    node = _ScenarioNode()
    started = time.monotonic()
    passed = False
    reason = ""

    from rich.console import Console

    console = Console()

    try:

        def done() -> bool:
            return node.mission_done

        console.print("[cyan]Waiting for search -> relocalize -> return -> done...[/cyan]")

        try:
            await asyncio.wait_for(spin_until(node, done), timeout=timeout_s)
        except TimeoutError:
            elapsed = time.monotonic() - started
            console.print(
                f"[red]✗ FAIL — timeout after {timeout_s}s "
                f"(override_count={node.override_count}, "
                f"entered_return={node.entered_return})[/red]"
            )
            write_report(
                "06_search_relocalize",
                False,
                elapsed,
                {
                    "reason": "timeout",
                    "override_count": node.override_count,
                    "entered_return": node.entered_return,
                },
            )
            return False

        elapsed = time.monotonic() - started

        if node.override_count > 0 and node.mission_done and node.entered_return:
            passed = True
        elif node.override_count == 0:
            reason = "mission completed but no /drone/pose_override was ever published"
        elif not node.entered_return:
            reason = "mission reached done without passing through return_to_origin"
        else:
            reason = "unexpected terminal state"

        if passed:
            console.print(
                f"[green]✓ PASS — relocalized ({node.override_count} overrides) and returned "
                f"to origin in {elapsed:.1f}s[/green]"
            )
            write_report(
                "06_search_relocalize",
                True,
                elapsed,
                {"override_count": node.override_count},
            )
        else:
            console.print(f"[red]✗ FAIL — {reason}[/red]")
            write_report("06_search_relocalize", False, elapsed, {"reason": reason})

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
