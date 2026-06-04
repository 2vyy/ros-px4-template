#!/usr/bin/env python3
"""Scenario 05 — ArUco marker hover.

Pass: mission_manager enters phase 'marker_hover' and stabilizes target pose.
Fail: timeout, or target pose error is too large.

Requires: a running sim with aruco_pose_publisher.
Run: just scenario 05_aruco_hover
"""

from __future__ import annotations

import asyncio
import math
import sys
import time

import cv2
import numpy as np
import rclpy
from _common import spin_until, write_report
from geometry_msgs.msg import PoseStamped, Vector3Stamped
from px4_ros_msgs.msg import MissionStatus
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CameraInfo, Image

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_TIMEOUT_S = 180.0


class _ScenarioNode(Node):
    def __init__(self) -> None:
        super().__init__("scenario_05_aruco_hover")
        self.entered_marker_hover = False
        self.mission_done = False
        self.drone_pose: PoseStamped | None = None
        self.marker_offset_body: Vector3Stamped | None = None
        self.target_pose: PoseStamped | None = None

        # Subscriptions
        self.create_subscription(
            MissionStatus, "/drone/mission_status", self._status_cb, _RELIABLE_QOS
        )
        self.create_subscription(PoseStamped, "/drone/pose_enu", self._pose_cb, _RELIABLE_QOS)
        self.create_subscription(PoseStamped, "/drone/target_pose", self._target_cb, _RELIABLE_QOS)
        self.create_subscription(
            Vector3Stamped, "/drone/marker_offset_body", self._offset_cb, _RELIABLE_QOS
        )

        # Publishers for synthetic camera data
        self.pub_image = self.create_publisher(Image, "/camera/image_raw", _RELIABLE_QOS)
        self.pub_info = self.create_publisher(CameraInfo, "/camera/camera_info", _RELIABLE_QOS)

        # Publish timer (10Hz)
        self.create_timer(0.1, self._timer_cb)

    def _status_cb(self, msg: MissionStatus) -> None:
        if msg.phase == "marker_hover":
            self.entered_marker_hover = True
        if msg.phase == "done":
            self.mission_done = True

    def _pose_cb(self, msg: PoseStamped) -> None:
        self.drone_pose = msg

    def _target_cb(self, msg: PoseStamped) -> None:
        self.target_pose = msg

    def _offset_cb(self, msg: Vector3Stamped) -> None:
        self.marker_offset_body = msg

    def _timer_cb(self) -> None:
        if self.drone_pose is None:
            return

        # Get current drone pose
        x = self.drone_pose.pose.position.x
        y = self.drone_pose.pose.position.y
        z = self.drone_pose.pose.position.z

        # Calculate yaw from quaternion
        q = self.drone_pose.pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny_cosp, cosy_cosp)

        # Marker physical location (at the final waypoint 8.0, 0.0)
        marker_x = 8.0
        marker_y = 0.0

        # 1. ENU relative offset
        dx_enu = marker_x - x
        dy_enu = marker_y - y

        # 2. Rotate to body FLU (Forward-Left-Up)
        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)
        dx_body = dx_enu * cos_yaw + dy_enu * sin_yaw
        dy_body = -dx_enu * sin_yaw + dy_enu * cos_yaw
        dz_body = -z

        # 3. Body to Camera frame (Nadir alignment)
        # Cam X = -Body Y
        # Cam Y = -Body X
        # Cam Z = -Body Z
        x_c = -dy_body
        y_c = -dx_body
        z_c = -dz_body

        # Canvas dimensions
        width = 640
        height = 640
        img = np.ones((height, width, 3), dtype=np.uint8) * 255

        # If marker is in front of camera, render it
        if z_c > 0.1:
            # Camera Intrinsics
            fx = fy = 500.0
            cx = cy = 320.0

            # Perspective projection
            u = int(fx * x_c / z_c + cx)
            v = int(fy * y_c / z_c + cy)

            # Check if within image bounds
            if 0 <= u < width and 0 <= v < height:
                # Render ArUco marker
                aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
                # Physical marker is 0.2m size, camera focal length is 500
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

        # Publish Image
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

        # Publish Camera Info
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

    try:

        def done() -> bool:
            return (node.entered_marker_hover and node.target_pose is not None) or node.mission_done

        from rich.console import Console

        console = Console()
        console.print("[cyan]Waiting for marker_hover phase...[/cyan]")

        try:
            await asyncio.wait_for(spin_until(node, done), timeout=timeout_s)
        except TimeoutError:
            elapsed = time.monotonic() - started
            console.print(f"[red]✗ FAIL — timeout after {timeout_s}s[/red]")
            write_report("05_aruco_hover", False, elapsed, {"reason": "timeout"})
            return False

        elapsed = time.monotonic() - started

        # Check assertions
        if node.entered_marker_hover and node.target_pose is not None:
            tgt_x = node.target_pose.pose.position.x
            tgt_y = node.target_pose.pose.position.y
            err_xy = math.dist((tgt_x, tgt_y), (8.0, 0.0))

            console.print(
                f"[cyan]Target pose when entering hover: ({tgt_x:.2f}, {tgt_y:.2f}) "
                f"- Error: {err_xy:.2f}m[/cyan]"
            )
            if err_xy < 0.5:
                passed = True
            else:
                reason = f"Target pose error too large: {err_xy:.2f}m"
        else:
            reason = "Mission completed or failed without entering marker_hover phase"

        if passed:
            console.print(
                "[green]✓ PASS — successfully verified ArUco hover target "
                f"in {elapsed:.1f}s[/green]"
            )
            write_report("05_aruco_hover", True, elapsed, {})
        else:
            console.print(f"[red]✗ FAIL — {reason}[/red]")
            write_report("05_aruco_hover", False, elapsed, {"reason": reason})

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
