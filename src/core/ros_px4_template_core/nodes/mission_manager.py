"""Mission manager — phase tick and path following.

=============================================================================
ROS 2 Interface
=============================================================================

Subscriptions:
    /drone/controller_status    [px4_ros_msgs/ControllerStatus]
    /drone/odom                 [nav_msgs/Odometry]   (position_node SoT pose)
    /drone/marker_detected      [std_msgs/Bool]
    /drone/marker_offset_body   [geometry_msgs/Vector3Stamped]

Publishers:
    /drone/target_pose      [geometry_msgs/PoseStamped]
    /drone/mission_status   [px4_ros_msgs/MissionStatus]
    /drone/mission_markers  [visualization_msgs/MarkerArray] - RViz waypoints
=============================================================================
"""

from __future__ import annotations

import math
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped, Vector3Stamped
from nav_msgs.msg import Odometry
from px4_ros_msgs.msg import ControllerStatus, MissionStatus
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool
from visualization_msgs.msg import Marker, MarkerArray

from ros_px4_template_core.lib.mission_profile import MissionProfileParams, build_mission_profile
from ros_px4_template_core.lib.mission_runtime import MissionContext, TickInputs, tick
from ros_px4_template_core.lib.structured_logger import StructuredLogger
from ros_px4_template_core.lib.waypoint_mission import EnuPoint, WaypointMission, load_path_yaml

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10,
)


def _default_path_file() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "paths" / "demo.yaml"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


class MissionManager(Node):
    """Runs path missions via lib/mission_runtime.tick()."""

    def __init__(self) -> None:
        super().__init__("mission_manager")
        self._tick_group = MutuallyExclusiveCallbackGroup()
        self._sub_group = ReentrantCallbackGroup()
        self.declare_parameter("log_dir", "./logs")
        self.declare_parameter("path_file", str(_default_path_file()))
        self.declare_parameter("tick_rate_hz", 10.0)
        self.declare_parameter("takeoff_altitude_m", 2.5)
        self.declare_parameter("takeoff_altitude_tolerance_m", 0.1)
        self.declare_parameter("tolerance_m", 0.4)
        self.declare_parameter("z_tolerance_m", 0.0)
        self.declare_parameter("hold_s", 2.0)
        self.declare_parameter("marker_hold_s", 10.0)

        log_dir = str(self.get_parameter("log_dir").value)
        path_file = str(self.get_parameter("path_file").value).strip()
        self._takeoff_alt = float(self.get_parameter("takeoff_altitude_m").value)
        self._takeoff_alt_tol = float(self.get_parameter("takeoff_altitude_tolerance_m").value)
        self._marker_hold_s = float(self.get_parameter("marker_hold_s").value)

        self.slog = StructuredLogger(self, log_dir=log_dir)
        z_tol_raw = float(self.get_parameter("z_tolerance_m").value)
        z_tolerance_m = z_tol_raw if z_tol_raw > 0.0 else None
        profile = MissionProfileParams(
            tolerance_m=float(self.get_parameter("tolerance_m").value),
            hold_s=float(self.get_parameter("hold_s").value),
            z_tolerance_m=z_tolerance_m,
        )
        if path_file:
            p = Path(path_file)
            if not p.is_absolute():
                p = _project_root() / p
            waypoints = load_path_yaml(p)
            self._mission: WaypointMission | None = build_mission_profile(waypoints, profile)
        else:
            self._mission = None
            self.get_logger().info("No path_file set — hover-only mode (no waypoints).")
        self._ctx = MissionContext()
        self._pos_enu = (0.0, 0.0, 0.0)
        self._have_pose = False
        self._controller_armed = False
        self._controller_alt_enu = 0.0
        self._marker_offset_enu: tuple[float, float] | None = None
        self._marker_offset_time = 0.0
        self._drone_yaw = 0.0

        self.create_subscription(
            ControllerStatus,
            "/drone/controller_status",
            self._controller_cb,
            _RELIABLE_QOS,
            callback_group=self._sub_group,
        )
        self.create_subscription(
            Odometry,
            "/drone/odom",
            self._odom_cb,
            _RELIABLE_QOS,
            callback_group=self._sub_group,
        )
        self.create_subscription(
            Bool,
            "/drone/marker_detected",
            self._marker_detected_cb,
            _RELIABLE_QOS,
            callback_group=self._sub_group,
        )
        self.create_subscription(
            Vector3Stamped,
            "/drone/marker_offset_body",
            self._marker_offset_cb,
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
        self.slog.info(
            "MissionManager ready",
            path=path_file or "(hover-only)",
            waypoints=len(self._mission.waypoints) if self._mission else 0,
        )

    def _controller_cb(self, msg: ControllerStatus) -> None:
        self._controller_armed = msg.armed
        self._controller_alt_enu = float(msg.altitude_enu_m)

    def _odom_cb(self, msg: Odometry) -> None:
        # position_node is the single source of truth: anchored-ENU pose on /drone/odom.
        pose = msg.pose.pose
        self._pos_enu = (
            pose.position.x,
            pose.position.y,
            pose.position.z,
        )
        self._have_pose = True

        # Calculate yaw from quaternion
        q = pose.orientation
        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        self._drone_yaw = math.atan2(siny_cosp, cosy_cosp)

    def _effective_pos_enu(self) -> tuple[float, float, float]:
        """ENU position for mission logic and status.

        Z uses the best of pose and controller altitude so takeoff gating and
        position_error_m stay correct before the first pose sample arrives.
        """
        x, y, z = self._pos_enu
        z_eff = max(z, self._controller_alt_enu)
        return (x, y, z_eff)

    def _marker_detected_cb(self, msg: Bool) -> None:
        if not msg.data:
            self._marker_offset_enu = None

    def _marker_offset_cb(self, msg: Vector3Stamped) -> None:
        body_x = float(msg.vector.x)
        body_y = float(msg.vector.y)

        # Rotate body FLU (Forward-Left-Up) to map ENU (East-North-Up) using self._drone_yaw
        cos_yaw = math.cos(self._drone_yaw)
        sin_yaw = math.sin(self._drone_yaw)
        enu_x = body_x * cos_yaw - body_y * sin_yaw
        enu_y = body_x * sin_yaw + body_y * cos_yaw

        self._marker_offset_enu = (enu_x, enu_y)
        self._marker_offset_time = self.get_clock().now().nanoseconds / 1e9

    def _tick(self) -> None:
        now = self.get_clock().now().nanoseconds / 1e9

        # Check marker offset age to invalidate stale detections
        if self._marker_offset_enu is not None:
            if now - self._marker_offset_time > 1.0:
                self._marker_offset_enu = None

        if self._mission is None:
            hover_target = EnuPoint(0.0, 0.0, float(self._takeoff_alt))
            self._publish_target(hover_target, frame_id="map")
            msg = MissionStatus()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.phase = "hover"
            msg.waypoint_index = 0
            msg.position_error_m = 0.0
            self._pub_status.publish(msg)
            self._pub_markers.publish(MarkerArray())
            return

        if not self._have_pose:
            takeoff_z = float(self._takeoff_alt)
            if self._mission is not None and self._mission.waypoints:
                takeoff_z = max(takeoff_z, float(self._mission.waypoints[0].z))
            self._publish_target(EnuPoint(0.0, 0.0, takeoff_z))
            return

        takeoff_z = self._takeoff_alt
        if self._mission.waypoints:
            takeoff_z = max(takeoff_z, float(self._mission.waypoints[0].z))
        pos = self._effective_pos_enu()
        altitude_ok = pos[2] >= takeoff_z - self._takeoff_alt_tol
        out = tick(
            self._ctx,
            self._mission,
            TickInputs(
                now=now,
                pos_enu=pos,
                controller_armed=self._controller_armed,
                altitude_ok=altitude_ok,
                marker_offset_enu=self._marker_offset_enu,
                marker_hold_s=self._marker_hold_s,
            ),
        )

        for ev in self._ctx.events:
            name = str(ev.pop("event", "EVENT"))
            self.slog.event(name, **ev)
            self.get_logger().info(f"mission {name}: {ev}")
        self._ctx.events.clear()

        self._publish_target(out.target)
        self._publish_status(out, now)
        self._publish_markers(out)

    def _publish_target(self, target, frame_id: str | None = None) -> None:
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = frame_id or (self._mission.frame_id if self._mission else "map")
        msg.pose.position.x = target.x
        msg.pose.position.y = target.y
        msg.pose.position.z = target.z
        msg.pose.orientation.w = 1.0
        self._pub_target.publish(msg)

    def _publish_status(self, out, now: float) -> None:
        err = math.dist(
            self._effective_pos_enu(),
            (out.target.x, out.target.y, out.target.z),
        )
        msg = MissionStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.phase = out.phase
        msg.waypoint_index = out.waypoint_index
        msg.position_error_m = float(err)
        self._pub_status.publish(msg)

    def _publish_markers(self, out) -> None:
        if self._mission is None:
            self._pub_markers.publish(MarkerArray())
            return
        arr = MarkerArray()
        stamp = self.get_clock().now().to_msg()
        fid = self._mission.frame_id

        for i, wp in enumerate(self._mission.waypoints):
            m = Marker()
            m.header.stamp = stamp
            m.header.frame_id = fid
            m.ns = "waypoints"
            m.id = i
            m.type = Marker.SPHERE
            m.action = Marker.ADD
            m.pose.position.x = wp.x
            m.pose.position.y = wp.y
            m.pose.position.z = wp.z
            m.pose.orientation.w = 1.0
            m.scale.x = m.scale.y = m.scale.z = 0.3
            m.color.g = 1.0
            m.color.a = 0.9
            arr.markers.append(m)

        if len(self._mission.waypoints) >= 2:
            line = Marker()
            line.header.stamp = stamp
            line.header.frame_id = fid
            line.ns = "path"
            line.id = 0
            line.type = Marker.LINE_STRIP
            line.action = Marker.ADD
            line.scale.x = 0.05
            line.color.b = 1.0
            line.color.a = 0.8
            for wp in self._mission.waypoints:
                from geometry_msgs.msg import Point

                p = Point()
                p.x, p.y, p.z = wp.x, wp.y, wp.z
                line.points.append(p)
            arr.markers.append(line)

        tgt = Marker()
        tgt.header.stamp = stamp
        tgt.header.frame_id = fid
        tgt.ns = "target"
        tgt.id = 0
        tgt.type = Marker.ARROW
        tgt.action = Marker.ADD
        tgt.pose.position.x = out.target.x
        tgt.pose.position.y = out.target.y
        tgt.pose.position.z = out.target.z
        tgt.pose.orientation.w = 1.0
        tgt.scale.x = 0.8
        tgt.scale.y = 0.15
        tgt.scale.z = 0.15
        tgt.color.r = tgt.color.g = 1.0
        tgt.color.a = 0.9
        arr.markers.append(tgt)

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
