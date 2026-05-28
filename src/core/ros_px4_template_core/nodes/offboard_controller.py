"""Offboard position controller — streams setpoints, optional auto-arm.

Yaw is omitted (NaN) for position-only missions so PX4 holds current heading.
=============================================================================
"""

from __future__ import annotations

import math
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from px4_msgs.msg import (
    OffboardControlMode,
    TrajectorySetpoint,
    VehicleCommand,
    VehicleCommandAck,
    VehicleLocalPosition,
    VehicleStatus,
)
from px4_ros_msgs.msg import ControllerStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from ros_px4_template_core.lib import events
from ros_px4_template_core.lib.frame_transforms import enu_to_ned, ned_to_enu
from ros_px4_template_core.lib.structured_logger import StructuredLogger

_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)

# PX4 custom main mode OFFBOARD
_PX4_CUSTOM_MAIN_MODE_OFFBOARD = 6

_ACK_RESULT_NAMES = {
    0: "ACCEPTED",
    1: "TEMPORARILY_REJECTED",
    2: "DENIED",
    3: "UNSUPPORTED",
    4: "FAILED",
    5: "IN_PROGRESS",
    6: "CANCELLED",
}


class OffboardController(Node):
    """Controls drone position via PX4 OFFBOARD mode."""

    def __init__(self) -> None:
        super().__init__("offboard_controller")
        self.declare_parameter("log_dir", "./logs")
        self.declare_parameter("target_altitude_m", 3.0)
        self.declare_parameter("position_tolerance_m", 0.3)
        self.declare_parameter("setpoint_rate_hz", 20.0)
        self.declare_parameter("auto_arm", True)
        self.declare_parameter("arm_delay_s", 15.0)
        self.declare_parameter("offboard_prestream_s", 1.0)

        log_dir = str(self.get_parameter("log_dir").value)
        self._target_alt = float(self.get_parameter("target_altitude_m").value)
        self._tolerance = float(self.get_parameter("position_tolerance_m").value)
        self._auto_arm = bool(self.get_parameter("auto_arm").value)
        self._arm_delay_s = float(self.get_parameter("arm_delay_s").value)
        self._prestream_s = float(self.get_parameter("offboard_prestream_s").value)

        self.slog = StructuredLogger(self, log_dir=log_dir)
        self._state = "IDLE"
        self._start_time = time.monotonic()
        self._setpoints_sent = 0
        self._last_arm_try = 0.0
        self._last_offboard_try = 0.0
        self._current_pos_enu = (0.0, 0.0, 0.0)
        self._setpoint_enu = (0.0, 0.0, self._target_alt)
        self._armed = False
        self._nav_state = 0
        self._arm_failed = False
        self._arm_fail_reason = ""
        self._px4_ever_disarmed: bool = False  # latch: blocks arm until PX4 DISARMED seen
        # Wall-clock time when first VehicleLocalPosition arrived (XRCE connected + PX4 alive).
        # Used as the real arm-readiness signal instead of a fixed delay from node start.
        self._xrce_connect_time: float | None = None

        self.create_subscription(
            PoseStamped, "/drone/target_pose", self._target_pose_cb, _RELIABLE_QOS
        )
        self.create_subscription(
            VehicleLocalPosition,
            "/fmu/out/vehicle_local_position",
            self._position_cb,
            _PX4_QOS,
        )
        self.create_subscription(
            VehicleStatus, "/fmu/out/vehicle_status", self._status_cb, _PX4_QOS
        )
        self.create_subscription(
            VehicleCommandAck,
            "/fmu/out/vehicle_command_ack",
            self._command_ack_cb,
            _PX4_QOS,
        )

        self._pub_setpoint = self.create_publisher(
            TrajectorySetpoint, "/fmu/in/trajectory_setpoint", _PX4_QOS
        )
        self._pub_offboard_mode = self.create_publisher(
            OffboardControlMode, "/fmu/in/offboard_control_mode", _PX4_QOS
        )
        self._pub_vehicle_cmd = self.create_publisher(
            VehicleCommand, "/fmu/in/vehicle_command", _PX4_QOS
        )
        self._pub_status = self.create_publisher(
            ControllerStatus, "/drone/controller_status", _RELIABLE_QOS
        )

        rate = float(self.get_parameter("setpoint_rate_hz").value)
        self.create_timer(1.0 / rate, self._control_loop)
        self.slog.info("OffboardController initialized", state=self._state)

    def _target_pose_cb(self, msg: PoseStamped) -> None:
        self._setpoint_enu = (
            msg.pose.position.x,
            msg.pose.position.y,
            msg.pose.position.z,
        )

    def _position_cb(self, msg: VehicleLocalPosition) -> None:
        self._current_pos_enu = ned_to_enu(msg.x, msg.y, msg.z)
        if self._xrce_connect_time is None:
            self._xrce_connect_time = time.monotonic()
            self.slog.event("XRCE_CONNECTED", wall_elapsed_s=round(self._elapsed(), 2))

    def _status_cb(self, msg: VehicleStatus) -> None:
        self._armed = msg.arming_state == VehicleStatus.ARMING_STATE_ARMED
        self._nav_state = int(msg.nav_state)
        if not self._px4_ever_disarmed and msg.arming_state == VehicleStatus.ARMING_STATE_DISARMED:
            self._px4_ever_disarmed = True
            self.slog.event("PX4_DISARMED_OBSERVED")

    def _command_ack_cb(self, msg: VehicleCommandAck) -> None:
        if msg.command != VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM:
            return
        result = int(msg.result)
        if result == VehicleCommandAck.VEHICLE_CMD_RESULT_ACCEPTED:
            self.slog.event(events.ARM_ACK_OK)
            return
        reason = _ACK_RESULT_NAMES.get(result, f"unknown({result})")
        self.slog.event(
            events.ARM_ACK_DENIED, result=result, reason=reason, param1=float(msg.result_param1)
        )
        # Only truly terminal: UNSUPPORTED or FAILED. DENIED can happen before
        # COM_ARM_WO_GPS=1 is applied via GCS; keep retrying so the next cycle succeeds.
        # TEMPORARILY_REJECTED and IN_PROGRESS are also non-terminal.
        if result in (
            VehicleCommandAck.VEHICLE_CMD_RESULT_UNSUPPORTED,
            VehicleCommandAck.VEHICLE_CMD_RESULT_FAILED,
        ):
            if not self._arm_failed:
                self._arm_failed = True
                self._arm_fail_reason = reason
                self.slog.error("Arm command failed terminally", reason=reason, result=result)

    def _elapsed(self) -> float:
        return time.monotonic() - self._start_time

    def _update_state_machine(self) -> None:
        if not self._auto_arm:
            self._state = "ARMED" if self._armed else "IDLE"
            return

        elapsed = self._elapsed()

        # XRCE-triggered arm: don't use a fixed wall-clock delay from node start,
        # because ROS timers only fire once Gazebo's sim clock flows, which means
        # arm_delay_s has already elapsed by the time the first callback fires.
        # Instead, arm as soon as the first VehicleLocalPosition message arrives
        # (proving XRCE is connected and PX4 is live), with a small settle buffer.
        xrce_ready = (
            self._xrce_connect_time is not None
            and (time.monotonic() - self._xrce_connect_time) >= self._arm_delay_s
            and self._setpoints_sent > 5
            and self._px4_ever_disarmed
        )

        if not xrce_ready:
            self._state = "PREARM"
            return

        # Hammer OFFBOARD mode at 2.0s until confirmed — early commands are
        # discarded by PX4 while XRCE timestamps are not yet synced.
        if self._nav_state != VehicleStatus.NAVIGATION_STATE_OFFBOARD:
            if elapsed - self._last_offboard_try >= 2.0:
                self._send_offboard_mode()
                self._last_offboard_try = elapsed

        if not self._armed and not self._arm_failed:
            if elapsed - self._last_arm_try >= 2.0:
                self._send_arm(True)
                self._last_arm_try = elapsed
                self.slog.event(events.ARM_COMMAND_SENT)

        if self._armed:
            self._state = "ARMED"
        elif self._arm_failed:
            self._state = "ARM_FAILED"
        else:
            self._state = "ARMING"

    def _control_loop(self) -> None:
        self._publish_offboard_mode()
        self._publish_setpoint()
        self._setpoints_sent += 1
        self._update_state_machine()

        status = ControllerStatus()
        status.header.stamp = self.get_clock().now().to_msg()
        status.state = self._state
        status.armed = self._armed
        status.altitude_enu_m = float(self._current_pos_enu[2])
        err = math.dist(self._current_pos_enu, self._setpoint_enu)
        status.position_error_m = float(err)
        self._pub_status.publish(status)

    def _publish_offboard_mode(self) -> None:
        msg = OffboardControlMode()
        msg.position = True
        msg.timestamp = int(self.get_clock().now().nanoseconds / 1000)
        self._pub_offboard_mode.publish(msg)

    def _publish_setpoint(self) -> None:
        ned = enu_to_ned(*self._setpoint_enu)
        msg = TrajectorySetpoint()
        msg.position = [float(ned[0]), float(ned[1]), float(ned[2])]
        msg.yaw = float("nan")
        msg.timestamp = int(self.get_clock().now().nanoseconds / 1000)
        self._pub_setpoint.publish(msg)

    def _vehicle_command(self, command: int, **params: float) -> None:
        msg = VehicleCommand()
        msg.timestamp = int(self.get_clock().now().nanoseconds / 1000)
        msg.command = command
        msg.param1 = float(params.get("param1", 0.0))
        msg.param2 = float(params.get("param2", 0.0))
        msg.param3 = float(params.get("param3", 0.0))
        msg.param4 = float(params.get("param4", 0.0))
        msg.param5 = float(params.get("param5", 0.0))
        msg.param6 = float(params.get("param6", 0.0))
        msg.param7 = float(params.get("param7", 0.0))
        msg.target_system = 1
        msg.target_component = 1
        msg.source_system = 1
        msg.source_component = 1
        msg.from_external = True
        self._pub_vehicle_cmd.publish(msg)

    def _send_arm(self, arm: bool) -> None:
        self._vehicle_command(
            VehicleCommand.VEHICLE_CMD_COMPONENT_ARM_DISARM,
            param1=1.0 if arm else 0.0,
        )

    def _send_offboard_mode(self) -> None:
        self._vehicle_command(
            VehicleCommand.VEHICLE_CMD_DO_SET_MODE,
            param1=1.0,
            param2=float(_PX4_CUSTOM_MAIN_MODE_OFFBOARD),
        )
        self.slog.event(events.OFFBOARD_MODE_COMMAND)

    def destroy_node(self) -> None:
        self.slog.close()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = OffboardController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
