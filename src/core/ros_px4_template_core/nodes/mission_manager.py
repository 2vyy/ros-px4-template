"""Mission manager — generic FSM engine adapter.

=============================================================================
ROS 2 Interface
Subscriptions:
    /drone/controller_status    [px4_ros_msgs/ControllerStatus]
    /drone/odom                 [nav_msgs/Odometry]   (position_node SoT pose)
    /drone/marker_detection     [px4_ros_msgs/MarkerDetection]
    /fmu/out/battery_status_v1  [px4_msgs/BatteryStatus]
    /fmu/out/vehicle_status_v1  [px4_msgs/VehicleStatus]  (failsafe only)
Publishers:
    /drone/target_pose      [geometry_msgs/PoseStamped]
        Orientation carries optional commanded ENU yaw (lib/target_pose codec);
        the all-zero quaternion means yaw omitted (PX4 holds heading).
    /drone/mission_status   [px4_ros_msgs/MissionStatus]
    /drone/mission_markers  [visualization_msgs/MarkerArray]
    /drone/land_command     [std_msgs/Empty]
        Published once per landing episode when the mission emits `Land`
        (e.g. `center_land`'s hand-off). offboard_controller reacts by
        commanding PX4's own NAV_LAND and suppressing its own OFFBOARD/arm
        commands. Fresh `GoTo` commands are NOT published while `Land` is
        active, so nothing fights PX4's descent.
=============================================================================
"""

from __future__ import annotations

import math
import threading
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from px4_msgs.msg import BatteryStatus, VehicleStatus
from px4_ros_msgs.msg import ControllerStatus, MarkerDetection, MissionStatus
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Empty
from visualization_msgs.msg import Marker, MarkerArray

from ros_px4_template_core.lib import events
from ros_px4_template_core.lib.frames import enu_yaw_from_quaternion
from ros_px4_template_core.lib.mission.commands import GoTo, Land
from ros_px4_template_core.lib.mission.detection import Detection
from ros_px4_template_core.lib.mission.engine import MissionContext, tick
from ros_px4_template_core.lib.mission.loader import load_mission_file
from ros_px4_template_core.lib.mission.telemetry import usable_battery_remaining
from ros_px4_template_core.lib.mission.types import Inputs
from ros_px4_template_core.lib.structured_logger import StructuredLogger
from ros_px4_template_core.lib.target_pose import target_yaw_to_quaternion

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10
)
_PX4_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)
_STABLE_FRESH_S = 0.3  # a detection counts toward stability if newer than this
_DEFAULT_MISSION = "config/missions/hover.yaml"


class MissionManager(Node):
    def __init__(self) -> None:
        super().__init__("mission_manager")
        self._tick_group = MutuallyExclusiveCallbackGroup()
        self._sub_group = ReentrantCallbackGroup()
        self._state_lock = threading.Lock()
        self.declare_parameter("log_dir", "./logs")
        self.declare_parameter("mission_file", _DEFAULT_MISSION)
        self.declare_parameter("tick_rate_hz", 10.0)
        self.declare_parameter("takeoff_altitude_m", 3.0)
        self.declare_parameter("takeoff_altitude_tolerance_m", 0.3)
        self.declare_parameter("marker_id", 0)

        self.slog = StructuredLogger(self)
        mission_file = str(self.get_parameter("mission_file").value).strip() or _DEFAULT_MISSION
        p = Path(mission_file)
        if not p.is_absolute():
            p = Path(get_package_share_directory("ros_px4_template_core")) / p
        self._mission = load_mission_file(p)
        self._ctx = MissionContext(state=self._mission.initial)
        self._takeoff_alt = float(self.get_parameter("takeoff_altitude_m").value)
        self._takeoff_alt_tol = float(self.get_parameter("takeoff_altitude_tolerance_m").value)
        self._marker_id = int(self.get_parameter("marker_id").value)
        self._marker_id_seen = self._marker_id

        self._pos_enu = (0.0, 0.0, 0.0)
        self._yaw_enu = 0.0
        self._have_odom = False
        self._odom_time = 0.0
        self._armed = False
        self._ctrl_alt = 0.0
        self._estimate_ok = True
        self._marker_offset_body: tuple[float, float, float] | None = None
        self._marker_time = 0.0
        self._marker_stability = 0
        self._last_target = (0.0, 0.0, self._takeoff_alt)
        self._last_yaw: float | None = None
        self._battery_remaining: float | None = None
        self._have_battery = False
        self._battery_time = 0.0
        self._failsafe_active = False
        self._have_vehicle_status = False
        self._vehicle_status_time = 0.0
        self._land_sent = False

        self.create_subscription(
            ControllerStatus,
            "/drone/controller_status",
            self._controller_cb,
            _RELIABLE_QOS,
            callback_group=self._sub_group,
        )
        self.create_subscription(
            Odometry, "/drone/odom", self._odom_cb, _RELIABLE_QOS, callback_group=self._sub_group
        )
        self.create_subscription(
            MarkerDetection,
            "/drone/marker_detection",
            self._detection_cb,
            _RELIABLE_QOS,
            callback_group=self._sub_group,
        )
        self.create_subscription(
            BatteryStatus,
            "/fmu/out/battery_status_v1",
            self._battery_cb,
            _PX4_QOS,
            callback_group=self._sub_group,
        )
        self.create_subscription(
            VehicleStatus,
            "/fmu/out/vehicle_status_v1",
            self._vehicle_status_cb,
            _PX4_QOS,
            callback_group=self._sub_group,
        )

        self._pub_target = self.create_publisher(PoseStamped, "/drone/target_pose", _RELIABLE_QOS)
        self._pub_status = self.create_publisher(
            MissionStatus, "/drone/mission_status", _RELIABLE_QOS
        )
        self._pub_markers = self.create_publisher(
            MarkerArray, "/drone/mission_markers", _RELIABLE_QOS
        )
        self._pub_land = self.create_publisher(Empty, "/drone/land_command", _RELIABLE_QOS)

        rate = float(self.get_parameter("tick_rate_hz").value)
        self.create_timer(1.0 / rate, self._tick, callback_group=self._tick_group)
        self.slog.info("MissionManager ready", mission=str(p), initial=self._mission.initial)

    def _controller_cb(self, msg: ControllerStatus) -> None:
        with self._state_lock:
            self._armed = msg.armed
            self._ctrl_alt = float(msg.altitude_enu_m)

    def _odom_cb(self, msg: Odometry) -> None:
        pose = msg.pose.pose
        q = pose.orientation
        pos_enu = (pose.position.x, pose.position.y, pose.position.z)
        yaw_enu = enu_yaw_from_quaternion(q.w, q.x, q.y, q.z)
        odom_time = self.get_clock().now().nanoseconds / 1e9
        with self._state_lock:
            self._pos_enu = pos_enu
            self._yaw_enu = yaw_enu
            self._have_odom = True
            self._odom_time = odom_time

    def _detection_cb(self, msg: MarkerDetection) -> None:
        marker_offset_body = (
            msg.offset_body_flu.x,
            msg.offset_body_flu.y,
            msg.offset_body_flu.z,
        )
        marker_time = self.get_clock().now().nanoseconds / 1e9
        with self._state_lock:
            if not msg.valid:
                self._marker_offset_body = None
                self._marker_stability = 0
                return
            self._marker_id_seen = int(msg.id)
            self._marker_offset_body = marker_offset_body
            self._marker_time = marker_time
            self._marker_stability += 1

    def _battery_cb(self, msg: BatteryStatus) -> None:
        remaining = usable_battery_remaining(
            connected=bool(msg.connected), remaining=float(msg.remaining)
        )
        battery_time = self.get_clock().now().nanoseconds / 1e9
        with self._state_lock:
            self._battery_remaining = remaining
            self._battery_time = battery_time
            self._have_battery = True

    def _vehicle_status_cb(self, msg: VehicleStatus) -> None:
        failsafe_active = bool(msg.failsafe)
        vehicle_status_time = self.get_clock().now().nanoseconds / 1e9
        with self._state_lock:
            self._failsafe_active = failsafe_active
            self._vehicle_status_time = vehicle_status_time
            self._have_vehicle_status = True

    def _snapshot(self, now: float) -> Inputs:
        dets: tuple[Detection, ...] = ()
        stability: dict[int, int] = {}
        with self._state_lock:
            pos_enu = self._pos_enu
            yaw_enu = self._yaw_enu
            have_odom = self._have_odom
            odom_time = self._odom_time
            armed = self._armed
            ctrl_alt = self._ctrl_alt
            estimate_ok = self._estimate_ok
            marker_offset_body = self._marker_offset_body
            marker_id_seen = self._marker_id_seen
            marker_time = self._marker_time
            marker_stability = self._marker_stability
            battery_remaining = self._battery_remaining
            have_battery = self._have_battery
            battery_time = self._battery_time
            failsafe_active = self._failsafe_active
            have_vehicle_status = self._have_vehicle_status
            vehicle_status_time = self._vehicle_status_time
            if marker_offset_body is None or now - marker_time > 1.0:
                self._marker_stability = 0
                marker_stability = 0

        if marker_offset_body is not None and now - marker_time <= 1.0:
            dets = (
                Detection(
                    id=marker_id_seen,
                    offset_body_flu=marker_offset_body,
                    stamp=marker_time,
                ),
            )
            if now - marker_time <= _STABLE_FRESH_S:
                stability = {marker_id_seen: marker_stability}
        z_eff = max(pos_enu[2], ctrl_alt)
        return Inputs(
            now=now,
            pose_enu=(pos_enu[0], pos_enu[1], z_eff),
            yaw_enu=yaw_enu,
            armed=armed,
            altitude_ok=z_eff >= self._takeoff_alt - self._takeoff_alt_tol,
            estimate_ok=estimate_ok,
            detections=dets,
            detection_stability=stability,
            input_ages={
                "odom": (now - odom_time) if have_odom else float("inf"),
                "battery": (now - battery_time) if have_battery else float("inf"),
                "vehicle_status": (
                    (now - vehicle_status_time) if have_vehicle_status else float("inf")
                ),
            },
            battery_remaining=battery_remaining,
            failsafe_active=failsafe_active,
        )

    def _tick(self) -> None:
        now = self.get_clock().now().nanoseconds / 1e9
        if not self._have_odom:
            self._publish_target((0.0, 0.0, self._takeoff_alt), None)
            return
        inputs = self._snapshot(now)
        command = tick(self._ctx, self._mission, inputs)

        for ev in self._ctx.events:
            name = str(ev.pop("event", "EVENT"))
            self.slog.event(name, **ev)
            self.get_logger().info(f"mission {name}: {ev}")
        self._ctx.events.clear()

        if isinstance(command, GoTo):
            self._last_target = (command.x, command.y, command.z)
            self._last_yaw = command.yaw
            # A fresh GoTo means any prior landing episode has ended (e.g. the
            # mission diverted back through reacquire); a later Land is a new
            # episode and must publish /drone/land_command again.
            self._land_sent = False
        if isinstance(command, Land) and not self._land_sent:
            self._land_sent = True
            self._pub_land.publish(Empty())
            self.slog.event(events.LAND_COMMAND_SENT_MISSION)
        if not isinstance(command, Land):
            self._publish_target(self._last_target, self._last_yaw)
        self._publish_status(inputs, now)
        self._publish_markers(self._last_target)

    def _publish_target(self, target, yaw_enu: float | None) -> None:
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        msg.pose.position.x = float(target[0])
        msg.pose.position.y = float(target[1])
        msg.pose.position.z = float(target[2])
        qw, qx, qy, qz = target_yaw_to_quaternion(yaw_enu)
        msg.pose.orientation.w = qw
        msg.pose.orientation.x = qx
        msg.pose.orientation.y = qy
        msg.pose.orientation.z = qz
        self._pub_target.publish(msg)

    def _publish_status(self, inputs: Inputs, now: float) -> None:
        msg = MissionStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.phase = self._ctx.state
        wpi = self._ctx.scratch.get(self._ctx.state, {}).get("idx", 0)
        msg.waypoint_index = int(wpi)
        msg.position_error_m = float(math.dist(inputs.pose_enu, self._last_target))
        self._pub_status.publish(msg)

    def _publish_markers(self, target) -> None:
        arr = MarkerArray()
        m = Marker()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = "map"
        m.ns = "target"
        m.id = 0
        m.type = Marker.ARROW
        m.action = Marker.ADD
        m.pose.position.x = float(target[0])
        m.pose.position.y = float(target[1])
        m.pose.position.z = float(target[2])
        m.pose.orientation.w = 1.0
        m.scale.x, m.scale.y, m.scale.z = 0.8, 0.15, 0.15
        m.color.r = m.color.g = 1.0
        m.color.a = 0.9
        arr.markers.append(m)
        self._pub_markers.publish(arr)

    def destroy_node(self) -> None:
        self.slog.close()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = MissionManager()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
