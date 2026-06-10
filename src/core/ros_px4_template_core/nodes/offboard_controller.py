"""Offboard position controller — streams setpoints, optional auto-arm.

Yaw is omitted (NaN) for position-only missions so PX4 holds current heading.
PX4 mc_pos_control tracks ``/drone/target_pose`` waypoints in OFFBOARD mode.
=============================================================================
"""

from __future__ import annotations

import math

import rclpy
from geometry_msgs.msg import PoseStamped, Vector3Stamped
from nav_msgs.msg import Odometry
from px4_msgs.msg import (
    OffboardControlMode,
    TrajectorySetpoint,
    VehicleCommand,
    VehicleCommandAck,
    VehicleStatus,
)
from px4_ros_msgs.msg import ControllerStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from ros_px4_template_core.lib import events, offboard_fsm
from ros_px4_template_core.lib.frames import enu_setpoint_to_px4_ned
from ros_px4_template_core.lib.offboard_fsm import NAV_STATE_OFFBOARD
from ros_px4_template_core.lib.setpoint_hold import (
    effective_target_setpoint,
    is_target_pose_stale,
)
from ros_px4_template_core.lib.structured_logger import StructuredLogger

_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)

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
    """Streams position setpoints to PX4 OFFBOARD mode."""

    def __init__(self) -> None:
        super().__init__("offboard_controller")
        self.declare_parameter("log_dir", "./logs")
        self.declare_parameter("target_altitude_m", 3.0)
        self.declare_parameter("setpoint_rate_hz", 20.0)
        self.declare_parameter("auto_arm", True)
        self.declare_parameter("arm_delay_s", 15.0)
        self.declare_parameter("target_pose_timeout_s", 2.0)
        self.declare_parameter("position_ramp_s", 0.0)

        self._target_alt = float(self.get_parameter("target_altitude_m").value)
        self._auto_arm = bool(self.get_parameter("auto_arm").value)
        self._arm_delay_s = float(self.get_parameter("arm_delay_s").value)
        self._target_pose_timeout_s = float(self.get_parameter("target_pose_timeout_s").value)

        self.slog = StructuredLogger(self)
        self._state = "IDLE"
        self._start_time_ns = self.get_clock().now().nanoseconds
        self._setpoints_sent = 0
        self._last_arm_try = 0.0
        self._last_offboard_try = 0.0
        self._current_pos_enu = (0.0, 0.0, 0.0)
        self._setpoint_enu = (0.0, 0.0, self._target_alt)
        self._armed = False
        self._nav_state = 0
        self._arm_failed = False
        self._arm_fail_reason = ""
        self._px4_ever_disarmed = False
        self._xrce_connect_time: float | None = None
        self._last_target_pose_time: float | None = None
        self._target_pose_stale = False
        self._offboard_since: float | None = None
        self._initial_pos_enu: tuple[float, float, float] | None = None
        self._have_odom = False
        self._setpoint_origin_ned: tuple[float, float, float] | None = None

        self.create_subscription(
            PoseStamped, "/drone/target_pose", self._target_pose_cb, _RELIABLE_QOS
        )
        self.create_subscription(Odometry, "/drone/odom", self._odom_cb, _RELIABLE_QOS)
        self.create_subscription(
            Vector3Stamped,
            "/drone/local_origin",
            self._local_origin_cb,
            QoSProfile(
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                history=HistoryPolicy.KEEP_LAST,
                depth=1,
            ),
        )
        self.create_subscription(
            VehicleStatus, "/fmu/out/vehicle_status_v1", self._status_cb, _PX4_QOS
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
        self._last_target_pose_time = self.get_clock().now().nanoseconds / 1e9
        if self._target_pose_stale:
            self._target_pose_stale = False
            self.slog.event(events.TARGET_POSE_STALE, active=False)

    def _active_setpoint_enu(self) -> tuple[float, float, float]:
        now = self.get_clock().now().nanoseconds / 1e9
        active = effective_target_setpoint(
            self._setpoint_enu,
            self._current_pos_enu,
            self._last_target_pose_time,
        )
        stale = is_target_pose_stale(
            self._last_target_pose_time,
            now,
            self._target_pose_timeout_s,
        )
        if stale and not self._target_pose_stale:
            self._target_pose_stale = True
            self.slog.event(events.TARGET_POSE_STALE, active=True)
        elif not stale and self._target_pose_stale:
            self._target_pose_stale = False
            self.slog.event(events.TARGET_POSE_STALE, active=False)
        return active

    def _odom_cb(self, msg: Odometry) -> None:
        self._current_pos_enu = (
            float(msg.pose.pose.position.x),
            float(msg.pose.pose.position.y),
            float(msg.pose.pose.position.z),
        )
        ros_time_us = int(self.get_clock().now().nanoseconds / 1000)
        if ros_time_us > 0 and self._xrce_connect_time is None:
            self._xrce_connect_time = ros_time_us / 1e6
            self.slog.event("XRCE_CONNECTED", wall_elapsed_s=round(self._elapsed(), 2))
        self._have_odom = True

    def _local_origin_cb(self, msg: Vector3Stamped) -> None:
        self._setpoint_origin_ned = (
            float(msg.vector.x),
            float(msg.vector.y),
            float(msg.vector.z),
        )

    def _status_cb(self, msg: VehicleStatus) -> None:
        was_armed = self._armed
        self._armed = msg.arming_state == VehicleStatus.ARMING_STATE_ARMED
        self._nav_state = int(msg.nav_state)
        if was_armed and not self._armed:
            self._auto_arm = False
            self.slog.event("AUTO_ARM_DISABLED_ON_DISARM")
        if (
            not self._px4_ever_disarmed
            and msg.arming_state == VehicleStatus.ARMING_STATE_DISARMED
            and msg.pre_flight_checks_pass
        ):
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
        if result in (
            VehicleCommandAck.VEHICLE_CMD_RESULT_UNSUPPORTED,
            VehicleCommandAck.VEHICLE_CMD_RESULT_FAILED,
        ):
            if not self._arm_failed:
                self._arm_failed = True
                self._arm_fail_reason = reason
                self.slog.error("Arm command failed terminally", reason=reason, result=result)

    def _elapsed(self) -> float:
        if self._start_time_ns == 0:
            self._start_time_ns = self.get_clock().now().nanoseconds
        return (self.get_clock().now().nanoseconds - self._start_time_ns) / 1e9

    def _update_state_machine(self) -> None:
        self._auto_arm = bool(self.get_parameter("auto_arm").value)
        xrce_elapsed = (
            (self.get_clock().now().nanoseconds / 1e9 - self._xrce_connect_time)
            if self._xrce_connect_time is not None
            else 0.0
        )
        result = offboard_fsm.tick(
            offboard_fsm.FsmInputs(
                elapsed_s=self._elapsed(),
                auto_arm=self._auto_arm,
                armed=self._armed,
                arm_failed=self._arm_failed,
                xrce_connected=self._xrce_connect_time is not None,
                xrce_elapsed_s=xrce_elapsed,
                setpoints_sent=self._setpoints_sent,
                px4_ever_disarmed=self._px4_ever_disarmed,
                nav_state=self._nav_state,
                arm_delay_s=self._arm_delay_s,
                last_arm_try_s=self._last_arm_try,
                last_offboard_try_s=self._last_offboard_try,
            )
        )
        self._state = result.state
        if result.send_offboard:
            self._send_offboard_mode()
            self._last_offboard_try = self._elapsed()
        if result.send_arm:
            self._send_arm(True)
            self._last_arm_try = self._elapsed()
            self.slog.event(events.ARM_COMMAND_SENT)

        if self._nav_state == NAV_STATE_OFFBOARD and self._offboard_since is None:
            self._offboard_since = self._elapsed()
            self._initial_pos_enu = self._current_pos_enu
        elif self._nav_state != NAV_STATE_OFFBOARD:
            self._offboard_since = None
            self._initial_pos_enu = None

    def _ramped_setpoint_enu(
        self, mission_enu: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        ramp_s = float(self.get_parameter("position_ramp_s").value)
        if self._offboard_since is None or ramp_s <= 0.0 or self._initial_pos_enu is None:
            return mission_enu
        t = self._elapsed() - self._offboard_since
        if t >= ramp_s:
            return mission_enu
        alpha = max(0.0, min(1.0, t / ramp_s))
        start = self._initial_pos_enu
        return (
            start[0] + (mission_enu[0] - start[0]) * alpha,
            start[1] + (mission_enu[1] - start[1]) * alpha,
            start[2] + (mission_enu[2] - start[2]) * alpha,
        )

    def _control_loop(self) -> None:
        if not self._have_odom or self._setpoint_origin_ned is None:
            self._publish_offboard_mode()
            self._setpoints_sent += 1
            self._update_state_machine()
            return

        mission_active = self._active_setpoint_enu()
        self._publish_offboard_mode()
        if self._nav_state == NAV_STATE_OFFBOARD:
            # uXRCE writes trajectory_setpoint directly; do not publish before OFFBOARD
            # (PX4/PX4-Autopilot#25273) or setpoints fight mc_pos_control.
            self._publish_position_setpoint(self._ramped_setpoint_enu(mission_active))
        self._setpoints_sent += 1
        self._update_state_machine()

        status = ControllerStatus()
        status.header.stamp = self.get_clock().now().to_msg()
        status.state = "TARGET_STALE" if self._target_pose_stale else self._state
        status.armed = self._armed
        status.altitude_enu_m = float(self._current_pos_enu[2])
        status.position_error_m = float(math.dist(self._current_pos_enu, mission_active))
        self._pub_status.publish(status)

    def _get_px4_timestamp(self) -> int:
        return int(self.get_clock().now().nanoseconds / 1000)

    def _publish_offboard_mode(self) -> None:
        msg = OffboardControlMode()
        msg.position = True
        msg.timestamp = self._get_px4_timestamp()
        self._pub_offboard_mode.publish(msg)

    def _publish_position_setpoint(self, target_enu: tuple[float, float, float]) -> None:
        ox, oy, oz = self._setpoint_origin_ned
        x_ned, y_ned, z_ned = enu_setpoint_to_px4_ned(
            *target_enu,
            origin_x_ned=ox,
            origin_y_ned=oy,
            origin_z_ned=oz,
        )
        msg = TrajectorySetpoint()
        msg.timestamp = self._get_px4_timestamp()
        msg.position = [float(x_ned), float(y_ned), float(z_ned)]
        msg.velocity = [float("nan"), float("nan"), float("nan")]
        msg.acceleration = [float("nan"), float("nan"), float("nan")]
        msg.yaw = float("nan")
        msg.yawspeed = float("nan")
        self._pub_setpoint.publish(msg)

    def _vehicle_command(self, command: int, **params: float) -> None:
        msg = VehicleCommand()
        msg.timestamp = self._get_px4_timestamp()
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
