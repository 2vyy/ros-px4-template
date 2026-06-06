"""Mission manager — generic FSM engine adapter.

=============================================================================
ROS 2 Interface
Subscriptions:
    /drone/controller_status    [px4_ros_msgs/ControllerStatus]
    /drone/odom                 [nav_msgs/Odometry]   (position_node SoT pose)
    /drone/marker_detection     [px4_ros_msgs/MarkerDetection]
Publishers:
    /drone/target_pose      [geometry_msgs/PoseStamped]
    /drone/mission_status   [px4_ros_msgs/MissionStatus]
    /drone/mission_markers  [visualization_msgs/MarkerArray]
=============================================================================
"""

from __future__ import annotations

import math
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from px4_ros_msgs.msg import ControllerStatus, MarkerDetection, MissionStatus
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from visualization_msgs.msg import Marker, MarkerArray

from ros_px4_template_core.lib.mission.commands import GoTo, Hold
from ros_px4_template_core.lib.mission.detection import Detection
from ros_px4_template_core.lib.mission.engine import MissionContext, tick
from ros_px4_template_core.lib.mission.loader import load_mission_file
from ros_px4_template_core.lib.mission.types import Inputs
from ros_px4_template_core.lib.structured_logger import StructuredLogger

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10
)
_STABLE_FRESH_S = 0.3  # a detection counts toward stability if newer than this
_DEFAULT_MISSION = "config/missions/hover.yaml"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


class MissionManager(Node):
    def __init__(self) -> None:
        super().__init__("mission_manager")
        self._tick_group = MutuallyExclusiveCallbackGroup()
        self._sub_group = ReentrantCallbackGroup()
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
            p = _project_root() / p
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

        self._pub_target = self.create_publisher(PoseStamped, "/drone/target_pose", _RELIABLE_QOS)
        self._pub_status = self.create_publisher(
            MissionStatus, "/drone/mission_status", _RELIABLE_QOS
        )
        self._pub_markers = self.create_publisher(
            MarkerArray, "/drone/mission_markers", _RELIABLE_QOS
        )

        rate = float(self.get_parameter("tick_rate_hz").value)
        self.create_timer(1.0 / rate, self._tick, callback_group=self._tick_group)
        self.slog.info("MissionManager ready", mission=str(p), initial=self._mission.initial)

    def _controller_cb(self, msg: ControllerStatus) -> None:
        self._armed = msg.armed
        self._ctrl_alt = float(msg.altitude_enu_m)

    def _odom_cb(self, msg: Odometry) -> None:
        pose = msg.pose.pose
        self._pos_enu = (pose.position.x, pose.position.y, pose.position.z)
        q = pose.orientation
        self._yaw_enu = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        )
        self._have_odom = True
        self._odom_time = self.get_clock().now().nanoseconds / 1e9

    def _detection_cb(self, msg: MarkerDetection) -> None:
        if not msg.valid:
            self._marker_offset_body = None
            self._marker_stability = 0
            return
        self._marker_id_seen = int(msg.id)
        self._marker_offset_body = (
            msg.offset_body_flu.x,
            msg.offset_body_flu.y,
            msg.offset_body_flu.z,
        )
        self._marker_time = self.get_clock().now().nanoseconds / 1e9
        self._marker_stability += 1

    def _snapshot(self, now: float) -> Inputs:
        dets: tuple[Detection, ...] = ()
        stability: dict[int, int] = {}
        if self._marker_offset_body is not None and now - self._marker_time <= 1.0:
            dets = (
                Detection(
                    id=self._marker_id_seen,
                    offset_body_flu=self._marker_offset_body,
                    stamp=self._marker_time,
                ),
            )
            if now - self._marker_time <= _STABLE_FRESH_S:
                stability = {self._marker_id_seen: self._marker_stability}
        else:
            self._marker_stability = 0
        z_eff = max(self._pos_enu[2], self._ctrl_alt)
        return Inputs(
            now=now,
            pose_enu=(self._pos_enu[0], self._pos_enu[1], z_eff),
            yaw_enu=self._yaw_enu,
            armed=self._armed,
            altitude_ok=z_eff >= self._takeoff_alt - self._takeoff_alt_tol,
            estimate_ok=self._estimate_ok,
            detections=dets,
            detection_stability=stability,
            input_ages={"odom": (now - self._odom_time) if self._have_odom else float("inf")},
        )

    def _tick(self) -> None:
        now = self.get_clock().now().nanoseconds / 1e9
        if not self._have_odom:
            self._publish_target((0.0, 0.0, self._takeoff_alt))
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
        elif not isinstance(command, Hold):
            self._last_target = self._last_target
        self._publish_target(self._last_target)
        self._publish_status(inputs, now)
        self._publish_markers(self._last_target)

    def _publish_target(self, target) -> None:
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "map"
        msg.pose.position.x = float(target[0])
        msg.pose.position.y = float(target[1])
        msg.pose.position.z = float(target[2])
        msg.pose.orientation.w = 1.0
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
