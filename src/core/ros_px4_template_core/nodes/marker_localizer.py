"""Known-marker relocalization: MarkerDetection + odom + marker map -> /drone/pose_override.

=============================================================================
ROS 2 Interface
Subscriptions:
    /drone/marker_detection  [px4_ros_msgs/MarkerDetection]
    /drone/odom              [nav_msgs/Odometry]
Publishers:
    /drone/pose_override     [geometry_msgs/PoseStamped]   anchored-ENU fix
=============================================================================
"""

from __future__ import annotations

from pathlib import Path

import rclpy
import yaml
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from px4_ros_msgs.msg import MarkerDetection
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy

from ros_px4_template_core.lib.frames import (
    drone_pose_from_marker,
    enu_quaternion_from_yaw,
    enu_yaw_from_quaternion,
)
from ros_px4_template_core.lib.structured_logger import StructuredLogger

_RELIABLE_QOS = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=10
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


class MarkerLocalizer(Node):
    def __init__(self) -> None:
        super().__init__("marker_localizer")
        self.declare_parameter("log_dir", "./logs")
        self.declare_parameter("marker_map_file", "config/markers.yaml")
        # Relocalization is per-mission. Missions that visually servo onto a marker
        # (e.g. marker_hover) must NOT relocalize on it: the override would fight the
        # dead-reckoned estimate they hold against. Such missions set enabled=false.
        self.declare_parameter("enabled", True)
        self.slog = StructuredLogger(self)

        if not bool(self.get_parameter("enabled").value):
            self.slog.info("marker_localizer disabled (relocalization off for this mission)")
            return

        p = Path(str(self.get_parameter("marker_map_file").value))
        if not p.is_absolute():
            p = _project_root() / p
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        self._map: dict[int, tuple[float, float, float]] = {
            int(k): (float(v["x"]), float(v["y"]), float(v["z"]))
            for k, v in (doc.get("markers") or {}).items()
        }
        self._yaw = 0.0

        self.create_subscription(Odometry, "/drone/odom", self._odom_cb, _RELIABLE_QOS)
        self.create_subscription(
            MarkerDetection, "/drone/marker_detection", self._detection_cb, _RELIABLE_QOS
        )
        self._pub = self.create_publisher(PoseStamped, "/drone/pose_override", _RELIABLE_QOS)
        self.slog.info("marker_localizer ready", markers=sorted(self._map))

    def _odom_cb(self, msg: Odometry) -> None:
        q = msg.pose.pose.orientation
        self._yaw = enu_yaw_from_quaternion(q.w, q.x, q.y, q.z)

    def _detection_cb(self, msg: MarkerDetection) -> None:
        if not msg.valid or msg.id not in self._map:
            return
        offset = (msg.offset_body_flu.x, msg.offset_body_flu.y, msg.offset_body_flu.z)
        x, y, z = drone_pose_from_marker(self._map[msg.id], offset, self._yaw)
        out = PoseStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = "map"
        out.pose.position.x, out.pose.position.y, out.pose.position.z = x, y, z
        # Relocalization corrects position only; pass current heading through so a
        # fix never teleports yaw.
        qw, qx, qy, qz = enu_quaternion_from_yaw(self._yaw)
        out.pose.orientation.w = qw
        out.pose.orientation.x = qx
        out.pose.orientation.y = qy
        out.pose.orientation.z = qz
        self._pub.publish(out)
        self.slog.event("POSE_OVERRIDE", marker_id=int(msg.id), x=x, y=y, z=z)

    def destroy_node(self) -> None:
        self.slog.close()
        super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = MarkerLocalizer()
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
