#!/usr/bin/env python3
"""Scenario 08 — Precision landing on a marker (center_land -> Land -> NAV_LAND).

Pass, in order: mission reaches `descend` and descends; the commanded
altitude FREEZES when the synthetic marker is withheld and the mission
diverts to `reacquire`; descent resumes once the marker reappears; PX4
accepts `NAV_LAND`; the vehicle disarms; the mission reaches the terminal
`done` state. (The no-later-arm/OFFBOARD property is verified separately by
log inspection during live verification -- see AGENTS.md Step 8.2 / the
plan 042 addendum -- not asserted here.)

Fail: timeout, or any funnel stage does not happen (see `write_report` detail
for exactly which one).

Requires: a running sim with aruco_pose_publisher (`--vision aruco`) and the
`precision_land` overlay/mission.
Run: just scenario 08_precision_land
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
from nav_msgs.msg import Odometry
from px4_msgs.msg import VehicleCommand, VehicleCommandAck
from px4_ros_msgs.msg import ControllerStatus, MissionStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from ros_px4_template_core.lib.frames import enu_offset_to_body_flu, enu_yaw_from_quaternion
from sensor_msgs.msg import CameraInfo, Image

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_TIMEOUT_S = 240.0
_MARKER_X, _MARKER_Y = 8.0, 0.0
_LOSS_TRIGGER_Z = 2.3  # withhold the marker once descent is clearly underway
_FREEZE_HOLD_S = 2.0  # how long to hold the marker off once 'reacquire' is observed
_FREEZE_TOL_M = 0.15


class _ScenarioNode(Node):
    def __init__(self) -> None:
        super().__init__("scenario_08_precision_land")
        self.phase: str | None = None
        self.drone_pose: Odometry | None = None
        self.armed: bool | None = None
        self.disarmed_seen = False

        self.entered_descend = False
        self.min_z_seen: float | None = None
        self.xy_err_at_min_z: float | None = None
        self.froze_on_loss = False
        self.reacquired = False
        self.nav_land_ack: str | None = None

        # Loss-experiment state machine: idle -> withheld -> frozen_hold -> resumed -> done
        self._loss_stage = "idle"
        self._freeze_start_time: float | None = None
        self._freeze_start_z: float | None = None

        self.create_subscription(
            MissionStatus, "/drone/mission_status", self._status_cb, _RELIABLE_QOS
        )
        self.create_subscription(Odometry, "/drone/odom", self._pose_cb, _RELIABLE_QOS)
        self.create_subscription(
            ControllerStatus, "/drone/controller_status", self._controller_cb, _RELIABLE_QOS
        )
        self.create_subscription(
            VehicleCommandAck, "/fmu/out/vehicle_command_ack", self._ack_cb, _PX4_QOS
        )

        self.pub_image = self.create_publisher(Image, "/camera/image_raw", _RELIABLE_QOS)
        self.pub_info = self.create_publisher(CameraInfo, "/camera/camera_info", _RELIABLE_QOS)

        self.create_timer(0.1, self._timer_cb)

    def _status_cb(self, msg: MissionStatus) -> None:
        self.phase = msg.phase
        if msg.phase == "descend":
            self.entered_descend = True
            if self._loss_stage == "resumed":
                self.reacquired = True
                self._loss_stage = "done"
        if msg.phase == "reacquire" and self._loss_stage == "withheld":
            self._loss_stage = "frozen_hold"
            self._freeze_start_time = time.monotonic()
            if self.drone_pose is not None:
                self._freeze_start_z = self.drone_pose.pose.pose.position.z

    def _pose_cb(self, msg: Odometry) -> None:
        self.drone_pose = msg
        z = msg.pose.pose.position.z
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        if self.entered_descend and (self.min_z_seen is None or z < self.min_z_seen):
            self.min_z_seen = z
            self.xy_err_at_min_z = math.dist((x, y), (_MARKER_X, _MARKER_Y))

    def _controller_cb(self, msg: ControllerStatus) -> None:
        was_armed = self.armed
        self.armed = msg.armed
        if was_armed and not msg.armed:
            self.disarmed_seen = True

    def _ack_cb(self, msg: VehicleCommandAck) -> None:
        if msg.command != VehicleCommand.VEHICLE_CMD_NAV_LAND:
            return
        self.nav_land_ack = (
            "ACCEPTED"
            if msg.result == VehicleCommandAck.VEHICLE_CMD_RESULT_ACCEPTED
            else f"result={msg.result}"
        )

    @property
    def publish_marker(self) -> bool:
        return self._loss_stage in ("idle", "resumed", "done")

    def _timer_cb(self) -> None:
        if self.drone_pose is None:
            return
        z = self.drone_pose.pose.pose.position.z

        if self._loss_stage == "idle" and self.entered_descend and z <= _LOSS_TRIGGER_Z:
            self._loss_stage = "withheld"  # stop publishing; wait for 'reacquire'

        if self._loss_stage == "frozen_hold" and self._freeze_start_time is not None:
            elapsed = time.monotonic() - self._freeze_start_time
            if elapsed >= _FREEZE_HOLD_S:
                if self._freeze_start_z is not None:
                    self.froze_on_loss = abs(z - self._freeze_start_z) <= _FREEZE_TOL_M
                self._loss_stage = "resumed"  # start publishing again

        if self.publish_marker:
            self._publish_marker_frame()

    def _publish_marker_frame(self) -> None:
        assert self.drone_pose is not None
        x = self.drone_pose.pose.pose.position.x
        y = self.drone_pose.pose.pose.position.y
        z = self.drone_pose.pose.pose.position.z
        q = self.drone_pose.pose.pose.orientation
        yaw = enu_yaw_from_quaternion(q.w, q.x, q.y, q.z)

        dx_enu = _MARKER_X - x
        dy_enu = _MARKER_Y - y
        dx_body, dy_body = enu_offset_to_body_flu((dx_enu, dy_enu, 0.0), yaw)
        dz_body = -z

        # Body -> camera (nadir alignment): Cam X = -Body Y, Cam Y = -Body X, Cam Z = -Body Z.
        x_c = -dy_body
        y_c = -dx_body
        z_c = -dz_body

        width = height = 640
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


def _detail(node: _ScenarioNode) -> dict:
    return {
        "entered_descend": node.entered_descend,
        "froze_on_loss": node.froze_on_loss,
        "reacquired": node.reacquired,
        "min_z_seen": round(node.min_z_seen, 2) if node.min_z_seen is not None else None,
        "xy_err_at_min_z": (
            round(node.xy_err_at_min_z, 2) if node.xy_err_at_min_z is not None else None
        ),
        "nav_land_ack": node.nav_land_ack,
        "disarmed_seen": node.disarmed_seen,
    }


async def run(timeout_s: float = _TIMEOUT_S) -> bool:
    rclpy.init()
    from _common import trigger_auto_arm, trigger_cleanup

    arm_trigger_ok = trigger_auto_arm()
    node = _ScenarioNode()
    started = time.monotonic()
    passed = False
    reason = ""

    try:

        def done() -> bool:
            return node.disarmed_seen and node.phase == "done"

        from rich.console import Console

        console = Console()
        console.print(
            "[cyan]Waiting for the precision-landing funnel: descend -> freeze "
            "on marker loss -> reacquire -> resumed descent -> NAV_LAND -> "
            "disarm -> done...[/cyan]"
        )

        try:
            await asyncio.wait_for(spin_until(node, done), timeout=timeout_s)
        except TimeoutError:
            elapsed = time.monotonic() - started
            console.print(f"[red]✗ FAIL — timeout after {timeout_s}s[/red]")
            write_report(
                "08_precision_land",
                False,
                elapsed,
                {"reason": "timeout", "arm_trigger_ok": arm_trigger_ok, **_detail(node)},
            )
            return False

        elapsed = time.monotonic() - started
        detail = _detail(node)

        if not node.entered_descend:
            reason = "never entered descend phase"
        elif not node.froze_on_loss:
            reason = "altitude did not freeze on synthetic marker loss"
        elif not node.reacquired:
            reason = "did not re-enter descend after marker was restored"
        elif node.nav_land_ack != "ACCEPTED":
            reason = f"NAV_LAND ack not accepted ({node.nav_land_ack})"
        elif not node.disarmed_seen:
            reason = "vehicle never observed disarmed"
        elif node.phase != "done":
            reason = f"mission did not reach terminal 'done' (phase={node.phase})"
        else:
            passed = True

        if passed:
            console.print(
                f"[green]✓ PASS — landed xy_err={detail['xy_err_at_min_z']}m "
                f"in {elapsed:.1f}s[/green]"
            )
            write_report(
                "08_precision_land",
                True,
                elapsed,
                {"detail": f"landed xy_err={detail['xy_err_at_min_z']}m", **detail},
            )
        else:
            console.print(f"[red]✗ FAIL — {reason}[/red]")
            write_report("08_precision_land", False, elapsed, {"reason": reason, **detail})

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
