"""Mission manager — phase tick, path following, marker hover.

=============================================================================
ROS 2 Interface
=============================================================================

Subscriptions:
    /drone/controller_status  [px4_ros_msgs/ControllerStatus]
    /fmu/out/vehicle_local_position  [px4_msgs/VehicleLocalPosition]
    /vision/marker_pose  [geometry_msgs/PoseStamped]

Publishers:
    /drone/target_pose  [geometry_msgs/PoseStamped]
    /drone/mission_status  [px4_ros_msgs/MissionStatus]
    /drone/mission_markers  [visualization_msgs/MarkerArray]
=============================================================================
"""

from __future__ import annotations

import math
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped
from px4_msgs.msg import VehicleLocalPosition
from px4_ros_msgs.msg import ControllerStatus, MissionStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from visualization_msgs.msg import Marker, MarkerArray

from ros_px4_template_core.lib.frame_transforms import ned_to_enu
from ros_px4_template_core.lib.mission_runtime import MissionContext, TickInputs, tick
from ros_px4_template_core.lib.structured_logger import StructuredLogger
from ros_px4_template_core.lib.waypoint_mission import WaypointMission, load_mission_yaml

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


def _default_mission_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "missions" / "inspect_aruco.yaml"


class MissionManager(Node):
    """Runs inspect/path missions via lib/mission_runtime.tick()."""

    def __init__(self) -> None:
        super().__init__("mission_manager")
        self.declare_parameter("log_dir", "./logs")
        self.declare_parameter("mission_file", str(_default_mission_path()))
        self.declare_parameter("tick_rate_hz", 10.0)
        self.declare_parameter("takeoff_altitude_m", 2.5)

        log_dir = str(self.get_parameter("log_dir").value)
        mission_path = str(self.get_parameter("mission_file").value).strip()
        if not mission_path:
            mission_path = str(_default_mission_path())
        self._takeoff_alt = float(self.get_parameter("takeoff_altitude_m").value)

        self.slog = StructuredLogger(self, log_dir=log_dir)
        self._mission: WaypointMission = load_mission_yaml(mission_path)
        self._ctx = MissionContext()
        self._pos_enu = (0.0, 0.0, 0.0)
        self._controller_armed = False
        self._marker_valid = False
        self._marker_pos: tuple[float, float, float] | None = None
        self._marker_stamp = None

        self.create_subscription(
            ControllerStatus,
            "/drone/controller_status",
            self._controller_cb,
            _RELIABLE_QOS,
        )
        self.create_subscription(
            VehicleLocalPosition,
            "/fmu/out/vehicle_local_position",
            self._position_cb,
            _PX4_QOS,
        )
        self.create_subscription(
            PoseStamped,
            "/vision/marker_pose",
            self._marker_cb,
            _RELIABLE_QOS,
        )

        self._pub_target = self.create_publisher(PoseStamped, "/drone/target_pose", _RELIABLE_QOS)
        self._pub_status = self.create_publisher(
            MissionStatus, "/drone/mission_status", _RELIABLE_QOS
        )
        self._pub_markers = self.create_publisher(
            MarkerArray, "/drone/mission_markers", _RELIABLE_QOS
        )

        rate = float(self.get_parameter("tick_rate_hz").value)
        self.create_timer(1.0 / rate, self._tick)
        self.slog.info(
            "MissionManager ready",
            mission=mission_path,
            waypoints=len(self._mission.waypoints),
        )

    def _controller_cb(self, msg: ControllerStatus) -> None:
        self._controller_armed = msg.armed

    def _position_cb(self, msg: VehicleLocalPosition) -> None:
        self._pos_enu = ned_to_enu(msg.x, msg.y, msg.z)

    def _marker_cb(self, msg: PoseStamped) -> None:
        self._marker_valid = True
        self._marker_pos = (
            msg.pose.position.x,
            msg.pose.position.y,
            msg.pose.position.z,
        )
        self._marker_stamp = self.get_clock().now()

    def _tick(self) -> None:
        now = self.get_clock().now().nanoseconds / 1e9
        marker_valid = self._marker_valid
        if self._marker_stamp is not None:
            age = (self.get_clock().now() - self._marker_stamp).nanoseconds / 1e9
            if age > (self._mission.marker.lost_timeout_s if self._mission.marker else 1.0):
                marker_valid = False

        altitude_ok = self._pos_enu[2] >= self._takeoff_alt
        out = tick(
            self._ctx,
            self._mission,
            TickInputs(
                now=now,
                pos_enu=self._pos_enu,
                controller_armed=self._controller_armed,
                altitude_ok=altitude_ok,
                marker_valid=marker_valid,
                marker_position=self._marker_pos if marker_valid else None,
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

    def _publish_target(self, target) -> None:
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self._mission.frame_id
        msg.pose.position.x = target.x
        msg.pose.position.y = target.y
        msg.pose.position.z = target.z
        msg.pose.orientation.w = 1.0
        self._pub_target.publish(msg)

    def _publish_status(self, out, now: float) -> None:
        err = math.dist(
            self._pos_enu,
            (out.target.x, out.target.y, out.target.z),
        )
        msg = MissionStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.phase = out.phase
        msg.waypoint_index = out.waypoint_index
        msg.marker_seen = out.marker_seen
        msg.position_error_m = float(err)
        self._pub_status.publish(msg)

    def _publish_markers(self, out) -> None:
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

        if self._marker_valid and self._marker_pos is not None:
            mk = Marker()
            mk.header.stamp = stamp
            mk.header.frame_id = fid
            mk.ns = "marker"
            mk.id = 0
            mk.type = Marker.CUBE
            mk.action = Marker.ADD
            mk.pose.position.x = self._marker_pos[0]
            mk.pose.position.y = self._marker_pos[1]
            mk.pose.position.z = self._marker_pos[2]
            mk.pose.orientation.w = 1.0
            mk.scale.x = mk.scale.y = 0.5
            mk.scale.z = 0.02
            mk.color.r = 1.0
            mk.color.g = 0.5
            mk.color.a = 0.9
            arr.markers.append(mk)

        self._pub_markers.publish(arr)

    def destroy_node(self) -> None:
        self.slog.close()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = MissionManager()
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
